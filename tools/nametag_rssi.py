#!/usr/bin/env python3

import argparse
import asyncio
from pathlib import Path

import PIL  # type: ignore
import PIL.Image  # type: ignore
import PIL.ImageDraw  # type: ignore
import PIL.ImageFont  # type: ignore

import nametag.bluetooth
import nametag.logging_setup
import nametag.protocol


async def run():
    parser = argparse.ArgumentParser()
    parser.add_argument("--adapter", default="hci0", help="BT interface")
    parser.add_argument("--code", default="", help="Device code to find")
    args = parser.parse_args()

    fonts_dir = Path(__file__).parent.parent / "assets" / "fonts"
    font_path = fonts_dir / "OperatorMonoSSm-Bold.otf"
    font = PIL.ImageFont.truetype(str(font_path), 15)
    image = PIL.Image.new("1", (48, 12))

    async with nametag.bluetooth.Scanner(adapter=args.adapter) as scanner:
        last_rssi = {}
        while True:
            print("Scanning...")
            for dev in scanner.visible_tags():
                if args.code.upper() not in ("", dev.code.upper()):
                    print(f"  {dev.code.upper()} - skipping per --code")
                    continue

                if last_rssi.get(dev.address) == dev.rssi:
                    print(f"  {dev.code.upper()}: {dev.rssi} (no change)")
                    continue

                print(f"  {dev.code.upper()}: {dev.rssi} - updating...")
                text = f"{dev.rssi}"
                image.paste(0, box=(0, 0) + image.size)
                draw = PIL.ImageDraw.Draw(image)
                center_xy = (image.size[0] / 2, image.size[1] / 2)
                draw.text(center_xy, text, fill=1, font=font, anchor="mm")
                steps = nametag.protocol.show_frames([image], msec=1000)

                try:
                    async with nametag.bluetooth.Connection(dev) as conn:
                        await conn.do_steps(steps)
                except nametag.bluetooth.BluetoothError as e:
                    print(f"    *** {str(e)}")
                    continue

                last_rssi[dev.address] = dev.rssi

            print()
            await asyncio.sleep(1.0)


asyncio.run(run())
