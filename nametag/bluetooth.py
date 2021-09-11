# Hardware access to the nametag via bluepy (see protocol.py for encoding)

import asyncio
import contextlib
import datetime
import logging
import re
import struct
import time
from typing import Any, Iterable, List, Optional, Pattern

import attr
import bleak  # type: ignore
import bleak.backends.device  # type: ignore
import bleak.exc  # type: ignore

from .protocol import ProtocolStep

logger = logging.getLogger(__name__)


class BluetoothError(Exception):
    pass


@attr.define
class ScanTag:
    address: str
    code: str
    rssi: int
    _device: bleak.backends.device.BLEDevice


class Scanner:
    def __init__(self, *, adapter="hci0"):
        self.adapter = adapter
        self._exits = contextlib.AsyncExitStack()
        self._scanner = None

    async def __aenter__(self):
        try:
            assert self._scanner is None
            logger.debug("Starting scanner...")
            make_scanner = bleak.BleakScanner(adapter=self.adapter)
            self._scanner = await self._exits.enter_async_context(make_scanner)
            await self._scanner.start()
        except (bleak.exc.BleakError, asyncio.TimeoutError) as e:
            raise BluetoothError(str(e))
        return self

    async def __aexit__(self, exc_type, exc, tb):
        try:
            logger.debug("Stopping scanner...")
            await self._exits.aclose()
        except (bleak.exc.BleakError, asyncio.TimeoutError) as e:
            raise BluetoothError(str(e))

    def visible_tags(self) -> List[ScanTag]:
        assert self._scanner
        out = []
        for bleak_dev in self._scanner.discovered_devices:
            if bleak_dev.name == "CoolLED":
                mdata = list(bleak_dev.metadata["manufacturer_data"].items())
                if len(mdata) == 1 and mdata[0][1][4:6] == b"\xff\xff":
                    dev = ScanTag(
                        address=bleak_dev.address.lower(),
                        code=struct.pack(">H", mdata[0][0]).hex().upper(),
                        rssi=bleak_dev.rssi,
                        device=bleak_dev,
                    )
                    out.append(dev)
        return out


class Connection:
    def __init__(self, tag: ScanTag):
        self.tag = tag
        self._exits = contextlib.AsyncExitStack()
        self._client: Optional[bleak.BleakClient] = None
        self._received: asyncio.Queue[bytes] = asyncio.Queue()

    async def __aenter__(self):
        try:
            assert self._client is None
            t = self.tag
            logger.debug(f"[{t.code}] Connecting ({t.address})...")
            make_client = bleak.BleakClient(t._device)
            self._client = await self._exits.enter_async_context(make_client)

            char_uuid = "0000fff1-0000-1000-8000-00805f9b34fb"
            self._char = self._client.services.get_characteristic(char_uuid)
            await self._client.start_notify(self._char, self._on_notify)
            logger.debug(f"[{t.code}] Connected and subscribed")
        except (bleak.exc.BleakError, asyncio.TimeoutError) as e:
            raise BluetoothError(str(e))
        return self

    async def __aexit__(self, exc_type, exc, tb):
        try:
            logger.debug(f"[{self.tag.code}] Disconnecting...")
            await self._exits.aclose()
        except (bleak.exc.BleakError, asyncio.TimeoutError) as e:
            raise BluetoothError(str(e))

    async def do_steps(self, steps: Iterable[ProtocolStep]):
        assert self._client
        prefix = f"[{self.tag.code}]\n      "

        for step in steps:
            while True:
                while self._received.qsize():
                    self._received.get_nowait()

                for packet in step.packets:
                    try:
                        logger.debug(f"{prefix}Sending: {packet.hex()}")
                        await self._client.write_gatt_char(self._char, packet)
                    except (bleak.exc.BleakError, asyncio.TimeoutError) as e:
                        raise BluetoothError(str(e))

                if step.confirm_regex:
                    confirm_text = f"/{str(step.confirm_regex.pattern)[2:-1]}/"
                    logger.debug(f"{prefix}-- Expect: {confirm_text}")
                    reply = await self._received.get()
                    if step.confirm_regex.fullmatch(reply):
                        logger.debug(f"{prefix}>> Fulfil: {confirm_text}")
                    elif step.retry_regex and step.retry_regex.fullmatch(reply):
                        text = f"/{str(step.retry_regex.pattern)[2:-1]}/"
                        logger.debug(f"{prefix}** Retry:  {text}")
                        continue
                    else:
                        raise BluetoothError(f"Bad reply: {reply.hex()}")

                if step.delay_after:
                    logger.debug(f"{prefix}-- Delay: {step.delay_after:.1f}s")
                    await asyncio.sleep(step.delay_after)

                break

    async def readback(self) -> bytes:
        assert self._client
        try:
            data = await self._client.read_gatt_char(self._char)
            logger.debug(f"[{self.tag.code}]\n      -> Read:   {data.hex()}")
        except (bleak.exc.BleakError, asyncio.TimeoutError) as e:
            raise BluetoothError(str(e))

        if len(data) != 20:
            raise BluetoothError(f"Bad readback length: {len(data)}b")
        return data

    def _on_notify(self, handle: int, data: bytes):
        assert handle == self._char.handle
        logger.debug(f"[{self.tag.code}]\n      => Notify: {data.hex()}")
        self._received.put_nowait(data)


