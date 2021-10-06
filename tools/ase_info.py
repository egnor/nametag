#!/usr/bin/env python3

import argparse
from typing import Dict, List

from nametag import aseprite_loader, logging_setup

# must import after aseprite_import
import aseprite  # type: ignore  # isort: skip

parser = argparse.ArgumentParser()
parser.add_argument("ase_file", help="File to convert")
args = parser.parse_args()

print(f"=== Loading: {args.ase_file}")
with open(args.ase_file, "rb") as ase_file:
    ase = aseprite.AsepriteFile(ase_file.read())
print()


def decode_flags(flags: int, names: Dict[int, str]):
    found = [name for f, name in names.items() if flags & f]
    leftover = flags & ~sum(names.keys())
    return ",".join(found + ([f"0x{leftover:x}"] if leftover else []))


header_flags = {1: "opacity-valid"}

print(
    f"=== File:"
    f" {ase.header.width}x{ase.header.height}px"
    f" (px={ase.header.pixel_width}x{ase.header.pixel_height})"
    f" {ase.header.color_depth}bpp"
    f" ({ase.header.num_colors}col"
    f" tr=#{ase.header.palette_mask})"
    f" [{decode_flags(ase.header.flags, header_flags)}]"
    f" {ase.header.num_frames}fr {ase.header.filesize}b"
)

for fi, frame in enumerate(ase.frames):
    print(
        f"--- Frame F{fi + 1}:"
        f" t={frame.frame_duration}msec"
        f" chunks={frame.num_chunks} ({frame.size}b)"
    )

    for ci, chunk in enumerate(frame.chunks):
        print(f"  C{ci}:" f" {type(chunk).__name__}" f" ({chunk.chunk_size}b)")

        if isinstance(chunk, aseprite.PaletteChunk):
            print(
                f"    Colors: {chunk.palette_size}"
                f" [{chunk.first_color_index}-{chunk.last_color_index}]"
            )

        elif isinstance(chunk, aseprite.LayerChunk):
            layer_types = {0: "Normal", 1: "Group", 2: "Tilemap"}
            typ = layer_types.get(chunk.layer_type, f"type={chunk.layer_type}")
            layer_flags = {
                1: "vis",
                2: "edit",
                4: "!move",
                8: "bg",
                16: "linkcel",
                32: "collapse",
                64: "ref",
            }
            print(
                f"   {' ->' * chunk.layer_child_level}"
                f" L{chunk.layer_index}: {typ}"
                f" blend={chunk.blend_mode}"
                f" opacity={chunk.opacity}"
                f" [{decode_flags(chunk.flags, layer_flags)}]"
                f' "{chunk.name}"'
            )

        elif isinstance(chunk, aseprite.CelChunk):
            cel_types = {0: "RawData", 1: "Linked", 2: "ZImage", 3: "ZTiles"}
            typ = cel_types.get(chunk.cel_type, f"type={chunk.cel_type}")
            print(
                f"    {typ}: layer=L{chunk.layer_index}"
                f" pos=({chunk.x_pos},{chunk.y_pos}) opacity={chunk.opacity}"
            )

            if all(k in chunk.data for k in ("width", "height", "data")):
                d = chunk.data
                print(
                    f"    Data: {d['width']}x{d['height']}"
                    f" ({len(d['data'])}b)"
                )
            elif "link" in chunk.data:
                print(f"    Link: F{d['link']}")

        elif isinstance(chunk, aseprite.CelExtraChunk):
            extra_flags = {1: "bounds-valid"}
            print(
                f"    Precise:"
                f" {chunk.cel_width / 65536:.1f}x{chunk.cel_height / 65536:.1f}"
                f" pos=({chunk.precise_x_pos / 65536:.1f}"
                f"x{chunk.precise_y_pos / 65536:.1f})"
                f" [{decode_flags(chunk.flags, extra_flags)}]"
            )

        # TODO, add other chunk types as needed

    print()
