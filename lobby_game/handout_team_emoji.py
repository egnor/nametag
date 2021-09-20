#!/usr/bin/env python3

import shutil
import sys
from pathlib import Path
from typing import List, Tuple

import PIL.Image  # type: ignore

import nametag.aseprite_loader
import nametag.protocol

TEAMS = 50

EMOJIS = [
    ["sparkles", "moon", "thumbs_up"],  # puzzlewise *last*, use for team x0
    ["star", "fire", "sun"],
    ["rainbow", "crown", "confetti_ball"],
    ["mushroom", "nerd_face", "fire"],
    ["victory_hand", "confetti_ball", "rainbow"],
    ["tornado", "pray", "fire"],
    ["moon", "slightly_smiling", "bulb"],
    ["sparkles", "ribbon", "confetti_ball"],
    ["seedling", "heart", "sparkles"],
    ["nerd_face", "birthday", "rainbow"],
]


def pad_glyph(image_path, spacing):
    print(f"Glyph: {image_path} (pad={spacing})")
    with PIL.Image.open(image_path) as loaded_image:
        padded_image = PIL.Image.new("1", (loaded_image.size[0] + spacing, 12))
        padded_image.paste(loaded_image, box=(0, 0) + loaded_image.size)
        return padded_image


common_steps: List[nametag.protocol.ProtocolStep] = []
common_steps.extend(nametag.protocol.set_brightness(255))
common_steps.extend(nametag.protocol.set_speed(192))
common_steps.extend(nametag.protocol.set_mode(2))

art_dir = Path(__file__).parent
gen_dir = art_dir / "generated"
gen_dir.mkdir(exist_ok=True)

for team in range(1, TEAMS):
    print(f"=== team {team} ===")
    glyphs: List[PIL.Image.Image] = []

    glyphs = (
        [
            pad_glyph(art_dir / "sources" / "emoji" / f"{emoji}.ase", 10)
            for emoji in EMOJIS[team % 10]
        ]
        + [
            pad_glyph(art_dir / "sources" / "lobby" / "lobby-logo.ase", 5),
            pad_glyph(art_dir / "sources" / "lobby" / "lobby-team.ase", 5),
        ]
        + [
            pad_glyph(art_dir / "sources" / "lobby" / f"lobby-{n}.ase", 2)
            for n in str(team)
        ]
    )

    steps = common_steps[:] + list(nametag.protocol.show_glyphs(glyphs))
    setup_path = gen_dir / f"lobby-intro-team{team:02d}.tagsetup"
    print(f"Writing: {setup_path}")
    with setup_path.open("w") as file:
        file.write(nametag.protocol.to_str(steps))
    print()

print("=== emoji test ===")
glyphs = [
    pad_glyph(art_dir / "sources" / "emoji" / f"{emoji}.ase", 10)
    for emoji in list(sorted(set(e for emojis in EMOJIS for e in emojis)))
]

steps = common_steps + list(nametag.protocol.show_glyphs(glyphs))
test_path = gen_dir / "emoji-test.tagsetup"
print(f"Writing: {test_path}")
with test_path.open("w") as file:
    file.write(nametag.protocol.to_str(steps))