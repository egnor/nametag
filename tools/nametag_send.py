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

time_group = parser.add_argument_group("Timeouts")
time_group.add_argument("--connect_timeout", type=float, default=5.0)
time_group.add_argument("--io_timeout", type=float, default=2.0)
time_group.add_argument("--fail_timeout", type=float, default=30.0)

send_group = parser.add_argument_group("Commands to send")
send_group.add_argument("--packets", nargs="+", help="Raw packets hex file")
send_group.add_argument("--frames", nargs="+", help="Animation image files")
send_group.add_argument("--frame_msec", type=int, default=200, help="Per frame")
send_group.add_argument("--glyphs", nargs="+", help="Glyph image files")
send_group.add_argument("--mode", type=int, help="Mode to set")
send_group.add_argument("--scroll_msec", type=int, help="Frame msec")
send_group.add_argument("--brightness", type=int, help="Brightness (0-255)")
send_group.add_argument("--stash", help="Hex bytes to stash on device")

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

if args.scroll_msec is not None:
    print(f"Set scroll speed: {args.scroll_msec} msec")
    steps.extend(nametag.protocol.set_speed(args.scroll_msec))

if args.brightness is not None:
    print(f"Set brightness: {args.brightness} (of 255)")
    steps.extend(nametag.protocol.set_brightness(args.brightness))

if args.stash is not None:
    data = bytes.fromhex(args.stash)
    print(f"Set data stash: {data.hex()}")
    steps.extend(nametag.protocol.stash_data(data))

if not steps:
    print("No command requests (see --help for options)")
    sys.exit(0)

print(f"{len(steps)} packets to send")
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
                print(f"=== Connecting to nametag {matched[0].code} ===")
                async with nametag.bluetooth.RetryConnection(
                    matched[0],
                    connect_time=args.connect_timeout,
                    io_time=args.io_timeout,
                    fail_time=args.fail_timeout,
                ) as connection:
                    readback = await connection.readback()
                    stash = nametag.protocol.stash_from_readback(readback)
                    if stash:
                        print(f"Found data stash: {stash.hex()}")
                    else:
                        print("(No data stash found)")

                    await connection.do_steps(steps)
                break

            await asyncio.sleep(0.1)

    print()


asyncio.run(run())
