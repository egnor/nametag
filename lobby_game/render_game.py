import logging
import struct
from pathlib import Path
from typing import Dict, List

import attr
import PIL.Image  # type: ignore

from lobby_game import stash_state, tag_data
from nametag import aseprite_loader, protocol

art_dir = Path(__file__).resolve().parent.parent / "art"
game_dir = art_dir / "lobby-game"
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

state_memory: Dict[str, tag_data.TagState] = {}


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


def content_frames(
    content: tag_data.DisplayContent,
) -> List[PIL.Image.Image]:
    frames: List[PIL.Image.Image] = []
    blank_image = PIL.Image.new("1", (48, 12))
    for scene in content.scenes:
        image_path = scene.image_name and (game_dir / f"{scene.image_name}.ase")
        base_image = get_image(image_path) if image_path else blank_image
        if scene.text:
            font = art_dir / ("font-bold" if scene.bold else "font")
            image = add_text(image=base_image, font_dir=font, text=scene.text)
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

        if len(content.scenes) > 1:
            frames.append(blank_image)

    return frames


async def render_content(
    *,
    content: tag_data.DisplayContent,
    tag: protocol.Nametag,
):
    await tag.set_brightness(255)
    await tag.show_frames(content_frames(content), msec=500)
    await stash_state.write(tag=tag, state=content.new_state)


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
    content = tag_data.DisplayContent(
        new_state=tag_data.TagState(phase=b"TST"),
        scenes=[],
    )
    for arg in args.frames:
        parts = arg.split("+")
        scene = tag_data.DisplayScene()
        scene.image_name = "".join(parts[0:1])
        scene.text = "".join(parts[1:2])
        scene.bold = "bold" in parts[2:]
        scene.blink = "blink" in parts[2:]
        content.scenes.append(scene)

    frames = [f.convert("P") for f in content_frames(content)]
    frames[0].save(
        args.save_image,
        save_all=True,
        append_images=frames[1:],
        loop=0,
        duration=500,
    )
    print(f"Wrote image: {args.save_image}")
