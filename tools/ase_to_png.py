#!/usr/bin/env python3

import argparse
import sys
from pathlib import Path

sys.path.append(str(Path(__file__).parent.parent))
import art.aseprite_import
import nametag.logging_setup

parser = argparse.ArgumentParser()
parser.add_argument("ase_file", help="File to convert")
args = parser.parse_args()

image = art.aseprite_import.image_from_ase(args.ase_file)
image.save(args.ase_file.replace(".ase", "") + ".png")
