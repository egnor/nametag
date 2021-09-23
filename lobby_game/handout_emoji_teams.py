#!/usr/bin/env python3

import argparse
import asyncio
import logging
import time
from pathlib import Path

import lobby_game.render_emoji_teams
import lobby_game.tag_data
import nametag.bluetooth
import nametag.logging_setup


async def check_tag(
    conn: nametag.bluetooth.Connection, config: lobby_game.tag_data.TagConfig
):
    logging.info(f"{config} Connected, reading state stash...")
    state = lobby_game.tag_data.tagstate_from_readback(await conn.readback())
    if not state:
        logging.info(f"{config} No valid state stash, updating...")
    elif state.phase != b"EMO":
        logging.info(f'{config} Phase "{state.phase.decode()}", updating...')
    elif state.number != config.team:
        logging.info(f"{config} Team T#{state.number}, updating...")
    else:
        logging.info(f"{config} Good phase/team, disconnecting...")
        return

    steps = lobby_game.render_emoji_teams.steps_for_team(config.team)
    await conn.do_steps(steps)
    logging.info(f"{config} Done sending, disconnecting...")
    return True


async def run(args):
    tag_config = lobby_game.tag_data.load_tagconfigs(args.config)
    id_last_done: Dict[str, float] = {}
    id_task: Dict[str, asyncio.Task] = {}

    logging.info("Starting scanner")
    async with nametag.bluetooth.Scanner(adapter=args.adapter) as scanner:
        while True:
            now = time.time()
            for id in (i for i, r in scanner.harvest_tasks().items() if r):
                logging.info(f"{tag_config[id]} Done")
                id_last_done[id] = now

            diags: Dict[str, List[lobby_game.tag_data.TagConfig]] = {}
            visible = list(scanner.tags)
            visible.sort(key=lambda t: (id_last_done.get(t.id, 0), t.id))
            for tag in visible:
                config = tag_config.get(tag.id)
                if not config:
                    anon = lobby_game.tag_data.TagConfig(tag.id)
                    diags.setdefault("Unknown id", []).append(anon)
                elif not config.team:
                    diags.setdefault("No team", []).append(config)
                elif tag.id in scanner.tasks:
                    diags.setdefault("In process", []).append(config)
                elif now < id_last_done.get(tag.id, 0) + 30:
                    diags.setdefault("Recently done", []).append(config)
                elif tag.rssi <= -80 or not tag.rssi:
                    diags.setdefault("Weak signal", []).append(config)
                elif len(scanner.tasks) >= 5:
                    diags.setdefault("In queue", []).append(config)
                else:
                    diags.setdefault("Now connecting", []).append(config)
                    scanner.spawn_connection_task(tag, check_tag, config)

            logging.info(
                f"Checked {len(visible)} tags..."
                + "".join(
                    f"\n  {message}: {', '.join(repr(i) for i in ids)}"
                    for message, ids in sorted(diags.items())
                )
            )

            await asyncio.sleep(1.0)


parser = argparse.ArgumentParser()
parser.add_argument("--adapter", default="hci0", help="BT interface")
parser.add_argument("--config", help="Nametag list")
parser.add_argument("--debug", action="store_true")
args = parser.parse_args()
if args.debug:
    nametag.logging_setup.enable_debug()

asyncio.run(run(args))