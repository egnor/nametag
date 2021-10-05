import struct
from pathlib import Path
from typing import Dict, Iterable, List, Optional

import attr
import cattr
import cattr.preconf.tomlkit
import toml


@attr.frozen
class TagState:
    phase: bytes
    number: int = 0  # 16 bit signed
    string: bytes = b""  # Up to 12 bytes


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
    text: Optional[str] = None
    bold: bool = False
    blink: bool = False


@attr.define
class DisplayContent:
    new_state: TagState
    scenes: List[DisplayScene]


_state_struct = struct.Struct("<4ph")


def load_configs(filename: Optional[str] = None) -> Dict[str, TagConfig]:
    default_filename = Path(__file__).resolve().parent / "nametags.toml"
    toml_converter = cattr.preconf.tomlkit.make_converter()
    toml_data = toml.load(filename or default_filename)
    return {
        id: toml_converter.structure({"id": id, **value}, TagConfig)
        for id, value in toml_data.items()
    }
