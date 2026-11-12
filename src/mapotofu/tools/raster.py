"""Fonts by a short spec, and their glyphs rasterised.

A font spec is  path[#ttc_index][@axis=value,...], e.g.

    "Sans[wght].ttf@wght=500"   "Collection.ttc#2"   "Serif-Regular.otf"

    from mapotofu.tools.raster import FontSource

    font = FontSource("Sans[wght].ttf@wght=500")
    glyph = font.glyph("永")                 # None if the font has no such character
    glyph.ink                                # bool array [row, col], row 0 at the top
    glyph.to_em([[row, col]])                # pixels -> (x, y) in units of 1000 per em
    glyph.bbox()                             # the ink's box in those units

Glyphs are rasterised with FreeType, unhinted, at `res` pixels per em, onto a canvas that holds
the ink plus a margin. Everything downstream works in units of 1000 per em, whatever the font's
own units are.
"""

from __future__ import annotations

import os
import re

import freetype
import numpy as np
from fontTools.ttLib import TTFont

EM = 1000.0


def parse_spec(spec):
    """(path, index in a collection, {axis: value}) of a font spec."""
    path, loc, index = spec, {}, 0
    m = re.match(r"^(.*?)(?:@([A-Za-z0-9]{4}=[-\d.]+(?:,[A-Za-z0-9]{4}=[-\d.]+)*))?$", spec)
    if m and m.group(2):
        path = m.group(1)
        for kv in m.group(2).split(","):
            k, v = kv.split("=")
            loc[k] = float(v)
    base = os.path.basename(path)
    if "#" in base:
        path, idx = path.rsplit("#", 1)
        index = int(idx)
    return path, index, loc


def make_spec(path, index=0, loc=None):
    s = path + (f"#{index}" if index else "")
    if loc:
        s += "@" + ",".join(f"{k}={v:g}" for k, v in loc.items())
    return s


class Glyph:
    """A rasterised glyph: binary ink image plus the pixel -> em transform."""

    __slots__ = ("ink", "x0", "y0", "px", "advance", "ch")

    def __init__(self, ink, x0, y0, px, advance, ch):
        self.ink = ink        # bool array [row, col], row 0 at the top
        self.x0, self.y0 = x0, y0  # em coordinate of pixel (row 0, col 0) centre
        self.px = px          # em units per pixel
        self.advance = advance
        self.ch = ch

    def to_em(self, rc):
        """rc: (..., 2) array of (row, col) -> (..., 2) array of (x, y) in em units."""
        rc = np.asarray(rc, float)
        return np.stack([self.x0 + rc[..., 1] * self.px, self.y0 - rc[..., 0] * self.px], -1)

    def bbox(self):
        rows, cols = np.nonzero(self.ink)
        if not len(rows):
            return None
        (xa, ya), (xb, yb) = self.to_em(np.array([[rows.max(), cols.min()],
                                                   [rows.min(), cols.max()]]))
        return xa, ya, xb, yb


class FontSource:
    """A font opened by its spec: `cmap`, `upem`, `axes` ({tag: (min, default, max)}), a `label`
    for tables and sheets, and its glyphs rasterised at `res` pixels per em."""

    def __init__(self, spec, res=512):
        self.spec = spec
        self.path, self.index, self.loc = parse_spec(spec)
        tt = TTFont(self.path, fontNumber=self.index, lazy=True)
        self.upem = tt["head"].unitsPerEm
        self.cmap = tt.getBestCmap() or {}
        name = tt["name"]
        self.family = name.getBestFamilyName() or os.path.basename(self.path)
        self.subfamily = name.getBestSubFamilyName() or ""
        self.axes = ({a.axisTag: (a.minValue, a.defaultValue, a.maxValue) for a in tt["fvar"].axes}
                     if "fvar" in tt else {})
        tt.close()
        self.label = self.family + ("" if self.loc else f" {self.subfamily}")
        if self.loc:
            self.label += " @" + ",".join(f"{k}={v:g}" for k, v in self.loc.items())
        self.res = res
        self.face = freetype.Face(self.path, self.index)
        self.face.set_char_size(int(res * 64))  # 1 em = res px at 72 dpi
        if self.loc and self.axes:
            coords = [self.loc.get(t, d) for t, (_, d, _) in self.axes.items()]
            self.face.set_var_design_coords(coords)

    def has(self, ch):
        return ord(ch) in self.cmap

    def glyph(self, ch):
        if not self.has(ch):
            return None
        return self.glyph_index(self.face.get_char_index(ch), ch)

    def gray(self, ch):
        """The character's glyph in grey levels, drawn at `res` pixels per em: (uint8 array
        [row, col], the column of its left edge from the origin, the row of its top edge above
        the baseline, its advance in pixels), or None if the font lacks the character. A glyph
        without ink has an empty array."""
        if not self.has(ch):
            return None
        flags = freetype.FT_LOAD_NO_HINTING | freetype.FT_LOAD_NO_BITMAP | freetype.FT_LOAD_RENDER
        self.face.load_glyph(self.face.get_char_index(ch), flags)
        g = self.face.glyph
        bm = g.bitmap
        if bm.rows == 0 or bm.width == 0:
            return np.zeros((0, 0), np.uint8), 0, 0, g.advance.x / 64
        a = np.array(bm.buffer, np.uint8).reshape(bm.rows, bm.pitch)[:, : bm.width]
        return a, g.bitmap_left, g.bitmap_top, g.advance.x / 64

    def glyph_index(self, gid, ch=None):
        """Rasterise the glyph with this glyph ID (also glyphs no character maps to)."""
        flags = freetype.FT_LOAD_NO_HINTING | freetype.FT_LOAD_NO_BITMAP | freetype.FT_LOAD_RENDER
        self.face.load_glyph(gid, flags)
        g = self.face.glyph
        bm = g.bitmap
        if bm.rows == 0 or bm.width == 0:
            return None
        a = np.array(bm.buffer, np.uint8).reshape(bm.rows, bm.pitch)[:, : bm.width]
        pad = 3
        ink = np.pad(a >= 128, pad)
        px = EM / self.res
        x0 = (g.bitmap_left - pad + 0.5) * px
        y0 = (g.bitmap_top + pad - 0.5) * px
        return Glyph(ink, x0, y0, px, g.advance.x / 64 * px, ch)
