#!/usr/bin/env python3

import logging
from typing import Set, Tuple

import lobby_game.game_logic
import lobby_game.render_game
import nametag.logging_setup
from lobby_game.tag_data import TagConfig, TagState


def try_ghost(
    ghost_id: int,
    config: TagConfig,
    state: TagState,
    seen: Set[Tuple[TagConfig, TagState]],
    depth: int,
):
    content = lobby_game.game_logic.content_for_tag(
        ghost_id=ghost_id, config=config, state=state
    )

    for scene in content.scenes if content else []:
        lobby_game.render_game.scene_frames(scene)
        if scene.image_name in ("title-start", "title-next", "title-success"):
            break
    else:
        return

    assert content
    revisit = (config, content.new_state) in seen
    seen.add((config, content.new_state))

    print(
        f"{'  ' * depth}G{ghost_id} -> {content.new_state.string.decode()}"
        f" ({scene.image_name})"
        f"{' [SEEN]' if revisit else ''}"
    )

    if not revisit:
        try_ghost(1, config, content.new_state, seen, depth + 1)
        try_ghost(2, config, content.new_state, seen, depth + 1)
        try_ghost(3, config, content.new_state, seen, depth + 1)


logging.getLogger().setLevel(logging.WARNING)

for flavor in lobby_game.game_logic.FLAVOR_START.keys():
    print(f"=== {flavor} ===")
    config = TagConfig(id="XXXX", flavor=flavor)
    state = TagState(phase=b"ZZZ")
    try_ghost(0, config, state, set(), 0)
    print()
