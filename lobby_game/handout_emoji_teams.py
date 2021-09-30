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


async def check_tag(
    fruit: nametag.bluefruit.Bluefruit,
    dev: nametag.bluefruit.Device,
    tag: nametag.protocol.Nametag,
    config: lobby_game.tag_data.TagConfig,
    id_done: Dict[str, float]
):
    async with tag:
        logging.info(f"{config} Connected, reading state stash...")
        state = await lobby_game.tag_data.read_tagstate(tag)
        if not state:
            logging.info(f"{config} No valid state stash, updating...")
        elif state.phase != b"EMO":
            logging.info(f'{config} Phase {state.phase.decode()}, updating...')
        elif state.number != config.team:
            logging.info(f"{config} Team T#{state.number}, updating...")
        else:
            logging.info(f"{config} Good phase/team, disconnecting...")
            id_done[tag.id] = time.monotonic()
            return

        await lobby_game.render_emoji_teams.render_team(
            team=config.team, tag=tag
        )
        logging.info(f"{config} Done sending, disconnecting...")
        id_done[tag.id] = time.monotonic()


async def run(args):
    tag_config = lobby_game.tag_data.load_tagconfigs(args.config)
    id_done: Dict[str, float] = {}

    logging.info("Starting scanner")
    async with nametag.bluefruit.Bluefruit(port=args.port) as fruit:
        while True:
            now = time.monotonic()
            diags: Dict[str, List[lobby_game.tag_data.TagConfig]] = {}
            visible = list(nametag.protocol.visible_nametags(fruit).values())
            visible.sort(key=lambda t: (id_done.get(t.id, 0), t.id))
            for tag in visible:
                config = tag_config.get(tag.id)
                if not config:
                    anon = lobby_game.tag_data.TagConfig(tag.id)
                    diags.setdefault("Unknown id", []).append(anon)
                elif not config.team:
                    diags.setdefault("No team", []).append(config)
                elif tag.dev.task:
                    diags.setdefault("In process", []).append(config)
                elif now < id_done.get(tag.id, 0) + 30:
                    diags.setdefault("Recently done", []).append(config)
                elif tag.dev.rssi <= -80 or not tag.dev.rssi:
                    diags.setdefault("Weak signal", []).append(config)
                elif not fruit.ready_to_connect(tag.dev):
                    diags.setdefault("In queue", []).append(config)
                else:
                    diags.setdefault("Now connecting", []).append(config)
                    fruit.spawn_device_task(tag.dev, check_tag, tag, config, id_done)

            logging.info(
                f"Checked {len(visible)} tags..."
                + "".join(
                    f"\n  {message}: {', '.join(repr(i) for i in ids)}"
                    for message, ids in sorted(diags.items())
                )
            )

            await asyncio.sleep(0.2)


parser = argparse.ArgumentParser()
parser.add_argument("--port", default="/dev/ttyACM0")
parser.add_argument("--config", help="Nametag list")
parser.add_argument("--debug", action="store_true")
args = parser.parse_args()
if args.debug:
    nametag.logging_setup.enable_debug()

asyncio.run(run(args))
