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
                logger.debug(f"[{tag.id}] Task cancelled")
                raise
            except nametag.bluefruit.BluefruitError as exc:
                logger.error(f"[{tag.id}] {exc}")  # Common; skip stack trace
            except Exception:
                logger.error(f"[{tag.id}] Task failed", exc_info=True)
                raise

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
        state = states.get(id) or State()
        return (state.success_monotime, state.attempt_monotime, id)

    try:
        logging.debug("Starting scan loop...")
        next_status_monotime = 0.0
        while True:
            adapter.check_running()
            mono = time.monotonic()
            found = {
                id: dev
                for dev in adapter.scan.values()
                for id in [nametag.protocol.id_if_nametag(dev)]
                if id
            }

            found = dict(sorted(found.items(), key=lambda kv: priority(kv[0])))
            spawned = False
            status: Dict[str, str] = {}
            for id, dev in found.items():
                state = states.get(id) or State()
                if dev.fully_connected:
                    status[id] = f"|{id}|"
                elif not dev.fully_disconnected:
                    status[id] = f":{id}:"
                elif state.task:
                    status[id] = f".{id}."
                elif mono < state.success_monotime + options.success_delay:
                    status[id] = f"<{id}>"
                elif mono < state.attempt_monotime + options.attempt_delay:
                    status[id] = f"<{id}>"
                elif mono > dev.monotime + options.maximum_age:
                    status[id] = f"/{id}/"
                elif dev.rssi <= options.minimum_rssi or not dev.rssi:
                    status[id] = f"-{id}-"
                elif not adapter.ready_to_connect(dev):
                    status[id] = f"({id})"
                else:
                    status[id] = f"*{id}*"
                    spawn_connection(id, dev)
                    spawned = True

            if mono >= next_status_monotime or spawned:
                status_list = [v for k, v in sorted(status.items())]
                logging.info("Tags: " + (" ".join(status_list) or "(none)"))
                next_status_monotime = mono + options.status_interval

            await asyncio.sleep(options.loop_delay)

    finally:
        tasks = [state.task for state in states.values() if state.task]
        if tasks:
            logger.debug(f"Waiting for {len(tasks)} tasks...")
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
