#!/usr/bin/env python3

import argparse
import asyncio
import datetime
import logging
import sys
from pathlib import Path

import PIL  # type: ignore
import PIL.Image  # type: ignore
import PIL.ImageDraw  # type: ignore
import PIL.ImageFont  # type: ignore

sys.path.append(str(Path(__file__).parent.parent))
import nametag.bluetooth
import nametag.logging_setup
import nametag.protocol


class ClockUpdater:
    def __init__(self):
        fonts_dir = Path(__file__).parent.parent / "assets" / "fonts"
        font_path = fonts_dir / "OperatorMonoSSm-Bold.otf"
        self.font = PIL.ImageFont.truetype(str(font_path), 15)
        self.images = [PIL.Image.new("1", (48, 12)) for i in range(2)]

    def update_steps(self):
        for i, im in enumerate(self.images):
            sep = " " if i else ":"
            text = datetime.datetime.now().strftime(f"%H{sep}%M")
            if i == 0:
                print(f'Updating: "{text}"...')

            im.paste(0, box=(0, 0) + im.size)
            draw = PIL.ImageDraw.Draw(im)
            center_xy = (im.size[0] / 2, im.size[1] / 2)
            draw.text(center_xy, text, fill=1, font=self.font, anchor="mm")

        return nametag.protocol.show_frames(self.images, msec=500)
        return list(nametag.protocol.set_brightness(255)) + list(
            nametag.protocol.show_frames(self.images, msec=500)
        )


async def run():
    parser = argparse.ArgumentParser()
    parser.add_argument("--adapter", default="hci0", help="BT interface")
    parser.add_argument("--code", default="", help="Device code to find")
    parser.add_argument("--update_time", type=float, default=60.0)
    args = parser.parse_args()

    async with nametag.bluetooth.Scanner(adapter=args.adapter) as scanner:
        found = None
        while not found:
            for dev in scanner.visible_tags():
                if args.code.upper() in ("", dev.code.upper()):
                    found = dev
                    break

            print("Scanning...")
            await asyncio.sleep(1.0)

        print(f"Connecting: {found.code} ({found.address})")
        async with nametag.bluetooth.RetryConnection(
            found,
            connect_time=10,
            io_time=5,
            fail_time=None,
        ) as connection:
            clock = ClockUpdater()
            while True:
                await connection.do_steps(clock.update_steps())
                await asyncio.sleep(args.update_time)


asyncio.run(run())
