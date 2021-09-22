import functools
import logging
from pathlib import Path
from typing import Union

import PIL.Image  # type: ignore

import nametag.aseprite_loader


@functools.cache
def get_image(path: Path) -> PIL.Image:
    image = PIL.Image.open(path).convert(mode="1")
    image.info.pop("transparency", None)  # Work around PILlow bug
    return image


def image_of_text(frame_path: Path, font_dir: Path, text: str) -> PIL.Image:
    if not text:
        raise ValueError(f'Bad text: "{text}"')
    frame = get_image(frame_path)
    glyphs = [get_image(font_dir / (ch + ".ase")) for ch in text]

    text_w = sum(g.size[0] for g in glyphs) + len(glyphs) - 1
    text_h = max(g.size[1] for g in glyphs)
    if text_w > frame.size[0] or text_h > frame.size[1]:
        raise ValueError(
            f'Text "{text}" ({text_w}x{text_h}) '
            f"doesn't fit frame ({frame.size[0]}x{frame.size[1]}): {frame_path}"
        )

    cropped = frame.crop((0, frame.size[1] - text_h) + frame.size)
    proj_x, proj_y = cropped.getprojection()
    first_x = max((i + 1 for i, v in enumerate(proj_x) if v), default=0)
    if text_w > frame.size[0] - first_x:
        raise ValueError(
            f'Text "{text}" ({text_w}x{text_h}) '
            f"doesn't fit blank ({first_x},{frame.size[1] - text_h})-"
            f"({frame.size[0]},{frame.size[1]}): {frame_path}"
        )

    left_x = int((first_x + frame.size[0] - text_w) / 2.0)
    pasted = frame.copy()
    for glyph in glyphs:
        pasted.paste(glyph, box=(left_x, frame.size[1] - text_h))
        left_x += glyph.size[0] + 1
    return pasted


if __name__ == "__main__":  # For testing
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--frame", type=Path, required=True)
    parser.add_argument("--text", required=True)
    parser.add_argument("--font", type=Path, required=True)
    parser.add_argument("--save", type=Path, required=True)
    args = parser.parse_args()

    image = image_of_text(args.frame, args.font, args.text)
    image.save(args.save)
