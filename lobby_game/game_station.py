#!/usr/bin/env python3

import argparse
import asyncio
import logging
import time
from pathlib import Path
from typing import Iterable

import lobby_game.game_logic
import lobby_game.render_game
import lobby_game.tag_data
import nametag.bluetooth
import nametag.logging_setup


async def check_tag(
    conn: nametag.bluetooth.Connection,
    config: lobby_game.tag_data.TagConfig,
    ghost_id: int,
):
    logging.info(f"{config} Connected, reading state stash...")
    readback = await conn.readback()
    state = lobby_game.tag_data.tagstate_from_readback(readback)

    content = lobby_game.game_logic.content_for_tag(
        ghost_id=ghost_id, config=config, state=state
    )

    if content:
        steps = lobby_game.render_game.steps_for_content(content)
        await conn.do_steps(steps)
        logging.info(f"{config} Done sending, disconnecting...")
    return True


async def run(args):
    tag_config = lobby_game.tag_data.load_tagconfigs(args.config)
    id_task: Dict[str, asyncio.Task] = {}
    id_try_time: Dict[str, float] = {}
    id_done_time: Dict[str, float] = {}

    logging.info("Starting scanner")
    async with nametag.bluetooth.Scanner(adapter=args.adapter) as scanner:
        while True:
            now = time.time()
            for id in (id for id, r in scanner.harvest_tasks().items() if r):
                id_done_time[id] = now

            diags: Dict[str, List[lobby_game.tag_data.TagConfig]] = {}
            visible = list(scanner.tags)
            visible.sort(key=lambda t: (id_try_time.get(t.id, 0), t.id))
            for tag in visible:
                config = tag_config.get(tag.id)
                if not config:
                    anon = lobby_game.tag_data.TagConfig(tag.id)
                if tag.id in scanner.tasks:
                    diags.setdefault("In process", []).append(config)
                elif now < id_done_time.get(tag.id, 0) + 30:
                    diags.setdefault("Too soon", []).append(config)
                elif tag.rssi <= -80 or not tag.rssi:
                    diags.setdefault("Weak signal", []).append(config)
                elif len(scanner.tasks) >= 5:
                    diags.setdefault("In queue", []).append(config)
                else:
                    diags.setdefault("Now connecting", []).append(config)
                    scanner.spawn_connection_task(
                        tag, check_tag, config, args.ghost_id, timeout=60
                    )
                    id_try_time[tag.id] = now

            logging.info(
                f"Found {len(visible)} tags..."
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
parser.add_argument("--ghost_id", type=int, required=True, help="Station ID")
args = parser.parse_args()
if args.debug:
    nametag.logging_setup.enable_debug()

asyncio.run(run(args))
