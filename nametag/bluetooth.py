# Hardware access to the nametag via bluepy (see protocol.py for encoding)

import asyncio
import contextlib
import datetime
import logging
import re
import struct
import time
from typing import Any, Callable, Dict, Iterable, List, Optional

import attr
import bleak  # type: ignore
import bleak.backends.device  # type: ignore
import bleak.exc  # type: ignore

from .protocol import ProtocolStep

logger = logging.getLogger(__name__)


class BluetoothError(Exception):
    def __init__(self, message, exc=None):
        message += ": " + (str(exc) or type(exc).__qualname__) if exc else ""
        Exception.__init__(self, message)


@attr.define
class ScanTag:
    address: str
    id: str
    rssi: int
    _device: bleak.backends.device.BLEDevice


class Scanner:
    def __init__(self, *, adapter="hci0", restart_interval=10.0):
        self.adapter = adapter
        self.restart_interval = restart_interval
        self.tasks: Dict[str, asyncio.Task] = {}
        self._exits = contextlib.AsyncExitStack()
        self._scanner = None
        self._bopper = None

    async def __aenter__(self):
        try:
            assert self._scanner is None and self._bopper is None
            logger.debug("Starting scanner...")
            make_scanner = bleak.BleakScanner(adapter=self.adapter)
            self._scanner = await self._exits.enter_async_context(make_scanner)
            await self._scanner.start()
            self._bopper = asyncio.create_task(self._scan_bopper())
        except (bleak.exc.BleakError, asyncio.TimeoutError) as e:
            raise BluetoothError("Scan start", exc=e)
        return self

    async def __aexit__(self, exc_type, exc, tb):
        try:
            logger.debug("Stopping scanner...")
            self._bopper.cancel()
            asyncio.gather(self._bopper, return_exceptions=True)
            await self._exits.aclose()
        except (bleak.exc.BleakError, asyncio.TimeoutError) as e:
            logger.warning(f"Stopping scanner: {str(e) or type(e).__name__}")

        if self.tasks:
            logger.debug(f"Waiting for {len(self.tasks)} tasks...")
            [task.cancel() for task in self.tasks.values()]
            asyncio.gather(*self.tasks.values(), return_exceptions=True)
            logger.debug("All tasks complete")

        self._scanner = self._bopper = None

    async def _scan_bopper(self):
        while self.restart_interval:
            await asyncio.sleep(self.restart_interval)
            logger.debug(f"Bopping scanner off and back on")
            try:
                await self._scanner.stop()
                await self._scanner.start()
            except (bleak.exc.BleakError, asyncio.TimeoutError) as e:
                logger.warning(f"Bopping scanner: {str(e) or type(e).__name__}")

    @property
    def tags(self) -> List[ScanTag]:
        assert self._scanner
        out = []
        for bleak_dev in self._scanner.discovered_devices:
            if bleak_dev.name == "CoolLED":
                mdata = list(bleak_dev.metadata["manufacturer_data"].items())
                if len(mdata) == 1 and mdata[0][1][4:6] == b"\xff\xff":
                    dev = ScanTag(
                        address=bleak_dev.address.lower(),
                        id=struct.pack(">H", mdata[0][0]).hex().upper(),
                        rssi=bleak_dev.rssi,
                        device=bleak_dev,
                    )
                    out.append(dev)
        return out

    def spawn_connection_task(
        self, tag: ScanTag, asyncf: Callable, *args, timeout=60, **kwargs
    ):
        async def _connect():
            async with Connection(tag, timeout=timeout) as connection:
                return await asyncf(connection, *args, **kwargs)

        async def _task():
            time_text = f" ({timeout:.1f}s timeout)" if timeout else ""
            logger.debug(f"[{tag.id}] Starting connection task{time_text}...")
            await asyncio.wait_for(_connect(), timeout=timeout)

        if tag.id in self.tasks:
            raise ValueError(f"Another task running for {tag.id}")
        task = asyncio.create_task(_connect())
        self.tasks[tag.id] = task
        return task

    def harvest_tasks(self) -> Dict[str, Any]:
        done = {}
        for id, task in [(i, t) for i, t in self.tasks.items() if t.done()]:
            del self.tasks[id]
            try:
                done[id] = task.result()
                logger.debug(f"[{id}] Task complete")
            except (asyncio.CancelledError, TimeoutError, BluetoothError) as e:
                logger.warning(f"[{id}] {str(e) or type(e).__qualname__}")
                done[id] = None
        return done


