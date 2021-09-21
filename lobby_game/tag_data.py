import struct
from pathlib import Path
from typing import Dict, Iterable, Optional

import attr
import cattr
import cattr.preconf.tomlkit
import toml

import nametag.protocol


@attr.define
class TagState:
    phase: bytes
    number: int = 0  # 16 bit signed


@attr.define
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


_tagstate_struct = struct.Struct("<4ph")


def tagstate_from_readback(data: bytes) -> Optional[TagState]:
    stash = nametag.protocol.unstash_readback(data)
    if stash and len(stash) == _tagstate_struct.size:
        return TagState(*_tagstate_struct.unpack(stash))
    return None  # No/invalid stashed data.


def steps_from_tagstate(s: TagState) -> Iterable[nametag.protocol.ProtocolStep]:
    stash = _tagstate_struct.pack(*attr.astuple(s))
    return nametag.protocol.stash_data(stash)


def load_tagconfigs(filename: Optional[str] = None) -> Dict[str, TagConfig]:
    toml_converter = cattr.preconf.tomlkit.make_converter()
    toml_data = toml.load(filename or (Path(__file__).parent / "nametags.toml"))
    return {
        id: toml_converter.structure({"id": id, **value}, TagConfig)
        for id, value in toml_data.items()
    }
