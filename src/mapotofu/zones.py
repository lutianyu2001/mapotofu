"""The hinting values of the glyphs (the Private DICT of CFF2: alignment zones and stem widths),
by the source a glyph comes from and at every master.

A hinter aligns a glyph with the zones and stems of its font DICT, and a rasterizer snaps and
darkens stems by them. One set for a whole pool, taken at the default weight, fits few of its
glyphs: the Latin of another source has other heights, ideographs have no heights of that kind
at all, and stems grow with the weight. So a pool has a font DICT for each kind of glyph:

- glyphs of Source Han Sans keep the values of their font DICT there, which Adobe set for each
  kind (ideographs, kana, Latin, ...), read at the weight each master takes from it;
- glyphs of a Latin source get the baseline, the x-height and the cap height of that source at
  each master (sources.Latin.os2), and the stems measured in its l and H;
- glyphs of a CJK italic source get no zones, as ideographs have none, and the stems measured
  in its 丨 and 一.

The values depend on the sources alone, not on the pool, so that a glyph has the same key in
the hint cache wherever it is built.
"""

from __future__ import annotations

import functools
import io

from fontTools.misc.bezierTools import calcCubicParameters, solveCubic
from fontTools.misc.fixedTools import otRound
from fontTools.pens.basePen import BasePen
from fontTools.pens.boundsPen import BoundsPen
from fontTools.ttLib import TTFont
from fontTools.varLib.models import VariationModel, supportScalar

from . import sources
from .config import ITALIC_CJK_SOURCES, LATIN, MASTERS, ItalicCJKSource, LatinSource

# The values a Private DICT may blend, which are those a hinter and a rasterizer read.
FIELDS = (
    "BlueValues", "OtherBlues", "FamilyBlues", "FamilyOtherBlues", "BlueScale", "BlueShift", "BlueFuzz",
    "StdHW", "StdVW", "StemSnapH", "StemSnapV",
)
OVERSHOOT = 14  # how far a round letter passes its line: the height of a Latin zone
NO_ZONES = [-250, -250, 1100, 1100]  # zones no glyph reaches, as Source Han Sans gives its ideographs
STEMS = (80, 60)  # vertical and horizontal stem where a source has no glyph to measure

Values = dict[str, "int | float | list"]


# --- measuring stems -------------------------------------------------------------------------------


class _Segments(BasePen):
    """The outline as line and cubic segments, closed."""

    def __init__(self) -> None:
        super().__init__(None)
        self.segments: list[tuple] = []
        self._start = None

    def _moveTo(self, pt):
        self._start = pt

    def _lineTo(self, pt):
        self.segments.append((self._getCurrentPoint(), pt))

    def _curveToOne(self, pt1, pt2, pt3):
        self.segments.append((self._getCurrentPoint(), pt1, pt2, pt3))

    def _closePath(self):
        here = self._getCurrentPoint()
        if self._start is not None and here != self._start:
            self.segments.append((here, self._start))


def _draw(outline, pen) -> None:
    for op, args in outline:
        getattr(pen, op)(*args)


def _crossings(segment: tuple, axis: int, at: float) -> list[float]:
    """Where a line or cubic segment crosses the line on which the coordinate `axis` is `at`:
    the other coordinate of each crossing."""
    other = 1 - axis
    if len(segment) == 2:
        p, q = segment
        if (p[axis] - at) * (q[axis] - at) > 0 or p[axis] == q[axis]:
            return []
        t = (at - p[axis]) / (q[axis] - p[axis])
        return [p[other] + t * (q[other] - p[other])]
    a, b, c, d = calcCubicParameters(*segment)
    roots = solveCubic(a[axis], b[axis], c[axis], d[axis] - at)
    return [((a[other] * t + b[other]) * t + c[other]) * t + d[other] for t in roots if 0 <= t <= 1]


def stem(outline, vertical: bool) -> int | None:
    """The thickness of the stroke that a line through the middle of the glyph crosses first:
    of a vertical stem, cut by a horizontal line at half its height (which measures a slanted
    stem as wide as it stands on the line), or of a horizontal one, cut by a vertical line."""
    bounds = BoundsPen(None)
    _draw(outline, bounds)
    if bounds.bounds is None:
        return None
    x0, y0, x1, y1 = bounds.bounds
    axis, at = (1, (y0 + y1) / 2) if vertical else (0, (x0 + x1) / 2)
    pen = _Segments()
    _draw(outline, pen)
    crossings = sorted({round(c, 3) for segment in pen.segments for c in _crossings(segment, axis, at)})
    if len(crossings) < 2:
        return None
    return otRound(crossings[1] - crossings[0])


