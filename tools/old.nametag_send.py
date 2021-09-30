#!/usr/bin/env -S python3 -u

import argparse
import asyncio
import logging
import re
import sys
import time
from typing import List, Tuple

import PIL.Image  # type: ignore

import nametag.bluetooth
import nametag.logging_setup
import nametag.protocol

parser = argparse.ArgumentParser()
parser.add_argument("--adapter", default="hci0", help="BT interface")
parser.add_argument("--debug", action="store_true")

dev_group = parser.add_mutually_exclusive_group()
dev_group.add_argument("--address", default="", help="MAC to address")
dev_group.add_argument("--id", default="", help="Device ID to find")
dev_group.add_argument("--save_tagsetup", help="Save setup to file")

send_group = parser.add_argument_group("Commands to send")
send_group.add_argument("--tagsetup", help="Load setup from file")
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

print("=== Processing send command(s) ===")
steps: List[nametag.protocol.ProtocolStep] = []

if args.tagsetup:
    print(f"Loading setup: {args.tagsetup}")
    with open(args.tagsetup, "r") as load_file:
        steps.extend(nametag.protocol.from_str(load_file.read()))

if args.mode is not None:
    print(f"Set mode: {args.mode}")
    steps.extend(nametag.protocol.set_mode(args.mode))

if args.scroll_speed is not None:
    print(f"Set scroll speed: {args.scroll_speed}")
    steps.extend(nametag.protocol.set_speed(args.scroll_speed))

if args.brightness is not None:
    print(f"Set brightness: {args.brightness} (of 255)")
    steps.extend(nametag.protocol.set_brightness(args.brightness))

if args.packets:
    for packets_path in args.packets:
        print(f"Raw packets: {packets_path}")
        steps.append(nametag.protocol.ProtocolStep(packets=[]))
        with open(packets_path) as hex_file:
            for line in hex_file:
                line = line.strip().replace(":", " ")
                if line:
                    steps[-1].packets.append(bytes.fromhex(line))
                else:
                    steps[-1].confirm_regex = re.compile(b".*")
                    steps.append(nametag.protocol.ProtocolStep(packets=[]))

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
        size = (glyph.size[0] * 12 // glyph.size[1], 12)
        glyph = glyph.resize(size) if size != glyph.size else glyph
        if args.glyph_spacing:
            padded_size = (size[0] + args.glyph_spacing, size[1])
            padded_glyph = PIL.Image.new(mode="1", size=padded_size, color=0)
            padded_glyph.paste(glyph, (0, 0))
            glyph = padded_glyph
        glyphs.append(glyph)

    steps.extend(nametag.protocol.show_glyphs(glyphs))
    print()

if args.stash is not None:
    data = bytes.fromhex(args.stash)
    print(f"Set data stash: {data.hex()}")
    steps.extend(nametag.protocol.stash_data(data))

if not steps:
    print("No command requests (see --help for options)")
    sys.exit(1)

print(f"{len(steps)} packets to send")
print()

if args.save_tagsetup:
    print(f"Saving setup: {args.save_tagsetup}")
    with open(args.save_tagsetup, "w") as save_file:
        save_file.write(nametag.protocol.to_str(steps))
    print()
    sys.exit(0)


async def send_to_device(conn: nametag.bluetooth.Connection):
    print("Connected, reading data stash...")
    readback = await conn.readback()
    stash = nametag.protocol.unstash_readback(readback)
    if stash:
        print(f"Found stash ({stash.hex()}), sending...")
    else:
        print("No data stash, sending...")
    for r in range(args.repeat):
        await conn.do_steps(steps)
    print("Done sending, disconnecting...")
    print()
    return True


async def run():
    print("=== Finding nametag ===")
    next_print = 0.0
    async with nametag.bluetooth.Scanner(adapter=args.adapter) as scan:
        while True:
            if any(scan.harvest_tasks().values()):
                break

            if scan.tasks:
                await asyncio.sleep(0.1)
                continue  # Wait for task

            matched = [
                d
                for d in scan.tags
                if args.address.lower() in (d.address.lower(), "")
                and args.id.upper() in (d.id.upper(), "")
            ]

            now = time.monotonic()
            if matched or now >= next_print:
                next_print = now + 1.0
                if not scan.tags:
                    print("No nametags found, scanning...")
                else:
                    print(f"Matched {len(matched)} of {len(scan.tags)} tags:")
                    for d in scan.tags:
                        match = "*" if d in matched else " "
                        print(f"{match} {d.id} ({d.address}) rssi={d.rssi}")
                    print()

            if matched:
                print(f"=== Connecting to nametag {matched[0].id} ===")
                scan.spawn_connection_task(
                    matched[0], send_to_device, timeout=args.timeout
                )

            await asyncio.sleep(0.1)


asyncio.run(run())
