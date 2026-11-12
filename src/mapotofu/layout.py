"""Helpers for GSUB, GPOS and GDEF: reading substitutions, merging two disjoint layouts, and the
edits of SPEC 3.4, 3.5 and 5."""

from __future__ import annotations

import copy
from collections.abc import Iterable, Iterator

from fontTools.otlLib import builder as otl
from fontTools.ttLib import TTFont, newTable
from fontTools.ttLib.tables import otTables as ot

EXTENSION = {"GSUB": 7, "GPOS": 9}
SINGLE = {"GSUB": 1}


# --- walking -------------------------------------------------------------------------------


def walk(obj) -> Iterator[ot.BaseTable]:
    """Every otTables object below obj, depth first, obj included."""
    stack = [obj]
    while stack:
        cur = stack.pop()
        if isinstance(cur, ot.BaseTable):
            yield cur
            stack.extend(v for v in vars(cur).values() if isinstance(v, (ot.BaseTable, list)))
        elif isinstance(cur, list):
            stack.extend(v for v in cur if isinstance(v, (ot.BaseTable, list)))


def subtables(lookup: ot.Lookup) -> Iterator[ot.BaseTable]:
    """The subtables of a lookup with extension wrappers removed."""
    for st in lookup.SubTable:
        yield getattr(st, "ExtSubTable", st)


def lookup_type(lookup: ot.Lookup, tag: str) -> int:
    if lookup.LookupType == EXTENSION[tag]:
        return lookup.SubTable[0].ExtensionLookupType
    return lookup.LookupType


def langsystems(table) -> Iterator[tuple[str, str, ot.LangSys]]:
    """(script, language, LangSys) for every language system; the default one is "dflt"."""
    if not table.ScriptList:
        return
    for sr in table.ScriptList.ScriptRecord:
        if sr.Script.DefaultLangSys is not None:
            yield sr.ScriptTag, "dflt", sr.Script.DefaultLangSys
        for lr in sr.Script.LangSysRecord:
            yield sr.ScriptTag, lr.LangSysTag, lr.LangSys


def feature_lookups(table, tag: str, lang: str | None = None) -> list[int]:
    """Lookup indices of feature `tag` in the language systems `lang` (any if None), in order."""
    if not table or not table.FeatureList:
        return []
    feats = set()
    for _, ltag, ls in langsystems(table):
        if lang is None or ltag == lang:
            feats.update(i for i in ls.FeatureIndex if table.FeatureList.FeatureRecord[i].FeatureTag == tag)
    out: set[int] = set()
    for i in feats:
        out.update(table.FeatureList.FeatureRecord[i].Feature.LookupListIndex)
    return sorted(out)


def single_mapping(table, lookups: Iterable[int], tag: str = "GSUB") -> dict[str, str]:
    """The single substitutions of the given lookups, later lookups applied after earlier ones."""
    result: dict[str, str] = {}
    for li in sorted(lookups):
        lk = table.LookupList.Lookup[li]
        if lookup_type(lk, tag) != 1:
            continue
        step: dict[str, str] = {}
        for st in subtables(lk):
            for a, b in st.mapping.items():
                step.setdefault(a, b)
        for a, b in list(result.items()):
            if b in step:
                result[a] = step[b]
        for a, b in step.items():
            result.setdefault(a, b)
    return result


def feature_tags(table) -> set[str]:
    if not table or not table.FeatureList:
        return set()
    return {fr.FeatureTag for fr in table.FeatureList.FeatureRecord}


# --- editing --------------------------------------------------------------------------------


def _lookup_refs(table) -> Iterator[ot.BaseTable]:
    """Objects whose LookupListIndex is a single lookup index (nested lookup records)."""
    for lk in table.LookupList.Lookup:
        for st in subtables(lk):
            for obj in walk(st):
                if isinstance(getattr(obj, "LookupListIndex", None), int):
                    yield obj


def _features(table) -> Iterator[ot.Feature]:
    for fr in table.FeatureList.FeatureRecord:
        yield fr.Feature
    fv = getattr(table, "FeatureVariations", None)
    if fv:
        for rec in fv.FeatureVariationRecord:
            for sub in rec.FeatureTableSubstitution.SubstitutionRecord:
                yield sub.Feature


