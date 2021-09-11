import sys
from pathlib import Path

import PIL  # type: ignore

sys.path.append(str(Path(__file__).parent / "py_aseprite"))
import aseprite  # type: ignore


def parse_ase(path):
    with open(path, "rb") as file:
        data = file.read()
    return aseprite.AsepriteFile(data)


def image_from_ase(path):
    ase = parse_ase(path)
