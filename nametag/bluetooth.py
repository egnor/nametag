# Hardware access to the nametag via bluepy (see protocol.py for encoding)

import asyncio
import contextlib
import logging
import struct
import time
from typing import Any, Iterable, List, NamedTuple, Optional

import bleak  # type: ignore
import bleak.exc  # type: ignore

from .protocol import ProtocolStep

logger = logging.getLogger(__name__)


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
            new_scanner = bleak.BleakScanner(adapter=self.adapter)
            self._scanner = await self._exits.enter_async_context(new_scanner)
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
                if len(mdata) == 1 and mdata[0][1][2:] == b"\x02\x22\xff\xff":
                    dev = ScanTag(
                        address=bleak_dev.address.lower(),
                        code=struct.pack("<H", mdata[0][0]).hex().upper(),
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
            new_client = bleak.BleakClient(t.bt_internal)
            self._client = await self._exits.enter_async_context(new_client)

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
            if step.send:
                logger.debug(f"{prefix}Sending: {step.send.hex()}")
                while self._notified.qsize():
                    self._notified.get_nowait()
                try:
                    await self._client.write_gatt_char(self._char, step.send)
                except bleak.exc.BleakError as e:
                    raise BluetoothError(str(e))

            if step.expect is not None:
                expect_text = step.expect.hex() if step.expect else "[any]"
                logger.debug(f"{prefix}-- Expect: {expect_text}")
                while True:
                    data = await self._notified.get()
                    if step.expect in (b"", data):
                        break

                logger.debug(f"{prefix}>> Fulfil: {expect_text}")

    def _on_notify(self, handle: int, data: bytes):
        assert handle == self._char.handle
        logger.debug(f"[{self.tag.code}]\n      => Notify: {data.hex()}")
        self._notified.put_nowait(data)


class RetryConnection:
    """Wrapper for Connection that reconnects on Bluetooth errors."""

    def __init__(self, tag: ScanTag, *, retry_time=None, fail_time=None):
        self.tag = tag
        self.retry_time = retry_time
        self.fail_time = fail_time
        self._exits = contextlib.AsyncExitStack()
        self._connection: Optional[Connection] = None

    async def __aenter__(self):
        try:
            await asyncio.wait_for(self._establish(), self.retry_time)
        except asyncio.TimeoutError:
            logging.warn(f"[{self.tag.code}] Timeout, retrying...")
        except BluetoothError as e:
            detail = f"\n{e}".replace("\n", "\n      ")
            logging.warn(f"[{self.tag.code}] Error, retrying...{detail}")
        return self

    async def __aexit__(self, exc_type, exc, tb):
        await self._exits.aclose()

    async def do_steps(self, steps: Iterable[ProtocolStep]):
        assert self._connection
        mark_time = time.monotonic()
        steps = list(steps)
        while True:
            try:
                await asyncio.wait_for(self._establish(), self.retry_time)
                for s in steps:
                    mark_time = time.monotonic()
                    await asyncio.wait_for(
                        self._connection.do_steps([s]), self.retry_time
                    )
                return
            except BluetoothError as e:
                error, detail = "Error", f"\n{e}".replace("\n", "\n      ")
                exc: Exception = e
            except asyncio.TimeoutError as e:
                error, detail, exc = f"Timeout ({self.retry_time:.1f}s)", "", e

            t = time.monotonic() - mark_time
            error = f"[{self.tag.code}] {error}"
            if not self.fail_time:
                logging.warn(f"{error}, retrying...{detail}")
            elif t < self.fail_time:
                time_text = f"{t:.1f} < {self.fail_time:.1f}s"
                logging.warn(f"{error}, retrying ({time_text})...{detail}")
            else:
                message = f"{error} ({t:.1f} > {self.fail_time:.1f}s)"
                raise BluetoothError(message) from exc

    async def _establish(self):
        if not self._connection:
            new_conn = Connection(self.tag)
            self._connection = await self._exits.enter_async_context(new_conn)