# --- the values of each source ---------------------------------------------------------------------


LISTS = ("BlueValues", "OtherBlues", "FamilyBlues", "FamilyOtherBlues", "StemSnapH", "StemSnapV")


def _absolute(key: str, raw, scalars: list[float]) -> "int | float | list[int]":
    """A value of a Private DICT of a variable font at a location. A blended number is written
    [default, delta of each region]; in a list, each entry is so written with its default as it
    is and the deltas of its difference from the entry before (as fontTools reads CFF2)."""

    def moved(item) -> float:
        return sum(s * d for s, d in zip(scalars, item[1:])) if isinstance(item, list) else 0.0

    if key not in LISTS:
        return otRound(raw[0] + moved(raw)) if isinstance(raw, list) else raw
    out, before, value = [], 0, 0.0
    for item in raw:
        default = item[0] if isinstance(item, list) else item
        value += (default - before) + moved(item)
        out.append(otRound(value))
        before = default
    return out


@functools.cache
def shs() -> tuple[tuple[int, ...], tuple[tuple[Values, ...], ...]]:
    """The font DICT of each glyph of Source Han Sans, and the values of each font DICT at
    each master."""
    font = sources.shs().font
    top = font["CFF2"].cff.topDictIndex[0]
    store = top.VarStore.otVarStore
    regions = store.VarRegionList.Region
    tags = [a.axisTag for a in font["fvar"].axes]
    select = tuple(top.FDSelect.gidArray)
    dicts = []
    for fd in top.FDArray:
        private = fd.Private
        data = store.VarData[getattr(private, "vsindex", 0) or 0]
        supports = [
            {tag: (a.StartCoord, a.PeakCoord, a.EndCoord) for tag, a in zip(tags, regions[r].VarRegionAxis)}
            for r in data.VarRegionIndex
        ]
        at_masters = []
        for w in MASTERS:
            location = sources._normalize(font, sources.cjk_location(w))
            scalars = [supportScalar(location, support) for support in supports]
            values = {k: _absolute(k, private.rawDict[k], scalars) for k in FIELDS if k in private.rawDict}
            if "LanguageGroup" in private.rawDict:
                values["LanguageGroup"] = private.rawDict["LanguageGroup"]
            at_masters.append(values)
        dicts.append(tuple(at_masters))
    return select, tuple(dicts)


def _measure(glyph, i: int, vertical: bool) -> int | None:
    return stem(glyph.at(i).outline, vertical) if glyph is not None else None


@functools.cache
def latin(src: LatinSource) -> tuple[Values, ...]:
    """The values of a Latin source at each master."""
    lat = sources.latin(src)
    cmap = lat.font.getBestCmap()

    def glyph(*chars: str):
        return next((lat.glyph(cmap[ord(c)]) for c in chars if ord(c) in cmap), None)

    upright, bar = glyph("l", "I"), glyph("H", "-")
    out = []
    for i, w in enumerate(MASTERS):
        os2 = lat.os2(w)
        x, cap = os2["sxHeight"], os2["sCapHeight"]
        out.append({
            "BlueValues": [-OVERSHOOT, 0, x, x + OVERSHOOT, cap, cap + OVERSHOOT],
            "StdVW": _measure(upright, i, True) or STEMS[0],
            "StdHW": _measure(bar, i, False) or STEMS[1],
        })
    return tuple(out)


@functools.cache
def italic_cjk(src: ItalicCJKSource) -> tuple[Values, ...]:
    """The values of a CJK italic source, the same at every master: it has one weight."""
    ital = sources.italic_cjk(src)

    def glyph(cp: int):
        return ital.glyph(ital.cmap[cp]) if cp in ital.cmap else None

    values = {
        "BlueValues": list(NO_ZONES),
        "StdVW": _measure(glyph(0x4E28), 0, True) or STEMS[0],
        "StdHW": _measure(glyph(0x4E00), 0, False) or STEMS[1],
    }
    return (values,) * len(MASTERS)


