#!/usr/bin/env python3

import argparse
import asyncio
import logging
import time

from nametag import bluefruit, logging_setup


async def run(args):
    async with bluefruit.Bluefruit(port=args.port) as adapter:
        start_mono = time.monotonic()
        next_status = 0.0
        while True:
            await adapter.send_dummy(b"x" * args.packet)
            elapsed = time.monotonic() - start_mono
            read_total = adapter.totals["read"]
            write_total = adapter.totals["write"]
            delay = (write_total / args.bps) - elapsed
            await asyncio.sleep(max(0, min(1, delay)))
            if elapsed > next_status:
                logging.info(
                    f"=== tx={write_total}b/{elapsed:.1f}s"
                    f"={write_total/elapsed:.1f}Bps "
                    f"| rx={read_total}b/{elapsed:.1f}s"
                    f"={read_total/elapsed:.1f}Bps ==="
                )
                next_status += 1.0


parser = argparse.ArgumentParser()
parser.add_argument("--port")
parser.add_argument("--debug", action="store_true")
parser.add_argument("--bps", type=float, default=1000000)
parser.add_argument("--packet", type=int, default=128)

args = parser.parse_args()
if args.debug:
    logging_setup.enable_debug()

asyncio.run(run(args), debug=args.debug)
