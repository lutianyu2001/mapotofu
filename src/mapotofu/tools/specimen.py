"""Render sample lines of a font at several weights to a PNG, for looking at a build.

    mapo tool specimen FONT OUT.png [--text LINE ...] [--size N] [--weights W,W,...] [--vertical]

    from mapotofu.tools.specimen import render

    render("build/fonts/Gothic-SC-Upright.otf", "out.png", 40, [250, 400, 800], vertical=False)
    render("build/fonts/Gothic-SC-Upright.otf", "out.png", 40, [400], False, ["第 3 章 Chapter 3", "2026 年"])

The lines are shaped with HarfBuzz, so the font's layout features apply as they do in text.
"""

from __future__ import annotations

import argparse

import freetype
import uharfbuzz as hb
from PIL import Image, ImageDraw

LINES = [
    "Aa Gg 永国あア 「中文」，『日本語』。",
    "“Quotes” ‘and’ — dashes ——— … · Aa Ж Ω 0123456789",
    "->  != <= => === /* */ <!-- --> www ffi",
    "ぁぃぅ（括弧）【見出し】〜ー※〒①②③",
]
WIDTH = 34      # ems: the least length a line has room for; a longer line makes the picture longer


def render(path: str, out: str, size: int, weights: list[float], vertical: bool,
           lines: list[str] | None = None) -> None:
    """Set `lines` (LINES if not given) in the font at each of `weights`, a block of lines a
    weight with the weight beside each line, into the PNG `out`. A font without a weight axis has
    one weight: its lines are set once, without a number."""
    data = open(path, "rb").read()
    hbfont = hb.Font(hb.Face(hb.Blob(data)))
    face = freetype.Face(path)
    face.set_char_size(size * 64)
    upm = hbfont.face.upem
    scale = size / upm
    if not any(axis.tag == "wght" for axis in hbfont.face.axis_infos):
        weights = [None]
    shaped = []                                   # (weight, the glyphs of a line, its length)
    for w in weights:
        if w is not None:
            hbfont.set_variations({"wght": w})
        for text in lines or LINES:
            buf = hb.Buffer()
            buf.add_str(text)
            buf.guess_segment_properties()
            if vertical:
                buf.direction = "ttb"
            hb.shape(hbfont, buf, {})
            glyphs = [(info.codepoint, pos.x_advance, pos.y_advance, pos.x_offset, pos.y_offset)
                      for info, pos in zip(buf.glyph_infos, buf.glyph_positions)]
            shaped.append((w, glyphs, abs(sum(g[2] if vertical else g[1] for g in glyphs)) * scale))
    line_h = int(size * 1.6)
    width = max(int(size * WIDTH), int(max(length for _, _, length in shaped)) + 70)   # (the margin, the weight's number)
    img = Image.new("L", (width if not vertical else line_h * len(shaped) + 20,
                          line_h * len(shaped) + 20 if not vertical else width), 255)
    for r, (w, glyphs, _) in enumerate(shaped):
        if w is not None:
            try:
                face.set_var_design_coords((w,))
            except Exception:
                pass
        if vertical:
            x, y = img.width - (r + 1) * line_h, 10
        else:
            x, y = 10, 10 + r * line_h
        for glyph_id, x_advance, y_advance, x_offset, y_offset in glyphs:
            face.load_glyph(glyph_id, freetype.FT_LOAD_DEFAULT | freetype.FT_LOAD_NO_HINTING)
            g = face.glyph
            g.render(freetype.FT_RENDER_MODE_NORMAL)
            bmp = g.bitmap
            if bmp.width and bmp.rows:
                glyph = Image.frombytes("L", (bmp.width, bmp.rows), bytes(bmp.buffer))
                if vertical:
                    ox = x + line_h // 2 + x_offset * scale + g.bitmap_left
                    oy = y - y_offset * scale - g.bitmap_top + size * 0.88
                else:
                    ox = x + x_offset * scale + g.bitmap_left
                    oy = y + size - y_offset * scale - g.bitmap_top
                img.paste(0, (int(ox), int(oy)), glyph)
            x += x_advance * scale
            y -= y_advance * scale
        if not vertical and w is not None:
            ImageDraw.Draw(img).text((width - 40, 10 + r * line_h), str(int(w)), fill=128)
    img.save(out)


def parser(prog: str = "mapo tool specimen") -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog=prog, description="Render sample lines of a font at several weights into a PNG.")
    ap.add_argument("font", metavar="FONT")
    ap.add_argument("out", metavar="OUT.png")
    ap.add_argument("--text", action="append", metavar="LINE",
                    help="a line to set instead of the built-in sample lines; may be given several times, a line each")
    ap.add_argument("--size", type=int, default=32, metavar="N", help="pixels of an em (default: 32)")
    ap.add_argument("--weights", default="250,400,800", metavar="W,W,...",
                    help="the weights of a variable font to show (default: 250,400,800)")
    ap.add_argument("--vertical", action="store_true", help="set the lines vertically")
    return ap


def main(argv: list[str] | None = None) -> None:
    a = parser().parse_args(argv)
    render(a.font, a.out, a.size, [float(x) for x in a.weights.split(",")], a.vertical, a.text)


if __name__ == "__main__":
    main()
