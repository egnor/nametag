#!/usr/bin/env python3

import sys
from pathlib import Path

art_dir = Path(__file__).parent
sys.path.append(str(art_dir.parent / "py_aseprite"))
import aseprite

art_sources_dir = art_dir / "sources"
with (art_sources_dir / "emoji" / "ribbon.ase").open("rb") as ribbon_ase_file:
    ribbon_ase = aseprite.AsepriteFile(ribbon_ase_file.read())
    print(ribbon_ase)
    print(ribbon_ase.header)
    print(ribbon_ase.frames)
    print(ribbon_ase.frames[0].chunks)
    print(ribbon_ase.layers[0])
