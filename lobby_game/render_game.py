import logging
from pathlib import Path
from typing import Dict, List, Optional

import attr
import PIL.Image  # type: ignore

import lobby_game.game_logic
import lobby_game.tag_data
import nametag.aseprite_loader
import nametag.protocol

art_dir = Path(__file__).parent.parent / "art"
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


def get_image(path: Path) -> PIL.Image.Image:
    image = image_cache.get(path)
    if not image:
        logging.info(f"Loading image: {path}")
        image = PIL.Image.open(path).convert(mode="1")
        image.info.pop("transparency", None)  # Work around PILlow bug
        image_cache[path] = image
    return image


def image_of_text(
    frame_path: Path, font_dir: Path, text: str
) -> PIL.Image.Image:
    frame = get_image(frame_path)
    glyphs = [get_image(font_dir / (ch + ".ase")) for ch in text]
    spacing = list(1 + KERNING.get(ab, 0) for ab in zip(text[:-1], text[1:]))

    text_w = sum(g.size[0] for g in glyphs) + sum(spacing)
    text_h = max((g.size[1] for g in glyphs), default=0)
    if text_w > frame.size[0] or text_h > frame.size[1]:
        raise ValueError(
            f'Text "{text}" ({text_w}x{text_h}) '
            f"doesn't fit frame ({frame.size[0]}x{frame.size[1]}): {frame_path}"
        )

    cropped = frame.crop((0, frame.size[1] - text_h) + frame.size)
    proj_x, proj_y = cropped.getprojection()
    gap_x = max((i + 1 for i, v in enumerate(proj_x) if v), default=0)
    if text_w > frame.size[0] - gap_x:
        raise ValueError(
            f'Text "{text}" ({text_w}x{text_h}) '
            f"doesn't fit blank ({gap_x},{frame.size[1] - text_h})-"
            f"({frame.size[0]},{frame.size[1]}): {frame_path}"
        )

    left_x = (gap_x + frame.size[0] - text_w + 1) // 2
    pasted = frame.copy()
    for glyph, space_after in zip(glyphs, spacing + [0]):
        pasted.paste(glyph, box=(left_x, frame.size[1] - text_h))
        left_x += glyph.size[0] + space_after
    return pasted


def steps_for_content(
    content: lobby_game.game_logic.DisplayContent,
) -> List[nametag.protocol.ProtocolStep]:
    frames: List[PIL.Image.Image] = []
    blank_image = PIL.Image.new("1", (48, 12))

    if content.ghost_id and content.ghost_action:
        frame_name = f"ghost-{content.ghost_id}-{content.ghost_action}.ase"
        ghost_image = image_of_text(
            frame_path=lobby_dir / frame_name,
            font_dir=art_dir / "font",
            text=content.ghost_text,
        )

        frames.append(ghost_image)
        frames.append(ghost_image)
        frames.append(ghost_image)
        frames.append(blank_image)

    title_blank_image, status_text_image = [
        image_of_text(
            frame_path=lobby_dir / f"title-{content.status_title}.ase",
            font_dir=art_dir / "font-bold",
            text=word,
        )
        for word in ("", content.status_text)
    ]

    frames.append(title_blank_image)
    frames.append(status_text_image)
    frames.append(title_blank_image)
    frames.append(status_text_image)
    frames.append(title_blank_image)
    frames.append(status_text_image)
    frames.append(status_text_image)
    frames.append(status_text_image)
    frames.append(status_text_image)
    frames.append(blank_image)

    steps: List[nametag.protocol.ProtocolStep] = []
    steps.extend(nametag.protocol.set_brightness(255))
    steps.extend(nametag.protocol.show_frames(frames, msec=500))
    if content.new_state:
        steps.extend(lobby_game.tag_data.steps_from_tagstate(content.new_state))
    return steps


if __name__ == "__main__":  # For testing
    import argparse

    import nametag.logging_setup

    parser = argparse.ArgumentParser()
    ig = parser.add_argument_group("Write frame image")
    ig.add_argument("--frame", type=Path, default=lobby_dir / "title-start.ase")
    ig.add_argument("--text", default='"HELLO"')
    ig.add_argument("--font", type=Path, default=art_dir / "font-bold")
    ig.add_argument("--save_image", type=Path)

    cg = parser.add_argument_group("Write tagsetup")
    cg.add_argument("--ghost_id", type=int, default=0)
    cg.add_argument("--ghost_action", default="")
    cg.add_argument("--ghost_text", default="")
    cg.add_argument("--status_title", default="start")
    cg.add_argument("--status_text", default="HELLO")
    cg.add_argument("--save_tagsetup", type=Path)

    args = parser.parse_args()

    if not (args.save_image or args.save_tagsetup):
        parser.error("One of --save_image or --save_tagsetup required")

    if args.save_image:
        image = image_of_text(args.frame, args.font, args.text)
        image.save(args.save_image)

    if args.save_tagsetup:
        content = lobby_game.game_logic.DisplayContent(
            ghost_id=args.ghost_id,
            ghost_action=args.ghost_action,
            ghost_text=args.ghost_text,
            status_title=args.status_title,
            status_text=args.status_text,
            new_state=lobby_game.tag_data.TagState(phase=b"GAM"),
        )

        steps = steps_for_content(content)
        with open(args.save_tagsetup, "w") as tagsetup:
            tagsetup.write(nametag.protocol.to_str(steps))
