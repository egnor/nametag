#!/usr/bin/env python3

import os
from pathlib import Path
from subprocess import check_call, check_output

os.chdir(str(Path(__file__).parent.parent))
startup_venv = os.environ.get("VIRTUAL_ENV")

print("=== Update system packages (apt) ===")
apt_packages = ["direnv", "libjpeg-dev", "libfreetype6-dev", "pipenv"]
check_call(["sudo", "apt", "install"] + apt_packages)
print()

print("=== Update python virtualenv (pipenv) ===")
check_call(["pipenv", "install", "--dev"])
check_call(["direnv", "allow"])
venv_path = check_output(["pipenv", "--venv"], encoding="utf-8").strip()
activate_path = Path(venv_path) / "bin" / "activate_this.py"
exec(activate_path.open().read(), dict(__file__=str(activate_path)))
print()

if startup_venv == venv_path:
    print("::: Setup complete! :::")
else:
    print("*** Restart shell to activate virtualenv ***")
