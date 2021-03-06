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

from nametag import logging_setup, protocol, scanner

fonts_dir = Path(__file__).resolve().parent.parent / "external" / "fonts"
font_path = fonts_dir / "Spartan-Bold.ttf"
loaded_font = PIL.ImageFont.truetype(str(font_path), 10)


async def update_rssi(tag: protocol.Nametag):
    image = PIL.Image.new("1", (48, 12))
    draw = PIL.ImageDraw.Draw(image)
    center_xy = (image.size[0] / 2, image.size[1] / 2)

    text = f"{datetime.datetime.now().strftime('%H:%M')}{tag.dev.rssi}"
    draw.text(center_xy, text, fill=1, font=loaded_font, anchor="mm")
    logging.info(f'[{tag.id}] Showing "{text}"')
    await tag.show_frames([image], msec=1000)


parser = argparse.ArgumentParser()
parser.add_argument("--debug", action="store_true")
parser.add_argument("--toggle_interval", type=float, default=10.0)
args = parser.parse_args()
if args.debug:
    logging_setup.enable_debug()

options = scanner.ScannerOptions(success_delay=1.0)
scan_coro = scanner.scan_and_spawn(runner=update_rssi, options=options)
asyncio.run(scan_coro, debug=args.debug)
