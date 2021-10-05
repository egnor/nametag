import logging
from pathlib import Path
from typing import List

import PIL.Image  # type: ignore

from lobby_game import stash_state, tag_data
from nametag import aseprite_loader, protocol

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
    art_dir = Path(__file__).resolve().parent.parent / "art"
    with PIL.Image.open(art_dir / image_path) as loaded_image:
        padded_image = PIL.Image.new("1", (loaded_image.size[0] + spacing, 12))
        padded_image.paste(loaded_image, box=(0, 0) + loaded_image.size)
        return padded_image


loaded_emojis = {
    emoji: load_and_pad(f"emoji/{emoji}.ase", 10)
    for emoji in set(emoji for emojis in TEAM_EMOJIS for emoji in emojis)
}

loaded_logoteam = [
    load_and_pad("team-number/lobby-logo.ase", 5),
    load_and_pad("team-number/word-team.ase", 5),
]

loaded_digits = {
    digit: load_and_pad(f"team-number/digit-{digit}.ase", 2)
    for digit in range(0, 10)
}


async def render(*, team: int, tag: protocol.Nametag):
    glyphs: List[PIL.Image.Image] = []

    glyphs = (
        [loaded_emojis[emoji] for emoji in TEAM_EMOJIS[team % 10]]
        + loaded_logoteam
        + [loaded_digits[int(d)] for d in str(team)]
    )

    state = tag_data.TagState(b"EMO", number=team)

    await tag.set_brightness(255)
    await tag.set_speed(192)
    await tag.set_mode(2)
    await tag.show_glyphs(glyphs)
    await stash_state.write(tag=tag, state=state)
