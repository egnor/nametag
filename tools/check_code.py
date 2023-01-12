#!/usr/bin/env python3

import os
import re
from pathlib import Path
from subprocess import check_call
from typing import List

from nametag import logging_setup


def run(*args):
    print(f"\n=== {args[0]} ===")
    repo_dir = Path(__file__).resolve().parent.parent
    check_call(args, cwd=repo_dir)


sources = ["lobby_game", "nametag", "tools"]
run("black", *sources)
run("isort", *sources)
run("mypy", *sources)