class Connection:
    def __init__(self, tag: ScanTag, *, timeout=60):
        self.tag = tag
        self._timeout = timeout
        self._exits = contextlib.AsyncExitStack()
        self._client: Optional[bleak.BleakClient] = None
        self._received: asyncio.Queue[bytes] = asyncio.Queue()

    async def __aenter__(self):
        try:
            assert self._client is None
            t = self.tag
            logger.debug(f"[{t.id}] Connecting ({t.address})...")
            make_client = bleak.BleakClient(t._device, timeout=self._timeout)
            self._client = await self._exits.enter_async_context(make_client)
        except (bleak.exc.BleakError, asyncio.TimeoutError) as e:
            raise BluetoothError("Connecting", exc=e)

        try:
            char_uuid = "0000fff1-0000-1000-8000-00805f9b34fb"
            self._char = self._client.services.get_characteristic(char_uuid)
        except (bleak.exc.BleakError, asyncio.TimeoutError) as e:
            raise BluetoothError("Inspecting", exc=e)

        if not self._char:
            raise BluetoothError("No 0xfff1 characteristic!")

        try:
            await self._client.start_notify(self._char, self._on_notify)
            logger.debug(f"[{t.id}] Connected and subscribed")
        except (bleak.exc.BleakError, asyncio.TimeoutError) as e:
            raise BluetoothError("Start notify", exc=e)

        return self

    async def __aexit__(self, exc_type, exc, tb):
        try:
            logger.debug(f"[{self.tag.id}] Disconnecting...")
            await self._exits.aclose()
        except (bleak.exc.BleakError, asyncio.TimeoutError):
            logger.warning("Error disconnecting")

    async def do_steps(self, steps: Iterable[ProtocolStep]):
        assert self._client
        prefix = f"[{self.tag.id}]\n      "

        for step in steps:
            if step.delay_before:
                logger.debug(f"{prefix}-- Delay: {step.delay_before:.1f}s")
                await asyncio.sleep(step.delay_before)

            while True:
                while self._received.qsize():
                    self._received.get_nowait()

                for packet in step.packets:
                    try:
                        logger.debug(f"{prefix}Sending: {packet.hex()}")
                        await self._client.write_gatt_char(self._char, packet)
                    except (bleak.exc.BleakError, asyncio.TimeoutError) as e:
                        raise BluetoothError("Sending data", exc=e)

                if step.confirm_regex:
                    regex_text = f"/{str(step.confirm_regex.pattern)[2:-1]}/"
                    timeout = step.confirm_timeout
                    time_text = f" ({timeout:.1f}s)" if timeout else ""
                    logger.debug(f"{prefix}-- Expect{time_text}: {regex_text}")
                    try:
                        receive_coro = self._received.get()
                        reply = await asyncio.wait_for(receive_coro, timeout)
                    except asyncio.TimeoutError:
                        raise BluetoothError(f"Confirm timeout{time_text}")
                    if step.confirm_regex.fullmatch(reply):
                        logger.debug(f"{prefix}>> Fulfil: {regex_text}")
                    elif step.retry_regex and step.retry_regex.fullmatch(reply):
                        retry_text = f"/{str(step.retry_regex.pattern)[2:-1]}/"
                        logger.debug(f"{prefix}** Retry:  {retry_text}")
                        continue
                    else:
                        raise BluetoothError(f"Bad reply: {reply.hex()}")

                break

    async def readback(self) -> bytes:
        assert self._client
        try:
            data = await self._client.read_gatt_char(self._char)
            logger.debug(f"[{self.tag.id}]\n      -> Read:   {data.hex()}")
        except (bleak.exc.BleakError, asyncio.TimeoutError) as e:
            raise BluetoothError("Reading data", exc=e)

        if len(data) != 20:
            raise BluetoothError(f"Bad readback length: {len(data)}b")
        return data

    def _on_notify(self, handle: int, data: bytes):
        assert handle == self._char.handle
        logger.debug(f"[{self.tag.id}]\n      => Notify: {data.hex()}")
        self._received.put_nowait(data)
