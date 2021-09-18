#!/usr/bin/env python3

import argparse
import asyncio
import logging
from typing import Dict, List, Set, Tuple

import nametag.bluetooth
import nametag.logging_setup
import nametag.protocol


async def send_handout(
    tag: nametag.bluetooth.ScanTag,
    path: str,
    steps: List[nametag.protocol.ProtocolStep],
):
    logging.info(f"[{tag.code}] Connecting ({path})")
    async with nametag.bluetooth.RetryConnection(tag) as conn:
        logging.info(f"[{tag.code}] Sending ({path})")
        await conn.do_steps(steps)
        logging.info(f"[{tag.code}] Sent ({path})")
    logging.info(f"[{tag.code}] Done ({path})")


async def run(args):
    handouts: List[Tuple[str, List[nametag.protocol.ProtocolStep]]] = []
    for path in args.tagsetup:
        logging.info(f"Loading: {path}")
        with open(path, "r") as file:
            steps = list(nametag.protocol.from_str(file.read()))
            handouts.append((path, steps))

    code_task: Dict[str, asyncio.Task] = {}
    code_out: Set[str] = set()

    try:
        logging.info("Starting scanner")
        async with nametag.bluetooth.Scanner(adapter=args.adapter) as scanner:
            while True:
                visible = scanner.visible_tags()
                logging.info(
                    "Scanning... "
                    f"handouts={len(handouts)} "
                    f"started={len(code_task)} "
                    f"finished={sum(t.done() for t in code_task.values())} "
                    f"visible={len(visible)}"
                )
                for tag in visible:
                    if tag.code not in code_task and tag.code not in code_out:
                        if len(code_task) >= len(handouts):
                            logging.warning(f"{tag.code}: OUT OF HANDOUTS")
                            code_out.add(tag.code)
                        else:
                            path, steps = handouts[len(code_task)]
                            coro = send_handout(tag, path, steps)
                            task = asyncio.create_task(coro, name=tag.code)
                            code_task[tag.code] = task

                await asyncio.sleep(0.5)

    finally:
        for code, task in code_task.items():
            if not task.done():
                logging.warning(f"{code}: Cancelling task...")
                task.cancel("Cancelled by program shutdown")
            try:
                await task
            except BaseException as exc:  # includes ^C
                logging.warning(f"{code}: {str(exc) or type(exc).__name__}")


parser = argparse.ArgumentParser()
parser.add_argument("--adapter", default="hci0", help="BT interface")
parser.add_argument("tagsetup", nargs="+", help="tagsetup files to hand out")

args = parser.parse_args()
asyncio.run(run(args))
