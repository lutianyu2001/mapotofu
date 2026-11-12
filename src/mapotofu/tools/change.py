"""How each glyph of a font changes between two weights, and the glyphs that change unlike
the others of their kind.

    mapo tool change LIGHT HEAVY [--reference LIGHT HEAVY] [--only NAME]... [--res N]

    from mapotofu.tools.raster import FontSource
    from mapotofu.tools.change import changes, kinds, unlike

    light, heavy = FontSource("Serif[wght].ttf@wght=400"), FontSource("Serif[wght].ttf@wght=700")
    changed = changes(light, heavy)          # {glyph name: {"area": 1.43, "thick": 1.6, ...}}
    found = unlike(changed, kinds(light))
    found.listed                             # {glyph name: (kind, [("thin", 1.31), ...])}, the furthest off first

LIGHT and HEAVY are two weights of one font: two places on the axis of a variable font, or
two static fonts with the same glyph names. Every glyph both have is rasterised in each, and
what is measured is how much of each measure the heavier glyph has against the lighter:

    area      the ink
    thick     the thickness of the ink where it is commonest (its median over the ink; the
              thickness at a point is the shorter of the runs of ink through it, across and
              up and down): the stems set it
    thin      the same a tenth of the way up from the thinnest: hairlines, bars and serifs
    width     of the ink's box
    height    of the ink's box
    advance

A weight that was drawn after another one, or made from it by a program, is checked this way:
its glyphs should gain weight as the glyphs of their kind do. The glyphs go by kind, read
from their characters (capitals, small letters, other letters, figures, other numbers, marks,
punctuation, symbols; a glyph no character leads to goes with the glyph its name starts with,
`a.sc` with `a`). The change of a kind is the median over its glyphs. How far a glyph may be
off it is the band that holds all but the outermost 5% of the glyphs of that kind, and never
less than FLOOR: with --reference, the glyphs of another family of a close style between the
same two weights, which tells how far apart glyphs of one kind are in a font made with care;
without, the font's own glyphs. A glyph is listed when one of its changes lies outside the
band, with each such change in percent off its kind's, the furthest outside first.

With --only (or `tested`) only those glyphs are judged, and the others alone set the change
of their kind: for a font in which some glyphs were drawn and the others derived.

The list says where to look, not what is wrong; the glyph is judged by eye (mapo tool sheet).
The thickness is read off the ink itself and not off the skeleton (mapotofu.tools.stems): over
the ink it is steadier between two weights of a serif face, whose serifs gain or lose a branch
of the skeleton as the weight changes.
"""

from __future__ import annotations

import argparse
import math
import re
import unicodedata
from typing import NamedTuple

import numpy as np
from fontTools.ttLib import TTFont

from .raster import FontSource

KEYS = ("area", "thick", "thin", "width", "height", "advance")
OUTER = 2.5      # percent of the glyphs left outside the band at each end
FEW = 8          # glyphs of a kind a reference must have for its band to be taken
# The least a change must be off its kind's to be listed, however narrow the band.
FLOOR = {"area": 0.10, "thick": 0.15, "thin": 0.15, "width": 0.06, "height": 0.06, "advance": 0.06}
KINDS = {"Lu": "capitals", "Lt": "capitals", "Ll": "small", "Lo": "letters", "Lm": "letters", "Nd": "figures",
         "N": "numbers", "M": "marks", "P": "punctuation", "S": "symbols"}


def runs(ink: np.ndarray) -> np.ndarray:
    """For each pixel of ink, the length of the run of ink through it along its row."""
    a = np.pad(ink, ((0, 0), (1, 1)))
    at = np.arange(a.shape[1])[None, :]
    before = np.maximum.accumulate(np.where(a, -1, at), axis=1)
    after = np.minimum.accumulate(np.where(a, a.shape[1], at)[:, ::-1], axis=1)[:, ::-1]
    return np.where(a, after - before - 1, 0)[:, 1:-1]


