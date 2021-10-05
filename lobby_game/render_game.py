import logging
import struct
from pathlib import Path
from typing import Dict, List, Optional

import attr
import PIL.Image  # type: ignore

import lobby_game.game_logic
import lobby_game.tag_data
import nametag.aseprite_loader
import nametag.protocol

art_dir = Path(__file__).resolve().parent.parent / "art"
lobby_dir = art_dir / "lobby"
image_cache: Dict[Path, PIL.Image.Image] = {}

KERNING = {
    ('"', "A"): -1,
    ('"', "J"): -1,
    ("A", '"'): -1,
    ("A", "T"): -1,
    ("L", "T"): -1,
    ("T", "A"): -1,
    ("T", "J"): -1,
}

STATE_STRUCT = struct.Struct("<4ph")


def get_image(path: Path) -> PIL.Image.Image:
    image = image_cache.get(path)
    if not image:
        logging.info(f"Loading image: {path}")
        image = PIL.Image.open(path).convert(mode="1")
        image.info.pop("transparency", None)  # Work around PILlow bug
        image_cache[path] = image
    return image


def add_text(
    image: PIL.Image.Image, font_dir: Path, text: str
) -> PIL.Image.Image:
    glyphs = [get_image(font_dir / (ch + ".ase")) for ch in text]
    spacing = list(1 + KERNING.get(ab, 0) for ab in zip(text[:-1], text[1:]))

    text_w = sum(g.size[0] for g in glyphs) + sum(spacing)
    text_h = max((g.size[1] for g in glyphs), default=0)
    if text_w > image.size[0] or text_h > image.size[1]:
        raise ValueError(
            f'Text "{text}" ({text_w}x{text_h}) '
            f"doesn't fit image ({image.size[0]}x{image.size[1]})"
        )

    cropped = image.crop((0, image.size[1] - text_h) + image.size)
    proj_x, proj_y = cropped.getprojection()
    gap_x = max((i + 1 for i, v in enumerate(proj_x) if v), default=0)
    if text_w > image.size[0] - gap_x:
        raise ValueError(
            f'Text "{text}" ({text_w}x{text_h}) '
            f"doesn't fit blank ({gap_x},{image.size[1] - text_h})-"
            f"({image.size[0]},{image.size[1]})"
        )

    left_x = (gap_x + image.size[0] - text_w + 1) // 2
    pasted = image.copy()
    for glyph, space_after in zip(glyphs, spacing + [0]):
        pasted.paste(glyph, box=(left_x, image.size[1] - text_h))
        left_x += glyph.size[0] + space_after
    return pasted


def scene_frames(
    scene: lobby_game.tag_data.DisplayScene,
) -> List[PIL.Image.Image]:
    frames: List[PIL.Image.Image] = []
    blank_image = PIL.Image.new("1", (48, 12))

    image_path = scene.image_name and (lobby_dir / f"{scene.image_name}.ase")
    base_image = get_image(image_path) if image_path else blank_image
    if scene.text:
        font_dir = art_dir / ("font-bold" if scene.bold else "font")
        image = add_text(image=base_image, font_dir=font_dir, text=scene.text)
    else:
        image = base_image

    if scene.blink:
        frames.append(base_image)
        frames.append(image)
        frames.append(base_image)
        frames.append(image)
        frames.append(base_image)
        frames.append(image)
        frames.append(image)
        frames.append(image)
        frames.append(image)
    else:
        frames.append(image)
        frames.append(image)
        frames.append(image)

    frames.append(blank_image)
    return frames


async def read_state(
    tag: nametag.protocol.Nametag,
) -> Optional[lobby_game.tag_data.TagState]:
    stash = await tag.read_stash()
    if stash and len(stash) >= STATE_STRUCT.size:
        fixed, end = stash[: STATE_STRUCT.size], stash[STATE_STRUCT.size :]
        phase, num = STATE_STRUCT.unpack(fixed)
        return lobby_game.tag_data.TagState(phase=phase, number=num, string=end)
    return None  # No/invalid stashed data.


async def write_state(
    *, tag: nametag.protocol.Nametag, state: lobby_game.tag_data.TagState
):
    await tag.write_stash(
        STATE_STRUCT.pack(state.phase, state.number) + state.string
    )


async def render_content(
    *,
    content: lobby_game.tag_data.DisplayContent,
    tag: nametag.protocol.Nametag,
):
    frames = []
    for scene in content.scenes:
        frames.extend(scene_frames(scene))

    await tag.set_brightness(255)
    await tag.show_frames(frames, msec=500)
    if content.new_state:
        await write_state(tag=tag, state=content.new_state)


if __name__ == "__main__":  # For testing
    import argparse

    import nametag.logging_setup

    parser = argparse.ArgumentParser()
    parser.add_argument("--save_image", type=Path, default="tmp.gif")
    parser.add_argument(
        "--frames",
        type=str,
        nargs="+",
        default=["ghost-1-say+HELLO+bold+blink"],
        help="List of imagename+TEXT[+bold][+blink]",
    )

    args = parser.parse_args()
    frames = []
    for arg in args.frames:
        parts = arg.split("+")
        scene = lobby_game.tag_data.DisplayScene()
        scene.image_name = "".join(parts[0:1])
        scene.text = "".join(parts[1:2])
        scene.bold = "bold" in parts[2:]
        scene.blink = "blink" in parts[2:]
        frames.extend(scene_frames(scene))

    frames = [f.convert("P") for f in frames]
    frames[0].save(
        args.save_image,
        save_all=True,
        append_images=frames[1:],
        loop=0,
        duration=500,
    )
    print(f"Wrote image: {args.save_image}")
