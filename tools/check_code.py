#!/usr/bin/env python3

import os
from pathlib import Path
from subprocess import check_call

os.chdir(str(Path(__file__).parent.parent))


def run(*args):
    print(f"\n=== {args[0]} ===")
    check_call(args)


run("black", "-l", "80", "--exclude", "foreign", ".")

run("isort", "--profile", "black", "--skip", "foreign", ".")

run(
    "mypy",
    "--namespace-packages",
    "--explicit-package-bases",
    "--exclude",
    "^foreign/",
    ".",
)