def insert_lookup(table, index: int, lookup: ot.Lookup) -> None:
    """Insert a lookup at `index` and renumber every reference to the lookups after it."""
    for obj in _lookup_refs(table):
        if obj.LookupListIndex >= index:
            obj.LookupListIndex += 1
    for feat in _features(table):
        feat.LookupListIndex = [i + 1 if i >= index else i for i in feat.LookupListIndex]
    table.LookupList.Lookup.insert(index, lookup)
    table.LookupList.LookupCount = len(table.LookupList.Lookup)


def add_feature(table, tag: str, lookups: list[int]) -> int:
    fr = ot.FeatureRecord()
    fr.FeatureTag = tag
    fr.Feature = ot.Feature()
    fr.Feature.FeatureParams = None
    fr.Feature.LookupListIndex = list(lookups)
    fr.Feature.LookupCount = len(lookups)
    table.FeatureList.FeatureRecord.append(fr)
    table.FeatureList.FeatureCount = len(table.FeatureList.FeatureRecord)
    return len(table.FeatureList.FeatureRecord) - 1


def drop_features(table, tags: set[str]) -> None:
    """Detach features from every language system (unused lookups are pruned by the subsetter)."""
    if not table or not table.FeatureList:
        return
    drop = {i for i, fr in enumerate(table.FeatureList.FeatureRecord) if fr.FeatureTag in tags}
    for _, _, ls in langsystems(table):
        ls.FeatureIndex = [i for i in ls.FeatureIndex if i not in drop]
        ls.FeatureCount = len(ls.FeatureIndex)
        if ls.ReqFeatureIndex in drop:
            ls.ReqFeatureIndex = 0xFFFF


def sort_features(table) -> None:
    """Order FeatureRecords by tag, as the specification asks, and renumber references."""
    if not table or not table.FeatureList:
        return
    recs = table.FeatureList.FeatureRecord
    order = sorted(range(len(recs)), key=lambda i: (recs[i].FeatureTag, i))
    remap = {old: new for new, old in enumerate(order)}
    table.FeatureList.FeatureRecord = [recs[i] for i in order]
    for _, _, ls in langsystems(table):
        ls.FeatureIndex = sorted(remap[i] for i in ls.FeatureIndex)
        if ls.ReqFeatureIndex != 0xFFFF:
            ls.ReqFeatureIndex = remap[ls.ReqFeatureIndex]
    fv = getattr(table, "FeatureVariations", None)
    if fv:
        for rec in fv.FeatureVariationRecord:
            for sub in rec.FeatureTableSubstitution.SubstitutionRecord:
                sub.FeatureIndex = remap[sub.FeatureIndex]


def single_lookup(mapping: dict[str, str], tag: str = "GSUB") -> ot.Lookup:
    return otl.buildLookup([otl.buildSingleSubstSubtable(mapping)], flags=0)


def replace_single_feature(table, tag: str, mapping: dict[str, str]) -> None:
    """Make feature `tag` a single lookup holding `mapping` everywhere it appears (SPEC 5.2)."""
    old = {i for i, fr in enumerate(table.FeatureList.FeatureRecord) if fr.FeatureTag == tag}
    if not old:
        return
    table.LookupList.Lookup.append(single_lookup(mapping))
    li = len(table.LookupList.Lookup) - 1
    table.LookupList.LookupCount = li + 1
    for i in old:
        feat = table.FeatureList.FeatureRecord[i].Feature
        feat.LookupListIndex = [li]
        feat.LookupCount = 1


def share_default_features(table) -> None:
    """Append the features of DFLT/dflt to the CJK scripts and languages (SPEC 5.1)."""
    if not table or not table.ScriptList:
        return
    dflt = next((sr.Script.DefaultLangSys for sr in table.ScriptList.ScriptRecord if sr.ScriptTag == "DFLT"), None)
    if dflt is None:
        return
    extra = list(dflt.FeatureIndex)
    for script, lang, ls in langsystems(table):
        if (script in ("hani", "kana", "bopo", "hang") and lang == "dflt") or lang in (
            "JAN ",
            "KOR ",
            "ZHS ",
            "ZHT ",
            "ZHH ",
        ):
            ls.FeatureIndex = sorted(set(ls.FeatureIndex) | set(extra))
            ls.FeatureCount = len(ls.FeatureIndex)


