import sys
from pathlib import Path

import PIL

sys.path.append(str(Path(__file__).parent.parent / "py_aseprite"))
import aseprite


def parse_ase(path):
    with open(path, "rb") as file:
        data = file.read()
    return aseprite.AsepriteFile(data)


def image_from_ase(path):
    ase = parse_ase(path)
