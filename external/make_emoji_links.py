#!/usr/bin/env python3

import os
import shutil
from pathlib import Path

import emoji  # type: ignore

twemoji_dir = Path(__file__).parent.parent / "external" / "twemoji" / "assets"

links_dir = Path(__file__).parent / "emoji"
shutil.rmtree(links_dir, ignore_errors=True)
links_dir.mkdir()

dicts = (emoji.UNICODE_EMOJI_ALIAS_ENGLISH, emoji.UNICODE_EMOJI["en"])
for emoji, name in (item for d in dicts for item in d.items()):
    hex = "-".join(f"{ord(ch):x}" for ch in emoji)
    name = name.lower().strip(":")
    symlinks = [
        (twemoji_dir / "72x72" / f"{hex}.png", links_dir / f"{name}.png"),
        (twemoji_dir / "svg" / f"{hex}.svg", links_dir / f"{name}.svg"),
    ]
    for source, link_path in symlinks:
        if source.exists():
            relpath = Path(os.path.relpath(source, start=link_path.parent))
            if not link_path.is_symlink():
                link_path.symlink_to(relpath)
