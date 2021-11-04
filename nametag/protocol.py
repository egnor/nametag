# Protocol encoding for the nametag (see bluetooth.py for hardware access)

import asyncio
import logging
import operator
import struct
import time
from functools import reduce
from typing import Dict, Iterable, Optional

import attr
import crcmod  # type: ignore
import PIL.Image  # type: ignore

from nametag.bluefruit import Bluefruit, BluefruitError, Device

logger = logging.getLogger(__name__)


class ProtocolError(BluefruitError):
    pass


@attr.frozen
class StashState:
    data: bytes
    from_backup: bool
    stash_displaced: bool
    backup_monotime: float


class Nametag:
    def __init__(self, *, adapter: Bluefruit, dev: Device):
        tag_id = Nametag.id_if_nametag(dev)
        if not tag_id:
            raise ValueError("Device ({dev.addr}) is not a Nametag")
        self.adapter = adapter
        self.dev = dev
        self.id = tag_id
        self._sent_notify = False

    async def __aenter__(self):
        await self.adapter.connect(self.dev)
        return self

    async def __aexit__(self, exc_type, exc, tb):
        einfo = (exc_type, exc, None) if isinstance(exc, Exception) else None
        eintro = " for error:" if einfo else "..."
        logger.debug(f"[{self.id}] Disconnecting{eintro}", exc_info=einfo)
        try:
            await self.adapter.disconnect(self.dev)
        except BluefruitError as exc:
            logger.warning(f"[{self.id}] Disconnect failed: {exc}")

    async def show_glyphs(self, glyphs: Iterable[PIL.Image.Image]):
        as_bytes = []
        for i, glyph in enumerate(glyphs):
            if glyph.mode != "1":
                raise ValueError(f'Image mode "{glyph.mode}" instead of "1"')
            if glyph.size[1] > 48 or glyph.size[1] != 12:
                raise ValueError(f"Image size {glyph.size} != ([1-48], 12)")
            as_bytes.append(glyph.transpose(PIL.Image.TRANSPOSE).tobytes())

        if not as_bytes:
            raise ValueError("No glyphs to show")

        header = struct.pack(
            ">24xB80sH",
            len(as_bytes),
            bytes(len(b) for b in as_bytes),
            sum(len(b) for b in as_bytes),
        )

        await asyncio.sleep(0.5)
        await self.send_bulk_message(header + b"".join(as_bytes), tag=2)

    async def show_frames(self, frames: Iterable[PIL.Image.Image], *, msec=250):
        as_bytes = []
        for i, frame in enumerate(frames):
            if frame.size != (48, 12):
                raise ValueError(f"Frame #{i} size {frame.size()} != (48, 12)")
            as_bytes.append(frame.transpose(PIL.Image.TRANSPOSE).tobytes())

        if not as_bytes:
            raise ValueError("No frames to show")

        header = struct.pack(">24xBH", len(as_bytes), msec)

        await asyncio.sleep(0.5)
        await self.send_bulk_message(header + b"".join(as_bytes), tag=4)

    async def set_mode(self, mode: int):
        await self.send_short_message(struct.pack(">B", mode), tag=6)

    async def set_speed(self, speed):
        await self.send_short_message(struct.pack(">B", speed), tag=7)

    async def set_brightness(self, brightness):
        await self.send_short_message(struct.pack(">B", brightness), tag=8)

    _stash_crc = crcmod.mkCrcFun(0x1CF)  # Koopman's 0xe7

    async def write_stash(self, data: bytes):
        if len(data) > 18:
            raise ValueError(f"Stash data too long ({len(data)}b)")
        header = struct.pack("BB", 0x80 | len(data), Nametag._stash_crc(data))
        packet = header + data
        await self.send_raw_packet(packet)
        await self.flush()
        read = await self.adapter.read(self.dev, 3)
        if not read.startswith(packet):
            raise ProtocolError(f"Sent stash {packet!r}, read back {read!r}")

        logger.debug(f"[{self.id}] Wrote stash: {data!r} (=> backup)")
        state = stash_backup[self.id] = StashState(
            data=data,
            from_backup=True,
            stash_displaced=False,
            backup_monotime=time.monotonic(),
        )

    async def read_stash(self) -> Optional[StashState]:
        packet = await self.adapter.read(self.dev, 3)
        if len(packet) > 2:
            size = packet[0] ^ 0x80
            data = packet[2 : 2 + size]
            if len(data) == size and packet[1] == Nametag._stash_crc(data):
                logger.debug(f"[{self.id}] Read stash: {data!r} (=> backup)")
                state = stash_backup[self.id] = StashState(
                    data=data,
                    from_backup=False,
                    stash_displaced=False,
                    backup_monotime=time.monotonic(),
                )
                return state

        backup = stash_backup.get(self.id)
        if not backup:
            logger.warning(f"[{self.id}] No stash ({packet!r}), no backup")
            return None

        backup = attr.evolve(backup, from_backup=True)
        age = backup.backup_monotime - time.monotonic()
        logger.warning(
            f"[{self.id}] No stash ({packet!r}), using backup ({age:.1f}s old"
            f"{', displaced' if backup.stash_displaced else ''}): "
            f"{backup.data!r}"
        )
        return backup

    async def flush(self):
        await self.adapter.flush(self.dev)

    async def send_raw_packet(self, packet: bytes):
        backup = stash_backup.get(self.id)
        if backup and not backup.stash_displaced:
            logger.debug(f"[{self.id}] Stash displaced: {backup.data!r}")
            stash_backup[self.id] = attr.evolve(backup, stash_displaced=True)
        await self.adapter.write(self.dev, 3, packet)

    async def send_short_message(self, data: bytes, *, tag: int):
        packet = Nametag._encode(data, tag=tag)
        await self.send_raw_packet(packet)

    async def send_bulk_message(self, body: bytes, *, tag: int):
        def chunks(data: bytes, *, size: int) -> Iterable[bytes]:
            for s in range(0, len(data), size):
                yield data[s : s + size]

        if not self._sent_notify:
            await self.adapter.write(self.dev, 4, b"\x00\x01")  # CCCD notify
            self._sent_notify = True

        for index, chunk in enumerate(chunks(body, size=128)):
            body = struct.pack(">xHHB", len(body), index, len(chunk)) + chunk
            body += struct.pack(">B", reduce(operator.xor, body, 0))
            packets = list(chunks(Nametag._encode(body, tag=tag), size=20))

            while True:
                notify_future = self.adapter.prepare_notify(self.dev, 3)
                for packet in packets:
                    await self.send_raw_packet(packet)

                try:
                    notify = await asyncio.wait_for(notify_future, timeout=3.0)
                except asyncio.TimeoutError:
                    raise ProtocolError("Notify timeout")

                expect = Nametag._encode(struct.pack(">xHx", index), tag=tag)
                assert expect[-2:] == b"\0\3"
                if notify == expect:
                    break

                if (
                    notify[: len(expect) - 2] != expect[:-2]
                    or notify[-1:] != expect[-1:]
                    or len(notify[len(expect) - 2 : -1]) > 2
                ):
                    raise ProtocolError("Bad reply {notify}, expected {expect}")

    @staticmethod
    def id_if_nametag(dev: Device) -> Optional[str]:
        if 0xFFF0 in dev.uuids and dev.mdata[6:8] == b"\xff\xff":
            return dev.mdata[1::-1].hex().upper()
        return None

    @staticmethod
    def _encode(body: bytes, *, tag: int) -> bytes:
        def escape123(data: bytes) -> bytes:
            data = data.replace(b"\2", b"\2\6")
            data = data.replace(b"\1", b"\2\5")
            data = data.replace(b"\3", b"\2\7")
            return data

        typed = struct.pack(">B", tag) + body
        sized_typed = struct.pack(">H", len(typed)) + typed
        return b"\1" + escape123(sized_typed) + b"\3"


stash_backup: Dict[str, StashState] = {}
