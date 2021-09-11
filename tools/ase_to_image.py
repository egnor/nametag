#!/usr/bin/env python3

import argparse
import sys
from pathlib import Path

sys.path.append(str(Path(__file__).parent.parent))
import art.aseprite_import
import nametag.logging_setup

parser = argparse.ArgumentParser()
parser.add_argument("ase_file", help="File to convert")
parser.add_argument("out_file", nargs="?", help="File to convert")
args = parser.parse_args()

print(f"Reading: {args.ase_file}")
image = art.aseprite_import.image_from_ase(args.ase_file)

out_file = args.out_file or args.ase_file.replace(".ase", "") + ".png"
print(f"Writing: {out_file}")
image.save(out_file)
