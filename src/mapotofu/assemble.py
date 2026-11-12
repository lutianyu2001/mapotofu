"""Assemble the parts of one font at every master and build the variable font (first build step)."""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass

from fontTools.designspaceLib import AxisDescriptor, DesignSpaceDocument, SourceDescriptor
from fontTools.fontBuilder import FontBuilder
from fontTools.otlLib import builder as otl
from fontTools.ttLib import TTFont, newTable
from fontTools.ttLib.tables import otTables as ot
from fontTools.varLib import build as varlib_build
from fontTools.varLib.featureVars import addFeatureVariations
from fontTools.varLib.models import piecewiseLinearMap

from . import layout, meta, sources, zones
from .charsets import KANA_VERTICAL, Cat, category, is_tiered, source_of
from .config import AXIS_DEFAULT, AXIS_MAX, AXIS_MIN, ITALIC_CJK, LATIN, MASTERS
from .glyphs import Glyph, GlyphStore, Master, bounds, charstring
from .parts import ItalicCJKPart, Part, cjk_part, italic_cjk_part, latin_part
from .tiers import shs_cmap, tiers

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class View:
    """One output font. family is Gothic, UI, Mono or Ext; region is SC, TC, J, or CJK for the
    shared extension."""

    family: str
    region: str
    italic: bool

    @property
    def is_ext(self) -> bool:
        return self.family == "Ext"

    @property
    def shs_region(self) -> str:
        return "J" if self.region == "CJK" else self.region

    @property
    def key(self) -> str:
        return f"{self.family}-{self.region}-{'Italic' if self.italic else 'Upright'}"


@dataclass
class Assembly:
    view: View
    store: GlyphStore
    cjk: Part
    latin: Part | None
    italic_cjk: ItalicCJKPart | None
    cmap: dict[int, str]
    uvs: list
    order: list[str]
    cont: tuple[str, str | None] | None = None  # continuation dash and its vertical form


# --- choosing code points -----------------------------------------------------------------------------


def _codepoints(view: View) -> tuple[set[int], set[int]]:
    """Code points taken from Source Han Sans and from the Latin source."""
    t = tiers()
    if view.is_ext:
        cps = t.shared if view.region == "CJK" else t.ext[view.region]
        return set(cps), set()
    shs = shs_cmap(view.region)
    lat_font = sources.latin(LATIN[(view.family, view.italic)]).font
    lat = set(lat_font.getBestCmap())
    main = t.main[view.region]
    cjk, latin = set(), set()
    for cp in shs.keys() | lat:
        if is_tiered(cp) and cp not in main:
            continue
        src = source_of(cp, view.family, cp in shs, cp in lat)
        if src == "cjk":
            cjk.add(cp)
        elif src == "latin":
            latin.add(cp)
    return cjk, latin


def prepare(view: View, store: GlyphStore | None = None) -> Assembly:
    """Choose and load the glyphs of a font; fonts sharing a store share glyphs by name."""
    store = store if store is not None else GlyphStore()
    cjk_cps, lat_cps = _codepoints(view)
    ital = None
    if view.italic and view.region in ITALIC_CJK:
        ital = italic_cjk_part(view.region, cjk_cps, KANA_VERTICAL, store)
        cjk_cps -= ital.cmap.keys()
    cjk = cjk_part(view.family, view.shs_region, cjk_cps, store)
    latin = latin_part(LATIN[(view.family, view.italic)], view.family, lat_cps, store) if lat_cps else None
    cmap = dict(cjk.cmap)
    if latin:
        cmap.update(latin.cmap)
    if ital:
        cmap.update(ital.cmap)
    uvs = [] if ital else list(cjk.uvs)
    order = _glyph_order(cmap, cjk, latin, ital)
    asm = Assembly(view, store, cjk, latin, ital, cmap, uvs, order)
    if view.family in ("Gothic", "Mono"):
        _continuation_dash(asm)
    return asm


def _glyph_order(cmap, cjk: Part, latin: Part | None, ital: ItalicCJKPart | None) -> list[str]:
    """.notdef, Latin, other glyphs of Source Han Sans, then ideographs by code point (SPEC 5.4)."""
    ideo: dict[str, int] = {}
    for cp in sorted(cmap):
        if category(cp) is Cat.IDEO:
            ideo.setdefault(cmap[cp], cp)
    out = [".notdef"]
    seen = {".notdef"}

    def add(names):
        for n in names:
            if n not in seen and n not in ideo:
                seen.add(n)
                out.append(n)

    if latin:
        add(latin.order)
    add(cjk.order)
    if ital:
        add(ital.order)
    out.extend(sorted(ideo, key=ideo.get))
    return out


