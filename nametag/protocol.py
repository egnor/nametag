# Protocol encoding for the nametag (see bluetooth.py for hardware access)

import operator
import re
import struct
from functools import reduce
from typing import Iterable, Optional, Pattern, Union

import crcmod  # type: ignore
import PIL  # type: ignore

ProtocolStep = Union[bytes, Pattern[bytes]]


def _chunks(data: bytes, *, chunk_size: int) -> Iterable[bytes]:
    for s in range(0, len(data), chunk_size):
        yield data[s : s + chunk_size]


def _encode(data: bytes, *, tag: int) -> Iterable[ProtocolStep]:
    def escape123(data: bytes) -> bytes:
        data = data.replace(b"\2", b"\2\6")
        data = data.replace(b"\1", b"\2\5")
        data = data.replace(b"\3", b"\2\7")
        return data

    typed = struct.pack(">B", tag) + data
    sized_typed = struct.pack(">H", len(typed)) + typed
    escaped_sized_typed = b"\1" + escape123(sized_typed) + b"\3"
    return _chunks(escaped_sized_typed, chunk_size=20)


def _encode_chunked(data: bytes, *, tag: int) -> Iterable[ProtocolStep]:
    byte_re = b"(\2[\5\6\7]|[^\2])"  # one byte encoded with escape123()
    for index, chunk in enumerate(_chunks(data, chunk_size=128)):
        body = struct.pack(">xHHB", len(data), index, len(chunk)) + chunk
        body = body + struct.pack(">B", reduce(operator.xor, body, 0))
        yield from _encode(body, tag=tag)

        (expect,) = _encode(data=struct.pack(">xHx", index), tag=tag)
        yield re.compile(re.escape(expect))


def show_glyphs(glyphs: Iterable[PIL.Image.Image]) -> Iterable[ProtocolStep]:
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
    return _encode_chunked(tag=2, data=header + b"".join(as_bytes))


def show_frames(
    frames: Iterable[PIL.Image.Image], *, msec=250
) -> Iterable[ProtocolStep]:
    as_bytes = []
    for i, frame in enumerate(frames):
        if frame.size != (48, 12):
            raise ValueError(f"Frame #{i} size {frame.size()} != (48, 12)")
        as_bytes.append(frame.transpose(PIL.Image.TRANSPOSE).tobytes())

    if not as_bytes:
        raise ValueError("No frames to show")

    header = struct.pack(">24xBH", len(as_bytes), msec)
    return _encode_chunked(tag=4, data=header + b"".join(as_bytes))


def set_mode(mode) -> Iterable[ProtocolStep]:
    return _encode(struct.pack(">B", mode), tag=6)


def set_speed(speed) -> Iterable[ProtocolStep]:
    return _encode(data=struct.pack(">B", speed), tag=7)


def set_brightness(brightness) -> Iterable[ProtocolStep]:
    return _encode(data=struct.pack(">B", brightness), tag=8)


_stash_crc = crcmod.mkCrcFun(0x1CF)  # Koopman's 0xe7


def stash_data(data: bytes) -> Iterable[ProtocolStep]:
    if len(data) > 18:
        raise ValueError(f"Stash data too long ({len(data)}b): {data.hex()}")
    data = struct.pack("BB", 0x80 | len(data), _stash_crc(data)) + data
    return [data]


def stash_from_readback(data: bytes) -> Optional[bytes]:
    if len(data) > 2:
        stash_size = data[0] ^ 0x80
        stash_data = data[2 : 2 + stash_size]
        if len(stash_data) == stash_size and data[1] == _stash_crc(stash_data):
            return stash_data

    return None  # Invalid stash
