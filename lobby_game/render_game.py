import logging
import struct
from pathlib import Path
from typing import Dict, List, Optional

import attr
import PIL.Image  # type: ignore

from lobby_game import stash_state, tag_data
from nametag import aseprite_loader, protocol

art_dir = Path(__file__).resolve().parent.parent / "art"
game_dir = art_dir / "lobby-game"
image_cache: Dict[Optional[Path], PIL.Image.Image] = {}

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


def get_image(path: Optional[Path]) -> PIL.Image.Image:
    image = image_cache.get(path)
    if not image:
        if not path:
            image = PIL.Image.new(mode="1", size=(48, 12), color=0)
        else:
            logging.info(f"Loading image: {path}")
            image = PIL.Image.open(path).convert(mode="1")
            image.info.pop("transparency", None)  # Work around PILlow bug
        image_cache[path] = image
    return image


def image_text(
    image_path: Optional[Path], font_dir: Path, text: str
) -> PIL.Image.Image:
    image = get_image(image_path)

    try:
        glyphs = [get_image(font_dir / (ch + ".ase")) for ch in text]
    except FileNotFoundError as exc:
        raise ValueError(f'Bad text ({font_dir}): "{text}"') from exc

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
            f"({image.size[0]},{image.size[1]}) in {image_path}"
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
    for scene in content.scenes:
        image_name = scene.image_name
        image_path = (game_dir / f"{image_name}.ase") if image_name else None
        font_dir = art_dir / ("font-bold" if scene.bold else "font")

        try:
            base_image = image_text(image_path, font_dir, "")
            image = image_text(image_path, font_dir, scene.text)
        except ValueError as exc:
            raise ValueError(f"Bad scene: {scene}") from exc

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
            frames.append(get_image(None))

    return frames


async def render_content(
    *,
    content: tag_data.DisplayContent,
    tag: protocol.Nametag,
):
    await tag.set_brightness(255)
    await tag.show_frames(content_frames(content), msec=500)
    await stash_state.write(tag=tag, state=content.new_state)


def render_to_file(
    *, content: tag_data.DisplayContent, path: Path, zoom: int = 1
):
    frames = [
        f.convert("P").resize((f.size[0] * zoom, f.size[1] * zoom))
        for f in content_frames(content)
    ]
    frames[0].save(
        path,
        save_all=True,
        append_images=frames[1:],
        loop=0,
        duration=500,
    )


if __name__ == "__main__":  # For testing
    import argparse

    from nametag import logging_setup

    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--frames",
        type=str,
        nargs="+",
        default=["need-tagC+LOVE+bold+blink"],
        help="List of imagename+TEXT[+bold][+blink]",
    )
    parser.add_argument("--save_image", type=Path, default="tmp.gif")
    parser.add_argument("--zoom", type=int, default=15)

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

    render_to_file(content=content, path=args.save_image, zoom=args.zoom)
    print(f"Wrote image: {args.save_image}")