# --- continuation dash (SPEC 3.5) -------------------------------------------------------------------


def _continuation_dash(asm: Assembly) -> None:
    g = asm.cmap.get(0x2014)
    if g is None:
        return
    glyph = asm.store[g]
    if not all((b := bounds(m.outline)) and b[0] > 0 for m in glyph.masters):
        return
    cont = f"{g}.cont"
    masters = []
    for m in glyph.masters:
        x0, y0, x1, y1 = bounds(m.outline)
        left = -(m.width - x1)  # meets the right end of the dash before it
        t = y1 - y0
        mid = (y0 + y1) / 2
        outline = [
            ("moveTo", ((x1, y0),)),
            ("lineTo", ((x1, y1),)),
            ("lineTo", ((left, y1),)),
            ("lineTo", ((left - t / 2, mid),)),
            ("lineTo", ((left, y0),)),
            ("closePath", ()),
        ]
        masters.append(Master(outline, m.width, m.height, m.vorg))
    asm.store.add(cont, Glyph(masters, glyph.linear))
    vcont = None
    vert = _vertical_form(asm, 0x2015)
    if vert is not None:
        vglyph = asm.store[vert]
        if all(bounds(m.outline) for m in vglyph.masters):
            vcont = f"{vert}.cont"
            vmasters = []
            for m in vglyph.masters:
                x0, y0, x1, y1 = bounds(m.outline)
                top_gap = m.vorg - y1  # space above the bar inside its em box
                bottom_gap = y0 - (m.vorg - m.height)
                top = y1 + top_gap + bottom_gap  # meets the lower end of the bar above
                t = x1 - x0
                mid = (x0 + x1) / 2
                outline = [
                    ("moveTo", ((x0, y0),)),
                    ("lineTo", ((x1, y0),)),
                    ("lineTo", ((x1, top),)),
                    ("lineTo", ((mid, top + t / 2),)),
                    ("lineTo", ((x0, top),)),
                    ("closePath", ()),
                ]
                vmasters.append(Master(outline, m.width, m.height, m.vorg))
            asm.store.add(vcont, Glyph(vmasters, vglyph.linear))
    asm.cont = (cont, vcont)
    asm.order.append(cont)
    if vcont:
        asm.order.append(vcont)


def _vertical_form(asm: Assembly, cp: int) -> str | None:
    g = asm.cjk.cmap.get(cp)
    if g is None:
        return None
    font = sources.load(asm.cjk.layout, asm.cjk.layout_order)
    gsub = font["GSUB"].table
    return layout.single_mapping(gsub, layout.feature_lookups(gsub, "vert")).get(g)


# --- one master ----------------------------------------------------------------------------------------


def _edit_layout(asm: Assembly, tables: dict) -> None:
    gsub = tables["GSUB"].table
    for tag in ("vert", "vrt2"):
        if tag not in layout.feature_tags(gsub):
            continue
        lookups = layout.feature_lookups(gsub, tag)
        mapping = layout.single_mapping(gsub, lookups)
        extra = {}
        g14, g15 = asm.cmap.get(0x2014), asm.cmap.get(0x2015)
        if g14 and g15 and g15 in mapping:  # SPEC 3.4
            extra[g14] = mapping[g15]
        if asm.italic_cjk:
            extra.update(asm.italic_cjk.vert)
        if asm.cont and asm.cont[1]:
            extra[asm.cont[0]] = asm.cont[1]
        if all(layout.lookup_type(gsub.LookupList.Lookup[i], "GSUB") == 1 for i in lookups):
            mapping.update(extra)
            layout.replace_single_feature(gsub, tag, mapping)  # SPEC 5.2
        elif extra:
            gsub.LookupList.Lookup.append(layout.single_lookup(extra))
            layout.every_langsys_feature(gsub, tag, len(gsub.LookupList.Lookup) - 1)
    if asm.cont:
        dash, cont = asm.cmap[0x2014], asm.cont[0]
        layout.insert_lookup(gsub, 0, layout.single_lookup({dash: cont}))
        st = ot.ChainContextSubst()
        st.Format = 3
        st.BacktrackCoverage = [_coverage([dash, cont])]
        st.InputCoverage = [_coverage([dash])]
        st.LookAheadCoverage = []
        rec = ot.SubstLookupRecord()
        rec.SequenceIndex = 0
        rec.LookupListIndex = 1
        st.SubstLookupRecord = [rec]
        st.BacktrackGlyphCount, st.InputGlyphCount, st.LookAheadGlyphCount, st.SubstCount = 1, 1, 0, 1
        layout.insert_lookup(gsub, 0, otl.buildLookup([st]))
        layout.every_langsys_feature(gsub, "calt", 0)
    for tag in ("GSUB", "GPOS"):
        layout.share_default_features(tables[tag].table)
        layout.merge_same_tag_features(tables[tag].table)
        layout.sort_features(tables[tag].table)


