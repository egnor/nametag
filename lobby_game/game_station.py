#!/usr/bin/env python3

import argparse
import asyncio
import logging
import time
from pathlib import Path
from typing import Dict

import lobby_game.game_logic
import lobby_game.render_game
import lobby_game.tag_data
import nametag.bluefruit
import nametag.logging_setup
import nametag.protocol
import nametag.scanner


async def check_tag(
    tag: nametag.protocol.Nametag,
    tag_config: Dict[str, lobby_game.tag_data.TagConfig],
    ghost_id: int,
):
    config = tag_config.get(tag.id, lobby_game.tag_data.TagConfig(tag.id))
    if not config.team:
        logging.info(f"{config} No team assignment, disconnecting...")
        return

    logging.info(f"{config} Connected, reading state stash...")
    state = await lobby_game.tag_data.read_state(tag)
    content = lobby_game.game_logic.content_for_tag(
        ghost_id=ghost_id, config=config, state=state
    )

    if content:
        await lobby_game.render_game.render(content=content, tag=tag)
        logging.info(f"{config} Done sending, disconnecting...")
    return True


async def run(args):
    tag_config = lobby_game.tag_data.load_configs(args.config)
    async with nametag.bluefruit.Bluefruit(port=args.port) as adapter:
        await nametag.scanner.scan_and_spawn(
            adapter=adapter,
            runner=check_tag,
            tag_config=tag_config,
            ghost_id=args.ghost_id,
        )


parser = argparse.ArgumentParser()
parser.add_argument("--config", help="Nametag list")
parser.add_argument("--debug", action="store_true")
parser.add_argument("--ghost_id", type=int, required=True, help="Station ID")
parser.add_argument("--port", default="/dev/ttyACM0")
args = parser.parse_args()
if args.debug:
    nametag.logging_setup.enable_debug()

asyncio.run(run(args))
