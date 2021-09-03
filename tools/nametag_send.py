#!/usr/bin/env python3

import argparse
import asyncio
import logging
import sys
import time
from pathlib import Path
from typing import List, Tuple

import PIL.Image  # type: ignore

sys.path.append(str(Path(__file__).parent.parent))
import nametag.bluetooth
import nametag.logging
import nametag.protocol

logging.getLogger().setLevel(logging.DEBUG)
logging.getLogger("asyncio").setLevel(logging.INFO)
logging.getLogger("bleak").setLevel(logging.INFO)

parser = argparse.ArgumentParser()
dev_group = parser.add_argument_group("Device matching")
dev_group.add_argument("--adapter", default="hci0", help="BT interface")
dev_group.add_argument("--address", default="", help="MAC to address")
dev_group.add_argument("--code", default="", help="Device code to find")

parser.add_argument("--retry_time", type=float, default=5.0, help="Step retry")
parser.add_argument("--fail_time", type=float, default=30.0, help="Timeout")

parser.add_argument("--packets", nargs="+", help="Raw packets hex file")
parser.add_argument("--frames", nargs="+", help="Animation image files")
parser.add_argument("--frame_msec", type=int, default=200, help="Frame time")
parser.add_argument("--glyphs", nargs="+", help="Glyph image files")
parser.add_argument("--mode", type=int, help="Mode to set")
parser.add_argument("--speed", type=int, help="Speed to set")
parser.add_argument("--brightness", type=int, help="Brightness to set (0-255)")
args = parser.parse_args()

steps: List[nametag.protocol.ProtocolStep] = []

print("=== Processing send command(s) ===")

if args.packets:
    for packets_path in args.packets:
        print(f"Raw packets: {packets_path}")
        with open(packets_path) as hex_file:
            for line in hex_file:
                line = line.strip().replace(":", " ")
                if line:
                    data = bytes.fromhex(line)
                    step = nametag.protocol.ProtocolStep(data, None)
                else:
                    step = nametag.protocol.ProtocolStep(None, b"")
                steps.append(step)

if args.frames:
    frames: List[PIL.Image.Image] = []
    for frame_path in args.frames:
        print(f"Frame image: {frame_path}")
        frame = PIL.Image.open(frame_path).convert(mode="1")
        frames.append(frame.resize((48, 12)))

    frame_data = nametag.protocol.show_frames(frames, msec=args.frame_msec)
    steps.extend(frame_data)
    print()

if args.glyphs:
    glyphs: List[PIL.Image.Image] = []
    for glyph_path in args.glyphs:
        print(f"Glyph image: {glyph_path}")
        glyph = PIL.Image.open(glyph_path).convert(mode="1")
        new_width = glyph.size[0] * 12 // glyph.size[1]
        glyphs.append(glyph.resize((new_width, 12)))

    steps.extend(nametag.protocol.show_glyphs(glyphs))
    print()

if args.mode is not None:
    print(f"Set mode: {args.mode}")
    steps.extend(nametag.protocol.set_mode(args.mode))

if args.speed is not None:
    print(f"Set speed: {args.speed}")
    steps.extend(nametag.protocol.set_speed(args.speed))

if args.brightness is not None:
    print(f"Set brightness: {args.brightness}")
    steps.extend(nametag.protocol.set_brightness(args.brightness))

if not steps:
    print("No command requests (see --help for options)")
    sys.exit(0)

print(f"{len(steps)} packets")
print()


async def run():
    print("=== Finding nametag ===")
    last_print = 0.0
    async with nametag.bluetooth.Scanner(adapter=args.adapter) as scanner:
        while True:
            visible = scanner.visible_tags()
            matched = [
                d
                for d in visible
                if args.address.lower() in (d.address.lower(), "")
                and args.code.upper() in (d.code.upper(), "")
            ]

            now = time.monotonic()
            if matched or now - last_print >= 1.0:
                last_print = now
                if not visible:
                    print("No nametags found, scanning...")
                else:
                    print(f"Matched {len(matched)} of {len(visible)} nametags:")
                    for d in visible:
                        match = "*" if d in matched else " "
                        print(f"{match} {d.code} ({d.address}) rssi={d.rssi}")
                    print()

            if matched:
                print("=== Connecting to nametag {matched[0].code} ===")
                async with nametag.bluetooth.RetryConnection(
                    matched[0],
                    retry_time=args.retry_time,
                    fail_time=args.fail_time,
                ) as connection:
                    await connection.do_steps(steps)
                break

            await asyncio.sleep(0.1)

    print()


asyncio.run(run())
