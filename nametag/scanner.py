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
    status_interval: float = 0.5


async def scan_and_spawn(
    adapter: nametag.bluefruit.Bluefruit,
    runner: Callable,
    *args,
    options: ScannerOptions = ScannerOptions(),
    **kwargs,
):
    @attr.define
    class State:
        task: Optional[asyncio.Task] = None
        attempt_monotime: float = 0.0
        success_monotime: float = 0.0

    states: Dict[str, State] = {}

    def spawn_connection(id: str, dev: nametag.bluefruit.Device):
        tag = nametag.protocol.Nametag(adapter=adapter, dev=dev)
        state = states.setdefault(id, State())

        async def tag_task():
            try:
                logger.debug(f"[{tag.id}] Connecting...")
                adapter.busy_connecting.remove(tag.dev.addr)  # Handoff
                async with tag:
                    logger.debug(f"[{tag.id}] Connected, running task...")
                    await runner(tag, *args, **kwargs)
                    logger.debug(f"[{tag.id}] Task complete, disconnecting...")
                state.success_monotime = time.monotonic()
                logger.debug(f"[{tag.id}] Done and disconnected")
            except asyncio.CancelledError:
                pass
            except nametag.bluefruit.BluefruitError as e:
                logger.error(f"[{tag.id}] {e}")
            except Exception:
                logger.error(f"[{tag.id}] Task failed", exc_info=True)

        def task_done(task):
            adapter.busy_connecting.discard(tag.dev.addr)
            assert state.task is task
            state.task = None

        assert not state.task
        assert not adapter.busy_connecting
        state.attempt_monotime = time.monotonic()
        state.task = asyncio.create_task(tag_task())
        adapter.busy_connecting.add(tag.dev.addr)
        state.task.add_done_callback(task_done)

    def priority(id: str):
        return ((states.get(id) or State()).attempt_monotime, id)

    try:
        logging.debug("Starting scan loop...")
        next_status_monotime = 0.0
        while True:
            mono = time.monotonic()
            found = {
                id: dev
                for dev in adapter.scan.values()
                for id in [nametag.protocol.id_if_nametag(dev)]
                if id
            }

            found = dict(sorted(found.items(), key=lambda kv: priority(kv[0])))
            spawned = False
            status: List[str] = []
            for id, dev in found.items():
                state = states.get(id) or State()
                if dev.fully_connected:
                    status.append(f"|{id}|")
                elif not dev.fully_disconnected:
                    status.append(f":{id}:")
                elif state.task:
                    status.append(f".{id}.")
                elif mono < state.success_monotime + options.success_delay:
                    status.append(f"<{id}>")
                elif mono < state.attempt_monotime + options.attempt_delay:
                    status.append(f"<{id}>")
                elif mono > dev.monotime + options.maximum_age:
                    status.append(f"/{id}/")
                elif dev.rssi <= options.minimum_rssi or not dev.rssi:
                    status.append(f"-{id}-")
                elif not adapter.ready_to_connect(dev):
                    status.append(f"({id})")
                else:
                    spawn_connection(id, dev)
                    status.append(f"*{id}*")
                    spawned = True

            if mono >= next_status_monotime or spawned:
                logging.info("Tags: " + (" ".join(status) or "(none)"))
                next_status_monotime = mono + options.status_interval

            await asyncio.sleep(options.loop_delay)

    finally:
        tasks = [state.task for state in states.values() if state.task]
        if tasks:
            logger.debug("Waiting for {len(tasks)} tasks...")
            [task.cancel() for task in tasks]
            await asyncio.gather(*tasks, return_exceptions=True)
            logger.debug("All tasks complete")


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
    parser.add_argument("--port", default="/dev/ttyACM0")
    args = parser.parse_args()
    if args.debug:
        nametag.logging_setup.enable_debug()

    asyncio.run(test_main(args))
