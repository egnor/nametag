# Protocol encoding for the nametag (see bluetooth.py for hardware access)

import operator
import struct
from functools import reduce
from typing import Iterable, NamedTuple, Optional

import crcmod  # type: ignore
import PIL  # type: ignore


class ProtocolStep(NamedTuple):
    send: Optional[bytes]
    expect: Optional[bytes]


def _chunks(*, data: bytes, size: int, expect=None) -> Iterable[ProtocolStep]:
    yield from (
        ProtocolStep(
            send=data[s : s + size],
            expect=None if s + size < len(data) else expect,
        )
        for s in range(0, len(data), size)
    )


def _encode(*, tag: int, data: bytes, expect=None) -> Iterable[ProtocolStep]:
    def escape123(data: bytes) -> bytes:
        data = data.replace(b"\2", b"\2\6")
        data = data.replace(b"\1", b"\2\5")
        data = data.replace(b"\3", b"\2\7")
        return data

    typed = struct.pack(">B", tag) + data
    sized_typed = struct.pack(">H", len(typed)) + typed
    escaped_sized_typed = b"\1" + escape123(sized_typed) + b"\3"
    return _chunks(data=escaped_sized_typed, size=20, expect=expect)


def _encode_chunked(*, tag: int, data: bytes) -> Iterable[ProtocolStep]:
    for index, (chunk, expect) in enumerate(_chunks(data=data, size=128)):
        chunk = chunk or b""
        body = struct.pack(">xHHB", len(data), index, len(chunk)) + chunk
        body = body + struct.pack(">B", reduce(operator.xor, body, 0))
        exp = next(iter(_encode(tag=tag, data=struct.pack(">xHx", index))))[0]
        yield from _encode(tag=tag, data=body, expect=exp)


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
    return _encode(tag=6, data=struct.pack(">B", mode))


def set_speed(speed) -> Iterable[ProtocolStep]:
    return _encode(tag=7, data=struct.pack(">B", speed))


def set_brightness(brightness) -> Iterable[ProtocolStep]:
    return _encode(tag=8, data=struct.pack(">B", brightness))


_stash_crc = crcmod.mkCrcFun(0x1CF)  # Koopman's 0xe7


def stash_data(data: bytes) -> Iterable[ProtocolStep]:
    if len(data) > 18:
        raise ValueError(f"Stash data too long ({len(data)}b): {data.hex()}")
    data = struct.pack("BB", 0x80 | len(data), _stash_crc(data)) + data
    return [ProtocolStep(send=data, expect=None)]


def stash_from_readback(data: bytes) -> Optional[bytes]:
    if len(data) > 2:
        stash_size = data[0] ^ 0x80
        stash_data = data[2 : 2 + stash_size]
        if len(stash_data) == stash_size and data[1] == _stash_crc(stash_data):
            return stash_data

    return None  # Invalid stash