def every_langsys_feature(table, tag: str, lookup_index: int) -> None:
    """Make lookup `lookup_index` part of feature `tag` in every language system (SPEC 3.5)."""
    for fr in table.FeatureList.FeatureRecord:
        if fr.FeatureTag == tag and lookup_index not in fr.Feature.LookupListIndex:
            fr.Feature.LookupListIndex = sorted([*fr.Feature.LookupListIndex, lookup_index])
            fr.Feature.LookupCount = len(fr.Feature.LookupListIndex)
    new = None
    for _, _, ls in langsystems(table):
        if not any(table.FeatureList.FeatureRecord[i].FeatureTag == tag for i in ls.FeatureIndex):
            if new is None:
                new = add_feature(table, tag, [lookup_index])
            ls.FeatureIndex = sorted([*ls.FeatureIndex, new])
            ls.FeatureCount = len(ls.FeatureIndex)


# --- merging two layouts with disjoint glyph sets ---------------------------------------------


def _empty(tag: str):
    t = getattr(ot, tag)()
    t.Version = 0x00010000
    t.ScriptList = ot.ScriptList()
    t.ScriptList.ScriptRecord = []
    t.FeatureList = ot.FeatureList()
    t.FeatureList.FeatureRecord = []
    t.LookupList = ot.LookupList()
    t.LookupList.Lookup = []
    return t


def _copy_langsys(ls: ot.LangSys, offset: int) -> ot.LangSys:
    new = ot.LangSys()
    new.LookupOrder = None
    new.ReqFeatureIndex = 0xFFFF
    new.FeatureIndex = [i + offset for i in ls.FeatureIndex]
    new.FeatureCount = len(new.FeatureIndex)
    return new


def _union(a: ot.LangSys | None, b: ot.LangSys | None) -> ot.LangSys:
    new = ot.LangSys()
    new.LookupOrder = None
    new.ReqFeatureIndex = 0xFFFF
    new.FeatureIndex = sorted(set(a.FeatureIndex if a else []) | set(b.FeatureIndex if b else []))
    new.FeatureCount = len(new.FeatureIndex)
    return new


def merge_layout(tag: str, first, second, mark_class_offset: int, mark_set_offset: int):
    """Merge two GSUB or GPOS tables that act on disjoint glyphs.

    A language system present in one table only also receives the default features of the
    other script, since the other font would have used its default language there."""
    first = copy.deepcopy(first) if first else _empty(tag)
    second = copy.deepcopy(second) if second else _empty(tag)
    lk_off = len(first.LookupList.Lookup)
    ft_off = len(first.FeatureList.FeatureRecord)

    for obj in _lookup_refs(second):
        obj.LookupListIndex += lk_off
    for fr in second.FeatureList.FeatureRecord:
        fr.Feature.LookupListIndex = [i + lk_off for i in fr.Feature.LookupListIndex]
    for lk in second.LookupList.Lookup:
        if lk.LookupFlag & 0xFF00:
            lk.LookupFlag = (lk.LookupFlag & 0x00FF) | (((lk.LookupFlag >> 8) + mark_class_offset) << 8)
        if lk.LookupFlag & 0x0010:
            lk.MarkFilteringSet += mark_set_offset

    out = _empty(tag)
    out.LookupList.Lookup = first.LookupList.Lookup + second.LookupList.Lookup
    out.FeatureList.FeatureRecord = first.FeatureList.FeatureRecord + second.FeatureList.FeatureRecord

    scripts_a = {sr.ScriptTag: sr.Script for sr in first.ScriptList.ScriptRecord}
    scripts_b = {sr.ScriptTag: sr.Script for sr in second.ScriptList.ScriptRecord}
    for s in sorted(set(scripts_a) | set(scripts_b)):
        a, b = scripts_a.get(s), scripts_b.get(s)
        da = a.DefaultLangSys if a else None
        db = _copy_langsys(b.DefaultLangSys, ft_off) if b and b.DefaultLangSys else None
        script = ot.Script()
        script.DefaultLangSys = _union(da, db) if (da or db) else None
        langs_a = {lr.LangSysTag: lr.LangSys for lr in (a.LangSysRecord if a else [])}
        langs_b = {lr.LangSysTag: _copy_langsys(lr.LangSys, ft_off) for lr in (b.LangSysRecord if b else [])}
        script.LangSysRecord = []
        for lang in sorted(set(langs_a) | set(langs_b)):
            lr = ot.LangSysRecord()
            lr.LangSysTag = lang
            lr.LangSys = _union(langs_a.get(lang, da), langs_b.get(lang, db))
            script.LangSysRecord.append(lr)
        script.LangSysCount = len(script.LangSysRecord)
        sr = ot.ScriptRecord()
        sr.ScriptTag = s
        sr.Script = script
        out.ScriptList.ScriptRecord.append(sr)
    for t in (out.LookupList, out.FeatureList, out.ScriptList):
        for attr, lst in (("LookupCount", "Lookup"), ("FeatureCount", "FeatureRecord"), ("ScriptCount", "ScriptRecord")):
            if hasattr(t, lst):
                setattr(t, attr, len(getattr(t, lst)))
    if getattr(first, "FeatureVariations", None) or getattr(second, "FeatureVariations", None):
        raise ValueError("cannot merge FeatureVariations")
    out.FeatureVariations = None
    return out