def _kind(name: str) -> tuple:
    """What decides the font DICT of a glyph of the first step, by its name there."""
    prefix = name.split(".", 1)[0]
    if name == ".notdef":
        return ("cid", shs()[0][0])
    if prefix.startswith("cid") and prefix[3:].isdigit():
        return ("cid", shs()[0][int(prefix[3:])])
    if any(prefix == src.tag for src in LATIN.values()):
        return ("latin", prefix)
    if prefix in ITALIC_CJK_SOURCES:
        return ("italic", prefix)
    raise ValueError(f"no source for the glyph {name}")


def _values(kind: tuple) -> tuple[Values, ...]:
    if kind[0] == "cid":
        return shs()[1][kind[1]]
    if kind[0] == "latin":
        return latin(next(src for src in LATIN.values() if src.tag == kind[1]))
    return italic_cjk(ITALIC_CJK_SOURCES[kind[1]])


# --- the font DICTs of a pool ----------------------------------------------------------------------


def _blended(key: str, at_masters: list, model: VariationModel, order: list[int]):
    """The value of a Private DICT that is `at_masters` at the model's masters, as fontTools
    writes it: a number or list where the masters agree, else blended, the deltas in the order
    of the regions of the font (`order`: for each region, its place among the model's)."""

    def deltas(values: list) -> list:
        d = model.getDeltas(values)
        return [d[0]] + [d[j] for j in order]

    def whole(n):
        return int(n) if float(n).is_integer() else n

    if isinstance(at_masters[0], list):
        if len({len(v) for v in at_masters}) != 1:
            raise ValueError(f"{key} has not as many values at every master")
        if all(v == at_masters[0] for v in at_masters):
            return list(at_masters[0])
        out, previous = [], [0] * len(at_masters)
        for column in zip(*at_masters):
            row = deltas([v - p for v, p in zip(column, previous)])
            row[0] = column[0]  # the default is written as it is, the deltas are of the difference
            out.append([whole(n) for n in row])
            previous = column
        return out
    if all(v == at_masters[0] for v in at_masters):
        return at_masters[0]
    return [whole(n) for n in deltas(list(at_masters))]


def apply(font: TTFont, order: list[str]) -> None:
    """Give the CFF2 of a pool of the first step (glyphs named as in `order`, one font DICT) a
    font DICT for each kind of glyph in it, with that kind's values at every master."""
    from fontTools.cffLib import FDSelect, FontDict, PrivateDict
    from fontTools.ttLib import newTable

    table = font["CFF2"]
    top = table.cff.topDictIndex[0]
    store = top.VarStore.otVarStore
    # The values vary over the regions the Private DICTs name: the first set, which glyphs
    # without a set of their own use too. It is that of every master where a glyph has them
    # all, else that of the masters every glyph has.
    coords = [n for _, n in sources.axis_map()]
    peaks = [store.VarRegionList.Region[r].VarRegionAxis[0].PeakCoord for r in store.VarData[0].VarRegionIndex]
    used = [coords.index(0)] + [min(range(len(coords)), key=lambda i: abs(coords[i] - p)) for p in peaks]
    model = VariationModel([{"wght": coords[i]} if coords[i] else {} for i in used], ["wght"])
    own = [support["wght"][1] for support in model.supports[1:]]
    regions = [1 + min(range(len(own)), key=lambda j: abs(own[j] - p)) for p in peaks]
    assert sorted(regions) == list(range(1, len(peaks) + 1)), (peaks, own)

    kinds = [_kind(name) for name in order]
    listed = sorted(set(kinds), key=lambda k: (("cid", "latin", "italic").index(k[0]), k[1]))
    dicts = []
    for kind in listed:
        at = _values(kind)
        # A file, as when a Private DICT is read, so that it is one of CFF2.
        private = PrivateDict(None, io.BytesIO(), 0, isCFF2=True, vstore=top.VarStore)
        for key in at[0]:
            private.rawDict[key] = _blended(key, [at[i][key] for i in used], model, regions)
        fd = FontDict()
        fd.setCFF2(True)
        fd.Private = private
        dicts.append(fd)
    top.FDArray.items = dicts
    select = FDSelect()
    select.format = 3
    select.gidArray = [listed.index(kind) for kind in kinds]
    top.FDSelect = select
    # Compiled and read again, so that every charstring knows its own Private DICT.
    data = table.compile(font)
    font["CFF2"] = table = newTable("CFF2")
    table.decompile(data, font)
