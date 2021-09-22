from pathlib import Path
from typing import List, Optional

import PIL.Image

import lobby_game.render_word_text
import nametag.protocol


art_dir = Path(__file__).parent.parent / "art"


def steps_for_game(
    ghost: Optional[int],
    ghost_accept: Optional[bool],
    ghost_word: Optional[str],
    title: str,
    title_word: str
) -> List[nametag.protocol.ProtocolStep]:
    frames = []

    blank_image = PIL.Image.new("1", (48, 12))

    if ghost is not None:
        accept = "accept" if ghost_accept else "reject"
        print(accept)
        ghost_image = lobby_game.render_word_text.image_of_text(
            frame_path=art_dir / "lobby" / f"ghost-{ghost}-{accept}.ase",
            font_dir=art_dir / "font",
            text=f'"{ghost_word}"',
        )

        frames.append(ghost_image)
        frames.append(ghost_image)
        frames.append(ghost_image)
        frames.append(blank_image)
        frames.append(blank_image)

    title_blank_image, title_word_image = [
        lobby_game.render_word_text.image_of_text(
            frame_path=art_dir / "lobby" / f"title-{title}.ase",
            font_dir=art_dir / "font-bold",
            text=word,
        )
        for word in ("", f'"{title_word}"')
    ]

    frames.append(title_blank_image)
    frames.append(title_word_image)
    frames.append(title_blank_image)
    frames.append(title_word_image)
    frames.append(title_blank_image)
    frames.append(title_word_image)
    frames.append(title_word_image)
    frames.append(title_word_image)
    frames.append(title_word_image)
    frames.append(blank_image)

    steps = []
    steps.extend(nametag.protocol.set_brightness(255))
    steps.extend(nametag.protocol.show_frames(frames, msec=500))
    return steps


if __name__ == "__main__":  # For testing
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--ghost", type=int)
    parser.add_argument("--ghost_accept", type=bool)
    parser.add_argument("--ghost_word")
    parser.add_argument("--title", type=str, required=True)
    parser.add_argument("--title_word", type=str, required=True)
    parser.add_argument("--save_tagsetup", type=Path, required=True)
    args = parser.parse_args()

    print(args.ghost_accept)

    steps = steps_for_game(
        ghost=args.ghost,
        ghost_accept=args.ghost_accept,
        ghost_word=args.ghost_word,
        title=args.title,
        title_word=args.title_word
    )

    with open(args.save_tagsetup, "w") as tagsetup:
        tagsetup.write(nametag.protocol.to_str(steps))
