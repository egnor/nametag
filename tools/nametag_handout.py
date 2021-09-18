#!/usr/bin/env python3

import argparse
import asyncio
import logging
from typing import Dict, List, Tuple

import nametag.bluetooth
import nametag.logging_setup
import nametag.protocol


async def send_handout(
    tag: nametag.bluetooth.ScanTag,
    path: str,
    steps: List[nametag.protocol.ProtocolStep],
):
    logging.info(f"[{tag.code}] Connecting to send {path}")
    async with nametag.bluetooth.RetryConnection(tag) as conn:
        logging.info(f"[{tag.code}] Sending {path}")
        await conn.do_steps(steps)
        logging.info(f"[{tag.code}] Sent {path}")


async def run(args):
    handouts: List[Tuple[str, List[nametag.protocol.ProtocolStep]]] = []
    for path in args.tagsetup:
        logging.info(f"Loading: {path}")
        with open(path, "r") as file:
            steps = list(nametag.protocol.from_str(file.read()))
            handouts.append((path, steps))

    logging.info("Starting scanner")
    async with nametag.bluetooth.Scanner(adapter=args.adapter) as scanner:
        code_task: Dict[str, asyncio.Task] = {}
        while True:
            logging.info(
                "Scanning... "
                f"handouts={len(handouts)} "
                f"started={len(code_task)} "
                f"finished={sum(t.done() for t in code_task.values())} "
            )
            for tag in scanner.visible_tags():
                if tag.code not in code_task:
                    if len(code_task) >= len(handouts):
                        logging.warn(f"{tag.code}: OUT OF HANDOUTS")
                        code_task[tag.code] = None
                    else:
                        path, steps = handouts[len(code_task)]
                        coro = send_handout(tag, path, steps)
                        task = asyncio.create_task(coro, name=tag.code)
                        code_task[tag.code] = task

            await asyncio.sleep(0.5)


parser = argparse.ArgumentParser()
parser.add_argument("--adapter", default="hci0", help="BT interface")
parser.add_argument("tagsetup", nargs="+", help="tagsetup files to hand out")

args = parser.parse_args()
asyncio.run(run(args))
