#!/usr/bin/env python3

import os
import re
from pathlib import Path
from subprocess import check_call
from typing import List

os.chdir(str(Path(__file__).resolve().parent.parent))


def run(*args):
    print(f"\n=== {args[0]} ===")
    check_call(args)


excludes = ["external/", "arduino/work/"]
exclude_re = f"({'|'.join(re.escape(e) for e in excludes)})"
run("black", "-l", "80", "--exclude", f"^/{exclude_re}", ".")

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
