import argparse
import asyncio
import logging

from nametag import logging_setup, scanner


async def test_task(tag):
    print(f"  [{tag.id}] connected, reading...")
    stash = await tag.read_stash()
    # to_stash = b"HELLO"
    to_stash = b"\x03GAM\x00\x00MAN"
    print(f"  [{tag.id}] stash is {stash}, writing {to_stash}...")
    await tag.write_stash(to_stash)
    print(f"  [{tag.id}] wrote, disconnecting...")


parser = argparse.ArgumentParser()
parser.add_argument("--debug", action="store_true")
parser.add_argument("--port")
args = parser.parse_args()
if args.debug:
    logging_setup.enable_debug()

asyncio.run(scanner.scan_and_spawn(runner=test_task), debug=args.debug)