def _coverage(glyphs: list[str]) -> ot.Coverage:
    cov = ot.Coverage()
    cov.glyphs = list(glyphs)
    return cov


def master_font(asm: Assembly, i: int, order: list[str] | None = None, outlines: bool = True) -> TTFont:
    """The font at master i. With outlines False every glyph is empty: the layout and metrics
    are what matters, the outlines come from a shared pool (see build_group)."""
    order = order or asm.order
    w = MASTERS[i]
    cjk = sources.instantiate(asm.cjk.layout, asm.cjk.layout_order, asm.cjk.location(w))
    if asm.latin:
        lat = sources.instantiate(asm.latin.layout, asm.latin.layout_order, asm.latin.location(w))
        tables = layout.merge_fonts_layout(cjk, lat)
    else:
        tables = {t: cjk[t] for t in ("GSUB", "GPOS", "GDEF") if t in cjk}
    _edit_layout(asm, tables)

    _notdef(asm.store, i)
    fb = _glyph_font(asm.store, order, i, outlines)
    fb.setupCharacterMap(asm.cmap, uvs=asm.uvs or None)
    gid = {n: i for i, n in enumerate(order)}
    for tag, table in tables.items():
        layout.sort_coverages(table.table, gid)
        fb.font[tag] = table
    if "BASE" in cjk:
        fb.font["BASE"] = cjk["BASE"]
    if asm.latin:
        # At each master its own, so that what the source varies with the weight varies in the
        # font (varLib writes MVAR for it) and reaches the static weights when they are instanced.
        latin = sources.latin(LATIN[(asm.view.family, asm.view.italic)])
        for field, value in latin.os2(w).items():
            setattr(fb.font["OS/2"], field, value)
    return fb.font


def _notdef(store: GlyphStore, i: int) -> Master:
    if ".notdef" not in store:
        store.add(".notdef", sources.shs().glyph(0))
    return store[".notdef"].at(i)


def _glyph_font(store: GlyphStore, order: list[str], i: int, outlines: bool) -> FontBuilder:
    """A font with the glyphs and metrics of master i, without cmap or layout."""
    w = MASTERS[i]
    sparse = w not in (AXIS_MIN, AXIS_DEFAULT, AXIS_MAX)
    fb = FontBuilder(1000, isTTF=False)
    fb.setupGlyphOrder(order)
    charstrings, hmtx, vmtx, vorg = {}, {}, {}, {}
    for n in order:
        g = store[n]
        # An empty charstring in a non-default master marks the glyph as absent there.
        empty = not outlines or (g.static and w != AXIS_DEFAULT) or (g.linear and sparse)
        charstrings[n] = charstring(g.at(i), empty=empty)
    fb.setupCFF("mapotofu", {"FullName": "mapotofu"}, charstrings, {})
    for n in order:
        m = store[n].at(i)
        # The side bearings are those of the glyph as its charstring draws it (the curves, their
        # points rounded), not of its control points. Only the default master's reach the
        # variable font, where every glyph has its outline.
        b = charstrings[n].calcBounds(None)
        vorg[n] = round(m.vorg)
        hmtx[n] = (round(m.width), math.floor(b[0]) if b else 0)
        vmtx[n] = (round(m.height), vorg[n] - math.ceil(b[3]) if b else 0)
    fb.setupHorizontalMetrics(hmtx)
    fb.setupHorizontalHeader(ascent=1160, descent=-288)
    fb.setupVerticalMetrics(vmtx)
    fb.setupVerticalHeader(ascent=500, descent=-500)
    fb.setupCharacterMap({})
    fb.setupOS2()
    fb.setupPost(keepGlyphNames=False)
    fb.setupNameTable({"familyName": "mapotofu", "styleName": "Regular"})
    t = newTable("VORG")
    t.majorVersion, t.minorVersion = 1, 0
    t.defaultVertOriginY = 880
    t.VOriginRecords = {n: v for n, v in vorg.items() if v != 880}
    t.numVertOriginYMetrics = len(t.VOriginRecords)
    fb.font["VORG"] = t
    return fb


# --- variable font -------------------------------------------------------------------------------------


