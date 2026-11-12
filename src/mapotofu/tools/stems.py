"""Stroke widths and glyph size of fonts, measured on their rasterised glyphs.

    mapo tool stems FONT... [--chars TEXT] [--res N]

    from mapotofu.tools.raster import FontSource
    from mapotofu.tools.stems import font_stems, glyph_stems

    font_stems(FontSource("Sans[wght].ttf@wght=500"))    # medians over the characters
    glyph_stems(FontSource("Kai.ttf").glyph("王"))         # one glyph

A stroke's width is twice the distance from its centre line to its edge: the glyph is
rasterised, thinned to its skeleton, and the distance transform read along it, away from
where strokes meet. How the outline is drawn does not matter, so fonts with round ends, curved
sides or strokes of a brush are measured as plain gothics are. (AFDKO's otfstemhist reads
stems off the outline's straight edges, for hinting: on a font with straight strokes the two
agree; on a rounded one it pairs the wrong edges.)

Per font, medians over the characters measured, in units of 1000 per em:

    stem_v   width of vertical strokes (those running within 12 degrees of the vertical)
    stem_h   width of horizontal strokes
    hv       stem_h / stem_v
    weight   width of all strokes, whatever their direction
    spread   the 90th percentile of a glyph's stroke widths over its 10th: 1 for a monoline
    face     the larger side of the ink's box: the glyph's size in the em

It tells which weight of a source matches a master (`cjk_weights`, the weights of
`italic_cjk`) and what `scale` fits one font's glyphs to another's.
"""

from __future__ import annotations

import argparse
import math

import numpy as np
from scipy.spatial import cKDTree

from .raster import FontSource
from .skeleton import SkelGraph

# Characters built of 横 and 竖, common to the Chinese and Japanese standards; and Latin letters
# with plain stems, for a font without them.
HAN = "一二三十土王田中日目口工正生主古世其具直真草早車東書里重量事高面百西画由甲申用同国固回因"
LATIN = "HEFLTIilnmhu"
HORIZONTAL, VERTICAL = 12.0, 12.0     # degrees off the axis a stroke may run to count as 横 / 竖


def trimmed(x):
    """Mean of the middle half: as robust as a median, but not stuck on the discrete
    values a pixel distance transform produces."""
    lo, hi = np.percentile(x, [25, 75])
    sel = x[(x >= lo) & (x <= hi)]
    return float(sel.mean()) if len(sel) else float(np.median(x))


def graph_stems(graph: SkelGraph, px: float) -> dict:
    """weight, spread, hv, stem_h and stem_v of one glyph from its skeleton graph; px is the
    size of a pixel in the units wanted (Glyph.px). NaN where the glyph has too little of it
    (no horizontal stroke, say)."""
    pts, body = graph.body_mask()
    widths = 2 * graph.dt[pts[:, 0], pts[:, 1]] * px
    out = {"weight": np.nan, "spread": np.nan, "hv": np.nan, "stem_h": np.nan, "stem_v": np.nan}
    if body.sum() >= 10:
        wb = widths[body]
        out["weight"] = trimmed(wb)
        out["spread"] = float(np.percentile(wb, 90) / max(np.percentile(wb, 10), 1e-6))
    if body.sum() < 30:
        return out
    # the direction of the skeleton at each point, from the points around it
    P, W = pts[body].astype(float), widths[body]
    hor, ver = [], []
    for i, nb in enumerate(cKDTree(P).query_ball_point(P, r=6.0)):
        if len(nb) < 5:
            continue
        _, _, vt = np.linalg.svd(P[nb] - P[nb].mean(0), full_matrices=False)
        dr, dc = vt[0]
        a = math.degrees(math.atan2(-dr, dc)) % 180
        if a < HORIZONTAL or a > 180 - HORIZONTAL:
            hor.append(W[i])
        elif 90 - VERTICAL < a < 90 + VERTICAL:
            ver.append(W[i])
    h = trimmed(np.array(hor)) if len(hor) >= 15 else np.nan
    v = trimmed(np.array(ver)) if len(ver) >= 15 else np.nan
    out.update(hv=h / v, stem_h=h, stem_v=v)
    return out


def glyph_stems(glyph) -> dict:
    """graph_stems of a rasterised glyph (raster.Glyph), and `face`: the larger side of its
    ink's box."""
    out = graph_stems(SkelGraph(glyph.ink), glyph.px)
    box = glyph.bbox()
    out["face"] = max(box[2] - box[0], box[3] - box[1]) if box else np.nan
    return out


def font_stems(font: FontSource, chars: str | None = None) -> dict:
    """The medians of glyph_stems over the characters the font has (HAN, or LATIN if it has
    none of those, when no characters are given), and `glyphs`, how many were measured."""
    if chars is None:
        chars = HAN if any(font.has(ch) for ch in HAN) else LATIN
    rows = [glyph_stems(g) for g in (font.glyph(ch) for ch in dict.fromkeys(chars)) if g is not None]
    out = {"glyphs": len(rows)}
    for key in ("stem_v", "stem_h", "hv", "weight", "spread", "face"):
        values = [r[key] for r in rows if not np.isnan(r[key])]
        out[key] = float(np.median(values)) if values else np.nan
    return out


def parser(prog: str = "mapo tool stems") -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        prog=prog, description="Measure the stroke widths and the glyph size of fonts, in units of 1000 per em.",
        epilog="A FONT is a file, a face of a collection (Font.ttc#2) or a place on the axes of a variable "
        "font (Font[wght].ttf@wght=500).",
    )
    ap.add_argument("fonts", nargs="+", metavar="FONT")
    ap.add_argument("--chars", metavar="TEXT", help="the characters to measure (default: Han characters built of "
                    "horizontal and vertical strokes; Latin letters for a font without them)")
    ap.add_argument("--res", type=int, default=512, metavar="N", help="pixels per em of the raster (default: 512)")
    return ap


def main(argv: list[str] | None = None) -> None:
    args = parser().parse_args(argv)
    rows = []
    for spec in args.fonts:
        font = FontSource(spec, args.res)
        rows.append((font.label, font_stems(font, args.chars)))
    width = max(len(label) for label, _ in rows)
    print(f"{'font':<{width}}  glyphs  stem_v  stem_h     hv  weight  spread    face")
    for label, r in rows:
        print(f"{label:<{width}}  {r['glyphs']:>6}  {r['stem_v']:>6.1f}  {r['stem_h']:>6.1f}  {r['hv']:>5.3f}  "
              f"{r['weight']:>6.1f}  {r['spread']:>6.2f}  {r['face']:>6.1f}")


if __name__ == "__main__":
    main()
