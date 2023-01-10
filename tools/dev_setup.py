#!/usr/bin/env python3

import os
from pathlib import Path
from subprocess import check_call, check_output

repo_dir = Path(__file__).resolve().parent.parent
os.chdir(str(repo_dir))

print("=== Update system packages (apt) ===")
apt_packages = ["direnv", "libjpeg-dev", "libfreetype6-dev", "python3-dev"]
check_call(["sudo", "apt", "install"] + apt_packages)

print("\n=== Update python virtualenv (pipenv) ===")
venv_dir = repo_dir / "python_venv"
if not (venv_dir / "bin/activate.sh").is_file():
    import venv  # pylint: disable=wrong-import-position
    venv.create(venv_dir, symlinks=True, with_pip=True)
    check_call([venv_dir / "bin/pip", "install", "-e", "."])

check_call(["direnv", "allow"])
print("\n::: Setup complete! :::")
