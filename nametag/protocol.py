# Protocol encoding for the nametag (see bluetooth.py for hardware access)

import asyncio
import operator
import re
import struct
from functools import reduce
from typing import Dict, Iterable, Optional, Pattern

import crcmod  # type: ignore
import PIL.Image  # type: ignore

from nametag.bluefruit import Bluefruit, BluefruitError, Device


class ProtocolError(BluefruitError):
    pass


def find_nametags(fruit: Bluefruit) -> Dict[str, Device]:
    return {id: d for d in fruit.scan.values() for id in [nametag_id(d)] if id}


def nametag_id(dev: Device) -> Optional[str]:
    if dev.mdata[6:8] == b"\xff\xff":
        return dev.mdata[1::-1].hex().upper()
    else:
        return None


class Nametag:
    def __init__(self, bluefruit: Bluefruit, dev: Device):
        self.bluefruit = bluefruit
        self.dev = dev
        self.id = nametag_id(dev)

    async def __aenter__(self):
        await self.bluefruit.connect(self.dev)
        await self.bluefruit.write(self.dev, 4, b"\x00\x01")  # CCCD notify
        return self

    async def __aexit__(self, exc_type, exc, tb):
        if self.dev.fully_connected:
            await self.bluefruit.disconnect(self.dev)

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

    async def write_stash(self, data: bytes):
        if len(data) > 18:
            raise ValueError(f"Stash data too long ({len(data)}b)")
        packet = struct.pack("BB", 0x80 | len(data), _stash_crc(data)) + data
        await self.send_raw_packet(packet)

    async def read_stash(self) -> Optional[bytes]:
        packet = await self.bluefruit.read(self.dev, 3)
        if len(packet) > 2:
            size = packet[0] ^ 0x80
            data = packet[2 : 2 + size]
            if len(data) == size and packet[1] == _stash_crc(data):
                return data

        return None  # Invalid stash

    async def send_raw_packet(self, packet: bytes):
        await self.bluefruit.write(self.dev, 3, packet)

    async def send_short_message(self, data: bytes, *, tag: int):
        packet = _encode(data, tag=tag)
        await self.send_raw_packet(packet)

    async def send_bulk_message(self, body: bytes, *, tag: int):
        byte_re = b"(\2[\5\6\7]|[^\2])"  # one byte encoded with escape123()
        for index, chunk in enumerate(_chunks(body, chunk_size=128)):
            body = struct.pack(">xHHB", len(body), index, len(chunk)) + chunk
            body += struct.pack(">B", reduce(operator.xor, body, 0))
            packets = list(_chunks(_encode(body, tag=tag), chunk_size=20))

            while True:
                notify_future = self.bluefruit.prepare_notify(self.dev, 3)
                for packet in packets:
                    await self.send_raw_packet(packet)

                try:
                    notify = await asyncio.wait_for(notify_future, timeout=3.0)
                except asyncio.TimeoutError:
                    raise ProtocolError("Notify timeout")

                expect = _encode(struct.pack(">xHx", index), tag=tag)
                assert expect[-2:] == b"\0\3"
                if notify == expect:
                    break

                if (
                    notify[: len(expect) - 2] != expect[:-2]
                    or notify[-1:] != expect[-1:]
                    or len(notify[len(expect) - 2 : -1]) > 2
                ):
                    raise ProtocolError("Bad reply {notify}, expected {expect}")


_stash_crc = crcmod.mkCrcFun(0x1CF)  # Koopman's 0xe7


def _chunks(data: bytes, *, chunk_size: int) -> Iterable[bytes]:
    for s in range(0, len(data), chunk_size):
        yield data[s : s + chunk_size]


def _encode(body: bytes, *, tag: int) -> bytes:
    def escape123(data: bytes) -> bytes:
        data = data.replace(b"\2", b"\2\6")
        data = data.replace(b"\1", b"\2\5")
        data = data.replace(b"\3", b"\2\7")
        return data

    typed = struct.pack(">B", tag) + body
    sized_typed = struct.pack(">H", len(typed)) + typed
    return b"\1" + escape123(sized_typed) + b"\3"


if __name__ == "__main__":
    import argparse

    import nametag.logging_setup

    async def test_task(fruit, dev):
        async with Nametag(fruit, dev) as tag:
            print(f"  [{tag.id}] connected, reading...")
            stash = await tag.read_stash()
            print(f"  [{tag.id}] stash is {stash}, writing...")
            await tag.write_stash(b"HELLO")
            print(f"  [{tag.id}] wrote, disconnecting...")

    async def test_main(args):
        async with Bluefruit(port=args.port) as fruit:
            for i in range(10):
                await asyncio.sleep(1)
                tags = find_nametags(fruit)
                print()
                print(f"=== {len(tags)} devices ===")
                for id, dev in tags.items():
                    print(id, dev)
                    if fruit.ready_to_connect(dev):
                        fruit.spawn_device_task(dev, test_task)

    parser = argparse.ArgumentParser()
    parser.add_argument("--debug", action="store_true")
    parser.add_argument("--port", default="/dev/ttyACM0")
    args = parser.parse_args()
    if args.debug:
        nametag.logging_setup.enable_debug()

    asyncio.run(test_main(args))
