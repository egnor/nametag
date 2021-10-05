#!/usr/bin/env python3

import logging
from typing import Set, Tuple

from lobby_game import game_logic, render_game, tag_data
from nametag import logging_setup


def try_ghost(
    ghost_id: int,
    config: tag_data.TagConfig,
    state: tag_data.TagState,
    seen: Set[Tuple[tag_data.TagConfig, tag_data.TagState]],
    depth: int,
):
    content = game_logic.content_for_tag(
        ghost_id=ghost_id, config=config, state=state
    )

    if not content:
        return

    # render_game.content_frames(content)  # ensure it works
    for scene in content.scenes:
        if scene.image_name in ("welcome2", "accept2", "success2"):
            break
    else:
        return

    assert content
    revisit = (config, content.new_state) in seen
    seen.add((config, content.new_state))

    scenes_text = "; ".join(
        f"{s.image_name}/{s.text}" if s.text else str(s.image_name)
        for s in content.scenes
    )

    print(
        f"{'  ' * depth}G{ghost_id} -> {content.new_state.string.decode()}"
        f" ({scenes_text}){' [SEEN]' if revisit else ''}"
    )

    if not revisit:
        try_ghost(1, config, content.new_state, seen, depth + 1)
        try_ghost(2, config, content.new_state, seen, depth + 1)
        try_ghost(3, config, content.new_state, seen, depth + 1)


logging.getLogger().setLevel(logging.WARNING)

for flavor in game_logic.FLAVOR_START.keys():
    print(f"=== {flavor} ===")
    config = tag_data.TagConfig(id="XXXX", flavor=flavor)
    state = tag_data.TagState(phase=b"ZZZ")
    try_ghost(0, config, state, set(), 0)
    print()