def glyph_measures(glyph) -> dict[str, float]:
    """The measures of a rasterised glyph (raster.Glyph), in units of 1000 per em (the area in
    their squares)."""
    ink, px = glyph.ink, glyph.px
    rows, columns = np.nonzero(ink)
    thickness = np.minimum(runs(ink), runs(ink.T).T)[ink] * px
    return {
        "area": float(ink.sum()) * px * px,
        "thick": float(np.percentile(thickness, 50)),
        "thin": float(np.percentile(thickness, 10)),
        "width": float(columns.max() - columns.min() + 1) * px,
        "height": float(rows.max() - rows.min() + 1) * px,
        "advance": float(glyph.advance),
    }


def glyph_order(font: FontSource) -> list[str]:
    """The names of the font's glyphs, by glyph ID."""
    opened = TTFont(font.path, fontNumber=font.index, lazy=True)
    try:
        return opened.getGlyphOrder()
    finally:
        opened.close()


def changes(light: FontSource, heavy: FontSource, names=None) -> dict[str, dict[str, float]]:
    """For each glyph both fonts have (by name) and draw, how much of each measure of KEYS the
    heavy one has against the light one (NaN where the light one has none: no advance). With
    `names`, only those glyphs are measured."""
    there = {name: gid for gid, name in enumerate(glyph_order(heavy))}
    wanted = None if names is None else set(names)
    out = {}
    for gid, name in enumerate(glyph_order(light)):
        if name not in there or (wanted is not None and name not in wanted):
            continue
        a, b = light.glyph_index(gid), heavy.glyph_index(there[name])
        if a is None or b is None or a.ink.sum() < 8 or b.ink.sum() < 8:
            continue
        lighter, heavier = glyph_measures(a), glyph_measures(b)
        out[name] = {key: heavier[key] / lighter[key] if lighter[key] else math.nan for key in KEYS}
    return out


def kind_of(char: str) -> str | None:
    """The kind of a character's glyph, None for one without ink (a space, a control)."""
    category = unicodedata.category(char)
    return KINDS.get(category) or KINDS.get(category[0])


def kinds(font: FontSource) -> dict[str, str]:
    """The kind of each glyph of the font that has one, by name: its character's, or that of the
    glyph its name starts with (before the first `.` or `_`)."""
    encoded: dict[str, str | None] = {}
    for code, name in sorted(font.cmap.items()):
        encoded.setdefault(name, kind_of(chr(code)))
    out = {}
    for name in glyph_order(font):
        kind = encoded[name] if name in encoded else encoded.get(re.split(r"[._]", name)[0])
        if kind:
            out[name] = kind
    return out


class Unlike(NamedTuple):
    """What unlike() found: `level[kind, key]`, the change of a kind; `band[kind, key]`, how far
    off it a glyph may be (low, high: factors of the level); `listed`, the glyphs outside, the
    furthest first: {name: (kind, [(key, its change against the level), ...])}."""

    level: dict[tuple[str, str], float]
    band: dict[tuple[str, str], tuple[float, float]]
    listed: dict[str, tuple[str, list[tuple[str, float]]]]


def _finite(values) -> np.ndarray:
    values = np.array(list(values), float)
    return values[np.isfinite(values)]


def unlike(changed: dict, kind: dict, reference: dict | None = None, reference_kind: dict | None = None,
           tested=None) -> Unlike:
    """The glyphs of `changed` (changes()) that change unlike their kind (`kind`: {name: kind},
    kinds() or the caller's own). `reference` and `reference_kind` are the same of another
    family, whose glyphs then give the band; `tested` names the glyphs to judge, the others
    alone setting the change of their kind (default: all are judged, and all set it)."""
    judged = set(changed) if tested is None else set(tested) & set(changed)
    level, band = {}, {}
    for k in sorted({kind[n] for n in changed if n in kind}):
        members = [n for n in changed if kind.get(n) == k]
        setting = [n for n in members if tested is None or n not in judged] or members
        spread = [reference[n] for n in reference if (reference_kind or {}).get(n) == k] if reference else []
        if len(spread) < FEW:
            spread = [changed[n] for n in setting]
        for key in KEYS:
            values, of = _finite(changed[n][key] for n in setting), _finite(c[key] for c in spread)
            if not len(values) or not len(of):
                continue
            level[k, key] = float(np.median(values))
            middle = float(np.median(of))
            low, high = np.percentile(of, OUTER) / middle, np.percentile(of, 100 - OUTER) / middle
            band[k, key] = (min(float(low), 1 - FLOOR[key]), max(float(high), 1 + FLOOR[key]))
    found = {}
    for name in judged:
        k, outside, furthest = kind.get(name), [], 0.0
        for key in KEYS:
            if (k, key) not in level or not math.isfinite(changed[name][key]):
                continue
            off = changed[name][key] / level[k, key]
            low, high = band[k, key]
            if not low <= off <= high:
                furthest = max(furthest, (off - high if off > high else low - off) / (high - low))
                outside.append((key, off))
        if outside:
            found[name] = (furthest, k, outside)
    order = sorted(found, key=lambda n: (-found[n][0], n))
    return Unlike(level, band, {n: found[n][1:] for n in order})


