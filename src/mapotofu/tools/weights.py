"""How the measures of a family change with weight: its strokes, the width of its glyphs and
their spacing, each weight against one of them.

    mapo tool weights FONT FONT... [--base N] [--chars TEXT] [--res N]

    from mapotofu.tools.raster import FontSource
    from mapotofu.tools.weights import font_measures, against

    fonts = [FontSource(f"Serif[wght].ttf@wght={w}") for w in (300, 400, 700)]
    rows = [font_measures(font) for font in fonts]
    against(rows, 1)                         # each weight in percent of the second

Each FONT is one weight of the family: a static font, or a place on the axis of a variable
one. Per font, medians over the characters measured, in units of 1000 per em:

    stem_v, stem_h, hv, weight, spread, face    as mapo tool stems measures them
    ink        the width of the ink's box
    bearings   both side bearings together: the advance less the ink
    advance

The table has a line a measure and a column a font: the base font (--base, the first by
default) in those units, the others in percent of it. It shows what a family does as it gains
weight: how much faster the stems grow than the thin strokes, whether the glyphs widen, what
the spacing gives up. Two families set side by side tell how alike their weight axes are,
and the table of one of a close style is what a weight derived by a program is fitted to.
"""

from __future__ import annotations

import argparse

import numpy as np

from .raster import FontSource
from .stems import HAN, LATIN, font_stems

KEYS = ("stem_v", "stem_h", "hv", "weight", "spread", "face", "ink", "bearings", "advance")


def font_measures(font: FontSource, chars: str | None = None) -> dict:
    """stems.font_stems of the font, and the medians of `ink`, `bearings` and `advance` over the
    same characters (HAN, or LATIN if it has none of those, when none are given)."""
    if chars is None:
        chars = HAN if any(font.has(ch) for ch in HAN) else LATIN
    out = font_stems(font, chars)
    found = []
    for glyph in (font.glyph(ch) for ch in dict.fromkeys(chars)):
        if glyph is not None:
            x0, _, x1, _ = glyph.bbox()
            found.append((x1 - x0, glyph.advance - (x1 - x0), glyph.advance))
    for key, values in zip(("ink", "bearings", "advance"), zip(*found)):
        out[key] = float(np.median(values))
    for key in KEYS:
        out.setdefault(key, np.nan)
    return out


def against(rows: list[dict], base: int = 0) -> list[dict]:
    """Each row of measures in percent of the row `base` (NaN where that one has none)."""
    return [{key: 100 * row[key] / rows[base][key] if rows[base][key] else np.nan for key in KEYS} for row in rows]


def table(labels: list[str], rows: list[dict], base: int = 0) -> str:
    """A line a measure, a column a font: the base in units of 1000 per em (the ratios hv and
    spread as they are), the others in percent of it."""
    percent = against(rows, base)
    widths = [max(len(label), 8) for label in labels]
    lines = [f"{'':<10}" + "".join(f"  {label:>{w}}" for label, w in zip(labels, widths)),
             f"{'glyphs':<10}" + "".join(f"  {row['glyphs']:>{w}}" for row, w in zip(rows, widths))]
    for key in KEYS:
        cells = []
        for i, w in enumerate(widths):
            value = rows[i][key] if i == base else percent[i][key]
            text = "-" if np.isnan(value) else f"{value:.{2 if key in ('hv', 'spread') else 1}f}" if i == base else f"{value:.0f}%"
            cells.append(f"  {text:>{w}}")
        lines.append(f"{key:<10}" + "".join(cells))
    return "\n".join(lines) + "\n"


def parser(prog: str = "mapo tool weights") -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        prog=prog, description="Show how the measures of a family change with weight: each weight in percent of one of them.",
        epilog="A FONT is a file, a face of a collection (Font.ttc#2) or a place on the axes of a variable "
        "font (Font[wght].ttf@wght=500).",
    )
    ap.add_argument("fonts", nargs="+", metavar="FONT", help="a weight of the family")
    ap.add_argument("--base", type=int, default=1, metavar="N",
                    help="the font the others are set against, by its place among them (default: 1, the first)")
    ap.add_argument("--chars", metavar="TEXT", help="the characters to measure (default: Han characters built of "
                    "horizontal and vertical strokes; Latin letters for a font without them)")
    ap.add_argument("--res", type=int, default=512, metavar="N", help="pixels per em of the raster (default: 512)")
    return ap


def main(argv: list[str] | None = None) -> None:
    args = parser().parse_args(argv)
    if not 1 <= args.base <= len(args.fonts):
        raise SystemExit(f"mapo tool weights: --base {args.base}: there are {len(args.fonts)} fonts")
    fonts = [FontSource(spec, args.res) for spec in args.fonts]
    rows = [font_measures(font, args.chars) for font in fonts]
    print(table([font.label for font in fonts], rows, args.base - 1), end="")


if __name__ == "__main__":
    main()
