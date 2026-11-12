"""Every glyph of a font, at several weights or in several builds side by side: PNGs to look
the whole font over.

    mapo tool proof OUT FONT... [--size N] [--columns N] [--rows N] [--mark NAME]...

    from mapotofu.tools.proof import pages

    for number, image in enumerate(pages(["Sans[wght].ttf@wght=300", "Sans[wght].ttf@wght=700"]), 1):
        image.save(f"proof-{number:02d}.png")

A tile a glyph, in the order of the first FONT's glyphs, with the glyph's name above it and a
cell a FONT in it: the weights of a variable font, to see that every glyph interpolates (a
badly matched one shows between its masters: a bulge, a dent, a stroke crossing itself), or
two builds of a font. A glyph is found in the other fonts by its name; a font without it
leaves its cell empty. The names given with --mark are written in red, for the glyphs a
check has listed. The pages are OUT-01.png, OUT-02.png and so on, each with the fonts' names
at its top. (mapo tool sheet draws chosen characters, a row a font; this draws all the
glyphs, also those no character leads to.)
"""

from __future__ import annotations

import argparse
from collections.abc import Iterator
from pathlib import Path

import freetype
import numpy as np
from fontTools.ttLib import TTFont
from PIL import Image, ImageDraw

from .raster import FontSource

GRID, PAPER = 150, 255
NAME, MARKED, HEAD = (40, 40, 160), (220, 0, 0), (60, 60, 60)
STRIP = 14       # pixels of the strip a name is written in


def _open(font: FontSource) -> TTFont:
    return TTFont(font.path, fontNumber=font.index, lazy=True)


def _frame(font: FontSource) -> tuple[float, float, float, float]:
    """The box that holds every glyph of the font, in ems: the font's own (head), kept within
    what a glyph can sensibly reach."""
    opened = _open(font)
    head = opened["head"]
    x0, y0, x1, y1 = (v / head.unitsPerEm for v in (head.xMin, head.yMin, head.xMax, head.yMax))
    opened.close()
    return max(min(x0, 0.0), -0.5), max(min(y0, 0.0), -0.8), min(max(x1, 0.5), 2.0), min(max(y1, 0.5), 1.6)


def _cell(font: FontSource, gid: int | None, frame, size: int) -> np.ndarray:
    """The glyph in grey levels (0 white .. 255 ink) on a cell that shows `frame`, at `size`
    pixels per em; empty for a font without the glyph."""
    x0, y0, x1, y1 = frame
    cell = np.zeros((round((y1 - y0) * size), round((x1 - x0) * size)), np.uint8)
    if gid is None:
        return cell
    font.face.load_glyph(gid, freetype.FT_LOAD_NO_HINTING | freetype.FT_LOAD_NO_BITMAP | freetype.FT_LOAD_RENDER)
    slot = font.face.glyph
    bitmap = slot.bitmap
    if not bitmap.rows or not bitmap.width:
        return cell
    a = np.array(bitmap.buffer, np.uint8).reshape(bitmap.rows, bitmap.pitch)[:, : bitmap.width]
    c0, r0 = slot.bitmap_left - round(x0 * size), round(y1 * size) - slot.bitmap_top
    rs = slice(max(r0, 0), min(r0 + a.shape[0], cell.shape[0]))
    cs = slice(max(c0, 0), min(c0 + a.shape[1], cell.shape[1]))
    if rs.start < rs.stop and cs.start < cs.stop:
        cell[rs, cs] = a[rs.start - r0:rs.stop - r0, cs.start - c0:cs.stop - c0]
    return cell


def pages(specs: list[str], size: int = 120, columns: int = 6, rows: int = 8, marked=()) -> Iterator[Image.Image]:
    """The pages, one image after another: `columns` by `rows` tiles of the glyphs of the first
    font spec, each a cell a spec at `size` pixels per em, the names in `marked` in red."""
    fonts = [FontSource(spec, size) for spec in specs]
    orders = []
    for font in fonts:
        opened = _open(font)
        orders.append(opened.getGlyphOrder())
        opened.close()
    names = [name for name in orders[0] if name != ".notdef"]
    index = [{name: gid for gid, name in enumerate(order)} for order in orders]
    frames = [_frame(font) for font in fonts]
    frame = (min(f[0] for f in frames), min(f[1] for f in frames), max(f[2] for f in frames), max(f[3] for f in frames))
    marked = set(marked)
    head = "   |   ".join(font.label for font in fonts)
    for start in range(0, len(names), columns * rows):
        chunk = names[start:start + columns * rows]
        tiles = [np.hstack([np.pad(_cell(font, where.get(name), frame, size), 1) for font, where in zip(fonts, index)])
                 for name in chunk]
        th, tw = tiles[0].shape
        img = Image.new("RGB", (columns * (tw + 4) + 4, STRIP + 4 + rows * (th + STRIP + 4)), (GRID,) * 3)
        draw = ImageDraw.Draw(img)
        draw.rectangle((0, 0, img.width, STRIP + 1), fill=(PAPER,) * 3)
        draw.text((4, 1), f"{head}     glyphs {start + 1} to {start + len(chunk)} of {len(names)}", fill=HEAD)
        for i, (name, tile) in enumerate(zip(chunk, tiles)):
            x, y = 4 + (i % columns) * (tw + 4), STRIP + 4 + (i // columns) * (th + STRIP + 4)
            draw.rectangle((x, y, x + tw - 1, y + STRIP - 1), fill=(PAPER,) * 3)
            draw.text((x + 3, y + 1), name, fill=MARKED if name in marked else NAME)
            img.paste(Image.fromarray((PAPER - tile.astype(int) * 235 // 255).astype(np.uint8)), (x, y + STRIP))
        yield img


def write(out: str, specs: list[str], size: int = 120, columns: int = 6, rows: int = 8, marked=()) -> list[Path]:
    """The pages written as OUT-01.png, OUT-02.png ... (pages of an earlier run beyond the last
    one are removed); the files written."""
    prefix = Path(out)
    written = []
    for number, image in enumerate(pages(specs, size, columns, rows, marked), 1):
        written.append(prefix.with_name(f"{prefix.name}-{number:02d}.png"))
        image.save(written[-1])
    for old in prefix.parent.glob(f"{prefix.name}-[0-9][0-9]*.png"):
        if old not in written:
            old.unlink()
    return written


def parser(prog: str = "mapo tool proof") -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        prog=prog, description="Draw every glyph of a font, a cell a FONT (its weights, or builds of it), into PNGs.",
        epilog="A FONT is a file, a face of a collection (Font.ttc#2) or a place on the axes of a variable "
        "font (Font[wght].ttf@wght=500).",
    )
    ap.add_argument("out", metavar="OUT", help="the pages are OUT-01.png, OUT-02.png, ...")
    ap.add_argument("fonts", nargs="+", metavar="FONT")
    ap.add_argument("--size", type=int, default=120, metavar="N", help="pixels of an em (default: 120)")
    ap.add_argument("--columns", type=int, default=6, metavar="N", help="glyphs in a row of a page (default: 6)")
    ap.add_argument("--rows", type=int, default=8, metavar="N", help="rows of a page (default: 8)")
    ap.add_argument("--mark", action="append", default=[], metavar="NAME",
                    help="write this glyph's name in red; may be given several times")
    return ap


def main(argv: list[str] | None = None) -> None:
    args = parser().parse_args(argv)
    written = write(args.out, args.fonts, args.size, args.columns, args.rows, args.mark)
    print(f"{len(written)} pages: {args.out}-01.png to {written[-1].name}" if written else "no glyphs")


if __name__ == "__main__":
    main()
