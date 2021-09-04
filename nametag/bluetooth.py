# Hardware access to the nametag via bluepy (see protocol.py for encoding)

import asyncio
import contextlib
import logging
import re
import struct
import time
from typing import Any, Iterable, List, NamedTuple, Optional, Pattern, Union

import bleak  # type: ignore
import bleak.exc  # type: ignore

logger = logging.getLogger(__name__)

ProtocolStep = Union[bytes, Optional[Pattern[bytes]]]


class BluetoothError(Exception):
    pass


class ScanTag(NamedTuple):
    address: str
    code: str
    rssi: int
    bt_internal: Any


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
        except bleak.exc.BleakError as e:
            raise BluetoothError(str(e))
        return self

    async def __aexit__(self, exc_type, exc, tb):
        try:
            logger.debug("Stopping scanner...")
            await self._exits.aclose()
        except bleak.exc.BleakError as e:
            raise BluetoothError(str(e))

    def visible_tags(self) -> List[ScanTag]:
        assert self._scanner
        out = []
        for bleak_dev in self._scanner.discovered_devices:
            if bleak_dev.name == "CoolLED":
                mdata = list(bleak_dev.metadata["manufacturer_data"].items())
                if len(mdata) == 1 and mdata[0][1][4:] == b"\xff\xff":
                    dev = ScanTag(
                        address=bleak_dev.address.lower(),
                        code=struct.pack(">H", mdata[0][0]).hex().upper(),
                        rssi=bleak_dev.rssi,
                        bt_internal=bleak_dev,
                    )
                    out.append(dev)
        return out


class Connection:
    def __init__(self, tag: ScanTag):
        self.tag = tag
        self._exits = contextlib.AsyncExitStack()
        self._client: Optional[bleak.BleakClient] = None
        self._notified: asyncio.Queue[bytes] = asyncio.Queue()

    async def __aenter__(self):
        try:
            assert self._client is None
            t = self.tag
            logger.debug(f"[{t.code}] Connecting ({t.address})...")
            make_client = bleak.BleakClient(t.bt_internal)
            self._client = await self._exits.enter_async_context(make_client)

            char_uuid = "0000fff1-0000-1000-8000-00805f9b34fb"
            self._char = self._client.services.get_characteristic(char_uuid)
            await self._client.start_notify(self._char, self._on_notify)
            logger.debug(f"[{t.code}] Connected and subscribed")
        except bleak.exc.BleakError as e:
            raise BluetoothError(str(e))
        return self

    async def __aexit__(self, exc_type, exc, tb):
        try:
            logger.debug(f"[{self.tag.code}] Disconnecting...")
            await self._exits.aclose()
        except bleak.exc.BleakError as e:
            raise BluetoothError(str(e))

    async def do_steps(self, steps: Iterable[ProtocolStep]):
        assert self._client
        prefix = f"[{self.tag.code}]\n      "
        for step in steps:
            if isinstance(step, bytes):
                logger.debug(f"{prefix}Sending: {step.hex()}")
                while self._notified.qsize():
                    self._notified.get_nowait()
                try:
                    await self._client.write_gatt_char(self._char, step)
                except bleak.exc.BleakError as e:
                    raise BluetoothError(str(e))

            elif isinstance(step, re.Pattern):
                logger.debug(f"{prefix}-- Expect: {step.pattern!r}")
                while True:
                    data = await self._notified.get()
                    if step.fullmatch(data):
                        break

                logger.debug(f"{prefix}>> Fulfil: {step.pattern!r}")

            else:
                raise ValueError(f"Bad protocol step: {step}")

    async def readback(self) -> bytes:
        assert self._client
        try:
            data = await self._client.read_gatt_char(self._char)
        except bleak.exc.BleakError as e:
            raise BluetoothError(str(e))

        if len(data) != 20:
            raise BluetoothError("Bad readback length: {len(data)}b")
        logger.debug(f"[{self.tag.code}]\n      -> Read:   {data.hex()}")
        return data

    def _on_notify(self, handle: int, data: bytes):
        assert handle == self._char.handle
        logger.debug(f"[{self.tag.code}]\n      => Notify: {data.hex()}")
        self._notified.put_nowait(data)


class RetryConnection:
    """Wrapper for Connection that reconnects on Bluetooth errors."""

    def __init__(
        self, tag: ScanTag, *, connect_time=None, io_time=None, fail_time=None
    ):
        self.tag = tag
        self.connect_time = connect_time
        self.io_time = io_time
        self.fail_time = fail_time
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
                return await asyncio.wait_for(do_readback, self.io_time)
            except BluetoothError as e:
                await self._on_error("Read error", e)
            except asyncio.TimeoutError as e:
                await self._on_error(f"Read timeout ({self.io_time:.1f}s)", e)

    async def do_steps(self, steps: Iterable[ProtocolStep]):
        self._fail_timer_start = time.monotonic()
        steps = list(steps)
        while True:
            await self._connect_if_needed()
            assert self._connection
            try:
                for s in steps:
                    do_step = self._connection.do_steps([s])
                    await asyncio.wait_for(do_step, self.io_time)
                    self._fail_timer_start = time.monotonic()  # Made progress
                return
            except BluetoothError as e:
                await self._on_error("Write error", e)
            except asyncio.TimeoutError as e:
                await self._on_error(f"Write timeout ({self.io_time:.1f}s)", e)

    async def _connect_if_needed(self):
        if self._connection:
            return

        while True:
            try:
                make_conn = Connection(self.tag)
                enter_conn = self._exits.enter_async_context(make_conn)
                conn = await asyncio.wait_for(enter_conn, self.connect_time)
                self._connection = conn
                self._fail_timer_start = time.monotonic()  # Made progress
                return
            except BluetoothError as e:
                await self._on_error("Connection error", e)
            except asyncio.TimeoutError as e:
                message = f"Connection timeout ({self.connect_time:.1f}s)"
                await self._on_error(message, e)

    async def _on_error(self, message: str, exc: Exception):
        self._connection = None
        await self._exits.aclose()

        message = f"[{self.tag.code}] {message}"
        detail = f"\n{exc or ''}".replace("\n", "\n      ").rstrip()
        elapsed = time.monotonic() - self._fail_timer_start
        if not self.fail_time:
            logging.warn(f"{message}, retrying...{detail}")
        elif elapsed < self.fail_time:
            time_text = f"{elapsed:.1f} < {self.fail_time:.1f}s"
            logging.warn(f"{message}, retrying ({time_text})...{detail}")
        else:
            message = f"{message} ({elapsed:.1f} > {self.fail_time:.1f}s)"
            raise BluetoothError(message) from exc
