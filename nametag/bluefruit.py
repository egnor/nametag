# Bluetooth LE I/O via the Bluefruit gadget

import asyncio
import collections
import logging
import os
import time
import urllib.parse
from typing import Callable, Dict, Iterable, List, Optional, Set

import attr
import logfmt.parser  # type: ignore
import serial  # type: ignore

logger = logging.getLogger(__name__)


class BluefruitError(Exception):
    pass


BAUD = 250000
MAX_SEND_SPACE = 64
MAX_CONNECTIONS = 5
MAX_WRITES = 5
MAX_SCAN_AGE = 60.0


@attr.define
class Device:
    addr: str
    monotime: float = attr.ib(default=0.0, repr=lambda t: f"{t:.3f}")
    rssi: int = 0
    uuids: Set[int] = attr.ib(factory=set)
    mdata: bytes = b""

    _handle_factory = lambda: _set_future(-1)
    handle: asyncio.Future = attr.ib(factory=_handle_factory, repr=False)
    writes: List[asyncio.Future] = attr.ib(factory=list, repr=False)
    reads: Dict[int, asyncio.Future] = attr.ib(factory=dict, repr=False)
    notify: Dict[int, asyncio.Future] = attr.ib(factory=dict, repr=False)

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
        self._devs: Dict[str, Device] = {}
        self.busy_connecting: Set[str] = set()

        self._handles: Dict[int, Device] = {}
        self._serial: _SerialPort = _SerialPort(port=port)
        self._reader: asyncio.Task = None
        self._send_space: asyncio.Future = _set_future()

    async def __aenter__(self):
        self._serial.__enter__()
        self._reader = asyncio.create_task(self._reader_task())
        return self

    async def __aexit__(self, exc_type, exc, tb):
        logger.debug("Stopping serial reader task...")
        self._reader.cancel()
        self._serial.__exit__(exc_type, exc, tb)
        try:
            await self._reader
        except asyncio.CancelledError:
            logging.debug("Reader task cancelled")
        except BluefruitError as exc:
            raise BluefruitError("Reader task failed") from exc
        finally:
            self._poison_all(BluefruitError("Stopped"))

    @property
    def totals(self):
        return self._serial.totals

    @property
    def devices(self):
        self._reader.done() and self._reader.result()
        return self._devs

    def ready_to_connect(self, dev: Device) -> bool:
        self._reader.done() and self._reader.result()
        active = sum(1 for d in self._devs.values() if not d.fully_disconnected)
        return (
            active < MAX_CONNECTIONS
            and dev.fully_disconnected
            and not self.busy_connecting
        )

    async def connect(self, dev: Device):
        self._reader.done() and self._reader.result()
        if not dev.fully_disconnected:
            raise BluefruitError(f"Connect ({dev.addr}) but not disconnected")
        if self.busy_connecting:
            b = ", ".join(self.busy_connecting)
            raise BluefruitError(f"Connect ({dev.addr}) while busy ({b})")
        dev.handle = _set_future(update=dev.handle)
        self.busy_connecting.add(dev.addr)
        await self._send_command(f"conn {dev.addr}")
        try:
            await dev.handle
        finally:
            self.busy_connecting.remove(dev.addr)

    async def disconnect(self, dev: Device):
        await asyncio.gather(*dev.writes, return_exceptions=True)  # Flush.
        try:
            handle = await dev.handle
        except BluefruitError:
            return  # Error on connect/disconnect, assume not connected

        self._reader.done() and self._reader.result()
        if handle >= 0:
            dev.handle = _set_future(update=dev.handle)
            await self._send_command(f"disconn {handle}")
            await dev.handle

    async def write(self, dev: Device, attr: int, data: bytes):
        while len(dev.writes) >= MAX_WRITES:
            await dev.writes[0]

        self._reader.done() and self._reader.result()
        if not dev.fully_connected:
            raise BluefruitError("Write to non-connected device")
        dev.writes.append(_set_future())
        text = _to_text(data)
        await self._send_command(f"write {dev.handle.result()} {attr} {text}")

    async def read(self, dev: Device, attr: int) -> bytes:
        self._reader.done() and self._reader.result()
        if dev.writes:
            await dev.writes[-1]  # Wait for writes so far to clear.
        if not dev.fully_connected:
            raise BluefruitError("Read from non-connected device")
        dev.reads[attr] = _set_future(update=dev.reads.get(attr))
        await self._send_command(f"read {dev.handle.result()} {attr}")
        return await dev.reads[attr]

    def prepare_notify(self, dev: Device, attr: int) -> asyncio.Future:
        self._reader.done() and self._reader.result()
        if not dev.fully_connected:
            raise BluefruitError("Notify prepare for non-connected device")
        future = dev.notify[attr] = _set_future(update=dev.notify.get(attr))
        return future

    async def send_dummy(self, data: bytes, *, echo: bool = False):
        self._reader.done() and self._reader.result()
        command = "echo" if echo else "noop"
        await self._send_command(f"{command} {_to_text(data)}")

    async def _reader_task(self):
        logger.debug("Starting serial reader task...")
        buffer = bytearray(await self._serial.read())  # Wait for first read.
        logger.debug("Receiving from device...")
        self._send_space = _set_future(MAX_SEND_SPACE, update=self._send_space)
        while True:
            buffer.extend(await self._serial.read())
            lines = buffer.split(b"\n")
            buffer = lines.pop()
            for line in lines:
                self._on_serial_line(line)

    def _poison_device(self, dev: Device, exc: Exception):
        if dev.handle and not dev.handle.done():
            dev.handle.set_exception(exc)
            dev.handle.exception()  # Avoid warning if not accessed

        writes, dev.writes = dev.writes, []
        for write in [w for w in writes if not w.done()]:
            write.set_exception(exc)
            write.exception()  # Avoid warning if not accessed

        for read in [r for r in dev.reads.values() if not r.done()]:
            read.set_exception(exc)
            read.exception()  # Avoid warning if not accessed

        for notify in [n for n in dev.notify.values() if not n.done()]:
            notify.set_exception(exc)
            notify.exception()  # Avoid warning if not accessed

    def _poison_all(self, exc: Exception):
        self._send_space = _set_future(exc=exc, update=self._send_space)
        self._send_space.exception()
        for dev in self._devs.values():
            self._poison_device(dev, exc)

    async def _send_command(self, line: str):
        data = (line + "\n").encode("L1")
        while data:
            space = await self._send_space
            send, data = data[:space], data[space:]
            if data:
                send_text = send.decode("L1").strip()
                unsent_text = data.decode("L1").strip()
                logger.debug(f"=> <{send_text}> // <{unsent_text}>")
            else:
                logger.debug(f"=> <{send.decode('L1').strip()}>")
            self._serial.write(send)
            self._send_space = _set_future((space - len(send)) or None)

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

    def _on_conn_message(self, message):
        dev = self._devs.get(message["conn"])
        handle = int(message["handle"])
        if not dev:
            logger.warning(f'Unmatched "conn": {message}')
            return

        self._handles[handle] = dev
        dev.handle = _set_future(handle, update=dev.handle)
        dev.monotime = time.monotonic()

    def _on_conn_fail_message(self, message):
        addr = message["conn_fail"]
        if isinstance(addr, str):
            failed = [self._devs.get(addr)]
            if not failed[0]:
                logger.warning(f'Unmatched "conn_fail": {message}')
                return
        else:
            failed = list(self._devs.values())

        for dev in failed:
            if not dev.handle.done():
                exc = BluefruitError(f"Connection failed: {message}")
                dev.handle.set_exception(exc)

    def _on_disconn_message(self, message):
        dev = self._handles.pop(int(message["conn"]), None)
        if not dev:
            logger.warning(f'Unmatched "disconn": {message}')
            return

        dev.monotime = time.monotonic()
        dev.handle = _set_future(-1, update=dev.handle)
        self._poison_device(dev, BluefruitError(f"Disconnected: {message}"))

    def _on_disconn_fail_message(self, message):
        dev = self._handles.get(int(message["conn"]))
        if not dev:
            logger.warning(f'Unmatched "disconn_fail": {message}')
            return

        exc = BluefruitError(f"Disconnection failed: {message}")
        dev.handle = _set_future(exc=exc, update=dev.handle)

    def _on_notify_message(self, message):
        dev = self._handles.get(int(message["conn"]))
        attr = int(message["attr"])
        data = _to_binary(message["data"])
        if not dev:
            logger.warning(f'Unmatched "notify": {message}')
            return

        dev.monotime = time.monotonic()
        dev.notify[attr] = _set_future(data, update=dev.notify.get(attr))

    def _on_read_message(self, message):
        dev = self._handles.get(int(message["conn"]))
        attr = int(message["attr"])
        data = _to_binary(message["data"])
        if not dev or attr not in dev.reads:
            logger.warning(f'Unmatched "read": {message}')
            return

        dev.monotime = time.monotonic()
        dev.reads[attr] = _set_future(data, update=dev.reads[attr])

    def _on_read_fail_message(self, message):
        dev = self._handles.get(int(message["conn"]))
        attr = int(message["attr"])
        if not dev or attr not in dev.reads:
            logger.warning(f'Unmatched "read_fail": {message}')
            return

        exc = BluefruitError(f"[{dev.id}] Read failed: {message}")
        dev.reads[attr] = _set_future(exc=exc, update=dev.reads[attr])

    def _on_rx_message(self, message):
        count = int(message["rx"])
        old_space = self._send_space.result() if self._send_space.done() else 0
        new_space = min(count + old_space, MAX_SEND_SPACE)
        self._send_space = _set_future(new_space, update=self._send_space)

    def _on_scan_message(self, message):
        addr = message["scan"]
        dev = self._devs.get(addr)
        if not dev:
            dev = self._devs[addr] = Device(addr=addr)
            logger.debug(f"[{dev.addr}] NEW DEVICE")

        dev.monotime = time.monotonic()
        dev.rssi = int(message.get("s", 0))
        dev.uuids = {int(u, 16) for u in message.get("u", "").split(",") if u}
        dev.mdata = _to_binary(str(message.get("m", "")))

    def _on_time_message(self, message):
        mono = time.monotonic()
        self._devs, old_scan = {}, self._devs
        for addr, dev in old_scan.items():
            h = dev.handle
            age = mono - dev.monotime
            if age < MAX_SCAN_AGE or not dev.fully_disconnected:
                self._devs[addr] = dev
            else:
                logger.debug(f"[{dev.addr}] LOST ({age:.1f}s)")

    def _on_write_message(self, message):
        dev = self._handles.get(int(message["conn"]))
        count = int(message["count"])
        if not dev:
            logger.warning(f'Unmatched "write": {message}')
            return

        dev.monotime = time.monotonic()
        if count > len(dev.writes):
            logger.warning(
                f'Unmatched "write" '
                f"(count={count} > pending={len(dev.writes)}: {message}"
            )

        done, dev.writes = dev.writes[:count], dev.writes[count:]
        for write in [w for w in done if not w.done()]:
            write.set_result(True)

    def _on_write_fail_message(self, message):
        dev = self._handles.get(int(message["conn"]))
        if not dev or not dev.writes:
            logger.warning(f'Unmatched "write_fail": {message}')
            return

        exc = BluefruitError(f"Write failed: {message}")
        writes, dev.writes = dev.writes, []
        for write in [w for w in writes if not w.done()]:
            write.set_exception(exc)


