#!/usr/bin/env python3

import argparse
import asyncio
import logging
from typing import Any, Dict, List, Optional, Tuple

import nametag.bluetooth
import nametag.logging_setup
import nametag.protocol


async def send_handout(
    conn: nametag.bluetooth.Connection,
    tag: nametag.bluetooth.ScanTag,
    path: str,
    steps: List[nametag.protocol.ProtocolStep],
):
    logging.info(f"[{tag.id}] Sending ({path})")
    await conn.do_steps(steps)
    logging.info(f"[{tag.id}] Sent ({path})")
    return True


async def run(args):
    handouts: List[Tuple[str, List[nametag.protocol.ProtocolStep]]] = []
    for path in args.tagsetup:
        logging.info(f"Loading: {path}")
        with open(path, "r") as file:
            steps = list(nametag.protocol.from_str(file.read()))
            handouts.append((path, steps))

    id_done: Dict[str, Optional[bool]] = {}
    logging.info("Starting scanner")
    async with nametag.bluetooth.Scanner(adapter=args.adapter) as scan:
        while True:
            id_done.update(scan.harvest_tasks())
            logging.info(
                "Scanning... "
                f"visible={len(scan.tags)} "
                f"started={len(id_done)} "
                f"running={len(scan.tasks)} "
                f"done={sum(1 for r in id_done.values() if r == True)} "
                f"handouts={len(handouts)}"
            )
            for tag in scan.tags:
                if (
                    len(scan.tasks) < args.connections
                    and tag.id not in scan.tasks
                    and (args.loop or not id_done.get(tag.id))
                ):
                    path, st = handouts[len(id_done) % len(handouts)]
                    scan.spawn_connection_task(tag, send_handout, tag, path, st)
                    id_done.setdefault(tag.id, False)

            await asyncio.sleep(1.0)


parser = argparse.ArgumentParser()
parser.add_argument("--adapter", default="hci0", help="BT interface")
parser.add_argument("--debug", action="store_true")
parser.add_argument("--connections", type=int, default=5, help="Concurrency")
parser.add_argument("--loop", action="store_true", help="Keep reprogramming")
parser.add_argument("tagsetup", nargs="+", help="tagsetup files to hand out")

args = parser.parse_args()
if args.debug:
    nametag.logging_setup.enable_debug()

asyncio.run(run(args))
