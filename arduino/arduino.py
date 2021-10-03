#!/usr/bin/env python3

import argparse
import os
import platform
from pathlib import Path
from subprocess import run

source_dir = Path(__file__).resolve().parent
arduino_dir = source_dir / "work"
bin_dir = source_dir.parent / "external" / "arduino"
cli_bin = bin_dir / f"arduino-cli-{platform.system()}-{platform.machine()}"

os.environ["ARDUINO_DIRECTORIES_DATA"] = str(arduino_dir / "data")
os.environ["ARDUINO_DIRECTORIES_DOWNLOADS"] = str(arduino_dir / "downloads")
os.environ["ARDUINO_DIRECTORIES_USER"] = str(arduino_dir / "user")

board_urls = "https://www.adafruit.com/package_adafruit_index.json"
os.environ["ARDUINO_BOARD_MANAGER_ADDITIONAL_URLS"] = board_urls

parser = argparse.ArgumentParser()
parser.add_argument("--show-properties", action="store_true")
parser.add_argument("--fqbn", default="adafruit:nrf52:feather52832")
parser.add_argument("--port", default="/dev/ttyUSB0")
parser.add_argument("--programmer", default="nrfutil_boot")
parser.add_argument("arg", nargs="*")

commands = parser.add_mutually_exclusive_group(required=True)
commands.add_argument("--burn-bootloader", action="store_true")
commands.add_argument("--build", action="store_true")
commands.add_argument("--cli", action="store_true")
commands.add_argument("--setup", action="store_true")
commands.add_argument("--upload", action="store_true")

args = parser.parse_args()
if args.cli:
    run([cli_bin] + args.arg)

if args.setup:
    run([cli_bin, "update"], check=True)
    run([cli_bin, "upgrade"], check=True)
    run([cli_bin, "core", "install", "adafruit:nrf52"], check=True)

if args.build or args.upload:
    extra_flags = "-DSERIAL_BUFFER_SIZE=2048"

    command = [
        str(cli_bin),
        "compile",
        f"--build-cache-path={arduino_dir / 'build_cache'}",
        f"--build-path={arduino_dir / 'build'}",
        f"--build-property=compiler.c.extra_flags={extra_flags}",
        f"--build-property=compiler.cpp.extra_flags={extra_flags}",
        f"--fqbn={args.fqbn}",
        f"--output-dir={arduino_dir / 'build_output'}",
        f"--port={args.port}",
        f"--warnings=all",
    ]
    if args.show_properties:
        command.append("--show-properties")
    if args.upload:
        command.append("--upload")
    command.extend(args.arg or [source_dir / "bluetalk"])
    run(command, check=True)

if args.burn_bootloader:
    command = [
        str(cli_bin),
        "burn-bootloader",
        f"--fqbn={args.fqbn}",
        f"--port={args.port}",
        f"--programmer={args.programmer}",
    ]
    run(command, check=True)
