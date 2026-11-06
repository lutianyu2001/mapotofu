"""Access to the source fonts: outlines at each master, and layout-only copies with stable names."""

from __future__ import annotations

import functools
import io

from fontTools.misc.fixedTools import otRound
from fontTools.ttLib import TTFont
from fontTools.ttLib.scaleUpem import scale_upem
from fontTools.varLib.instancer import instantiateVariableFont
from fontTools.varLib.models import piecewiseLinearMap
from fontTools.varLib.varStore import VarStoreInstancer

from . import layout
from .config import AXIS_DEFAULT, AXIS_MAX, AXIS_MIN, CJK_WEIGHT_MAP, MASTERS, SHS, SOURCES, KaiSource, LatinSource
from .glyphs import Glyph, Master, record

OUTLINE_TABLES = ("CFF2", "CFF ", "glyf", "loca", "gvar", "HVAR", "VVAR", "VORG", "cvar", "fpgm", "prep", "cvt ", "gasp")


def cjk_location(weight: float) -> dict[str, float]:
    return {"wght": piecewiseLinearMap(weight, dict(CJK_WEIGHT_MAP))}


@functools.cache
def axis_map() -> tuple[tuple[float, float], ...]:
    """(weight of the fonts, normalized coordinate) at each master.

    Source Han Sans has a single region and is linear in its own normalized coordinate. The
    output's normalized coordinate is made an affine function of it on each side of the default,
    so its glyphs need only the extreme and default masters. Every source is piecewise linear
    between masters both in weight and in this coordinate, so the result is exact."""
    font = TTFont(SOURCES / SHS["J"], lazy=True)
    axis = next(a for a in font["fvar"].axes if a.axisTag == "wght")
    seg = font["avar"].segments["wght"]

    def ns(w: float) -> float:
        x = cjk_location(w)["wght"]
        return piecewiseLinearMap((x - axis.minValue) / (axis.maxValue - axis.minValue), seg)

    lo, mid, hi = ns(AXIS_MIN), ns(AXIS_DEFAULT), ns(AXIS_MAX)
    return tuple((w, (ns(w) - mid) / ((mid - lo) if w < AXIS_DEFAULT else (hi - mid))) for w in MASTERS)


def cid(gid: int) -> str:
    return ".notdef" if gid == 0 else f"cid{gid:05d}"


def load(data: bytes, order: list[str] | None = None) -> TTFont:
    font = TTFont(io.BytesIO(data), recalcBBoxes=False, recalcTimestamp=False)
    if order is not None:
        font.setGlyphOrder(order)
    return font


def dump(font: TTFont) -> bytes:
    buf = io.BytesIO()
    font.recalcBBoxes = False
    font.save(buf)
    return buf.getvalue()


def instantiate(data: bytes, order: list[str], location: dict[str, float]) -> TTFont:
    """A static copy of a layout-only variable font."""
    font = load(data, order)
    for tag in font.keys():
        font[tag]
    return instantiateVariableFont(font, location)


# --- Source Han Sans ------------------------------------------------------------------------------


class SourceHanSans:
    """Glyph data is the same in every region (one CFF2 shared by the region fonts), so outlines
    are read from the J font and named by glyph ID."""

    def __init__(self) -> None:
        self.font = TTFont(SOURCES / SHS["J"])
        self.names = self.font.getGlyphOrder()
        self.sets = [self.font.getGlyphSet(location=cjk_location(w), normalized=False) for w in MASTERS]
        vvar = self.font["VVAR"].table
        axes = self.font["fvar"].axes
        self.vorg_default = self.font["VORG"].defaultVertOriginY
        self.vorg = self.font["VORG"].VOriginRecords
        self.vorg_map = vvar.VOrgMap.mapping if vvar.VOrgMap else None
        self.vorg_inst = [VarStoreInstancer(vvar.VarStore, axes, _normalize(self.font, cjk_location(w))) for w in MASTERS]

    def glyph(self, gid: int) -> Glyph:
        name = self.names[gid]
        masters = []
        for i, gs in enumerate(self.sets):
            g = gs[name]
            vorg = self.vorg.get(name, self.vorg_default)
            if self.vorg_map is not None and name in self.vorg_map:
                vorg += self.vorg_inst[i][self.vorg_map[name]]
            masters.append(Master(record(g, gs), g.width, g.height, otRound(vorg)))
        return Glyph(masters, linear=True)