def off(outside: list[tuple[str, float]]) -> str:
    """What is outside the band, as text: `thin +31%, width -7%`."""
    return ", ".join(f"{key} {100 * factor - 100:+.0f}%" for key, factor in outside)


def table(found: Unlike, judged: int, chars: dict[str, str] | None = None, numbers: dict[str, str] | None = None) -> str:
    """The kinds with their change and band, then the glyphs listed, a line each; `chars` gives
    a glyph's character and `numbers` a label to put before its name."""
    lines = ["change of each kind, and the band around it in percent:", ""]
    for k in sorted({k for k, _ in found.level}):
        cells = [f"{key} {found.level[k, key]:.2f} {100 * found.band[k, key][0] - 100:+.0f}..{100 * found.band[k, key][1] - 100:+.0f}"
                 for key in KEYS if (k, key) in found.level]
        lines.append(f"  {k:<12}{'   '.join(cells)}")
    lines += ["", f"{len(found.listed)} of {judged} glyphs change unlike their kind, the furthest off first:", ""]
    width = max(map(len, found.listed), default=0)
    for name, (k, outside) in found.listed.items():
        number = f"{numbers[name]}  " if numbers and name in numbers else ""
        lines.append(f"  {number}{name:<{width}}  {(chars or {}).get(name, ''):<2} {k:<12}{off(outside)}")
    return "\n".join(lines) + "\n"


def report(light: str, heavy: str, reference: tuple[str, str] | None = None, only=None, res: int = 512) -> str:
    """The table of two font specs, with the band from the two specs of `reference` if given and
    only the glyphs named in `only` judged."""
    first, second = FontSource(light, res), FontSource(heavy, res)
    changed, kind = changes(first, second), kinds(first)
    other, other_kind = None, None
    if reference:
        a, b = FontSource(reference[0], res), FontSource(reference[1], res)
        other, other_kind = changes(a, b), kinds(a)
    if only is not None and (missing := sorted(set(only) - set(changed))):
        raise SystemExit(f"mapo tool change: not a glyph both fonts draw: {', '.join(missing)}")
    found = unlike(changed, kind, other, other_kind, only)
    judged = len([n for n in (changed if only is None else only) if n in kind])
    chars = {name: chr(code) for code, name in sorted(first.cmap.items(), reverse=True)}
    head = f"{first.label} to {second.label}" + (f", against {a.label} to {b.label}" if reference else "")
    return f"{head}\n{table(found, judged, chars)}"


def parser(prog: str = "mapo tool change") -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        prog=prog, description="List the glyphs that change between two weights of a font unlike the others of their kind.",
        epilog="LIGHT and HEAVY are two weights of one font: each a file, a face of a collection (Font.ttc#2) or a place "
        "on the axes of a variable font (Font[wght].ttf@wght=500).",
    )
    ap.add_argument("light", metavar="LIGHT")
    ap.add_argument("heavy", metavar="HEAVY")
    ap.add_argument("--reference", nargs=2, metavar=("LIGHT", "HEAVY"),
                    help="two weights of another family, whose glyphs tell how far a glyph may be off its kind "
                    "(default: the font's own glyphs)")
    ap.add_argument("--only", action="append", metavar="NAME",
                    help="judge only this glyph, by its name; may be given several times. The other glyphs alone then "
                    "set the change of their kind")
    ap.add_argument("--res", type=int, default=512, metavar="N", help="pixels per em of the raster (default: 512)")
    return ap


def main(argv: list[str] | None = None) -> None:
    args = parser().parse_args(argv)
    print(report(args.light, args.heavy, args.reference, args.only, args.res), end="")


if __name__ == "__main__":
    main()
