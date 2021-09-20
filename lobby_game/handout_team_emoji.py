#!/usr/bin/env python3

import argparse
import asyncio
import logging
import os
import shutil
import sys
import time
from pathlib import Path
from typing import List, Tuple

import PIL.Image  # type: ignore

import lobby_game.tag_data
import nametag.aseprite_loader
import nametag.bluetooth
import nametag.logging_setup
import nametag.protocol

TEAM_EMOJIS = [
    ["sparkles", "moon", "thumbs_up"],  # puzzlewise *last*, use for team x0
    ["star", "fire", "sun"],
    ["rainbow", "crown", "confetti_ball"],
    ["mushroom", "nerd_face", "fire"],
    ["victory_hand", "confetti_ball", "rainbow"],
    ["tornado", "pray", "fire"],
    ["moon", "slightly_smiling", "bulb"],
    ["sparkles", "ribbon", "confetti_ball"],
    ["seedling", "heart", "sparkles"],
    ["nerd_face", "birthday", "rainbow"],
]


def load_and_pad(image_path: str, spacing: int):
    print(f"Loading: {image_path} (pad={spacing})")
    art_dir = Path(__file__).parent.parent / "art"
    with PIL.Image.open(art_dir / image_path) as loaded_image:
        padded_image = PIL.Image.new("1", (loaded_image.size[0] + spacing, 12))
        padded_image.paste(loaded_image, box=(0, 0) + loaded_image.size)
        return padded_image


loaded_emojis = {
    emoji: load_and_pad(f"emoji/{emoji}.ase", 10)
    for emoji in set(emoji for emojis in TEAM_EMOJIS for emoji in emojis)
}

loaded_logoteam = [
    load_and_pad("lobby/lobby-logo.ase", 5),
    load_and_pad("lobby/lobby-team.ase", 5),
]

loaded_digits = {
    digit: load_and_pad(f"lobby/lobby-{digit}.ase", 2) for digit in range(0, 10)
}


def team_steps(team: int) -> List[nametag.protocol.ProtocolStep]:
    glyphs: List[PIL.Image.Image] = []

    glyphs = (
        [loaded_emojis[emoji] for emoji in TEAM_EMOJIS[team % 10]]
        + loaded_logoteam
        + [loaded_digits[int(d)] for d in str(team)]
    )

    state = lobby_game.tag_data.TagState(b"EMO", value=team)

    steps: List[nametag.protocol.ProtocolStep] = []
    steps.extend(nametag.protocol.set_brightness(255))
    steps.extend(nametag.protocol.set_speed(192))
    steps.extend(nametag.protocol.set_mode(2))
    steps.extend(nametag.protocol.show_glyphs(glyphs))
    steps.extend(lobby_game.tag_data.steps_from_tagstate(state))
    return steps


async def check_tag(
    conn: nametag.bluetooth.Connection, config: lobby_game.tag_data.TagConfig
):
    logging.info(f"{config} Connected, reading state stash...")
    readback = await conn.readback()
    state = lobby_game.tag_data.tagstate_from_readback(readback)
    if not state:
        logging.info(f"{config} No valid state stash, updating...")
    elif state.phase != b"EMO":
        phase = state.phase.decode()
        logging.info(f'{config} Wrong phase "{phase}", updating...')
    elif state.value != config.team:
        logging.info(f"{config} Wrong team T#{state.value}, updating...")
    else:
        logging.info(f"{config} Good phase/team, disconnecting...")
        return

    await conn.do_steps(team_steps(config.team))
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
                elif tag.rssi <= -80:
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
