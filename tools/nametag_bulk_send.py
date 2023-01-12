#!/usr/bin/env python3

import argparse
import asyncio
import datetime
import hashlib
import logging
import re
from pathlib import Path
from typing import Dict, List, Tuple

import attr
import cattr
import cattr.preconf.tomlkit
import cattrs.errors
import PIL.Image  # type: ignore
import tomlkit
import tomlkit.exceptions

from nametag import aseprite_loader, logging_setup, protocol, scanner


@attr.frozen
class TagConfig:
    glyphs: Tuple[str, ...] = attr.field(factory=tuple)


@attr.frozen
class Config:
    search: Tuple[str, ...] = attr.field(factory=tuple)
    spacing: int = 0
    mode: int = 2
    speed: int = 192
    brightness: int = 128
    tags: Dict[str, TagConfig] = attr.field(factory=dict)


@attr.define
class ScanState:
    config_path: Path
    config_time: float = 0.0
    config: Config = Config()
    tag_states: Dict[str, TagConfig] = attr.field(default={})


GLYPH_RX = re.compile(r"(?P<name>.[\w-]*)(:(?P<space>\d+))?")


async def update_tag(tag: protocol.Nametag, state: ScanState):
    try:
        config_time = state.config_path.stat().st_mtime
    except FileNotFoundError:
        logging.critical(f"Config not found: {state.config_path}")
        return

    if config_time != state.config_time:
        with open(state.config_path) as file:
            config_toml = tomlkit.load(file)

        converter = cattr.preconf.tomlkit.make_converter()
        state.config = converter.structure(config_toml, Config)
        state.config_time = config_time
        logging.info(f"Config loaded: {state.config_path}")
        logging.debug(f"Config: {state.config}")

    tag_config = state.config.tags.get(tag.id)
    if not tag_config:
        logging.warning(f"[{tag.id}] Tag not in config file")
        return

    config_hash = hashlib.blake2b(
        repr((tag_config, attr.evolve(state.config, tags={}))).encode("utf8"),
        digest_size=8
    ).digest()

    stash = await tag.read_stash()
    if stash and not stash.from_backup and stash.data == config_hash:
        logging.info(f"[{tag.id}] Stash matches config, skipping")
        return

    pil_exts = PIL.Image.registered_extensions()
    file_exts = {e for e, f in pil_exts.items() if f in PIL.Image.OPEN}

    glyph_images: List[PIL.Image.Image] = []
    for spec in tag_config.glyphs:
        parts = GLYPH_RX.fullmatch(spec)
        if not parts:
            logging.critical(f'[{tag.id}] Bad glyph spec "{spec}"')
            continue

        name, space = parts.group("name", "space")
        found: Optional[Path] = None
        for search in state.config.search:
            for ext in ["", *file_exts]:
                path = state.config_path.parent / search / (name + ext)
                if path.is_file():
                    found = path
                    break

        if not found:
            logging.error(f'[{tag.id}] Glyph "{name}" not found')
            continue

        logging.info(f"Loading: {found.resolve()}")
        image = PIL.Image.open(found).convert(mode="1")
        size = (image.size[0] * 12 // image.size[1], 12)
        image = image.resize(size) if size != image.size else image
        glyph_images.append(image)

        spacing = int(space) if space else state.config.spacing
        if spacing:
            space_size = (spacing, 12)
            space_image = PIL.Image.new(mode="1", size=space_size, color=0)
            glyph_images.append(space_image)

    logging.info(f"[{tag.id}] Glyphs: {' '.join(tag_config.glyphs)}")
    await tag.set_mode(state.config.mode)
    await tag.set_speed(state.config.speed)
    await tag.set_brightness(state.config.brightness)
    await tag.show_glyphs(glyph_images)
    await tag.write_stash(config_hash)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--debug", action="store_true")
    parser.add_argument("config", type=Path)
    args = parser.parse_args()
    if args.debug:
        logging_setup.enable_debug()

    options = scanner.ScannerOptions(success_delay=2.0)
    scan_coro = scanner.scan_and_spawn(
        runner=update_tag,
        options=options,
        state=ScanState(config_path=args.config)
    )

    asyncio.run(scan_coro, debug=args.debug)
