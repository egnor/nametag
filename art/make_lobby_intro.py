#!/usr/bin/env python3

import shutil
import sys
from pathlib import Path
from typing import List, Tuple

import PIL.Image  # type: ignore

import art.aseprite_import
import nametag.protocol

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
gen_dir.mkdir(exist_ok=True)

image = PIL.Image.new("1", (48, 12))

for team in range(1, TEAMS):
    print(f"=== team {team} ===")
    glyphs: List[PIL.Image.Image] = []

    def add_glyph(ase_path, spacing=0):
        print(f"Glyph: {ase_path} (pad={spacing})")
        ase_image = art.aseprite_import.image_from_ase(ase_path)
        padded_image = PIL.Image.new("1", (ase_image.size[0] + spacing, 12))
        padded_image.paste(ase_image, box=(0, 0) + ase_image.size)
        glyphs.append(padded_image)

    for emoji in EMOJIS[team % 10]:
        add_glyph(art_dir / "sources" / "emoji" / f"{emoji}.ase", spacing=10)

    add_glyph(art_dir / "sources" / "lobby" / "lobby-logo.ase", spacing=5)
    add_glyph(art_dir / "sources" / "lobby" / "lobby-team.ase", spacing=5)

    for n in str(team):
        add_glyph(art_dir / "sources" / "lobby" / f"lobby-{n}.ase", spacing=2)

    steps: List[nametag.protocol.ProtocolStep] = []
    steps.extend(nametag.protocol.set_brightness(255))
    steps.extend(nametag.protocol.set_speed(192))
    steps.extend(nametag.protocol.set_mode(2))
    steps.extend(nametag.protocol.show_glyphs(glyphs))

    setup_path = gen_dir / f"lobby-intro-team{team:02d}.tagsetup"
    print(f"Writing: {setup_path}")
    with setup_path.open("w") as file:
        file.write(nametag.protocol.to_str(steps))

print("=== emoji test ===")
all_emoji = set(sum(EMOJIS, []))
