import logging
from pathlib import Path
from typing import List

import PIL.Image  # type: ignore

import lobby_game.tag_data
import nametag.aseprite_loader
import nametag.protocol

TEAM_EMOJIS = [
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


def load_and_pad(image_path: str, spacing: int):
    print(f"Loading: {image_path} (pad={spacing})")
    art_dir = Path(__file__).parent.parent / "art"
    with PIL.Image.open(art_dir / image_path) as loaded_image:
        padded_image = PIL.Image.new("1", (loaded_image.size[0] + spacing, 12))
        padded_image.paste(loaded_image, box=(0, 0) + loaded_image.size)
        return padded_image


loaded_emojis = {
    emoji: load_and_pad(f"emoji/{emoji}.ase", 10)
    for emoji in set(emoji for emojis in TEAM_EMOJIS for emoji in emojis)
}

loaded_logoteam = [
    load_and_pad("lobby/lobby-logo.ase", 5),
    load_and_pad("lobby/lobby-team.ase", 5),
]

loaded_digits = {
    digit: load_and_pad(f"lobby/lobby-{digit}.ase", 2) for digit in range(0, 10)
}


def steps_for_team(team: int) -> List[nametag.protocol.ProtocolStep]:
    glyphs: List[PIL.Image.Image] = []

    glyphs = (
        [loaded_emojis[emoji] for emoji in TEAM_EMOJIS[team % 10]]
        + loaded_logoteam
        + [loaded_digits[int(d)] for d in str(team)]
    )

    state = lobby_game.tag_data.TagState(b"EMO", number=team)

    steps: List[nametag.protocol.ProtocolStep] = []
    steps.extend(nametag.protocol.set_brightness(255))
    steps.extend(nametag.protocol.set_speed(192))
    steps.extend(nametag.protocol.set_mode(2))
    steps.extend(nametag.protocol.show_glyphs(glyphs))
    steps.extend(lobby_game.tag_data.steps_from_tagstate(state))
    return steps
