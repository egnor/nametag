#!/usr/bin/env python3

import os
import re
from pathlib import Path
from subprocess import check_call
from typing import List

os.chdir(str(Path(__file__).parent.parent))


def run(*args):
    print(f"\n=== {args[0]} ===")
    check_call(args)


excludes = ["art/py_aseprite/", "art/twemoji/"]
exclude_re = f"^({'|'.join(re.escape(e) for e in excludes)})"
run("black", "-l", "80", "--exclude", exclude_re, ".")

isort_skips: List[str] = sum((["--skip", s] for s in excludes), [])
run("isort", "--profile", "black", *isort_skips, ".")

run(
    "mypy",
    "--namespace-packages",
    "--explicit-package-bases",
    "--exclude",
    exclude_re,
    ".",
)
