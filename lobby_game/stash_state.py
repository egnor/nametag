import logging
import struct
from typing import Dict, Optional

from lobby_game import tag_data
from nametag import protocol

logger = logging.getLogger(__name__)

state_struct = struct.Struct("<4ph")


async def read(
    tag: protocol.Nametag,
) -> Optional[tag_data.TagState]:
    stash = await tag.read_stash()
    if stash and len(stash) >= state_struct.size:
        fixed, end = stash[: state_struct.size], stash[state_struct.size :]
        phase, num = state_struct.unpack(fixed)
        return tag_data.TagState(phase=phase, number=num, string=end)
    return None


async def write(*, tag: protocol.Nametag, state: tag_data.TagState):
    await tag.write_stash(
        state_struct.pack(state.phase, state.number) + state.string
    )
