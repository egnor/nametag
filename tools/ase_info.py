#!/usr/bin/env python3

import argparse
import sys
from pathlib import Path

sys.path.append(str(Path(__file__).parent.parent))
import art.load_aseprite
import nametag.logging

parser = argparse.ArgumentParser()
parser.add_argument("ase_file", help="File to convert")
args = parser.parse_args()

ase = load_aseprite.parse_ase(args.ase_file)
