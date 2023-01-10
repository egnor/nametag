import struct
from pathlib import Path
from typing import Dict, List, Optional

import attr
import cattr
import cattr.preconf.tomlkit
import tomlkit


@attr.frozen
class TagState:
    phase: bytes
    number: int = 0  # 16 bit signed
    string: bytes = b""  # Up to 12 bytes

    def __bytes__(self):
        return _state_struct.pack(self.phase, self.number) + self.string

    @staticmethod
    def from_bytes(data: bytes) -> Optional["TagState"]:
        if len(data) >= _state_struct.size:
            fixed, tail = data[: _state_struct.size], data[_state_struct.size :]
            phase, number = _state_struct.unpack(fixed)
            return TagState(phase=phase, number=number, string=tail)
        return None


@attr.frozen
class TagConfig:
    id: str
    team: int = 0
    flavor: str = ""
    note: str = ""

    def __str__(self):
        return repr(self) + (f" ({self.note})" if self.note else "")

    def __repr__(self):
        return (
            f"[{self.id}"
            + (f"/{self.flavor}" if self.flavor else "")
            + (f"/T{self.team}" if self.team else "")
            + "]"
        )


@attr.define
class DisplayScene:
    image_name: Optional[str] = None
    text: str = ""
    bold: bool = False
    blink: bool = False


@attr.define
class DisplayProgram:
    new_state: TagState
    scenes: List[DisplayScene]


_state_struct = struct.Struct("<4ph")


def load_configs(filename: Optional[str] = None) -> Dict[str, TagConfig]:
    default_filename = Path(__file__).resolve().parent / "nametags.toml"
    toml_converter = cattr.preconf.tomlkit.make_converter()
    with open(filename or default_filename) as file:
        toml_data = tomlkit.load(file)
    return {
        id: toml_converter.structure({"id": id, **value}, TagConfig)
        for id, value in toml_data.items()
    }
