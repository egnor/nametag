#!/usr/bin/env python3

import shutil
import sys
from pathlib import Path
from typing import List, Tuple

import PIL.Image  # type: ignore

import art.aseprite_import

TEAMS = 50

EMOJIS = [
    ["star-struck", "birthday", "heart"],
    ["slightly-smiling", "bulb"],
    ["cartwheel", "fire"],
    ["heart", "seedling"],
    ["bulb", "notes"],
    ["tada", "cartwheel"],
    ["bell", "bulb"],
    ["notes", "ribbon"],
    ["sun", "confetti-ball"],
    ["bulb", "balloon", "star-struck"],
]

art_dir = Path(__file__).parent
gen_dir = art_dir / "generated"

image = PIL.Image.new("1", (48, 12))

for team in range(1, TEAMS):
    print(f"=== team {team} ===")
    team_dir = gen_dir / f"lobby-team{team:02d}-intro"
    shutil.rmtree(team_dir, ignore_errors=True)
    team_dir.mkdir(parents=True)

    glyph_index = 0
    def glyph(ase_path, spacing=0):
        global glyph_index
        ase_image = art.aseprite_import.image_from_ase(ase_path)
        padded_image = PIL.Image.new("1", (ase_image.size[0] + spacing, 12))
        padded_image.paste(ase_image, box=(0, 0) + ase_image.size)
        glyph_path = team_dir / f"glyph{glyph_index:02d}.png"
        print(glyph_path)
        padded_image.save(glyph_path)
        glyph_index += 1

    for emoji in EMOJIS[team % 10]:
        glyph(art_dir / "sources" / "emoji" / f"{emoji}.ase", spacing=10)

    glyph(art_dir / "sources" / "lobby" / "lobby-heart.ase", spacing=2)
    glyph(art_dir / "sources" / "lobby" / "lobby-circle-L.ase", spacing=2)
