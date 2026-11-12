"""Groups of code points that must stay in the same slice when a font is cut by code point
(PLAN 10.2), computed from the font's own layout rules.

Characters are linked when one rule involves several of them: a ligature, a contextual rule
(such as the continuation dash or the programming ligatures of Mono), a kerning subtable or
mark attachment. Single substitutions (vert, tnum, rvrn and the like) link nothing, because
subsetting keeps the substituted glyphs of every character it keeps.
"""

from __future__ import annotations

from collections import defaultdict

from fontTools.ttLib import TTFont
from fontTools.ttLib.tables import otTables as ot

from .layout import lookup_type, subtables, walk

MULTI_GSUB = {4, 5, 6, 8}  # ligature, context, chained context, reverse chained
MULTI_GPOS = {2, 3, 4, 5, 6, 7, 8}  # pair, cursive, mark attachment, context


def _glyphs_in(subtable) -> set[str]:
    out: set[str] = set()
    for obj in walk(subtable):
        if isinstance(obj, ot.Coverage):
            out.update(obj.glyphs)
        elif isinstance(obj, ot.ClassDef):
            out.update(obj.classDefs)
        for attr in ("Input", "Backtrack", "LookAhead", "Component", "Substitute"):
            v = getattr(obj, attr, None)
            if isinstance(v, list):
                out.update(x for x in v if isinstance(x, str))
        if isinstance(obj, ot.LigatureSubst):
            for first, ligs in obj.ligatures.items():
                out.add(first)
                for lig in ligs:
                    out.update(lig.Component)
        if isinstance(obj, ot.PairPos) and obj.Format == 1:
            for ps in obj.PairSet:
                out.update(r.SecondGlyph for r in ps.PairValueRecord)
    return out


def _reach(font: TTFont) -> dict[str, set[int]]:
    """Glyph -> code points whose text can produce it."""
    reach: dict[str, set[int]] = defaultdict(set)
    for cp, g in font.getBestCmap().items():
        reach[g].add(cp)
    if "GSUB" not in font:
        return reach
    gsub = font["GSUB"].table
    edges: dict[str, set[str]] = defaultdict(set)
    for lk in gsub.LookupList.Lookup:
        t = lookup_type(lk, "GSUB")
        for st in subtables(lk):
            if t == 1:
                for a, b in st.mapping.items():
                    edges[a].add(b)
            elif t == 2:
                for a, seq in st.mapping.items():
                    edges[a].update(seq)
            elif t == 3:
                for a, alts in st.alternates.items():
                    edges[a].update(alts)
            elif t == 4:
                for first, ligs in st.ligatures.items():
                    for lig in ligs:
                        for comp in (first, *lig.Component):
                            edges[comp].add(lig.LigGlyph)
    changed = True
    while changed:
        changed = False
        for a, outs in edges.items():
            src = reach.get(a)
            if not src:
                continue
            for b in outs:
                if not src <= reach[b]:
                    reach[b] |= src
                    changed = True
    return reach


def groups(font: TTFont) -> list[frozenset[int]]:
    """Sets of code points (two or more) that must share a slice."""
    reach = _reach(font)
    parent: dict[int, int] = {}

    def find(x: int) -> int:
        while parent.setdefault(x, x) != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(cps: set[int]) -> None:
        it = iter(cps)
        first = next(it, None)
        if first is None:
            return
        r = find(first)
        for cp in it:
            parent[find(cp)] = r

    for tag, multi in (("GSUB", MULTI_GSUB), ("GPOS", MULTI_GPOS)):
        if tag not in font:
            continue
        for lk in font[tag].table.LookupList.Lookup:
            if lookup_type(lk, tag) not in multi:
                continue
            for st in subtables(lk):
                cps: set[int] = set()
                for g in _glyphs_in(st):
                    cps |= reach.get(g, set())
                union(cps)
    out: dict[int, set[int]] = defaultdict(set)
    for cp in list(parent):
        out[find(cp)].add(cp)
    return [frozenset(s) for s in out.values() if len(s) > 1]
