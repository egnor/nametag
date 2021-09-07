# Protocol encoding for the nametag (see bluetooth.py for hardware access)

import attr
import datetime
import operator
import re
import struct
from functools import reduce
from typing import Iterable, Optional, Pattern, Union

import attr
import crcmod  # type: ignore
import PIL  # type: ignore

@attr.define
class ProtocolStep:
    packets: List[bytes]
    confirm_regex: Optional[Pattern[bytes]] = None
    retry_regex: Optional[Pattern[bytes]] = None
    delay_after: float = 0.0


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


def _encode_step(body: bytes, *, tag: int) -> ProtocolStep:
    return ProtocolStep(list(_chunks(_encode(body, tag=tag), chunk_size=20)))


def _bulk_steps(body: bytes, *, tag: int) -> Iterable[ProtocolStep]:
    byte_re = b"(\2[\5\6\7]|[^\2])"  # one byte encoded with escape123()
    for index, chunk in enumerate(_chunks(body, chunk_size=128)):
        chunk_body = struct.pack(">xHHB", len(body), index, len(chunk)) + chunk
        chunk_body += struct.pack(">B", reduce(operator.xor, chunk_body, 0))
        chunk_step = _encode_step(chunk_body, tag=tag)

        confirm_body = struct.pack(">xHx", index)
        confirm_packet = _encode(confirm_body, tag=tag)
        chunk_step.confirm_regex = re.compile(re.escape(confirm_packet))
        yield chunk_step


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
    return _bulk_steps(header + b"".join(as_bytes), tag=2)


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
    return _bulk_steps(header + b"".join(as_bytes), tag=4)


def set_mode(mode) -> Iterable[ProtocolStep]:
    step = _encode_step(struct.pack(">B", mode), tag=6)
    return [attr.evolve(step, delay_after=0.5)]


def set_speed(speed) -> Iterable[ProtocolStep]:
    step = _encode_step(struct.pack(">B", speed), tag=7)
    return [attr.evolve(step, delay_after=0.5)]


def set_brightness(brightness) -> Iterable[ProtocolStep]:
    step = _encode_step(struct.pack(">B", brightness), tag=8)
    return [attr.evolve(step, delay_after=0.5)]


_stash_crc = crcmod.mkCrcFun(0x1CF)  # Koopman's 0xe7


def stash_data(data: bytes) -> Iterable[ProtocolStep]:
    if len(data) > 18:
        raise ValueError(f"Stash data too long ({len(data)}b): {data.hex()}")
    data = struct.pack("BB", 0x80 | len(data), _stash_crc(data)) + data
    return [ProtocolStep(packets=[data])]


def unstash_readback(data: bytes) -> Optional[bytes]:
    if len(data) > 2:
        stash_size = data[0] ^ 0x80
        stash_data = data[2 : 2 + stash_size]
        if len(stash_data) == stash_size and data[1] == _stash_crc(stash_data):
            return stash_data

    return None  # Invalid stash
