#!/usr/bin/env python3

import argparse
import asyncio
import logging
import re
import sys
import time
from bisect import bisect_left
from pathlib import Path
from typing import List

import bleak  # type: ignore
import bleak.exc  # type: ignore

sys.path.append(str(Path(__file__).parent.parent))
import nametag.logging

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


def print_devices(devices: List, args: argparse.Namespace):
    matching = [dev for dev in devices if args.name in dev.name]
    print(f'Of {len(devices)} devices, {len(matching)} match "{args.name}":')
    for dev in matching:
        print(f'=== "{dev.name}" ({dev.address.lower()}) rssi={dev.rssi} ===')
        uuids = dev.metadata["uuids"]
        mdata = dev.metadata["manufacturer_data"]
        if uuids:
            print(f"Found {len(uuids)} service(s):")
            print("".join(f"  {short_uuid(u)}\n" for u in uuids))

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
        found = None
        while not found and time.monotonic() < start_time + args.time:
            for scan_dev in scanner.discovered_devices:
                if scan_dev.address.lower() == match:
                    found = scan_dev
            await asyncio.sleep(0.1)

        if found:
            print(
                f'Found "{found.name}" ({found.address}) rssi={found.rssi},'
                " connecting..."
            )
            async with bleak.BleakClient(found) as client:
                await probe_device(client, args)
        else:
            print(f"Not found after {time.monotonic() - start_time:.1f}s")
            print()


async def probe_device(client: bleak.BleakClient, args: argparse.Namespace):
    if args.write:
        await write_device(client, args)

    print("Discovering services...")
    collection = await client.get_services()
    print(f"Found {len(collection.services)} service(s):")

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
    parser.add_argument("--name", default="CoolLED", help="Name substring")
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
    asyncio.get_event_loop().run_until_complete(run())
