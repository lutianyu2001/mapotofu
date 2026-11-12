"""Render sample lines of a font at several weights to a PNG, for looking at a build.

    mapo tool specimen FONT OUT.png [--size N] [--weights W,W,...] [--vertical]

    from mapotofu.tools.specimen import render

    render("build/fonts/Gothic-SC-Upright.otf", "out.png", 40, [250, 400, 800], vertical=False)

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


def render(path: str, out: str, size: int, weights: list[float], vertical: bool) -> None:
    data = open(path, "rb").read()
    hbfont = hb.Font(hb.Face(hb.Blob(data)))
    face = freetype.Face(path)
    face.set_char_size(size * 64)
    upm = hbfont.face.upem
    scale = size / upm
    rows = [(w, line) for w in weights for line in LINES]
    line_h = int(size * 1.6)
    width = int(size * 34)
    img = Image.new("L", (width if not vertical else line_h * len(rows) + 20, line_h * len(rows) + 20 if not vertical else width), 255)
    for r, (w, text) in enumerate(rows):
        hbfont.set_variations({"wght": w})
        try:
            face.set_var_design_coords((w,))
        except Exception:
            pass
        buf = hb.Buffer()
        buf.add_str(text)
        buf.guess_segment_properties()
        if vertical:
            buf.direction = "ttb"
        hb.shape(hbfont, buf, {})
        if vertical:
            x, y = img.width - (r + 1) * line_h, 10
        else:
            x, y = 10, 10 + r * line_h
        for info, pos in zip(buf.glyph_infos, buf.glyph_positions):
            face.load_glyph(info.codepoint, freetype.FT_LOAD_DEFAULT | freetype.FT_LOAD_NO_HINTING)
            g = face.glyph
            bmp = g.bitmap if g.format == freetype.FT_GLYPH_FORMAT_BITMAP else None
            g.render(freetype.FT_RENDER_MODE_NORMAL)
            bmp = g.bitmap
            if bmp.width and bmp.rows:
                glyph = Image.frombytes("L", (bmp.width, bmp.rows), bytes(bmp.buffer))
                if vertical:
                    ox = x + line_h // 2 + pos.x_offset * scale + g.bitmap_left
                    oy = y - pos.y_offset * scale - g.bitmap_top + size * 0.88
                else:
                    ox = x + pos.x_offset * scale + g.bitmap_left
                    oy = y + size - pos.y_offset * scale - g.bitmap_top
                img.paste(0, (int(ox), int(oy)), glyph)
            x += pos.x_advance * scale
            y -= pos.y_advance * scale
        if not vertical:
            ImageDraw.Draw(img).text((width - 40, 10 + r * line_h), str(int(w)), fill=128)
    img.save(out)


def parser(prog: str = "mapo tool specimen") -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog=prog, description="Render sample lines of a font at several weights into a PNG.")
    ap.add_argument("font", metavar="FONT")
    ap.add_argument("out", metavar="OUT.png")
    ap.add_argument("--size", type=int, default=32, metavar="N", help="pixels of an em (default: 32)")
    ap.add_argument("--weights", default="250,400,800", metavar="W,W,...",
                    help="the weights of a variable font to show (default: 250,400,800)")
    ap.add_argument("--vertical", action="store_true", help="set the lines vertically")
    return ap


def main(argv: list[str] | None = None) -> None:
    a = parser().parse_args(argv)
    render(a.font, a.out, a.size, [float(x) for x in a.weights.split(",")], a.vertical)


if __name__ == "__main__":
    main()
