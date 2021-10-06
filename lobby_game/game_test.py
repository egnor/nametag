#!/usr/bin/env python3

import logging
import shutil
from pathlib import Path
from typing import Dict, List, Set, Tuple

from lobby_game import game_logic, render_game, tag_data
from nametag import logging_setup

out_dir = Path("tmp.game_test")
shutil.rmtree(out_dir, ignore_errors=True)
out_dir.mkdir()


def try_ghost(
    ghost_id: int,
    config: tag_data.TagConfig,
    state: tag_data.TagState,
    seen: Set[Tuple[tag_data.TagConfig, tag_data.TagState]],
    dead_ends: Dict[int, Set[str]],
    sequence: List[int],
):
    content = game_logic.content_for_tag(
        ghost_id=ghost_id, config=config, state=state
    )

    if not content:
        return

    name = f"{config.flavor}{''.join(str(g) for g in sequence)}.gif"
    render_game.render_to_file(content=content, path=out_dir / name, zoom=15)

    for scene in content.scenes:
        name = scene.image_name or ""
        bad_prefixes = ("reject-",)
        if any(name.startswith(p) for p in bad_prefixes):
            dead_ends.setdefault(ghost_id, set()).add(state.string.decode())

        good_prefixes = ("need-", "accept-", "success")
        if any(name.startswith(p) for p in good_prefixes):
            break
    else:
        return

    revisit = (config, content.new_state) in seen
    seen.add((config, content.new_state))

    scenes_text = "; ".join(
        f"{s.image_name}+{s.text}" if s.text else str(s.image_name)
        for s in content.scenes
    )

    print(
        f"{'  ' * len(sequence)}"
        f"G{ghost_id} -> {content.new_state.string.decode()}"
        f" ({scenes_text}){' [SEEN]' if revisit else ''}"
    )

    if not revisit:
        state = content.new_state
        for next in (1, 2, 3):
            try_ghost(next, config, state, seen, dead_ends, sequence + [next])


logging.getLogger().setLevel(logging.WARNING)

for flavor in game_logic.FLAVOR_START.keys():
    print(f"=== {flavor} ===")
    config = tag_data.TagConfig(id="XXXX", flavor=flavor)
    state = tag_data.TagState(phase=b"ZZZ")
    dead_ends: Dict[int, Set[str]] = {}
    try_ghost(0, config, state, set(), dead_ends, [])
    try_ghost(1, config, state, set(), dead_ends, [])  # verify reset logic
    print()

for ghost_id, ends in sorted(dead_ends.items()):
    print(f"=== DEAD ENDS FOR G{ghost_id} ===")
    print(", ".join(ends))
    print()
