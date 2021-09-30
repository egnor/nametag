#!/usr/bin/env -S python3 -u

import argparse
import asyncio
import logging
import re
import sys
import time
from typing import List, Tuple

import PIL.Image  # type: ignore

# import nametag.aseprite_loader
import nametag.bluefruit
import nametag.logging_setup
import nametag.protocol


async def send_to_nametag(tag: nametag.protocol.Nametag, args):
    if args.mode is not None:
        print(f"Setting mode: {args.mode}")
        await tag.set_mode(args.mode)

    if args.scroll_speed is not None:
        print(f"Setting scroll speed: {args.scroll_speed}")
        await tag.set_speed(args.scroll_speed)

    if args.brightness is not None:
        print(f"Setting brightness: {args.brightness} (of 255)")
        await tag.set_brightness(args.brightness)

    if args.packets:
        for packets_path in args.packets:
            print(f"Sending raw packets: {packets_path}")
            with open(packets_path) as hex_file:
                for line in hex_file:
                    line = line.strip().replace(":", " ")
                    if line:
                        await tag.send_raw_packet(bytes.fromhex(line))
                    else:
                        pass
                        # todo: wait for any notification

    if args.frames:
        frames: List[PIL.Image.Image] = []
        for frame_path in args.frames:
            print(f"Frame image: {frame_path}")
            frame = PIL.Image.open(frame_path).convert(mode="1")
            frames.append(frame.resize((48, 12)))

        await tag.show_frames(frames, msec=args.frame_msec)
        print()

    if args.glyphs:
        glyphs: List[PIL.Image.Image] = []
        for glyph_path in args.glyphs:
            print(f"Glyph image: {glyph_path}")
            glyph = PIL.Image.open(glyph_path).convert(mode="1")
            size = (glyph.size[0] * 12 // glyph.size[1], 12)
            glyph = glyph.resize(size) if size != glyph.size else glyph
            if args.glyph_spacing:
                pad_size = (size[0] + args.glyph_spacing, size[1])
                pad_glyph = PIL.Image.new(mode="1", size=pad_size, color=0)
                pad_glyph.paste(glyph, (0, 0))
                glyph = pad_glyph
            glyphs.append(glyph)

        await tag.show_glyphs(glyphs)
        print()

    if args.stash is not None:
        data = bytes.fromhex(args.stash)
        print(f"Setting data stash: {data.hex()}")
        await tag.write_stash(data)


async def talk_to_nametag(tag: nametag.protocol.Nametag, args):
    print("Connected, reading data stash...")
    stash = await tag.read_stash()
    if stash:
        print(f"Found stash ({stash.hex()}), sending...")
    else:
        print("No data stash, sending...")
    for r in range(args.repeat):
        await send_to_nametag(tag, args)
    print("Done sending, disconnecting...")


async def run(args):
    print("=== Finding nametag ===")
    next_print = 0.0
    async with nametag.bluefruit.Bluefruit(port=args.port) as fruit:
        while True:
            tags = nametag.protocol.find_nametags(fruit)

            matched = {
                id: dev
                for id, dev in tags.items()
                if args.address.lower() in (dev.addr.lower(), "")
                and args.id.upper() in (id.upper(), "")
            }

            now = time.monotonic()
            if matched or now >= next_print:
                next_print = now + 1.0
                if not tags:
                    print("No nametags found, scanning...")
                else:
                    print(f"Matched {len(matched)} of {len(tags)} tags:")
                    for id, dev in tags.items():
                        match = "*" if id in matched else " "
                        print(f"{match} {id} {dev}")
                    print()

            if matched:
                id, dev = next(iter(matched.items()))
                print(f"=== Connecting to nametag {id} ===")
                try:
                    async with nametag.protocol.Nametag(fruit, dev) as tag:
                        await talk_to_nametag(tag, args)
                    print("Done and disconnected.")
                    break
                except nametag.bluefruit.BluefruitError as e:
                    print(f"*** {e}")
                print()

            await asyncio.sleep(0.1)


parser = argparse.ArgumentParser()
parser.add_argument("--port", default="/dev/ttyACM0")
parser.add_argument("--debug", action="store_true")

dev_group = parser.add_mutually_exclusive_group()
dev_group.add_argument("--address", default="", help="MAC to address")
dev_group.add_argument("--id", default="", help="Device ID to find")

send_group = parser.add_argument_group("Commands to send")
send_group.add_argument("--packets", nargs="+", help="Raw packets hex file")
send_group.add_argument("--frames", nargs="+", help="Animation image files")
send_group.add_argument("--frame_msec", type=int, default=200, help="Per frame")
send_group.add_argument("--glyphs", nargs="+", help="Character image files")
send_group.add_argument("--glyph_spacing", type=int, default=0, help="Pixels")
send_group.add_argument("--mode", type=int, help="Mode to set")
send_group.add_argument("--scroll_speed", type=int, help="Scrolling (0-255)")
send_group.add_argument("--brightness", type=int, help="Brightness (0-255)")
send_group.add_argument("--stash", help="Hex bytes to stash on device")
send_group.add_argument("--repeat", type=int, default=1, help="Times to loop")
send_group.add_argument("--timeout", type=float, default=60.0)

args = parser.parse_args()
if args.debug:
    nametag.logging_setup.enable_debug()

asyncio.run(run(args))
