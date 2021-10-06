#!/usr/bin/env python3

import argparse
import subprocess
from pathlib import Path

UNIT = """
[Unit]
After=multi-user.target

[Service]
User=pi
WorkingDirectory=@DIR@
Environment="PYTHONPATH=@DIR@"
ExecStart=pipenv run lobby_game/game_station.py --ghost_id %i
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
"""

source_dir = Path(__file__).resolve().parent.parent

subprocess.run(
    ["sudo", "tee", "/etc/systemd/system/lobby_game@.service"],
    input=UNIT.replace("@DIR@", str(source_dir)),
    stdout=subprocess.DEVNULL,
    encoding="utf8",
    check=True,
)

parser = argparse.ArgumentParser()
parser.add_argument("--ghost_id", type=int, required=True)
args = parser.parse_args()

service_unit = f"lobby_game@{args.ghost_id}.service"
subprocess.run(["sudo", "systemctl", "enable", service_unit], check=True)
subprocess.run(["sudo", "systemctl", "start", service_unit], check=True)
