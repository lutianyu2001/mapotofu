"""The points of a glyph's outline as the font stores them, numbered, on-curve or off.

    mapo tool points FONT TEXT [--glyph NAME]... [--box X0 Y0 X1 Y1]

    from mapotofu.tools.points import contours

    for contour in contours("Font.ttf", "永"):
        for x, y, on in contour:
            ...

For looking at how a part of a glyph is drawn: which points make a corner or a round, whether
two builds put them at the same places. A sheet (mapo tool sheet --zoom) shows the shape; this
shows what it is made of, in the font's own units.

Each glyph is a heading (the character, its code point, the glyph's name, advance, contours and
points) and its contours; a point is a line of its number in the glyph, x, y and `on` or `off`.
Numbers run through the contours as in a TrueType glyph, so a point keeps its number whatever
part is shown. With --box only the points inside the box are listed (and only the contours that
have one there). Composite glyphs are drawn out: their points are those of their parts, placed.
In a font with PostScript outlines the `off` points are the control points of its cubic curves.
"""

from __future__ import annotations

import argparse

from fontTools.pens.recordingPen import DecomposingRecordingPointPen
from fontTools.ttLib import TTFont

from .raster import parse_spec


def _open(spec: str):
    path, index, location = parse_spec(spec)
    font = TTFont(path, fontNumber=index)
    return font, font.getGlyphSet(location=location or None)


def glyph_contours(glyphs, name: str) -> list[list[tuple[float, float, bool]]]:
    """The contours of a glyph of a fontTools glyph set: lists of (x, y, on-curve)."""
    pen = DecomposingRecordingPointPen(glyphs)
    glyphs[name].drawPoints(pen)
    found, contour = [], None
    for call, args, _ in pen.value:
        if call == "beginPath":
            contour = []
        elif call == "addPoint":
            (x, y), kind = args[0], args[1]
            contour.append((x, y, kind is not None))
        elif call == "endPath":
            found.append(contour)
    return found


def contours(spec: str, char: str | None = None, glyph: str | None = None) -> list[list[tuple[float, float, bool]]]:
    """The contours of a character's glyph (or of the glyph of that name) in the font of a
    spec (a file, Font.ttc#2, Font[wght].ttf@wght=500): lists of (x, y, on-curve)."""
    font, glyphs = _open(spec)
    name = glyph or (font.getBestCmap() or {}).get(ord(char))
    if name is None or name not in glyphs:
        raise KeyError(glyph or char)
    return glyph_contours(glyphs, name)


def report(spec: str, text: str = "", names: tuple[str, ...] = (), box=None) -> str:
    font, glyphs = _open(spec)
    cmap = font.getBestCmap() or {}
    hmtx = font["hmtx"]
    wanted = [(ch, cmap.get(ord(ch))) for ch in dict.fromkeys(text)] + [(None, name) for name in names]
    lines = []
    for ch, name in wanted:
        head = f"{ch}  U+{ord(ch):04X}" if ch else ""
        if name is None or name not in glyphs:
            lines.append(f"{head or name}: not in the font")
            continue
        found = glyph_contours(glyphs, name)
        count = sum(map(len, found))
        lines.append(f"{head + '  ' if head else ''}{name}  advance {hmtx[name][0]}  {len(found)} contours, {count} points")
        number = 0
        for k, contour in enumerate(found):
            shown = [(number + i, x, y, on) for i, (x, y, on) in enumerate(contour)
                     if box is None or (box[0] <= x <= box[2] and box[1] <= y <= box[3])]
            number += len(contour)
            if shown:
                lines.append(f"  contour {k}: {len(contour)} points")
                lines += [f"    {i:>5}  {x:>8g}  {y:>8g}  {'on' if on else 'off'}" for i, x, y, on in shown]
    return "\n".join(lines) + "\n"


def parser(prog: str = "mapo tool points") -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        prog=prog, description="List the points of glyphs' outlines: number, x, y, on-curve or off.",
        epilog="A FONT is a file, a face of a collection (Font.ttc#2) or a place on the axes of a variable "
        "font (Font[wght].ttf@wght=500).",
    )
    ap.add_argument("font", metavar="FONT")
    ap.add_argument("text", metavar="TEXT", nargs="?", default="", help="the characters whose glyphs to list")
    ap.add_argument("--glyph", action="append", default=[], metavar="NAME",
                    help="a glyph by its name, for one no character leads to; may be given several times")
    ap.add_argument("--box", nargs=4, type=float, metavar=("X0", "Y0", "X1", "Y1"),
                    help="only the points within this box, in font units")
    return ap


def main(argv: list[str] | None = None) -> None:
    args = parser().parse_args(argv)
    if not args.text and not args.glyph:
        raise SystemExit("mapo tool points: no character and no --glyph")
    box = None
    if args.box:
        x0, y0, x1, y1 = args.box
        box = (min(x0, x1), min(y0, y1), max(x0, x1), max(y0, y1))
    print(report(args.font, args.text, tuple(args.glyph), box), end="")


if __name__ == "__main__":
    main()
