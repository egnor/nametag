# Protocol encoding for the nametag (see bluetooth.py for hardware access)

import asyncio
import copy
import logging
import time
from typing import Callable, Dict, List, Optional

import attr
import serial.tools.list_ports  # type: ignore

from nametag import bluefruit, protocol

logger = logging.getLogger(__name__)


@attr.define
class ScannerOptions:
    port_regex: str = "VID:PID=10C4:EA60"  # Serial.hwid / Serial.device
    success_delay: float = 30.0
    attempt_delay: float = 0.5
    loop_delay: float = 0.1
    maximum_age: float = 5.0
    minimum_rssi: int = -80
    task_timeout: float = 30.0
    status_interval: float = 0.5


class StopScanningException(Exception):
    pass


async def scan_and_spawn(
    runner: Callable,
    *args,
    options: ScannerOptions = ScannerOptions(),
    **kwargs,
):
    id_task: Dict[str, asyncio.Task] = {}
    id_attempt_mono: Dict[str, float] = {}
    id_success_mono: Dict[str, float] = {}
    stop_received = None

    def spawn_connection(
        adapter: bluefruit.Bluefruit,
        id: str,
        dev: bluefruit.Device,
    ):
        tag = protocol.Nametag(adapter=adapter, dev=dev)

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
            except StopScanningException as exc:
                logger.debug(f"[{tag.id}] StopScanningException: {exc}")
                nonlocal stop_received
                stop_received = exc
            except bluefruit.BluefruitError as exc:
                logger.warning(f"[{tag.id}] {exc}")
            except asyncio.CancelledError:
                logger.debug(f"[{tag.id}] Tag task cancelled")
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

    def poll_adapter(adapter: bluefruit.Bluefruit) -> Dict[str, str]:
        monotime = time.monotonic()
        id_dev = [
            (tag_id, dev)
            for dev in adapter.devices().values()
            for tag_id in [protocol.Nametag.id_if_nametag(dev)]
            if tag_id and dev.monotime > monotime - 2 * options.maximum_age
        ]

        id_dev.sort(key=lambda id_dev: priority(id_dev[0]))
        id_status: Dict[str, str] = {}
        for id, dev in id_dev:
            attempt = id_attempt_mono.get(id)
            success = id_success_mono.get(id)
            success_retry = success + options.success_delay if success else 0
            attempt_retry = attempt + options.attempt_delay if attempt else 0
            started = (attempt or 0) > (success or 0)

            status = f"{id}{dev.rssi:+02d}"
            if dev.fully_connected:
                status = f"|{status}|"
            elif not dev.fully_disconnected:
                status = f":{status}:"
            elif id in id_task:
                status = f".{status}."
            elif monotime < success_retry and not started:
                status = f"+{status}+"
            elif monotime < attempt_retry:
                status = f"-{status}{'!' if started else '-'}"
            elif dev.monotime < monotime - options.maximum_age and not started:
                status = f"?{status}?"
            elif (dev.rssi or -100) <= options.minimum_rssi and not started:
                status = f"/{status}/"
            elif not adapter.ready_to_connect(dev):
                status = f"^{status}{'!' if started else '^'}"
            else:
                status = f"*{status}{'!' if started else '*'}"
                spawn_connection(adapter=adapter, id=id, dev=dev)

            id_status[id] = status

        for id in id_task.keys():
            id_status.setdefault(id, f"_{id}____")
        return id_status

    async def scan_with_adapter(adapter: bluefruit.Bluefruit):
        logger.debug("Starting scan loop...")
        next_status_monotime = 0.0
        try:
            while stop_received is None:
                id_status = poll_adapter(adapter)
                monotime = time.monotonic()
                spawned = any("*" in s or "#" in s for s in id_status.values())
                if monotime >= next_status_monotime or spawned:
                    status = " ".join(s for id, s in sorted(id_status.items()))
                    logger.info("Tags: " + (status or "(none)"))
                    next_status_monotime = monotime + options.status_interval
                await asyncio.sleep(options.loop_delay)

        finally:
            if id_task:
                logger.debug(f"Stopping {len(id_task)} tasks pre-exit...")
                [task.cancel() for task in id_task.values()]
                await asyncio.wait(list(id_task.values()))
                assert not id_task
                logger.debug("All tasks stopped, exiting...")

    next_status_monotime = 0.0
    while stop_received is None:
        ports = list(serial.tools.list_ports.grep(options.port_regex))
        monotime = time.monotonic()
        if monotime >= next_status_monotime or ports:
            next_status_monotime = monotime + 1.0
            logger.info(
                f"Scanning for adapter /{options.port_regex}/, "
                f"found {len(ports)}..."
                + "".join(f"\n  {p.device} {p.hwid}" for p in ports)
            )

        if ports:
            path = ports[0].device
            if len(ports) > 2:
                logger.warning(f"Multiple adapters found, using {path}")
            try:
                async with bluefruit.Bluefruit(port=path) as adapt:
                    await scan_with_adapter(adapt)
            except bluefruit.PortError as exc:
                logger.warning(f"Adapter I/O error ({exc}), retrying...")

        await asyncio.sleep(options.loop_delay)

    logger.info(f"Scanning stopped: {stop_received}")


if __name__ == "__main__":
    import argparse

    from nametag import logging_setup

    async def test_task(tag):
        print(f"  [{tag.id}] connected, reading...")
        stash = await tag.read_stash()
        to_stash = b"HELLO"
        print(f"  [{tag.id}] stash is {stash!r}, writing {to_stash!r}...")
        await tag.write_stash(to_stash)
        print(f"  [{tag.id}] wrote, disconnecting...")

    parser = argparse.ArgumentParser()
    parser.add_argument("--debug", action="store_true")
    parser.add_argument("--port")
    args = parser.parse_args()
    if args.debug:
        logging_setup.enable_debug()

    asyncio.run(scan_and_spawn(runner=test_task), debug=args.debug)
