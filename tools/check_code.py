#!/usr/bin/env python3

import os
from pathlib import Path
from subprocess import check_call

os.chdir(str(Path(__file__).parent.parent))

check_call(["black", "-l", "80", "--exclude", "foreign", "."])
check_call(["isort", "--profile", "black", "--skip", "foreign", "."])
check_call(["mypy", "--namespace-packages", "--explicit-package-bases", "--exclude", "/foreign/", "."])
