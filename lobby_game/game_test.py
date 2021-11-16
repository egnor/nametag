#!/usr/bin/env python3

import logging
import shutil
from pathlib import Path
from typing import Dict, List, Set, Tuple

from lobby_game import game_logic, render_game, tag_data
from nametag import logging_setup, protocol

out_dir = Path("tmp.game_test")
shutil.rmtree(out_dir, ignore_errors=True)
out_dir.mkdir()


def try_ghost(
    ghost_id: int,
    config: tag_data.TagConfig,
    state: tag_data.TagState,
    seen: Set[Tuple[tag_data.TagConfig, tag_data.TagState]],
    dead_ends: Dict[int, Set[str]],
    win_paths: Set[Tuple[int]],
    history: List[int],
):
    stash = protocol.StashState(
        data=bytes(state),
        from_backup=False,
        known_displaced=False,
        backup_monotime=0,
    )

    program = game_logic.program_for_tag(
        ghost_id=ghost_id, config=config, stash=stash
    )

    if not program:
        return

    name = f"{config.flavor}{''.join(str(g) for g in history)}.gif"
    render_game.render_to_file(program=program, path=out_dir / name, zoom=15)

    accepted = False
    for scene in program.scenes:
        name = scene.image_name or ""
        if name.startswith("reject-"):
            dead_ends.setdefault(ghost_id, set()).add(state.string.decode())

        if name.startswith("success"):
            win_paths.add(tuple(history))

        if any(name.startswith(p) for p in ("need-", "accept-", "success")):
            accepted = True

    if not accepted:
        return

    revisit = (config, program.new_state) in seen
    seen.add((config, program.new_state))

    scenes_text = "; ".join(
        f"{s.image_name}+{s.text}" if s.text else str(s.image_name)
        for s in program.scenes
    )

    print(
        f"{'  ' * len(history)}"
        f"G{ghost_id} -> {program.new_state.string.decode()}"
        f" ({scenes_text}){' [SEEN]' if revisit else ''}"
    )

    if not revisit:
        for next in (1, 2, 3):
            try_ghost(
                ghost_id=next,
                config=config,
                state=program.new_state,
                seen=seen,
                dead_ends=dead_ends,
                win_paths=win_paths,
                history=history + [next])


logging.getLogger().setLevel(logging.WARNING)

dead_ends: Dict[int, Set[str]] = {}
for flavor in game_logic.FLAVOR_START.keys():
    print(f"=== {flavor} ===")
    config = tag_data.TagConfig(id="XXXX", flavor=flavor)
    state = tag_data.TagState(phase=b"ZZZ")
    win_paths: Set[Tuple[int]] = set()
    try_ghost(0, config, state, set(), dead_ends, win_paths, [])
    try_ghost(1, config, state, set(), dead_ends, win_paths, [])  # test reset
    print()
    print("Good paths:")
    for path in sorted(win_paths):
        print("  " + " => ".join(f"{g}" for g in path))
    print()

for ghost_id, ends in sorted(dead_ends.items()):
    print(f"=== DEAD ENDS FOR G{ghost_id} ===")
    print(", ".join(sorted(ends)))
    print()
