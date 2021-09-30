# Hardware access to the nametag via Bluefruit gadget

import asyncio
import contextlib
import logging
import time
import urllib.parse
from typing import Dict, List, Optional

import attr
import logfmt.parser  # type: ignore
import serial  # type: ignore

from nametag.protocol import ProtocolStep

logger = logging.getLogger("bluefruit")


class BluefruitError(Exception):
    pass


@attr.define
class Tag:
    addr: str
    id: str
    monotime: float = attr.ib(default=0.0, repr=lambda t: f"{t:.3f}")
    rssi: int = 0

    _handle_factory = lambda: _set_future(-1)
    handle: asyncio.Future[int] = attr.ib(factory=_handle_factory, repr=False)
    reads: Dict[int, asyncio.Future[bytes]] = attr.ib(factory=dict, repr=False)
    writes: List[asyncio.Future[bool]] = attr.ib(factory=list, repr=False)

    @property
    def fully_connected(self):
        h = self.handle
        return h.done() and not h.exception() and h.result() >= 0

    @property
    def fully_disconnected(self):
        h = self.handle
        return h.done() and (h.exception() or h.result() < 0)


class Bluefruit:
    def __init__(self, *, port):
        self.tags: Dict[str, Tag] = {}
        self.busy_connecting: int = 0
        self._handles: Dict[int, Tag] = {}
        self._serial: _SerialPort = _SerialPort(port=port)
        self._reader: asyncio.Task = None
        self._exception: Exception = None
        self._scanning_mono: float = 0.0

    async def __aenter__(self):
        self._serial.__enter__()
        self._reader = asyncio.create_task(self._reader_task())
        self._send_serial("show")
        return self

    async def __aexit__(self, exc_type, exc, tb):
        self._reader.cancel()
        self._serial.__exit__(None, None, None)
        try:
            await self._reader
        except asyncio.CancelledError:
            pass
        for tag in self.tags.values():
            if tag.handle and not tag.handle.done():
                tag.handle.set_exception(BluefruitError("Stopped"))
                tag.handle.exception()  # Avoid warning if not accessed
            for read in [r for r in tag.reads.values() if not r.done()]:
                read.set_exception(BluefruitError("Stopped"))
                read.exception()  # Avoid warning if not accessed
            for write in [w for w in tag.writes if not w.done()]:
                write.set_exception(BluefruitError("Stopped"))
                write.exception()  # Avoid warning if not accessed

    async def _reader_task(self):
        try:
            await self._serial.read()  # start fresh after buffered data
            line_count = 0
            buffer = bytearray()
            while True:
                buffer.extend(await self._serial.read())
                lines = buffer.split(b"\n")
                buffer = lines.pop()
                for line in lines:
                    if line_count > 0:
                        self._on_serial_line(line)
                    line_count += 1
        except Exception as exc:
            self._exception = exc
            logger.critical(f"Reader failed ({type(exc).__name__}): {exc}")
            raise

    def _send_serial(self, line: str):
        logger.debug(f"=> {line}")
        self._serial.write(("\n" + line + "\n").encode(encoding="L1"))

    def _on_serial_line(self, line: bytes):
        message = _InputMessage(line)
        if message:
            first_key = next(iter(message.keys()))
            dispatch_method = getattr(self, f"_on_{first_key}_message", None)
            if dispatch_method:
                dispatch_method(message)
            if first_key not in ("scan", "time", "ERR"):
                logger.debug(f"{'<=' if dispatch_method else '<-'} {message}")

    def _on_ERR_message(self, message):
        logger.error(f"Bluefruit error: {message}")

    def _on_scan_message(self, message):
        self._on_scan_start_message(message)  # For startup or backstop
        uuids = set(int(u, 16) for u in message.get("u", "").split(",") if u)
        mdata = self._to_binary(message.get("m", ""))
        if not (0xFFF0 in uuids and mdata[6:8] == b"\xff\xff"):
            return

        addr = message["scan"]
        tag = self.tags.get(addr)
        if not tag:
            id = mdata[1::-1].hex().upper()
            tag = self.tags[addr] = Tag(addr=addr, id=id)
            logger.debug(f"NEW {tag.id} ({tag.addr})")

        tag.monotime = time.monotonic()
        tag.rssi = int(message.get("s", 0))

    def _on_scan_stop_message(self, message):
        if self._scanning_mono:
            logging.debug("Scanning inactive")
            self._scanning_mono = 0.0

    def _on_scan_start_message(self, message):
        if not self._scanning_mono:
            logging.debug("Scanning active")
            self._scanning_mono = time.monotonic()

    def _on_conn_message(self, message):
        tag = self.tags.get(message["conn"])
        handle = int(message["handle"])
        if not tag:
            logger.warning(f'Unmatched "conn": {message}')
            return

        self._handles[handle] = tag
        tag.handle = _set_future(handle, use=tag.handle)
        tag.monotime = time.monotonic()

    def _on_conn_fail_message(self, message):
        for tag in self.tags.values():
            if not tag.handle.done():
                exc = BluefruitError(f"Connection failed: {message}")
                tag.handle.set_exception(exc)
                tag.monotime = time.monotonic()

    def _on_disconn_message(self, message):
        tag = self._handles.pop(int(message["conn"]), None)
        if not tag:
            logger.warning(f'Unmatched "disconn": {message}')
            return

        tag.monotime = time.monotonic()
        tag.handle = _set_future(-1, use=tag.handle)
        exc = BluefruitError(f"Disconnected: {message}")
        for read in [r for r in tag.reads.values() if not r.done()]:
            read.set_exception(exc)

        pending_writes, tag.writes = tag.writes, []
        for write in [w for w in pending_writes if not w.done()]:
            write.set_exception(exc)

    def _on_disconn_fail_message(self, message):
        tag = self._handles.get(int(message["conn"]))
        if not tag:
            logger.warning(f'Unmatched "disconn_fail": {message}')
            return

        exc = BluefruitError(f"Disconnection failed: {message}")
        tag.handle = _set_future(exc=exc, use=tag.handle)
        tag.monotime = time.monotonic()

    def _on_read_message(self, message):
        tag = self._handles.get(int(message["conn"]))
        attr = int(message["attr"])
        data = _to_binary(message["data"])
        if not tag or attr not in tag.reads:
            logger.warning(f'Unmatched "read": {message}')
            return

        tag.monotime = time.monotonic()
        tag.reads[attr] = _set_future(data, use=tag.reads[attr])

    def _on_read_fail_message(self, message):
        tag = self._handles.get(int(message["conn"]))
        attr = int(message["attr"])
        if not tag or attr not in tag.reads:
            logger.warning(f'Unmatched "read_fail": {message}')
            return

        tag.monotime = time.monotonic()
        exc = BluefruitError(f"Read failed: {message}")
        tag.reads[attr] = _set_future(exc=exc, use=tag.reads[attr])

    def _on_time_message(self, message):
        if self._scanning_mono:  # Only age things out when scanning is active.
            mono = time.monotonic()
            self.tags, old_tags = {}, self.tags
            for addr, tag in old_tags.items():
                h = tag.handle
                age = mono - max(tag.monotime, self._scanning_mono)
                if age < 3 or not tag.fully_disconnected:
                    self.tags[addr] = tag
                else:
                    logger.debug(f"LOST ({age:.1f}s): {tag.id} ({tag.addr})")

    def _on_write_message(self, message):
        tag = self._handles.get(int(message["conn"]))
        if not tag:
            logger.warning(f'Unmatched "write": {message}')
            return

        tag.monotime = time.monotonic()
        count = int(message["count"])
        if count > len(tag.writes):
            logger.warning(
                f'Unmatched "write" '
                f"(count={count} > pending={len(tag.writes)}: {message}"
            )

        done, tag.writes = tag.writes[:count], tag_writes[count:]
        for write in done:
            _set_future(True, use=write)

    def _on_write_fail_message(self, message):
        tag = self._handles.get(int(message["conn"]))
        if not tag or not tag.writes:
            logger.warning(f'Unmatched "write_fail": {message}')
            return

        exc = BluefruitError("Write failed: {message}")
        done, tag.writes = tag.writes, []
        for write in done:
            _set_future(exc=exc, use=write)

    @staticmethod
    def _to_binary(text: str) -> bytes:
        return urllib.parse.unquote(text, encoding="L1").encode("L1")

    @staticmethod
    def _to_text(data: bytes) -> str:
        return urllib.parse.quote(data)


