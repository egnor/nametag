#!/usr/bin/env python3

import argparse
import asyncio
import logging
import time
from pathlib import Path
from typing import Dict

import lobby_game.render_emoji_teams
import lobby_game.tag_data
import nametag.bluefruit
import nametag.logging_setup
import nametag.protocol
import nametag.scanner


async def check_tag(
    tag: nametag.protocol.Nametag,
    tag_config: Dict[str, lobby_game.tag_data.TagConfig],
):
    config = tag_config.get(tag.id) or lobby_game.tag_data.TagConfig(tag.id)
    if not config.team:
        logging.info(f"{config} No team assignment, disconnecting...")
        return

    logging.info(f"{config} Connected, reading state stash...")
    state = await lobby_game.tag_data.read_state(tag)
    if not state:
        logging.info(f"{config} No valid state stash, updating...")
    elif state.phase != b"EMO":
        logging.info(f"{config} Phase {state.phase.decode()}, updating...")
    elif state.number != config.team:
        logging.info(f"{config} Team T#{state.number}, updating...")
    else:
        logging.info(f"{config} Good phase/team, disconnecting...")
        return

    await lobby_game.render_emoji_teams.render(team=config.team, tag=tag)
    logging.info(f"{config} Done sending, disconnecting...")


async def run(args):
    tag_config = lobby_game.tag_data.load_configs(args.config)
    async with nametag.bluefruit.Bluefruit(port=args.port) as adapter:
        options = nametag.scanner.ScannerOptions()
        options.success_delay = 86400
        await nametag.scanner.scan_and_spawn(
            adapter=adapter,
            options=options,
            runner=check_tag,
            tag_config=tag_config,
        )


parser = argparse.ArgumentParser()
parser.add_argument("--port", default="/dev/ttyACM0")
parser.add_argument("--config", help="Nametag list")
parser.add_argument("--debug", action="store_true")
args = parser.parse_args()
if args.debug:
    nametag.logging_setup.enable_debug()

asyncio.run(run(args), debug=args.debug)
