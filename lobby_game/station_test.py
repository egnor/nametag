#!/usr/bin/env python3

import argparse
import asyncio
import logging
import time
from pathlib import Path
from typing import Iterable

import PIL.Image  # type: ignore
import PIL.ImageFont  # type: ignore
import PIL.ImageDraw  # type: ignore

import lobby_game.tag_data
import nametag.bluetooth
import nametag.logging_setup
import nametag.protocol

fonts_dir = Path(__file__).parent.parent / "external" / "fonts"
font_path = fonts_dir / "Spartan-Bold.ttf"
loaded_font = PIL.ImageFont.truetype(str(font_path), 10)


def text_steps(text: str) -> Iterable[nametag.protocol.ProtocolStep]:
    image = PIL.Image.new("1", (48, 12))
    draw = PIL.ImageDraw.Draw(image)
    center_xy = (image.size[0] / 2, image.size[1] / 2)

    draw.text(center_xy, text, fill=1, font=loaded_font, anchor="mm")
    return nametag.protocol.show_frames([image], msec=1000)


async def check_tag(
    conn: nametag.bluetooth.Connection,
    config: lobby_game.tag_data.TagConfig,
    station: int,
):
    logging.info(f"{config} Connected, reading state stash...")
    state = lobby_game.tag_data.tagstate_from_readback(await conn.readback())
    if not state:
        logging.info(f"{config} No valid state stash, updating...")
        state = lobby_game.tag_data.TagState(b"STA", number=0)
    elif state.phase != b"STA":
        phase = state.phase.decode()
        logging.info(f'{config} Phase "{state.phase.decode()}", updating...')
        state = lobby_game.tag_data.TagState(b"STA", number=0)
    elif state.number % 10 == station:
        logging.info(f"{config} <{state.number}> here last, disconnecting...")
        return

    state.number = (state.number % 1000) * 10 + station
    text = f"{config.flavor}{state.number}"
    logging.info(f'{config} Sending "{text}"')

    steps = list(text_steps(text))
    steps.extend(lobby_game.tag_data.steps_from_tagstate(state))
    await conn.do_steps(steps)
    logging.info(f"{config} Done sending, disconnecting...")
    return True


async def run(args):
    tag_config = lobby_game.tag_data.load_tagconfigs(args.config)
    id_task: Dict[str, asyncio.Task] = {}
    id_time: Dict[str, float] = {}
    last_time: float = 0.0

    logging.info("Starting scanner")
    async with nametag.bluetooth.Scanner(adapter=args.adapter) as scanner:
        while True:
            scanner.harvest_tasks()

            now = time.time()
            diags: Dict[str, List[lobby_game.tag_data.TagConfig]] = {}
            visible = list(scanner.tags)
            visible.sort(key=lambda t: (id_time.get(t.id, 0), t.id))
            for tag in visible:
                config = tag_config.get(tag.id)
                if not config:
                    config = lobby_game.tag_data.TagConfig(tag.id, flavor="?")
                if tag.id in scanner.tasks:
                    diags.setdefault("In process", []).append(config)
                elif tag.rssi <= -80 or not tag.rssi:
                    diags.setdefault("Weak signal", []).append(config)
                elif now < last_time + 0.5:
                    diags.setdefault("Waiting", []).append(config)
                elif len(scanner.tasks) >= 5:
                    diags.setdefault("In queue", []).append(config)
                else:
                    diags.setdefault("Now connecting", []).append(config)
                    scanner.spawn_connection_task(
                        tag, check_tag, config, args.station, timeout=10
                    )
                    id_time[tag.id] = now
                    last_time = now

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
parser.add_argument("--station", type=int, required=True, help="Station ID")
args = parser.parse_args()
if args.debug:
    nametag.logging_setup.enable_debug()

asyncio.run(run(args))
