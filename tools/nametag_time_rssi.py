#!/usr/bin/env python3

import argparse
import asyncio
import datetime
import logging
from pathlib import Path

import PIL  # type: ignore
import PIL.Image  # type: ignore
import PIL.ImageDraw  # type: ignore
import PIL.ImageFont  # type: ignore

import nametag.bluetooth
import nametag.logging_setup
import nametag.protocol

fonts_dir = Path(__file__).parent.parent / "external" / "fonts"
font_path = fonts_dir / "Spartan-Bold.ttf"
loaded_font = PIL.ImageFont.truetype(str(font_path), 10)


async def update_rssi(
    conn: nametag.bluetooth.Connection, tag: nametag.bluetooth.ScanTag
):
    image = PIL.Image.new("1", (48, 12))
    draw = PIL.ImageDraw.Draw(image)
    center_xy = (image.size[0] / 2, image.size[1] / 2)

    text = f"{datetime.datetime.now().strftime('%H:%M')}{tag.rssi}"
    draw.text(center_xy, text, fill=1, font=loaded_font, anchor="mm")
    steps = nametag.protocol.show_frames([image], msec=1000)

    logging.info(f'[{tag.id}] Showing "{text}"')
    await conn.do_steps(steps)


async def run(args):
    logging.info("Starting scanner...")
    async with nametag.bluetooth.Scanner(
        adapter=args.adapter, toggle_interval=args.toggle_interval
    ) as scan:
        while True:
            scan.harvest_tasks()
            visible = scan.tags
            logging.info(f"Scanning: {' '.join(sorted(t.id for t in visible))}")
            for tag in visible:
                if tag.id in scan.tasks:
                    logging.debug(f"[{tag.id}] Update in progress...")
                elif not tag.rssi:
                    logging.debug(f"[{tag.id}] No RSSI data...")
                elif len(scan.tasks) >= 5:
                    logging.debug(f"[{tag.id}] Waiting for others...")
                else:
                    logging.info(f"[{tag.id}] Connecting...")
                    scan.spawn_connection_task(tag, update_rssi, tag)

            await asyncio.sleep(1.0)


parser = argparse.ArgumentParser()
parser.add_argument("--adapter", default="hci0", help="BT interface")
parser.add_argument("--debug", action="store_true")
parser.add_argument("--toggle_interval", type=float, default=10.0)
args = parser.parse_args()
if args.debug:
    nametag.logging_setup.enable_debug()

asyncio.run(run(args))