def merge_gdef(first, second) -> tuple[ot.GDEF | None, int, int]:
    """Merge two GDEF tables; return the table and the offsets of the second one's mark
    attachment classes and mark glyph sets."""
    a = first.table if first else None
    b = second.table if second else None
    gdef = ot.GDEF()
    gdef.Version = 0x00010000
    classes = {}
    for t in (a, b):
        if t and t.GlyphClassDef:
            classes.update(t.GlyphClassDef.classDefs)
    gdef.GlyphClassDef = ot.GlyphClassDef()
    gdef.GlyphClassDef.classDefs = classes
    gdef.AttachList = None
    # Ligature caret positions.
    carets = {}
    for t in (a, b):
        if t and t.LigCaretList:
            for g, lg in zip(t.LigCaretList.Coverage.glyphs, t.LigCaretList.LigGlyph):
                carets[g] = lg
    if carets:
        lcl = ot.LigCaretList()
        lcl.Coverage = ot.Coverage()
        lcl.Coverage.glyphs = list(carets)
        lcl.LigGlyph = list(carets.values())
        lcl.LigGlyphCount = len(carets)
        gdef.LigCaretList = lcl
    else:
        gdef.LigCaretList = None
    mark_off = 0
    attach = {}
    if a and a.MarkAttachClassDef:
        attach.update(a.MarkAttachClassDef.classDefs)
        mark_off = max(a.MarkAttachClassDef.classDefs.values(), default=0)
    if b and b.MarkAttachClassDef:
        attach.update({g: c + mark_off for g, c in b.MarkAttachClassDef.classDefs.items()})
    if attach:
        gdef.MarkAttachClassDef = ot.MarkAttachClassDef()
        gdef.MarkAttachClassDef.classDefs = attach
    else:
        gdef.MarkAttachClassDef = None
    sets = []
    set_off = 0
    for t in (a, b):
        mgs = getattr(t, "MarkGlyphSetsDef", None) if t else None
        if t is a:
            set_off = len(mgs.Coverage) if mgs else 0
        if mgs:
            sets.extend(mgs.Coverage)
    if sets:
        gdef.Version = 0x00010002
        gdef.MarkGlyphSetsDef = ot.MarkGlyphSetsDef()
        gdef.MarkGlyphSetsDef.MarkSetTableFormat = 1
        gdef.MarkGlyphSetsDef.Coverage = sets
        gdef.MarkGlyphSetsDef.MarkSetCount = len(sets)
    table = newTable("GDEF")
    table.table = gdef
    return table, mark_off, set_off


def merge_fonts_layout(first: TTFont, second: TTFont) -> dict[str, object]:
    """Merged GDEF, GSUB and GPOS of two fonts whose glyph names do not overlap."""
    gdef, mark_off, set_off = merge_gdef(first.get("GDEF"), second.get("GDEF"))
    out = {"GDEF": gdef}
    for tag in ("GSUB", "GPOS"):
        a = first[tag].table if tag in first else None
        b = second[tag].table if tag in second else None
        t = newTable(tag)
        t.table = merge_layout(tag, a, b, mark_off, set_off)
        out[tag] = t
    return out


