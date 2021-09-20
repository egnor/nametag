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
    tag: nametag.bluetooth.ScanTag, config: lobby_game.tag_data.TagConfig
):
    prefix = f"[{tag.code}] T#{config.team}"
    steps = team_steps(config.team)
    async with nametag.bluetooth.RetryConnection(
        tag, connect_timeout=60, step_timeout=20, fail_timeout=60
    ) as conn:
        logging.info(f"{prefix} Connected, reading state stash...")
        readback = await conn.readback()
        state = lobby_game.tag_data.tagstate_from_readback(readback)
        if not state:
            logging.info(f"{prefix} No valid state stash, updating...")
        elif state.phase != b"EMO":
            phase = state.phase.decode()
            logging.info(f'{prefix} Wrong phase "{phase}", updating...')
        elif state.value != config.team:
            logging.info(f"{prefix} Wrong team T#{state.value}, updating...")
        else:
            logging.info(f"{prefix} Valid phase/team, disconnecting...")
            return

        await conn.do_steps(steps)
        logging.info(f"{prefix} Done sending, disconnecting...")
    logging.info(f"{prefix} Done and closed")


async def run(args):
    tag_config = lobby_game.tag_data.load_tagconfigs(args.config)
    code_time: Dict[str, float] = {}
    code_task: Dict[str, asyncio.Task] = {}

    try:
        logging.info("Starting scanner")
        async with nametag.bluetooth.Scanner(adapter=args.adapter) as scanner:
            while True:
                now = time.time()
                code_task = {c: t for c, t in code_task.items() if not t.done()}
                diags: Dict[str, List[str]] = {}
                visible = list(scanner.visible_tags())
                visible.sort(key=lambda t: (code_time.get(t.code, 0), t.code))
                for tag in visible:
                    if tag.code not in tag_config:
                        diags.setdefault("Unknown code", []).append(tag.code)
                    elif not tag_config[tag.code].team:
                        diags.setdefault("No team", []).append(tag.code)
                    elif tag.code in code_task:
                        diags.setdefault("In process", []).append(tag.code)
                    elif now < code_time.get(tag.code, 0):
                        diags.setdefault("Recently done", []).append(tag.code)
                    elif tag.rssi <= -80:
                        diags.setdefault("Weak signal", []).append(tag.code)
                    elif len(code_task) >= 5:
                        diags.setdefault("In queue", []).append(tag.code)
                    else:
                        diags.setdefault("Now connecting", []).append(tag.code)
                        coro = check_tag(tag=tag, config=tag_config[tag.code])
                        code_task[tag.code] = asyncio.create_task(coro)
                        code_time[tag.code] = now + 60

                logging.info(
                    f"Checked {len(visible)} tags..."
                    + "".join(
                        f"\n  {message}: {', '.join(codes)}"
                        for message, codes in sorted(diags.items())
                    )
                )

                await asyncio.sleep(1.0)

    finally:
        if code_task:
            logging.info(f"Waiting for {len(code_task)} tasks...")
            asyncio.gather(*code_task.values(), return_exceptions=True)
            logging.info("All tasks complete")


parser = argparse.ArgumentParser()
parser.add_argument("--adapter", default="hci0", help="BT interface")
parser.add_argument("--config", default="nametags.toml", help="Nametag list")

args = parser.parse_args()
asyncio.run(run(args))
