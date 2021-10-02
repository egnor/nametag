#!/usr/bin/env python3

import argparse
import os
from pathlib import Path
from subprocess import run

source_dir = Path(__file__).parent
arduino_dir = source_dir / "work"
bin_dir = source_dir.parent / "external" / "arduino"
cli_bin = bin_dir / "arduino-cli-linux-x64"  # TODO: detect architecture

os.environ["ARDUINO_DIRECTORIES_DATA"] = str(arduino_dir / "data")
os.environ["ARDUINO_DIRECTORIES_DOWNLOADS"] = str(arduino_dir / "downloads")
os.environ["ARDUINO_DIRECTORIES_USER"] = str(arduino_dir / "user")

board_urls = "https://www.adafruit.com/package_adafruit_index.json"
os.environ["ARDUINO_BOARD_MANAGER_ADDITIONAL_URLS"] = board_urls

parser = argparse.ArgumentParser()
parser.add_argument("--cli", action="store_true")
parser.add_argument("--setup", action="store_true")
parser.add_argument("--show-properties", action="store_true")
parser.add_argument("--upload", action="store_true")
parser.add_argument("--fqbn", default="adafruit:nrf52:feather52832")
parser.add_argument("--port", default="/dev/ttyUSB0")
parser.add_argument("arg", nargs="*")

args = parser.parse_args()
if args.cli:
    run([cli_bin] + args.arg)

if args.setup:
    run([cli_bin, "update"], check=True)
    run([cli_bin, "upgrade"], check=True)
    run([cli_bin, "core", "install", "adafruit:nrf52"], check=True)

extra_flags = "-DSERIAL_BUFFER_SIZE=512"

command = [
    cli_bin,
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