# --- glyph order ------------------------------------------------------------------------------------

# (class name, coverage attribute, path to the array that follows the coverage's order)
_COVERED = (
    ("SinglePos", "Coverage", ("Value",)),
    ("PairPos", "Coverage", ("PairSet",)),
    ("CursivePos", "Coverage", ("EntryExitRecord",)),
    ("MarkBasePos", "MarkCoverage", ("MarkArray", "MarkRecord")),
    ("MarkBasePos", "BaseCoverage", ("BaseArray", "BaseRecord")),
    ("MarkLigPos", "MarkCoverage", ("MarkArray", "MarkRecord")),
    ("MarkLigPos", "LigatureCoverage", ("LigatureArray", "LigatureAttach")),
    ("MarkMarkPos", "Mark1Coverage", ("Mark1Array", "MarkRecord")),
    ("MarkMarkPos", "Mark2Coverage", ("Mark2Array", "Mark2Record")),
    ("ContextSubst", "Coverage", ("SubRuleSet",)),
    ("ContextPos", "Coverage", ("PosRuleSet",)),
    ("ChainContextSubst", "Coverage", ("ChainSubRuleSet",)),
    ("ChainContextPos", "Coverage", ("ChainPosRuleSet",)),
    ("ReverseChainSingleSubst", "Coverage", ("Substitute",)),
    ("LigCaretList", "Coverage", ("LigGlyph",)),
    ("AttachList", "Coverage", ("AttachPoint",)),
)


def sort_coverages(table, gid: dict[str, int]) -> None:
    """Sort every Coverage by glyph ID, reordering the arrays indexed by it, after the glyph
    order changed."""
    done = set()
    for obj in walk(table):
        cls = type(obj).__name__
        for name, cov_attr, path in _COVERED:
            if cls != name or not isinstance(getattr(obj, cov_attr, None), ot.Coverage):
                continue
            if name == "SinglePos" and getattr(obj, "Format", 0) != 2:
                continue
            owner = obj
            for attr in path[:-1]:
                owner = getattr(owner, attr)
            arr = getattr(owner, path[-1], None)
            cov = getattr(obj, cov_attr)
            if arr is None or not isinstance(arr, list):
                continue
            order = sorted(range(len(cov.glyphs)), key=lambda i: gid[cov.glyphs[i]])
            cov.glyphs = [cov.glyphs[i] for i in order]
            setattr(owner, path[-1], [arr[i] for i in order])
            done.add(id(cov))
    for obj in walk(table):
        if isinstance(obj, ot.Coverage) and id(obj) not in done:
            obj.glyphs = sorted(obj.glyphs, key=gid.__getitem__)
        elif isinstance(obj, ot.PairSet):
            obj.PairValueRecord = sorted(obj.PairValueRecord, key=lambda r: gid[r.SecondGlyph])


def merge_same_tag_features(table) -> None:
    """Give each language system one feature per tag. After merging two layouts a language
    system can list, say, the kern of both fonts, and shapers use only the first of them."""
    if not table or not table.FeatureList:
        return
    recs = table.FeatureList.FeatureRecord
    combined: dict[tuple[int, ...], int] = {}
    for _, _, ls in langsystems(table):
        by_tag: dict[str, list[int]] = {}
        for i in ls.FeatureIndex:
            by_tag.setdefault(recs[i].FeatureTag, []).append(i)
        new = []
        for tag, idx in by_tag.items():
            if len(idx) == 1:
                new.append(idx[0])
                continue
            key = tuple(sorted(idx))
            if key not in combined:
                lookups = sorted({li for i in key for li in recs[i].Feature.LookupListIndex})
                combined[key] = add_feature(table, tag, lookups)
            new.append(combined[key])
        ls.FeatureIndex = sorted(new)
        ls.FeatureCount = len(ls.FeatureIndex)
    for fr in table.FeatureList.FeatureRecord:
        fr.Feature.LookupListIndex = sorted(fr.Feature.LookupListIndex)