class RetryConnection:
    """Wrapper for Connection that reconnects on Bluetooth errors."""

    def __init__(
        self,
        tag: ScanTag,
        *,
        connect_timeout=None,
        step_timeout=None,
        fail_timeout=None,
    ):
        self.tag = tag
        self.connect_timeout = connect_timeout
        self.step_timeout = step_timeout
        self.fail_timeout = fail_timeout
        self._exits = contextlib.AsyncExitStack()
        self._connection: Optional[Connection] = None
        self._fail_timer_start = 0.0

    async def __aenter__(self):
        self._fail_timer_start = time.monotonic()
        await self._connect_if_needed()
        return self

    async def __aexit__(self, exc_type, exc, tb):
        self._connection = None
        await self._exits.aclose()

    async def readback(self):
        self._fail_timer_start = time.monotonic()
        while True:
            await self._connect_if_needed()
            assert self._connection
            try:
                do_readback = self._connection.readback()
                return await asyncio.wait_for(do_readback, self.step_timeout)
            except BluetoothError as e:
                await self._on_error("Read error", e)
            except asyncio.TimeoutError as e:
                message = f"Readback timeout ({self.step_timeout:.1f}s)"
                await self._on_error(message, e)

    async def do_steps(self, steps: Iterable[ProtocolStep]):
        self._fail_timer_start = time.monotonic()
        steps = list(steps)
        while True:
            await self._connect_if_needed()
            assert self._connection
            try:
                for s in steps:
                    do_step = self._connection.do_steps([s])
                    await asyncio.wait_for(do_step, self.step_timeout)
                    self._fail_timer_start = time.monotonic()  # Made progress
                return
            except BluetoothError as e:
                await self._on_error("Bluetooth error", e)
            except asyncio.TimeoutError as e:
                message = f"Write timeout ({self.step_timeout:.1f}s)"
                await self._on_error(message, e)

    async def _connect_if_needed(self):
        if self._connection:
            return

        while True:
            try:
                make_conn = Connection(self.tag)
                enter_conn = self._exits.enter_async_context(make_conn)
                conn = await asyncio.wait_for(enter_conn, self.connect_timeout)
                self._connection = conn
                self._fail_timer_start = time.monotonic()  # Made progress
                return
            except BluetoothError as e:
                await self._on_error("Connection error", e)
            except asyncio.TimeoutError as e:
                message = f"Connection timeout ({self.connect_timeout:.1f}s)"
                await self._on_error(message, e)

    async def _on_error(self, message: str, exc: Exception):
        self._connection = None
        await self._exits.aclose()

        message = f"[{self.tag.code}] {message}"
        detail = f"\n{exc or ''}".replace("\n", "\n      ").rstrip()
        elapsed = time.monotonic() - self._fail_timer_start
        if not self.fail_timeout:
            logging.warn(f"{message}, retrying...{detail}")
        elif elapsed < self.fail_timeout:
            time_text = f"{elapsed:.1f} < {self.fail_timeout:.1f}s"
            logging.warn(f"{message}, retrying ({time_text})...{detail}")
        else:
            message = f"{message} ({elapsed:.1f} > {self.fail_timeout:.1f}s)"
            raise BluetoothError(message) from exc
