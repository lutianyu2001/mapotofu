"""The parts a main font is made of: symbols and ideographs from Source Han Sans, Latin from Noto
Sans or JetBrains Mono, and, in italics, ideographs and kana from a regular-script font."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field

from fontTools import subset
from fontTools.fontBuilder import FontBuilder

from . import layout, sources
from .charsets import Cat, category, is_kana
from .config import KAI, OT_LANG, LatinSource
from .glyphs import Glyph, GlyphStore, Rule, renamed, resolve, transformed

GSUB_DROP = {"locl", "ccmp", "aalt", "pwid", "fwid", "hwid", "twid", "qwid"}  # SPEC 3.4
GPOS_DROP_MONO = {"kern", "vkrn", "palt", "vpal", "halt"}  # SPEC 3.4

# Characters whose proportional form UI uses before its width rules (SPEC 3.1).
UI_PWID = {0x2018, 0x2019, 0x201C, 0x201D}


@dataclass
class Part:
    """Layout-only variable font (bytes plus glyph order) and the glyphs it maps."""

    layout: bytes | None
    layout_order: list[str]
    location: Callable[[float], dict[str, float]]
    cmap: dict[int, str]
    uvs: list[tuple[int, int, str | None]] = field(default_factory=list)
    order: list[str] = field(default_factory=list)  # every glyph of the part, layout ones first


def _subset(font, unicodes, keep_features) -> None:
    opts = subset.Options()
    opts.layout_features = sorted(keep_features)
    opts.glyph_names = True
    opts.notdef_outline = True
    opts.name_IDs = ["*"]
    opts.name_languages = ["*"]
    opts.hinting = False
    opts.layout_closure = True
    opts.prune_unicode_ranges = False
    opts.prune_codepage_ranges = False
    opts.ignore_missing_unicodes = True
    opts.drop_tables = [t for t in opts.drop_tables if t != "BASE"]
    s = subset.Subsetter(opts)
    s.populate(unicodes=unicodes)
    s.subset(font)


def _set_cmap(font, cmap: dict[int, str], uvs) -> None:
    fb = FontBuilder(font=font)
    fb.setupCharacterMap(cmap, uvs=uvs or None)


def _uvs(font, cps: set[int]) -> list[tuple[int, int, str | None]]:
    """Variation sequences of the ideographs among cps (those of symbols, which select widths,
    would contradict the width rules)."""
    cps = {cp for cp in cps if category(cp) is Cat.IDEO}
    out = []
    for st in font["cmap"].tables:
        if st.format == 14:
            for vs, entries in st.uvsDict.items():
                out.extend((cp, vs, g) for cp, g in entries if cp in cps)
    return out


def _rename(data: bytes, order: list[str], names: dict[str, str]) -> tuple[bytes, list[str]]:
    new = [names.get(g, g) for g in order]
    font = sources.load(data, new)
    for tag in font.keys():
        font[tag]
    if "post" in font:
        font["post"].formatType = 3.0
    return sources.dump(font), new


# --- Source Han Sans ---------------------------------------------------------------------------------


def cjk_rule(family: str, cp: int) -> Rule | None:
    """SPEC 3.3."""
    if family == "Gothic":
        if cp == 0x00B7:
            return Rule("center", 1000)
        if cp in (0x2018, 0x201C):
            return Rule("right", 1000)
        if cp in (0x2019, 0x201D):
            return Rule("keep", 1000)
        if 0x2010 <= cp <= 0x2013:
            return Rule("stretch", 500)
        if cp in (0x2014, 0x2015):
            return Rule("stretch", 1000)
        if cp in (0x2025, 0x2026):
            return Rule("center", 1000)
    elif family == "UI":
        if cp in (0x00B7, 0x2010):
            return Rule("center", 500)
    elif family == "Mono":
        if cp == 0x00B7:
            return Rule("center", 500)
        if cp in (0x2018, 0x201C, 0x2019, 0x201D):
            return Rule("keep", 500)
        if 0x2010 <= cp <= 0x2015:
            return Rule("stretch", 500)
        if cp in (0x2025, 0x2026):
            return Rule("center", 500)
    if cp == 0x2E3A:
        return Rule("stretch", 2000)
    if cp == 0x2E3B:
        return Rule("stretch", 3000)
    if cp in (0x31B4, 0x31B5, 0x31B6, 0x31B7, 0x31BB):
        return Rule("center", 500)
    if family == "Mono" and category(cp) is not Cat.IDEO:
        return Rule("ceil")
    return None


def cjk_part(family: str, region: str, cps: set[int], store: GlyphStore) -> Part:
    data, order = sources.shs_layout(region)
    font = sources.load(data, list(order))
    for tag in ("cmap", "GSUB", "GPOS", "GDEF"):
        font[tag]
    best = font.getBestCmap()
    cmap = {cp: best[cp] for cp in cps if cp in best}
    gsub = font["GSUB"].table
    if family == "Gothic":
        lang = OT_LANG[region].ljust(4)
        locl = layout.single_mapping(gsub, layout.feature_lookups(gsub, "locl", lang))
        for cp, g in cmap.items():
            if category(cp) is Cat.AS and cp != 0x2010 and g in locl:
                cmap[cp] = locl[g]
    elif family == "UI":
        # Source Han Sans maps the em dash and horizontal bar to proportional glyphs and gives
        # the full-width ones through locl; UI keeps the full width (SPEC 3.3).
        lang = OT_LANG[region].ljust(4)
        locl = layout.single_mapping(gsub, layout.feature_lookups(gsub, "locl", lang))
        for cp in (0x2014, 0x2015):
            if cp in cmap:
                cmap[cp] = locl.get(cmap[cp], cmap[cp])
        pwid = layout.single_mapping(gsub, layout.feature_lookups(gsub, "pwid"))
        for cp in UI_PWID & cmap.keys():
            cmap[cp] = pwid.get(cmap[cp], cmap[cp])
    uvs = _uvs(font, set(cmap))
    _set_cmap(font, cmap, uvs)
    keep = (layout.feature_tags(gsub) - GSUB_DROP) | layout.feature_tags(font["GPOS"].table)
    if family == "Mono":
        keep -= GPOS_DROP_MONO
    _subset(font, set(cmap), keep)
    lay_order = font.getGlyphOrder()
    uvs = _uvs(font, set(cmap))

    shs = sources.shs()
    gid = {sources.cid(i): i for i in range(len(shs.names))}
    # One rule per glyph, from the lowest code point mapped to it; other code points whose rule
    # differs get a copy of the glyph that only the cmap uses.
    by_glyph: dict[str, list[int]] = {}
    for cp in sorted(cmap):
        by_glyph.setdefault(cmap[cp], []).append(cp)
    names: dict[str, str] = {}
    clones: dict[int, str] = {}
    base: dict[str, Glyph] = {}

    def make(g: str, rule: Rule | None) -> str:
        if g not in base:
            base[g] = shs.glyph(gid[g])
        src = base[g]
        r = resolve(rule, [m.width for m in src.masters]) if rule else None
        name = renamed(g, r)
        if name not in store:
            store.add(name, transformed(r, src) if r else src)
        return name

    for g in lay_order:
        if g == ".notdef":
            names[g] = g
            if g not in store:
                store.add(g, shs.glyph(0))
            continue
        cps_g = by_glyph.get(g, [])
        rule = cjk_rule(family, cps_g[0]) if cps_g else (Rule("ceil") if family == "Mono" else None)
        names[g] = make(g, rule)
        for cp in cps_g[1:]:
            other = make(g, cjk_rule(family, cp))
            if other != names[g]:
                clones[cp] = other
    new_data, new_order = _rename(sources.dump(font), lay_order, names)
    final = {cp: clones.get(cp, names[g]) for cp, g in cmap.items()}
    final_uvs = [(cp, vs, names[g] if g else None) for cp, vs, g in uvs]
    order = list(new_order) + sorted(set(clones.values()) - set(new_order))
    return Part(new_data, new_order, sources.cjk_location, final, final_uvs, order)


# --- Latin -------------------------------------------------------------------------------------------


def latin_part(src: LatinSource, family: str, cps: set[int], store: GlyphStore) -> Part:
    lat = sources.latin(src)
    data, order = sources.latin_font(src)
    font = sources.load(data, list(order))
    for tag in font.keys():
        font[tag]
    best = font.getBestCmap()
    cmap = {cp: best[cp] for cp in cps if cp in best}
    if family == "UI":  # SPEC 4.2: tabular figures by default
        gsub = font["GSUB"].table
        tnum = layout.single_mapping(gsub, layout.feature_lookups(gsub, "tnum"))
        for cp in range(0x30, 0x3A):
            if cp in cmap:
                cmap[cp] = tnum.get(cmap[cp], cmap[cp])
    _set_cmap(font, cmap, None)
    keep = layout.feature_tags(font["GSUB"].table) | layout.feature_tags(font["GPOS"].table)
    for tag in ("HVAR", "MVAR", "STAT", "gasp", "prep", "fpgm", "cvt ", "cvar"):
        if tag in font:
            del font[tag]
    _subset(font, set(cmap), keep)
    lay_order = font.getGlyphOrder()
    for g in lay_order[1:]:
        if g not in store:
            store.add(g, lat.glyph(g))
    # Outlines live in the store; the layout copy keeps only what instancing needs.
    for tag in ("glyf", "loca", "gvar"):
        if tag in font:
            del font[tag]
    font.sfntVersion = "OTTO"
    return Part(sources.dump(font), lay_order, lat.location, cmap, [], lay_order[1:])


# --- regular script ----------------------------------------------------------------------------------


@dataclass
class KaiPart:
    cmap: dict[int, str]  # default glyphs (the weight that holds at the default 400)
    subs: list[tuple[int, int, dict[str, str]]]  # (from, to weight, default glyph -> glyph)
    vert: dict[str, str]
    order: list[str]


def kai_part(group: str, cps: set[int], shs_vert_cps: set[int], store: GlyphStore) -> KaiPart:
    """Ideographs and kana of `cps` that every regular-script weight of `group` has.

    A kana that must move or turn in vertical text (shs_vert_cps) is only taken when each weight
    has a vertical form for it too."""
    from .config import AXIS_DEFAULT, AXIS_MAX

    weights = KAI[group]
    chosen: dict[int, list[tuple[object, str]]] = {}
    for cp in sorted(cps):
        if not (category(cp) is Cat.IDEO or is_kana(cp)):
            continue
        per = []
        for w in weights:
            hit = next(((sources.kai(s), sources.kai(s).cmap[cp]) for s in w.sources if cp in sources.kai(s).cmap), None)
            if hit is None or (cp in shs_vert_cps and hit[1] not in hit[0].vert):
                break
            per.append(hit)
        else:
            chosen[cp] = per
    default_idx = max(i for i, w in enumerate(weights) if w.start <= AXIS_DEFAULT)
    cmap, vert, order = {}, {}, []
    subs: list[tuple[int, int, dict[str, str]]] = []
    for i, w in enumerate(weights):
        hi = weights[i + 1].start if i + 1 < len(weights) else AXIS_MAX
        subs.append((w.start, hi, {}))
    for cp, per in chosen.items():
        names = []
        for k, g in per:
            n = k.name(g)
            if n not in store:
                store.add(n, k.glyph(g))
            names.append(n)
            order.append(n)
            if g in k.vert:
                vn = k.name(k.vert[g])
                if vn not in store:
                    store.add(vn, k.glyph(k.vert[g]))
                vert[n] = vn
                order.append(vn)
        cmap[cp] = names[default_idx]
        for i, n in enumerate(names):
            if i != default_idx and n != names[default_idx]:
                subs[i][2][names[default_idx]] = n
    subs = [s for i, s in enumerate(subs) if i != default_idx and s[2]]
    return KaiPart(cmap, subs, vert, list(dict.fromkeys(order)))
