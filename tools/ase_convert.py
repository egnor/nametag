#!/usr/bin/env python3

import argparse

import PIL.Image  # type: ignore

import nametag.aseprite_loader
import nametag.logging_setup

parser = argparse.ArgumentParser()
parser.add_argument("input_file", help="File to convert")
parser.add_argument("output_file", nargs="?", help="File to convert")
parser.add_argument("--mode", help="PIL mode to convert to")
args = parser.parse_args()

print(f"Reading: {args.input_file}")
image = PIL.Image.open(args.input_file)

if args.mode:
    print(f'Converting to mode "{args.mode}"')
    image = image.convert(args.mode)
    image.info.pop("transparency", None)  # Work around PILlow bug

out_file = args.output_file or args.input_file.replace(".ase", "") + ".png"
print(f"Writing: {out_file}")
image.save(out_file)
