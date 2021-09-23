#!/usr/bin/env python3

import logging
from typing import Set, Tuple

import lobby_game.game_logic
import lobby_game.render_game
import lobby_game.tag_data
import nametag.logging_setup


def try_ghost(
    ghost_id: int,
    config: lobby_game.tag_data.TagConfig,
    state: lobby_game.tag_data.TagState,
    depth: int = 0,
):
    content = lobby_game.game_logic.content_for_tag(
        ghost_id=ghost_id, config=config, state=state
    )

    if content and content.status_title in ("start", "next", "success"):
        print(
            f"{'  ' * depth}G{ghost_id} -> "
            f'{content.status_title} "{content.status_word}"'
            f"{' *****' if content.status_title == 'success' else ''}"
        )

        lobby_game.render_game.steps_for_content(content)

        next_state = lobby_game.tag_data.TagState(
            phase=b"GAM",
            number=content.ghost_id,
            string=content.status_word.encode(),
        )

        try_ghost(1, config, next_state, depth + 1)
        try_ghost(2, config, next_state, depth + 1)
        try_ghost(3, config, next_state, depth + 1)


logging.getLogger().setLevel(logging.WARNING)

for flavor in ["A", "B", "C"]:
    print(f"=== {flavor} ===")
    config = lobby_game.tag_data.TagConfig(id="XXXX", flavor=flavor)
    state = lobby_game.tag_data.TagState(phase=b"ZZZ")
    try_ghost(0, config, state)
    print()