# Protocol encoding for the nametag (see bluetooth.py for hardware access)

import datetime
import json
import operator
import re
import struct
from functools import reduce
from typing import Any, Iterable, List, Optional, Pattern

import attr
import cattr.preconf.json
import crcmod  # type: ignore
import PIL.Image  # type: ignore


@attr.define
class ProtocolStep:
    packets: List[bytes]
    confirm_regex: Optional[Pattern[bytes]] = None
    retry_regex: Optional[Pattern[bytes]] = None
    delay_before: float = 0.0


def _chunks(data: bytes, *, chunk_size: int) -> Iterable[bytes]:
    for s in range(0, len(data), chunk_size):
        yield data[s : s + chunk_size]


def _escape123(data: bytes) -> bytes:
    data = data.replace(b"\2", b"\2\6")
    data = data.replace(b"\1", b"\2\5")
    data = data.replace(b"\3", b"\2\7")
    return data


def _encode(body: bytes, *, tag: int) -> bytes:
    typed = struct.pack(">B", tag) + body
    sized_typed = struct.pack(">H", len(typed)) + typed
    return b"\1" + _escape123(sized_typed) + b"\3"


def _encode_step(body: bytes, *, tag: int) -> ProtocolStep:
    return ProtocolStep(list(_chunks(_encode(body, tag=tag), chunk_size=20)))


def _bulk_steps(
    body: bytes, *, tag: int, delay_before: float
) -> Iterable[ProtocolStep]:
    byte_re = b"(\2[\5\6\7]|[^\2])"  # one byte encoded with escape123()
    for index, chunk in enumerate(_chunks(body, chunk_size=128)):
        chunk_body = struct.pack(">xHHB", len(body), index, len(chunk)) + chunk
        chunk_body += struct.pack(">B", reduce(operator.xor, chunk_body, 0))
        chunk_step = _encode_step(chunk_body, tag=tag)

        rep = _encode(struct.pack(">xHx", index), tag=tag)
        chunk_step.confirm_regex = re.compile(re.escape(rep))

        assert rep[-2:] == b"\0\3"
        rx = re.escape(rep[:-2]) + b"([^\0]|\2[\5\6\7])" + re.escape(rep[-1:])
        chunk_step.retry_regex = re.compile(rx)
        chunk_step.delay_before, delay_before = delay_before, 0.0
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
    return _bulk_steps(header + b"".join(as_bytes), tag=2, delay_before=0.5)


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
    return _bulk_steps(header + b"".join(as_bytes), tag=4, delay_before=0.5)


def set_mode(mode) -> Iterable[ProtocolStep]:
    return [_encode_step(struct.pack(">B", mode), tag=6)]


def set_speed(speed) -> Iterable[ProtocolStep]:
    return [_encode_step(struct.pack(">B", speed), tag=7)]


def set_brightness(brightness) -> Iterable[ProtocolStep]:
    return [_encode_step(struct.pack(">B", brightness), tag=8)]


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


def _make_converter():
    conv = cattr.preconf.json.make_converter(omit_if_default=True)

    def _structure_pattern(s: str, cl: Any) -> Pattern[bytes]:
        return re.compile(conv.structure(s, bytes))

    def _unstructure_pattern(p: Pattern[bytes]) -> str:
        return conv.unstructure(p.pattern)

    conv.register_structure_hook(Pattern[bytes], _structure_pattern)
    conv.register_unstructure_hook(re.Pattern, _unstructure_pattern)
    return conv


_converter = _make_converter()


def to_str(steps: Iterable[ProtocolStep]) -> str:
    return json.dumps(_converter.unstructure(steps))


def from_str(to_load: str) -> Iterable[ProtocolStep]:
    return _converter.structure(json.loads(to_load), List[ProtocolStep])
