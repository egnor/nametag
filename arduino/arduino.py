#!/usr/bin/env python3

import argparse
import os
import platform
from pathlib import Path
from subprocess import run

source_dir = Path(__file__).resolve().parent
default_sketch_dir = source_dir / "bluetalk"
tool_dir = source_dir.parent / "external" / "arduino"
cli_bin = tool_dir / f"arduino-cli-{platform.system()}-{platform.machine()}"

work_dir = source_dir / "work"
os.environ["ARDUINO_DIRECTORIES_DATA"] = str(work_dir / "data")
os.environ["ARDUINO_DIRECTORIES_DOWNLOADS"] = str(work_dir / "downloads")
os.environ["ARDUINO_DIRECTORIES_USER"] = str(work_dir / "user")

board_urls = "https://www.adafruit.com/package_adafruit_index.json"
os.environ["ARDUINO_BOARD_MANAGER_ADDITIONAL_URLS"] = board_urls

parser = argparse.ArgumentParser()
parser.add_argument("--show-properties", action="store_true")
parser.add_argument("--fqbn", default="adafruit:nrf52:feather52832")
parser.add_argument("--port", default="/dev/ttyUSB0")
parser.add_argument("--programmer", default="nrfutil_boot")
parser.add_argument("extra", nargs="*")

commands = parser.add_mutually_exclusive_group(required=True)
commands.add_argument("--burn-bootloader", action="store_true")
commands.add_argument("--build", action="store_true")
commands.add_argument("--cli", action="store_true")
commands.add_argument("--setup", action="store_true")
commands.add_argument("--upload", action="store_true")

args = parser.parse_args()
if args.cli:
    run([cli_bin] + args.extra)

if args.setup:
    run([cli_bin, "update"], check=True)
    run([cli_bin, "upgrade"], check=True)
    run([cli_bin, "core", "install", "adafruit:nrf52"] + args.extra, check=True)

if args.build or args.upload:
    build_flags = "-DSERIAL_BUFFER_SIZE=2048"

    command = [
        str(cli_bin),
        "compile",
        f"--build-cache-path={work_dir / 'build_cache'}",
        f"--build-path={work_dir / 'build'}",
        f"--build-property=compiler.c.extra_flags={build_flags}",
        f"--build-property=compiler.cpp.extra_flags={build_flags}",
        f"--fqbn={args.fqbn}",
        f"--output-dir={work_dir / 'build_output'}",
        f"--port={args.port}",
        f"--warnings=all",
    ]
    if args.show_properties:
        command.append("--show-properties")
    if args.upload:
        command.append("--upload")
    run(command + (args.extra or [default_sketch_dir]), check=True)

if args.burn_bootloader:
    command = [
        str(cli_bin),
        "burn-bootloader",
        f"--fqbn={args.fqbn}",
        f"--port={args.port}",
        f"--programmer={args.programmer}",
    ]
    run(command + args.extra, check=True)
