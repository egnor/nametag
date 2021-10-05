#!/usr/bin/env python3

import argparse
import asyncio
import logging
import time
from pathlib import Path
from typing import Dict

from lobby_game import game_logic, render_game, stash_state, tag_data
from nametag import bluefruit, logging_setup, protocol, scanner


async def check_tag(
    tag: protocol.Nametag,
    tag_config: Dict[str, tag_data.TagConfig],
    ghost_id: int,
):
    config = tag_config.get(tag.id, tag_data.TagConfig(tag.id))
    if not config.team:
        logging.info(f"{config} No team assignment, disconnecting...")
        return

    logging.info(f"{config} Connected, reading state stash...")
    state = await stash_state.read(tag)
    content = game_logic.content_for_tag(
        ghost_id=ghost_id, config=config, state=state
    )

    if content:
        await render_game.render_content(content=content, tag=tag)
        logging.info(f"{config} Done sending, disconnecting...")
    return True


parser = argparse.ArgumentParser()
parser.add_argument("--config", help="Nametag list")
parser.add_argument("--debug", action="store_true")
parser.add_argument("--ghost_id", type=int, required=True, help="Station ID")
args = parser.parse_args()
if args.debug:
    logging_setup.enable_debug()

tag_config = tag_data.load_configs(args.config)
asyncio.run(
    scanner.scan_and_spawn(
        runner=check_tag,
        tag_config=tag_config,
        ghost_id=args.ghost_id,
    ),
    debug=args.debug,
)
