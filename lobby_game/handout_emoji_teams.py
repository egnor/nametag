#!/usr/bin/env python3

import argparse
import asyncio
import logging
import time
from pathlib import Path
from typing import Dict

from lobby_game import render_emoji_teams, tag_data
from nametag import bluefruit, logging_setup, protocol, scanner


async def check_tag(
    tag: protocol.Nametag,
    tag_config: Dict[str, tag_data.TagConfig],
):
    config = tag_config.get(tag.id) or tag_data.TagConfig(tag.id)
    if not config.team:
        logging.info(f"{config} No team assignment, disconnecting...")
        return

    logging.info(f"{config} Connected, reading state stash...")
    stash = await tag.read_stash()
    state = stash and tag_data.TagState.from_bytes(stash.data)
    if not state:
        logging.info(f"{config} No valid state stash, updating...")
    elif state.phase != b"EMO":
        logging.info(f"{config} Phase {state.phase.decode()}, updating...")
    elif state.number != config.team:
        logging.info(f"{config} Team T#{state.number}, updating...")
    else:
        logging.info(f"{config} Good phase/team, disconnecting...")
        return

    await render_emoji_teams.render(team=config.team, tag=tag)
    logging.info(f"{config} Done sending, disconnecting...")


async def run(args):
    tag_config = tag_data.load_configs(args.config)
    options = scanner.ScannerOptions()
    options.success_delay = 86400
    await scanner.scan_and_spawn(
        options=options,
        runner=check_tag,
        tag_config=tag_config,
    )


parser = argparse.ArgumentParser()
parser.add_argument("--config", help="Nametag list")
parser.add_argument("--debug", action="store_true")
args = parser.parse_args()
if args.debug:
    logging_setup.enable_debug()

asyncio.run(run(args), debug=args.debug)
