# Hardware access to the nametag via Bluefruit gadget

import asyncio
import contextlib
import logging
import time
import urllib.parse
from typing import Dict, List, Optional

import attr
import logfmt.parser
import serial  # type: ignore

from nametag.protocol import ProtocolStep

logger = logging.getLogger("bluefruit")


class BluefruitError(Exception):
    pass


@attr.define
class Nametag:
    address: str
    id: str
    time: float = 0.0
    rssi: int = 0
    handle: Optional[int] = None

    connect_result: Optional[asyncio.Future] = attr.ib(default=None, repr=False)
    read_results: Dict[int, asyncio.Future] = attr.ib(factory=dict, repr=False)
    write_results: List[asyncio.Future] = attr.ib(factory=list, repr=False)



class Bluefruit:
    def __init__(self, *, port):
        self.tags: Dict[str, Nametag] = {}
        self._serial = _SerialPort(port=port)
        self._reader: asyncio.Task = None
        self._exception: Exception = None

    async def __aenter__(self):
        self._serial.__enter__()
        self._serial.write(b"show\n")
        self._reader = asyncio.create_task(self._reader_task())
        return self

    async def __aexit__(self, exc_type, exc, tb):
        self._reader.cancel()
        self._serial.__exit__(None, None, None)
        try:
            await self._reader
        except asyncio.CancelledError:
            pass
        for tag in self.tags.values():
            if tag.connect_result and not tag.connect_result.done():
                tag.connect_result.set_exception(BluefruitError("Stopped"))
            for read_result in tag.read_results.values():
                read_result.set_exception(BluefruitError("Stopped"))
            for write_result in tag.write_results:
                write_result.set_exception(BluefruitError("Stopped"))

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
            logger.critical(f"Reader failed: {repr(exc)}")
            raise

    def _on_serial_line(self, line):
        text = line.decode(errors="ignore").strip()
        values = logfmt.parser.parse_line(text)
        values = {k: v for k, v in values.items() if k.isidentifier()}
        if values:
            first_key = next(iter(values.keys()))
            method = getattr(self, f"_on_{first_key}_message", None)
            if method:
                method(values)
            if first_key not in ("scan", "time", "ERR"):
                logger.debug(f"{'=>' if method else '->'} {text}")

    def _on_ERR_message(self, values):
        text = " ".join(f"{k}={v}" for k, v in values.items())
        logger.warning(f"Bluefruit error: {text}")

    def _on_scan_message(self, values):
        uuids = set(int(u, 16) for u in values.get("u", "").split(",") if u)
        mdata = self._to_binary(values.get("m", ""))
        if not (0xfff0 in uuids and mdata[6:8] == b"\xff\xff"):
            return

        address = values["scan"]
        tag = self.tags.get(address)
        if not tag:
            id = mdata[1::-1].hex().upper()
            tag = self.tags[address] = Nametag(address=address, id=id)
            logger.debug(f"NEW {tag.id} ({tag.address})")

        tag.time = time.time()
        tag.rssi = int(values.get("s", 0))

    def _on_conn_message(self, values):
        tag = self.tags.get(values["conn"])
        if tag:
            if not tag.connect_result or tag.connect_result.done():
                loop = asyncio.get_running_loop()
                tag.connect_result = loop.create_future()
            tag.connect_result.set_result(True)

    def _on_conn_fail_message(self, values):
        pass

    def _on_disconn_message(self, values):
        tag = self.tags.get(values["conn"])
        if tag:
            if not tag.connect_result or tag.connect_result.done():
                loop = asyncio.get_running_loop()
                tag.connect_result = loop.create_future()
            tag.connect_result.set_result(False)

    def _on_disconn_fail_message(self, values):
        pass

    def _on_read_message(self, values):
        pass

    def _on_read_fail_message(self, values):
        pass

    def _on_time_message(self, values):
        now = time.time()
        self.tags, old_tags = {}, self.tags
        for addr, tag in old_tags.items():
            if tag.time >= now - 10:
                self.tags[addr] = tag
            else:
                age = now - tag.time
                logger.debug(f"LOST ({age:.1f}s): {tag.id} ({tag.address})")
        pass

    def _on_write_message(self, values):
        pass

    def _on_write_fail_message(self, values):
        pass

    @staticmethod
    def _to_binary(text: str) -> bytes:
        return urllib.parse.unquote(text, encoding='L1').encode('L1')

    @staticmethod
    def _to_text(data: bytes) -> str:
        return urllib.parse.quote(data)


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
            self._from_serial = loop.create_future()
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
                logger.warning(f"Closing serial: {str(e) or type(e).__name__}")

    async def read(self) -> bytearray:
        data = await self._from_serial
        self._from_serial = asyncio.get_running_loop().create_future()
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
            if self._from_serial.done():
                self._from_serial = asyncio.get_running_loop().create_future()
            self._from_serial.set_exception(exc)

    def _on_serial_writable(self, fileno):
        try:
            written = self._serial.write(self._to_serial)
            self._to_serial = self._to_serial[written:]
        except serial.SerialException as exc:
            if self._from_serial.done():
                self._from_serial = asyncio.get_running_loop().create_future()
            self._from_serial.set_exception(exc)
            self._to_serial = b""

        if not self._to_serial:
            asyncio.get_running_loop().remove_writer(fileno)


if __name__ == "__main__":
    import argparse

    import nametag.logging_setup

    async def test(args):
        async with Bluefruit(port=args.port) as bluefruit:
            for i in range(20):
                await asyncio.sleep(1)
                for t in bluefruit.tags.values():
                    print(t)
                print()

    parser = argparse.ArgumentParser()
    parser.add_argument("--debug", action="store_true")
    parser.add_argument("--port", default="/dev/ttyACM0")
    args = parser.parse_args()
    if args.debug:
        nametag.logging_setup.enable_debug()

    asyncio.run(test(args))
