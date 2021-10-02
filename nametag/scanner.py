# Protocol encoding for the nametag (see bluetooth.py for hardware access)

import asyncio
import logging
import time
from typing import Callable, Dict, List, Optional

import attr

import nametag.bluefruit
import nametag.protocol

logger = logging.getLogger(__name__)


@attr.define
class ScannerOptions:
    success_delay: float = 30.0
    attempt_delay: float = 0.0
    loop_delay: float = 0.1
    maximum_age: float = 5.0
    minimum_rssi: int = -80
    task_timeout: float = 30.0
    status_interval: float = 0.5


async def scan_and_spawn(
    adapter: nametag.bluefruit.Bluefruit,
    runner: Callable,
    *args,
    options: ScannerOptions = ScannerOptions(),
    **kwargs,
):
    id_task: Dict[str, asyncio.Task] = {}
    id_attempt_mono: Dict[str, float] = {}
    id_success_mono: Dict[str, float] = {}

    def spawn_connection(id: str, dev: nametag.bluefruit.Device):
        tag = nametag.protocol.Nametag(adapter=adapter, dev=dev)

        async def tag_task():
            logger.debug(f"[{tag.id}] Connecting...")
            adapter.busy_connecting.remove(tag.dev.addr)  # Handoff
            async with tag:
                logger.debug(f"[{tag.id}] Connected, running tag task...")
                await asyncio.wait_for(
                    runner(tag, *args, **kwargs), timeout=options.task_timeout
                )
                logger.debug(f"[{tag.id}] Tag task complete, flushing...")
                await tag.flush()
                logger.debug(f"[{tag.id}] Flush complete, disconnecting...")

        def task_done(task):
            adapter.busy_connecting.discard(tag.dev.addr)
            assert id_task.pop(tag.id) is task
            try:
                task.result()
                id_success_mono[tag.id] = time.monotonic()
                logger.debug(f"[{tag.id}] Tag task successful")
            except asyncio.CancelledError:
                logger.debug(f"[{tag.id}] Tag task cancelled")
            except nametag.bluefruit.BluefruitError as exc:
                logger.warning(f"[{tag.id}] {exc}")
            except Exception:
                logger.error(f"[{tag.id}] Tag task failed", exc_info=True)

        assert tag.id not in id_task
        assert not adapter.busy_connecting
        id_attempt_mono[tag.id] = time.monotonic()
        adapter.busy_connecting.add(tag.dev.addr)
        task = id_task[tag.id] = asyncio.create_task(tag_task())
        task.add_done_callback(task_done)

    def priority(id: str):
        success_mono = id_success_mono.get(id, 0.0)
        attempt_mono = id_attempt_mono.get(id, 0.0)
        return (success_mono, attempt_mono, id)

    try:
        logging.debug("Starting scan loop...")
        next_status_monotime = 0.0
        while True:
            mono = time.monotonic()
            id_dev = [
                (tag_id, dev)
                for dev in adapter.devices().values()
                for tag_id in [nametag.protocol.id_if_nametag(dev)]
                if tag_id and dev.monotime > mono - 2 * options.maximum_age
            ]

            id_dev.sort(key=lambda id_dev: priority(id_dev[0]))
            spawned = False
            id_status: Dict[str, str] = {}
            for id, dev in id_dev:
                delay_end = max(
                    id_dict.get(id, -delay_opt) + delay_opt
                    for id_dict, delay_opt in [
                        (id_success_mono, options.success_delay),
                        (id_attempt_mono, options.attempt_delay),
                    ]
                )

                dev.fully_disconnected
                if dev.fully_connected:
                    id_status[id] = f"|{id}|"
                elif not dev.fully_disconnected:
                    id_status[id] = f":{id}:"
                elif id in id_task:
                    id_status[id] = f".{id}."
                elif mono < delay_end:
                    id_status[id] = f"+{id}+"
                elif dev.monotime < mono - options.maximum_age:
                    id_status[id] = f"/{id}/"
                elif dev.rssi <= options.minimum_rssi or not dev.rssi:
                    id_status[id] = f"-{id}-"
                elif not adapter.ready_to_connect(dev):
                    id_status[id] = f"({id})"
                else:
                    id_status[id] = f"*{id}*"
                    spawn_connection(id, dev)
                    spawned = True

            for id in id_task.keys():
                id_status.setdefault(id, f"_{id}_")

            if mono >= next_status_monotime or spawned:
                status = " ".join(s for id, s in sorted(id_status.items()))
                logging.info("Tags: " + (status or "(none)"))
                next_status_monotime = mono + options.status_interval

            await asyncio.sleep(options.loop_delay)

    finally:
        if id_task:
            logger.debug(f"Stopping {len(id_task)} tasks pre-exit...")
            [task.cancel() for task in id_task.values()]
            await asyncio.wait(id_task.values())
            logger.debug("All tasks stopped, exiting...")


if __name__ == "__main__":
    import argparse

    import nametag.logging_setup

    async def test_task(tag):
        print(f"  [{tag.id}] connected, reading...")
        stash = await tag.read_stash()
        print(f"  [{tag.id}] stash is {stash}, writing 'HELLO'...")
        await tag.write_stash(b"HELLO")
        print(f"  [{tag.id}] wrote, disconnecting...")

    async def test_main(args):
        async with nametag.bluefruit.Bluefruit(port=args.port) as adapter:
            await scan_and_spawn(adapter=adapter, runner=test_task)

    parser = argparse.ArgumentParser()
    parser.add_argument("--debug", action="store_true")
    parser.add_argument("--port")
    args = parser.parse_args()
    if args.debug:
        nametag.logging_setup.enable_debug()

    asyncio.run(test_main(args), debug=args.debug)