class _InputMessage(dict):
    def __init__(self, data):
        text = data.decode("L1").strip()
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
        self._fileno = None
        self.totals = collections.Counter()

    def __enter__(self):
        try:
            logger.debug(f"Opening serial ({self._port})")
            self._serial = serial.Serial(self._port, baudrate=BAUD, timeout=0)
            self._fileno = self._serial.fileno()

            loop = asyncio.get_running_loop()
            self._from_serial = _set_future()
            self._to_serial = bytearray()
            loop.add_reader(self._fileno, self._on_readable, self._fileno)
            return self
        except Exception:
            self.__exit__(None, None, None)
            raise

    def __exit__(self, exc_type, exc, tb):
        if self._serial and self._serial.is_open:
            try:
                logger.debug(f"Closing serial ({self._port})")
                loop = asyncio.get_running_loop()
                loop.remove_reader(self._fileno)
                loop.remove_writer(self._fileno)
                self._serial.close()
            except OSError as exc:
                logger.warning(f"Serial close failed ({self._port}): {exc}")

    async def read(self) -> bytearray:
        data = await self._from_serial
        self._from_serial = _set_future()
        return data

    def write(self, data: bytes):
        if self._from_serial.done():
            self._from_serial.result()  # Raise exception if present
        if not self._to_serial:
            loop = asyncio.get_running_loop()
            loop.add_writer(self._fileno, self._on_writable, self._fileno)
        self._to_serial.extend(data)

    def _on_readable(self, fileno):
        try:
            data = self._serial.read(self._serial.in_waiting)
            self.totals["read"] += len(data)
            if not self._from_serial.done():
                self._from_serial.set_result(bytearray(data))
            elif self._from_serial.cancelled() or self._from_serial.exception():
                asyncio.get_running_loop().remove_reader(fileno)
            elif not self._from_serial.exception():
                self._from_serial.result().extend(data)
        except OSError as os_error:
            logger.warning(f"Serial read failed ({self._port}): {os_error}")
            asyncio.get_running_loop().remove_reader(fileno)
            exc = BluefruitError("Serial read failed")
            exc.__cause__ = os_error
            self._from_serial = _set_future(exc=exc, update=self._from_serial)

    def _on_writable(self, fileno):
        try:
            written = self._serial.write(self._to_serial)
            self._to_serial = self._to_serial[written:]
            self.totals["write"] += written
        except OSError as os_error:
            logger.warning(f"Serial write failed ({self._port}): {os_error}")
            exc = BluefruitError("Serial write failed")
            exc.__cause__ = os_error
            self._from_serial = _set_future(exc=exc, update=self._from_serial)
            self._to_serial = b""

        if not self._to_serial:
            asyncio.get_running_loop().remove_writer(fileno)


def _set_future(result=None, *, exc=None, update=None):
    if update is None or update.done():
        update = asyncio.get_running_loop().create_future()
    if result is not None:
        update.set_result(result)
    if exc is not None:
        update.set_exception(exc)
    return update


def _to_binary(text: str) -> bytes:
    return urllib.parse.unquote(text, encoding="L1").encode("L1")


def _to_text(data: bytes) -> str:
    return urllib.parse.quote(data)
