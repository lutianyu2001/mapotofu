"""The same characters in several fonts, a row each: a PNG to compare them by eye.

    mapo tool sheet OUT.png TEXT FONT... [--size N] [--zoom CHAR X Y WIDTH]...

    from mapotofu.tools.raster import FontSource
    from mapotofu.tools.sheet import rows, zooms

    rows([FontSource(a, 200), FontSource(b, 200)], "永国あA").save("sheet.png")
    zooms([a, b], [("永", 520, 80, 300)], 360).save("zoom.png")

Without --zoom every font is a row of the characters, each in a cell of one em, with the font's
name under the row. With --zoom the sheet shows spots instead: one row per spot, one cell per
font, the part of CHAR's glyph WIDTH units wide around (X, Y), in units of 1000 per em from
the glyph's origin; the place to look at where two fonts differ in a detail.
"""

from __future__ import annotations

import argparse

import numpy as np
from PIL import Image, ImageDraw

from .raster import EM, FontSource

MARGIN = 0.12          # of a cell, above the ascent and below the descent of a row
BASELINE = 0.88        # the baseline's place in the em, from the top (a CJK em box)
GRID, PAPER, LABEL = 215, 255, 110


def _cell(font: FontSource, ch: str, size: int, left: float, top: float) -> np.ndarray:
    """A size x size cell of grey levels (0 white .. 255 ink) showing the character's glyph;
    (left, top) is the place of the cell's corner in pixels from the glyph's origin, x to the
    right, y upward."""
    cell = np.zeros((size, size), np.uint8)
    got = font.gray(ch)
    if got is None or not got[0].size:
        return cell
    a, bx, by, _ = got
    c0, r0 = int(round(bx - left)), int(round(top - by))
    rs, cs = slice(max(r0, 0), min(r0 + a.shape[0], size)), slice(max(c0, 0), min(c0 + a.shape[1], size))
    if rs.start < rs.stop and cs.start < cs.stop:
        cell[rs, cs] = a[rs.start - r0:rs.stop - r0, cs.start - c0:cs.stop - c0]
    return cell


def _sheet(grid: list[list[np.ndarray]], labels: list[str], size: int) -> Image.Image:
    """Cells in rows, a thin line between them, a label under each row."""
    cols, strip = max(len(row) for row in grid), 16
    img = Image.new("L", (cols * (size + 1) + 1, len(grid) * (size + 1 + strip) + 1), GRID)
    draw = ImageDraw.Draw(img)
    for r, (row, label) in enumerate(zip(grid, labels)):
        y = r * (size + 1 + strip) + 1
        for c, cell in enumerate(row):
            img.paste(Image.fromarray((PAPER - cell.astype(int) * 235 // 255).astype(np.uint8)), (c * (size + 1) + 1, y))
        draw.rectangle((1, y + size, img.width - 2, y + size + strip - 1), fill=PAPER)
        draw.text((4, y + size + 2), label, fill=LABEL)
    return img


def rows(fonts: list[FontSource], text: str) -> Image.Image:
    """The characters of `text` in each font, a row a font; a cell is one em of the font's
    raster (FontSource.res pixels, the same for all of them) plus a margin."""
    size = fonts[0].res
    cell, pad = int(round(size * (1 + 2 * MARGIN))), size * MARGIN
    grid = [[_cell(font, ch, cell, -pad, size * BASELINE + pad) for ch in text] for font in fonts]
    return _sheet(grid, [font.label for font in fonts], cell)


def zooms(specs: list[str], spots: list[tuple[str, float, float, float]], size: int = 360) -> Image.Image:
    """A row per spot (character, x, y, width in units of 1000 per em), a cell of `size` pixels
    per font spec: the part of the glyph `width` wide around (x, y)."""
    grid, labels = [], []
    for ch, x, y, width in spots:
        res = size * EM / width
        row = []
        for spec in specs:
            font = FontSource(spec, res)
            k = font.res / EM                                 # pixels per unit
            row.append(_cell(font, ch, size, (x - width / 2) * k, (y + width / 2) * k))
        grid.append(row)
        labels.append(f"U+{ord(ch):04X}  ({x:g}, {y:g})  {width:g} wide:  " + "  |  ".join(FontSource(s, 16).label for s in specs))
    return _sheet(grid, labels, size)


def parser(prog: str = "mapo tool sheet") -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        prog=prog, description="Draw the same characters in several fonts, a row each, into a PNG.",
        epilog="A FONT is a file, a face of a collection (Font.ttc#2) or a place on the axes of a variable "
        "font (Font[wght].ttf@wght=500).",
    )
    ap.add_argument("out", metavar="OUT.png")
    ap.add_argument("text", metavar="TEXT", help="the characters to draw")
    ap.add_argument("fonts", nargs="+", metavar="FONT")
    ap.add_argument("--size", type=int, metavar="N", help="pixels of an em (default: 160), or of a cell with --zoom (default: 360)")
    ap.add_argument("--zoom", nargs=4, action="append", metavar=("CHAR", "X", "Y", "WIDTH"),
                    help="show a spot instead of the whole glyphs: the part of CHAR's glyph WIDTH units wide around "
                    "(X, Y), in units of 1000 per em; may be given several times (TEXT is then not drawn)")
    return ap


def main(argv: list[str] | None = None) -> None:
    args = parser().parse_args(argv)
    if args.zoom:
        spots = [(ch, float(x), float(y), float(w)) for ch, x, y, w in args.zoom]
        img = zooms(args.fonts, spots, args.size or 360)
    else:
        img = rows([FontSource(spec, args.size or 160) for spec in args.fonts], args.text)
    img.save(args.out)


if __name__ == "__main__":
    main()