def _normalize(font: TTFont, loc: dict[str, float]) -> dict[str, float]:
    from fontTools.varLib.instancer import normalize

    out = {}
    for a in font["fvar"].axes:
        v = loc.get(a.axisTag, a.defaultValue)
        out[a.axisTag] = normalize(v, (a.minValue, a.defaultValue, a.maxValue), font["avar"].segments.get(a.axisTag) if "avar" in font else None)
    return out


@functools.cache
def shs() -> SourceHanSans:
    return SourceHanSans()


@functools.cache
def shs_layout(region: str) -> tuple[bytes, tuple[str, ...]]:
    """Source Han Sans of a region without outlines, glyphs named cidNNNNN."""
    font = TTFont(SOURCES / SHS[region], recalcBBoxes=False)
    order = [cid(i) for i in range(font["maxp"].numGlyphs)]
    font.setGlyphOrder(order)
    for tag in OUTLINE_TABLES:
        if tag in font:
            del font[tag]
    return dump(font), tuple(order)


# --- Latin -----------------------------------------------------------------------------------------


@functools.cache
def latin_font(src: LatinSource) -> tuple[bytes, tuple[str, ...]]:
    """The Latin source with glyphs renamed "<tag>.<name>", scaled if needed."""
    orig = TTFont(SOURCES / src.path, lazy=True).getGlyphOrder()
    order = [f"{src.tag}.{n}" for n in orig]
    font = TTFont(SOURCES / src.path, recalcBBoxes=False)
    font.setGlyphOrder(order)
    for tag in font.keys():
        font[tag]
    if src.scale != 1:
        # scale_upem scales everything (outlines, metrics, GPOS, variations) by new/old upem.
        font["head"].unitsPerEm = round(1000 / src.scale)
        scale_upem(font, 1000)
    return dump(font), tuple(order)


class Latin:
    def __init__(self, src: LatinSource) -> None:
        data, order = latin_font(src)
        self.src = src
        self.font = load(data, list(order))
        self.sets = [
            self.font.getGlyphSet(location={"wght": w, **dict(src.location)}, normalized=False) for w in MASTERS
        ]

    def location(self, weight: float) -> dict[str, float]:
        return {"wght": weight, **dict(self.src.location)}

    def glyph(self, name: str) -> Glyph:
        masters = []
        for gs in self.sets:
            g = gs[name]
            outline = record(g, gs)
            masters.append(Master(outline, g.width, 1000, 880))
        return Glyph(masters)


@functools.cache
def latin(src: LatinSource) -> Latin:
    return Latin(src)


# --- regular script (italics) ------------------------------------------------------------------------


class Kai:
    def __init__(self, src: KaiSource) -> None:
        self.src = src
        self.font = TTFont(SOURCES / src.path)
        self.cmap = self.font.getBestCmap()
        self.gs = self.font.getGlyphSet()
        gsub = self.font["GSUB"].table if "GSUB" in self.font else None
        self.vert = layout.single_mapping(gsub, layout.feature_lookups(gsub, "vert")) if gsub else {}
        self.vmtx = self.font["vmtx"].metrics if "vmtx" in self.font else {}

    def name(self, glyph: str) -> str:
        return f"{self.src.tag}.{glyph}"

    def glyph(self, glyph: str) -> Glyph:
        g = self.gs[glyph]
        outline = record(g, self.gs)
        from .glyphs import bounds

        b = bounds(outline)
        height, tsb = self.vmtx.get(glyph, (1000, 0))
        vorg = (b[3] + tsb) if b else 880
        return Glyph([Master(outline, g.width, height, otRound(vorg))])


@functools.cache
def kai(src: KaiSource) -> Kai:
    return Kai(src)
