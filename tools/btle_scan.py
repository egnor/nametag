#!/usr/bin/env python3

import argparse
import asyncio
import logging
import re
import time
from bisect import bisect_left
from typing import Any, Dict, List

import bleak  # type: ignore
import bleak.exc  # type: ignore

import nametag.logging_setup

logging.getLogger().setLevel(logging.DEBUG)
logging.getLogger("asyncio").setLevel(logging.INFO)
logging.getLogger("bleak").setLevel(logging.INFO)


def long_uuid(uuid: str):
    uuid = f"0000{uuid}" if len(uuid) == 4 else uuid
    return f"{uuid}-0000-1000-8000-00805f9b34fb" if len(uuid) == 8 else uuid


def short_uuid(uuid: str):
    uuid = long_uuid(uuid)
    m16 = re.match(r"0000([0-9a-f]{4})-0000-1000-8000-00805f9b34fb", uuid, re.I)
    m32 = re.match(r"([0-9a-f]{8})-0000-1000-8000-00805f9b34fb", uuid, re.I)
    return m16[1] if m16 else m32[1] if m32 else uuid


def hex_dump(data: bytes, *, prefix: str = ""):
    as_hex = " ".join(f"{b:02x}" for b in data)
    as_text = " ".join(
        f"{ch} " if ch.isprintable() and ch != "\ufffd" else "??"
        for ch in data.decode("ascii", "replace")
    )
    print(f'{prefix}[{as_hex}]\n{prefix}"{as_text.rstrip()}"')


def print_devices(devices: List[Any], args: argparse.Namespace):
    matching = [dev for dev in devices if args.name in dev.name]
    print(f'Of {len(devices)} devices, {len(matching)} match "{args.name}":')
    for dev in matching:
        print(f'=== "{dev.name}" ({dev.address.lower()}) rssi={dev.rssi} ===')
        uuids = dev.metadata.get("uuids", [])
        mdata = dev.metadata.get("manufacturer_data", {})
        if uuids:
            print(f"Service(s): ", ", ".join(short_uuid(u) for u in uuids))
        for mkey, mdata in mdata.items():
            print(f"Manufacturer data: {mkey:04x}")
            hex_dump(mdata, prefix="  ")
        print()


async def find_and_probe_device(args: argparse.Namespace):
    print(f"Scanning for {args.address} ({args.time:.1f}s)...")
    async with bleak.BleakScanner(adapter=args.adapter) as scanner:
        await scanner.start()
        start_time = time.monotonic()
        match = args.address.lower()
        while True:
            for dev in scanner.discovered_devices:
                if dev.address.lower() == match:
                    print(
                        f'Found "{dev.name}" ({dev.address})'
                        f" rssi={dev.rssi}, connecting..."
                    )
                    async with bleak.BleakClient(dev) as client:
                        await probe_device(client, args)
                    break

            elapsed = time.monotonic() - start_time
            if elapsed > args.time:
                print(f"Not found after {elapsed:.1f}s")
                print()

            await asyncio.sleep(0.1)


async def probe_device(client: bleak.BleakClient, args: argparse.Namespace):
    if args.write:
        await write_device(client, args)

    print("Discovering services...")
    collection = await client.get_services()

    def obj_text(obj):
        hex, desc = f"({short_uuid(obj.uuid)})", obj.description
        return hex if desc in (None, "Unknown", "") else f"{desc} {hex}"

    for serv in collection.services.values():
        print(f"=== #{serv.handle} {obj_text(serv)} ===")
        for char in serv.characteristics:
            support = ", ".join(char.properties)
            print(f"  #{char.handle} {obj_text(char)} {{{support}}}")
            for desc in char.descriptors:
                print(f"    [#{desc.handle} {obj_text(desc)}]")
            if "read" in char.properties:
                data = await client.read_gatt_char(char)
                hex_dump(data, prefix="    ")

        print()


async def write_device(client: bleak.BleakClient, args: argparse.Namespace):
    write_re = re.compile(r"(?:#([0-9]+)|([0-9a-f]+)) *[=:]([ 0-9a-f:]*)")
    m = write_re.match(args.write.lower())
    if not m:
        raise ValueError(f'Bad --write format: "{args.write}"')

    write_data = bytes.fromhex(m[3].replace(":", " "))
    if m[1]:
        handle = int(m[1])
        print(f"Writing to handle #{handle}:")
        hex_dump(write_data, prefix="  ")
        await client.write_gatt_char(handle, write_data)

    else:
        uuid = m[2]
        print(f"Writing to {short_uuid(m[2])}:")
        hex_dump(write_data, prefix="  ")
        await client.write_gatt_char(long_uuid(uuid), write_data)

    print()


async def run():
    parser = argparse.ArgumentParser()
    parser.add_argument("--adapter", default="hci0", help="BT interface")
    parser.add_argument("--time", type=int, default=2, help="Scan seconds")
    parser.add_argument("--name", default="", help="Name substring")
    parser.add_argument("--address", help="MAC of device to probe")
    parser.add_argument("--write", help="'uuid=hexbytes' or '#handle=hexbytes'")
    args = parser.parse_args()

    if args.write and not args.address:
        parser.error("--write without --address")

    if args.address:
        while True:
            try:
                await find_and_probe_device(args)
                break
            except bleak.exc.BleakError as exc:
                logging.error(f"{exc}, retrying...\n")

    else:
        print(f"Starting scan ({args.time:.1f}sec)...")
        devices = await bleak.BleakScanner.discover(
            adapter=args.adapter, timeout=args.time
        )
        print_devices(devices, args)


if __name__ == "__main__":
    asyncio.run(run())