def _designspace(fonts: list[TTFont]) -> DesignSpaceDocument:
    ds = DesignSpaceDocument()
    axis = AxisDescriptor()
    axis.name, axis.tag = "Weight", "wght"
    axis.minimum, axis.default, axis.maximum = AXIS_MIN, AXIS_DEFAULT, AXIS_MAX
    # Design coordinates are the normalized coordinate times 1000.
    design = {w: n * 1000 for w, n in sources.axis_map()}
    axis.map = [(w, design[w]) for w in MASTERS]
    ds.addAxis(axis)
    for w, font in zip(MASTERS, fonts):
        src = SourceDescriptor()
        src.font = font
        src.location = {"Weight": design[w]}
        src.name = f"master{w}"
        ds.addSource(src)
    return ds


POOLED = ("CFF2", "hmtx", "HVAR", "vmtx", "VVAR", "VORG", "maxp")


def _bbox(font: TTFont, tag: str) -> tuple[int, int, int, int]:
    """The bounding box of the glyphs of a CFF or CFF2 table (of a CFF2, at the default weight),
    as fontTools sets head's when saving."""
    from fontTools.misc.arrayTools import intRect, unionRect

    charstrings = font[tag].cff.topDictIndex[0].CharStrings
    box = None
    for cs in charstrings.values():
        bounds = cs.calcBounds(charstrings)
        if bounds is not None:
            box = bounds if box is None else unionRect(box, bounds)
    return intRect(box or (0, 0, 0, 0))


def _extent(masters: list[TTFont]) -> tuple[int, int]:
    """The lowest and the highest point of the pool's glyphs over the whole weight axis. Between
    two masters every point of a glyph moves in a straight line, so a glyph reaches furthest at
    one of the masters that hold it (the others have an empty charstring, which has no box)."""
    boxes = [_bbox(m, "CFF ") for m in masters]
    return min(b[1] for b in boxes), max(b[3] for b in boxes)


def build_group(views: list[View]) -> tuple[list[tuple[View, TTFont]], tuple[int, int]]:
    """Variable fonts of views that share one glyph pool: the same glyph order and byte-identical
    glyph tables (POOLED), so that a collection of them stores each glyph once. Each font maps
    only its own characters; a standalone font is cut from it by subsetting. With them, the
    lowest and the highest point of the pool's glyphs over all weights (see _extent)."""
    store = GlyphStore()
    asms = []
    for view in views:
        asms.append(prepare(view, store))
        log.info("%s: %d glyphs", view.key, len(asms[-1].order))
    order = list(dict.fromkeys(n for asm in asms for n in asm.order))
    log.info("pool of %s: %d glyphs", "+".join(v.key for v in views), len(order))
    if len(order) > 0xFFFF:
        raise ValueError(f"{len(order)} glyphs in the pool of {views}")
    pool_masters = []
    for i in range(len(MASTERS)):
        _notdef(store, i)
        pool_masters.append(_glyph_font(store, order, i, True).font)
    extent = _extent(pool_masters)
    pool, _, _ = varlib_build(_designspace(pool_masters))
    del pool_masters
    zones.apply(pool, order)
    bbox = _bbox(pool, "CFF2")
    out = []
    for asm in asms:
        vf, _, _ = varlib_build(_designspace([master_font(asm, i, order, outlines=False) for i in range(len(MASTERS))]))
        for tag in POOLED:
            vf[tag] = pool[tag]
        # Of the default weight, as in every variable font; fontTools would set it only when
        # saving.
        head = vf["head"]
        head.xMin, head.yMin, head.xMax, head.yMax = bbox
        if asm.italic_cjk and asm.italic_cjk.subs:
            _italic_cjk_variations(vf, asm.italic_cjk)
        meta.finalize(vf, asm.view, extent=extent)
        out.append((asm.view, vf))
    return out, extent


def build(view: View) -> TTFont:
    return build_group([view])[0][0][1]


def _normalize(w: float) -> float:
    """Normalized coordinate of a weight after avar, which FeatureVariations conditions use."""
    return piecewiseLinearMap(w, dict(sources.axis_map()))


def _italic_cjk_variations(vf: TTFont, ital: ItalicCJKPart) -> None:
    """Switch the CJK italic weight with the weight axis (PLAN 5)."""
    eps = 1 / 16384
    conds = []
    for lo, hi, mapping in ital.subs:
        top = _normalize(hi) - (eps if hi < AXIS_MAX else 0)
        conds.append(([{"wght": (_normalize(lo), top)}], mapping))
    addFeatureVariations(vf, conds, featureTag="rvrn")
