#!/usr/bin/env python3

import argparse
import asyncio
import logging

from nametag import logging_setup, scanner


async def test_task(tag, args):
    raw_packet = b"\x89\x3D"
    await tag.adapter.write(tag.dev, 3, raw_packet)
    await tag.adapter.flush(tag.dev)
    readback = await tag.adapter.read(tag.dev, 3)
    if readback.startswith(raw_packet):
        print(f"Successful loop: {readback!r}")
    else:
        raise scanner.StopScanningException(
            f"SENT {raw_packet!r}, GOT {readback!r}"
        )

    # stash_write = b"\x03GAM\x00\x00MAN"
    # await tag.write_stash(stash_write)
    # stash_read = await tag.read_stash()
    # assert stash_read == stash_write


parser = argparse.ArgumentParser()
parser.add_argument("--debug", action="store_true")
parser.add_argument("--port")
args = parser.parse_args()
if args.debug:
    logging_setup.enable_debug()

asyncio.run(scanner.scan_and_spawn(test_task, args), debug=args.debug)