class Connection:
    def __init__(self, *, fruit: Bluefruit, tag: Tag):
        self.fruit = fruit
        self.tag = tag

    async def __aenter__(self):
        if not self.tag.fully_disconnected:
            raise ValueError("Not fully disconnected: {tag}")
        self.tag.handle = _set_future(use=self.tag.handle)
        self.fruit._send_serial(f"conn {self.tag.addr}")
        self.fruit.busy_connecting += 1
        try:
            await self.tag.handle
        finally:
            self.fruit.busy_connecting -= 1

    async def __aexit__(self, exc_type, exc, tb):
        handle = await self.tag.handle
        if handle >= 0:
            self.tag.handle = _set_future(use=self.tag.handle)
            self.fruit._send_serial(f"disconn {handle}")
            await self.tag.handle


class _InputMessage(dict):
    def __init__(self, data):
        text = data.decode(encoding="L1").strip()
        values = logfmt.parser.parse_line(text)
        super().__init__((k, v) for k, v in values.items() if k.isidentifier())

    def __repr__(self):
        return "<" + " ".join(f"{k}={v}" for k, v in self.items()) + ">"


class _SerialPort:
    def __init__(self, *, port):
        self._port = port
        self._serial: pyserial.Serial = None
        self._from_serial: asyncio.Future = None
        self._to_serial = None

    def __enter__(self):
        try:
            logger.debug(f"Opening serial: {self._port}")
            self._serial = serial.Serial(self._port, timeout=0)

            loop = asyncio.get_running_loop()
            self._from_serial = _set_future()
            self._to_serial = bytearray()

            fileno = self._serial.fileno()
            loop.add_reader(fileno, self._on_serial_readable, fileno)
            return self
        except Exception:
            self.__exit__()
            raise

    def __exit__(self, exc_type, exc, tb):
        if self._serial and self._serial.is_open:
            try:
                logger.debug(f"Closing serial: {self._port}")
                fileno = self._serial.fileno()
                loop = asyncio.get_running_loop()
                loop.remove_reader(fileno)
                loop.remove_writer(fileno)
                self._serial.close()
            except serial.SerialException as e:
                logger.error(f"Closing serial: {str(e) or type(e).__name__}")

    async def read(self) -> bytearray:
        data = await self._from_serial
        self._from_serial = _set_future()
        return data

    def write(self, data: bytes):
        if self._from_serial.done():
            self._from_serial.result()  # Raise exception if present
        self._to_serial.extend(data)
        fd = self._serial.fileno()
        asyncio.get_running_loop().add_writer(fd, self._on_serial_writable, fd)

    def _on_serial_readable(self, fileno):
        try:
            data = self._serial.read(self._serial.in_waiting)
            if self._from_serial.done():
                self._from_serial.result().extend(data)
            else:
                self._from_serial.set_result(bytearray(data))
        except serial.SerialException as exc:
            asyncio.get_running_loop().remove_reader(fileno)
            self._from_serial = _set_future(exc=exc, use=self._from_serial)

    def _on_serial_writable(self, fileno):
        try:
            written = self._serial.write(self._to_serial)
            self._to_serial = self._to_serial[written:]
        except serial.SerialException as exc:
            self._from_serial = _set_future(exc=exc, use=self._from_serial)
            self._to_serial = b""

        if not self._to_serial:
            asyncio.get_running_loop().remove_writer(fileno)


def _set_future(result=None, *, exc=None, use=None):
    if use is None or use.done():
        use = asyncio.get_running_loop().create_future()
    if result is not None:
        use.set_result(result)
    if exc is not None:
        use.set_exception(exc)
    return use


if __name__ == "__main__":
    import argparse

    import nametag.logging_setup

    async def test(args):
        async with Bluefruit(port=args.port) as fruit:
            for i in range(10):
                await asyncio.sleep(1)
                print(f"=== {len(fruit.tags)} tags ===")
                for t in list(fruit.tags.values()):
                    print(t)
                    if t.fully_disconnected:
                        try:
                            async with Connection(fruit=fruit, tag=t) as conn:
                                print("  connected!")
                        except BluefruitError as e:
                            logging.error(f"{e}")
                    print()

    parser = argparse.ArgumentParser()
    parser.add_argument("--debug", action="store_true")
    parser.add_argument("--port", default="/dev/ttyACM0")
    args = parser.parse_args()
    if args.debug:
        nametag.logging_setup.enable_debug()

    asyncio.run(test(args))
