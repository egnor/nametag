import sys
from pathlib import Path
from typing import IO, Optional

import PIL.Image  # type: ignore

sys.path.append(str(Path(__file__).parent.parent / "external" / "py_aseprite"))
import aseprite  # type: ignore


def image_from_ase(data: bytes, layer_index: Optional[int] = None):
    ase = aseprite.AsepriteFile(data)
    image = PIL.Image.new(
        mode={8: "P", 16: "L", 32: "RGBA"}[ase.header.color_depth],
        size=(ase.header.width, ase.header.height),
    )

    frame = ase.frames[0]

    if image.mode == "P":
        palette_chunk = next(
            chunk
            for chunk in frame.chunks
            if isinstance(chunk, aseprite.PaletteChunk)
        )

        palette_data = [0, 0, 0, 0] * palette_chunk.first_color_index + [
            c[n]
            for c in palette_chunk.colors
            for n in ("red", "green", "blue", "alpha")
        ]
        image.putpalette(palette_data, rawmode="RGBA")

        darkest_index = min(
            range(len(palette_data) // 4),
            key=lambda i: sum(palette_data[4 * i : 4 * i + 4]),
        )
        image.paste(darkest_index, box=(0, 0) + image.size)

    if layer_index is None:
        layer_index = max(
            chunk.layer_index
            for chunk in frame.chunks
            if isinstance(chunk, aseprite.LayerChunk)
            and chunk.layer_type == 0
            and (chunk.flags & 1)
            and not (chunk.flags & 64)
        )

    cel = next(
        chunk
        for chunk in frame.chunks
        if isinstance(chunk, aseprite.CelChunk)
        and chunk.layer_index == layer_index
        and chunk.cel_type in (0, 2)
    )

    cel_image = PIL.Image.frombytes(
        mode=image.mode,
        size=(cel.data["width"], cel.data["height"]),
        data=cel.data["data"][:: 2 if image.mode == "L" else 1],
    )

    image.paste(cel_image, box=(cel.x_pos, cel.y_pos))
    return image


def open_factory(fp: Optional[IO], filename: Optional[str]):
    if fp:
        return image_from_ase(fp.read())
    else:
        assert filename is not None
        with open(filename, "rb") as fp:
            return image_from_ase(fp.read())


PIL.Image.register_open("ASE", open_factory)
PIL.Image.register_extension("ASE", ".ase")
