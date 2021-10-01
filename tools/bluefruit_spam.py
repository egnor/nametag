#!/usr/bin/env python3

import argparse
import asyncio
import logging
import time

import nametag.bluefruit
import nametag.logging_setup


async def run(args):
    async with nametag.bluefruit.Bluefruit(port=args.port) as adapter:
        start_mono = time.monotonic()
        next_status = 0.0
        while True:
            adapter.send_echo(b"01234567" * 16)
            elapsed = time.monotonic() - start_mono
            r_bytes = adapter.totals["read"]
            w_bytes = adapter.totals["write"]
            await asyncio.sleep(max(0, (w_bytes / args.bps) - elapsed))
            if elapsed > next_status:
                logging.info(
                    f"=== tx={w_bytes}b/{elapsed:.1f}s"
                    f"={w_bytes/elapsed:.1f}bps "
                    f"| rx={r_bytes}b/{elapsed:.1f}s"
                    f"={r_bytes/elapsed:.1f}bps ==="
                )
                next_status += 1.0


parser = argparse.ArgumentParser()
parser.add_argument("--port", default="/dev/ttyACM0")
parser.add_argument("--debug", action="store_true")
parser.add_argument("--bps", type=float, default=1024)

args = parser.parse_args()
if args.debug:
    nametag.logging_setup.enable_debug()

asyncio.run(run(args), debug=args.debug)
