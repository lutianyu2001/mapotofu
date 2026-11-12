"""Second build step for desktop use, made from the files of the first step only.

For each pool, the variable fonts' shared CFF2 is hinted once (mapotofu.hint); each static weight's
shared CFF is instanced from it and subroutinized once (mapotofu.instance), and each static font
instances its other tables from its own variable font. Those pool-backed fonts (build/pooled) go into the OTC collections, where the
identical glyph tables are stored once; the standalone OTF files are cut from them by
subsetting each to its own characters (mapotofu.cut).

Work is redone only where its key (mapotofu.stamps) changed. A pool's hinted CFF2 and a weight's
static CFF have keys of their own: when only other tables change (names, metrics, layout), they
are taken as they are from the previous output instead of being hinted or instanced again.

The CFF2 tables of the variable fonts are not subroutinized: cffsubr 0.4.0 (AFDKO tx) breaks
every glyph whose charstring selects a vsindex other than 0, which HarfBuzz and FreeType then
reject, and the sparse masters give most ideographs such a vsindex.
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path

from fontTools.ttLib import TTFont
from fontTools.ttLib.tables.DefaultTable import DefaultTable
from fontTools.ttLib.ttCollection import TTCollection
from fontTools.varLib.instancer import instantiateVariableFont

from . import cut, hint, hintcache, instance, meta, stamps
from .assemble import View
from .config import BUILD, COLLECTION, PACKAGING, ROOT, STATIC_WEIGHTS
from .shards import memory_available

log = logging.getLogger(__name__)

FONTS = BUILD / "fonts"
POOLED = BUILD / "pooled"
DIST = ROOT / "dist"
STATIC_SHARDS = 8  # processes instancing one static weight's CFF
# Memory of instancing a static CFF with all its shards, in multiples of its VF's size, until a
# run has measured it (Memory): 98 for Italic-J and 196 for Upright, however many shards, each
# holding memory in proportion to its glyphs.
STATIC_MEMORY = 200
STATIC_FONT_MEMORY = 20  # memory of the rest of a static font, in multiples of its VF's size
SUBR_MEMORY = 100  # memory of AFDKO tx subroutinizing a merged font, in multiples of its size: 95 measured
MEMORY_MARGIN = 1.15  # over the most memory a job was seen to take
CUT_MEMORY = 35  # memory of cutting a standalone font, in multiples of its pool-backed file's size


def stem(view: View) -> str:
    en, _ = meta.families(view)
    return en.replace(" ", "")


def file_name(view: View, weight: str | None) -> str:
    if weight is None:
        return f"{stem(view)}{'-Italic' if view.italic else ''}-VF.otf"
    return f"{stem(view)}-{meta.style_name(weight, view.italic).replace(' ', '')}.otf"


def pooled_path(view: View, weight: str | None) -> Path:
    return POOLED / (weight or "VF") / f"{view.key}.otf"


def dist_path(view: View, weight: str | None) -> Path:
    return DIST / ("variable" if weight is None else "static") / file_name(view, weight)


def _load_pool(views: list[View], directory: Path) -> list[TTFont]:
    # The fonts carry no glyph names (post format 3) and fontTools derives names from each one's
    # cmap; give the whole pool one list of names so that glyph tables move between its fonts.
    names = TTFont(directory / f"{views[0].key}.otf").getGlyphOrder()
    fonts = []
    for view in views:
        # No new date: hinting saves the first font of the pool on its way.
        font = TTFont(directory / f"{view.key}.otf", recalcTimestamp=False)
        font.setGlyphOrder(names)
        fonts.append(font)
    return fonts


def _compiled(font: TTFont, tag: str) -> DefaultTable:
    table = DefaultTable(tag)
    table.data = font[tag].compile(font)
    return table


def _previous(path: Path, tag: str) -> DefaultTable:
    """A glyph table taken as it is from an earlier output whose key for it still holds."""
    table = DefaultTable(tag)
    table.data = TTFont(path, lazy=True).reader[tag]
    return table


def _set_bounds(font: TTFont, cff: bytes) -> None:
    """Give a static font what follows from the outlines of its own weight. It arrives with the
    values of its variable font, which are the default weight's: the side bearings of hmtx and
    vmtx, the extremes hhea and vhea draw from them (worked out as fontTools does when it
    saves), and head's bounding box. cff is the weight's CFF, whose glyphs are in the font's
    glyph order.

    The Windows metrics cover every weight already (meta.finalize); should a glyph of this
    weight pass them all the same (instancing rounds each coordinate), they are widened, so
    that nothing is clipped."""
    from fontTools.misc.arrayTools import intRect, unionRect
    from fontTools.ttLib import newTable

    table = newTable("CFF ")
    table.decompile(cff, font)
    charstrings = table.cff.topDictIndex[0].CharStrings
    order = font.getGlyphOrder()
    assert len(charstrings.charStringsIndex) == len(order)
    hmtx, vmtx, vorg = font["hmtx"].metrics, font["vmtx"].metrics, font["VORG"]
    box, sides, ends = None, [], []
    for name, cs in zip(order, charstrings.charStringsIndex):
        bounds = cs.calcBounds(charstrings)
        if bounds is None:
            continue
        left, bottom, right, top = intRect(bounds)
        box = bounds if box is None else unionRect(box, bounds)
        width, height = hmtx[name][0], vmtx[name][0]
        tsb = vorg.VOriginRecords.get(name, vorg.defaultVertOriginY) - top
        hmtx[name], vmtx[name] = (width, left), (height, tsb)
        sides.append((left, width - right, right))
        ends.append((tsb, height - tsb - (top - bottom), tsb + top - bottom))
    hhea, vhea = font["hhea"], font["vhea"]
    hhea.advanceWidthMax = max(width for width, _ in hmtx.values())
    vhea.advanceHeightMax = max(height for height, _ in vmtx.values())
    hhea.minLeftSideBearing, hhea.minRightSideBearing, hhea.xMaxExtent = (
        (min(s[0] for s in sides), min(s[1] for s in sides), max(s[2] for s in sides)) if sides else (0, 0, 0)
    )
    vhea.minTopSideBearing, vhea.minBottomSideBearing, vhea.yMaxExtent = (
        (min(e[0] for e in ends), min(e[1] for e in ends), max(e[2] for e in ends)) if ends else (0, 0, 0)
    )
    head, os2 = font["head"], font["OS/2"]
    head.xMin, head.yMin, head.xMax, head.yMax = intRect(box or (0, 0, 0, 0))
    os2.usWinAscent = max(os2.usWinAscent, head.yMax)
    os2.usWinDescent = max(os2.usWinDescent, -head.yMin)


def _save_pooled(view: View, font: TTFont, weight: str | None, shared: DefaultTable) -> None:
    """Save a pool-backed font with the pool's glyph table, compiled once."""
    font[shared.tableTag] = shared
    # The raw table cannot be drawn. The boxes stand: a variable font's are the default weight's
    # from the first step, a static font's are set from its weight's CFF (_set_bounds).
    font.recalcBBoxes = False
    stamps.save(font, pooled_path(view, weight))


def unhinted_path(pool: str) -> Path:
    return hintcache.HINTS / "unhinted" / f"{pool}.toml"


def _report(pool: str, font: TTFont, unhinted: list[tuple[str, str]]) -> None:
    """hints/unhinted/POOL.toml: the glyphs of a pool left unhinted, by the characters whose
    text reaches them, for people to read."""
    path = unhinted_path(pool)
    if not unhinted:
        path.unlink(missing_ok=True)
        return
    from .slices import _reach

    reach = _reach(font)
    lines = [f"# Glyphs of the pool {pool} that otfautohint left unhinted; written by the build.\n"]
    for name, reason in unhinted:
        chars = " ".join(f"U+{cp:04X} {chr(cp)}" for cp in sorted(reach.get(name, ())))
        lines += [
            "[[glyph]]",
            f"name = {json.dumps(name)}",
            f"characters = {json.dumps(chars, ensure_ascii=False)}",
            f"reason = {json.dumps(reason, ensure_ascii=False)}",
            "",
        ]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8")


def package_variable(job: tuple[str, list[View], int, int, bool]) -> str:
    """Hint the pool's CFF2 once (or take it from the previous output) and give it to every
    font of the pool."""
    from .build import glyph_groups

    pool, views, processes, memory, reuse = job
    fonts = _load_pool(views, FONTS)
    if reuse:
        shared = _previous(pooled_path(views[0], None), "CFF2")
    else:
        hinted, unhinted = hint.hint_font(fonts[0], processes, memory, glyph_groups(views[0]))
        shared = _compiled(hinted, "CFF2")
        _report(pool, fonts[0], unhinted)
    for view, font in zip(views, fonts):
        _save_pooled(view, font, None, shared)
    return f"{pool} VF"


def cff_path(pool: str, weight: str) -> Path:
    """A pool's static CFF of a weight, as the table's bytes."""
    return POOLED / weight / f"{pool}.CFF"


def cff_name(pool: str, weight: str) -> str:
    """The name of a pool's static CFF, as PostScript names are written. A collection's fonts
    share the table, so it is named after the pool; a standalone font's has the font's own
    name (cut.name_cff)."""
    name = f"{COLLECTION}-{pool}-{weight}"
    return "".join(c for c in name if c.isascii() and c.isalnum() or c == "-")


def merged_path(pool: str, weight: str) -> Path:
    return POOLED / weight / f"{pool}.merged.otf"


def static_merge(job: tuple[str, list[View], str, int]) -> tuple[str, int]:
    """A pool's static weight instanced from its hinted CFF2 (hints are blended like the
    outlines), split over `shards` processes, into a font left for static_subr."""
    from .shards import peak

    pool, views, weight, shards = job
    first = pooled_path(views[0], None)
    names = TTFont(first).getGlyphOrder()
    data = instance.merge(first, names, STATIC_WEIGHTS[weight], shards, cff_name(pool, weight))
    path = merged_path(pool, weight)
    path.parent.mkdir(parents=True, exist_ok=True)
    part = path.with_name(path.name + ".part")
    part.write_bytes(data)
    part.replace(path)
    return f"{pool} {weight} merged", peak(shards)


def static_subr(job: tuple[str, list[View], str]) -> tuple[str, int]:
    """The pool's static CFF of a weight: the merged font subroutinized, compiled once for
    every font of the pool."""
    from .shards import peak

    pool, _, weight = job
    merged = merged_path(pool, weight)
    data = instance.subroutinize(merged.read_bytes())
    path = cff_path(pool, weight)
    part = path.with_name(path.name + ".part")
    part.write_bytes(data)
    part.replace(path)
    merged.unlink()
    return f"{pool} {weight} CFF", peak()


def static_font(job: tuple[str, list[View], View, str]) -> str:
    """One font of a static weight: its own tables instanced from its variable font, its
    metadata set, and the pool's static CFF."""
    from .build import extent

    pool, views, view, weight = job
    names = TTFont(pooled_path(views[0], None)).getGlyphOrder()
    vf = TTFont(pooled_path(view, None), recalcBBoxes=False)
    vf.setGlyphOrder(names)
    del vf["CFF2"]
    font = instantiateVariableFont(vf, {"wght": STATIC_WEIGHTS[weight]}, inplace=True, static=True)
    font.sfntVersion = "OTTO"
    meta.finalize(font, view, weight, extent=extent(view))
    shared = DefaultTable("CFF ")
    shared.data = cff_path(pool, weight).read_bytes()
    _set_bounds(font, shared.data)
    _save_pooled(view, font, weight, shared)
    from .shards import peak

    return f"{view.key} {weight}", peak()


def cut_job(job: tuple[View, str | None]) -> tuple[str, int]:
    """The standalone OTF of one font and weight, cut from its pool-backed file."""
    from .shards import peak

    view, weight = job
    out = dist_path(view, weight)
    cut.cut_font(pooled_path(view, weight), out, weight is not None)
    return out.name, peak()


class Memory:
    """build/memory.json: the most memory each kind of job took for each pool or font, so that
    the next run sets that much aside for it (with MEMORY_MARGIN) instead of an estimate."""

    path = BUILD / "memory.json"

    def __init__(self):
        self.data: dict[str, int] = json.loads(self.path.read_text()) if self.path.exists() else {}

    def need(self, name: str, estimate: int) -> int:
        seen = self.data.get(name)
        return int(seen * MEMORY_MARGIN) if seen else estimate

    def saw(self, name: str, result) -> None:
        if isinstance(result, tuple):
            self.data[name] = max(self.data.get(name, 0), result[1])
            part = self.path.with_name(self.path.name + ".part")
            part.write_text(json.dumps(self.data, indent=1, sort_keys=True) + "\n")
            part.replace(self.path)


def _collections() -> list[tuple[Path, list[Path]]]:
    """One OTC per style and weight for the main families, and one for the extensions."""
    from .build import pools

    out = []
    for weight in [None, *STATIC_WEIGHTS]:
        groups: dict[tuple[bool, bool], list[View]] = {}
        for views in pools().values():
            for v in views:
                groups.setdefault((v.is_ext, v.italic), []).append(v)
        for (ext, italic), views in groups.items():
            style = meta.style_name(weight or "Regular", italic).replace(" ", "")
            name = f"{COLLECTION}{'Ext' if ext else ''}-{style}.otc"
            if weight is None:
                name = f"{COLLECTION}{'Ext' if ext else ''}{'-Italic' if italic else ''}-VF.otc"
            out.append((DIST / "otc" / name, [pooled_path(v, weight) for v in views]))
    return out


def collections(store: stamps.Stamps) -> None:
    """Each collection whose fonts have all been packaged and changed since it was made."""
    code = stamps.sources(_collections, collections)
    for out, paths in _collections():
        if not all(p.exists() for p in paths):
            continue
        key = stamps.digest(code, [stamps.file(p) for p in paths], stamps.versions("fonttools"))
        if store.fresh(out, key):
            continue
        coll = TTCollection()
        coll.fonts = [TTFont(p, recalcBBoxes=False, recalcTimestamp=False) for p in paths]
        out.parent.mkdir(parents=True, exist_ok=True)
        part = out.with_name(out.name + ".part")
        coll.save(part, shareTables=True)
        part.replace(out)
        store.put(out, key=key)
        log.info("done %s", out)


def desktop(selected: dict[str, list[View]], jobs: int) -> None:
    """Hint each pool (`jobs` at a time, each split into runs over the cores), instance the
    static weights and cut the standalone fonts, as many at a time as cores and memory allow,
    each only where its key changed (see the module's documentation)."""
    from .build import run

    store = stamps.Stamps()
    cores = os.cpu_count() or 1
    memory = int(memory_available() * 0.75)
    pools_ = sorted(selected.items(), key=lambda kv: -len(kv[1]))
    meta_code = stamps.digest(
        stamps.modules("mapotofu.meta"), stamps.settings(exclude=PACKAGING), stamps.file(ROOT / "sources.toml"),
        meta.date(),
    )

    # Variable fonts: the hinted CFF2 is keyed by the first font of the pool.
    vf_code = stamps.sources(_load_pool, _compiled, _previous, _save_pooled, stamps.save, package_variable)
    hinted: dict[str, str] = {}
    vf_keys: dict[str, str] = {}
    work = []
    for pool, views in pools_:
        hinted[pool] = hint.key(FONTS / f"{views[0].key}.otf")
        for v in views:
            vf_keys[v.key] = stamps.digest(vf_code, hinted[pool], stamps.file(FONTS / f"{v.key}.otf"))
        if all(store.fresh(pooled_path(v, None), vf_keys[v.key]) for v in views):
            continue
        reuse = store.fresh(pooled_path(views[0], None), hinted[pool], "hint")
        work.append((pool, views, max(1, cores // jobs), memory // jobs, reuse))

    def vf_done(job, _) -> None:
        pool, views = job[0], job[1]
        for v in views:
            store.put(pooled_path(v, None), key=vf_keys[v.key], hint=hinted[pool])

    run(package_variable, work, jobs, done=vf_done)

    # Static weights: each pool's static CFF in two parts, instancing (much memory for a
    # while) and subroutinizing (long, in one thread, little memory), then each font with it.
    mem = Memory()
    cff_keys = {
        (pool, w): instance.key(pooled_path(views[0], None), STATIC_WEIGHTS[w], cff_name(pool, w))
        for pool, views in pools_
        for w in STATIC_WEIGHTS
    }
    work = [
        (pool, views, w, STATIC_SHARDS)
        for pool, views in pools_
        for w in STATIC_WEIGHTS
        if not store.fresh(cff_path(pool, w), cff_keys[pool, w])
    ]

    def size(view: View) -> int:
        return pooled_path(view, None).stat().st_size

    # As many as memory allows: their shards share the cores for a short while, and the rest of
    # each is single-threaded. A merged font left by an interrupted run is used as it is.
    run(
        static_merge,
        [job for job in work if not store.fresh(merged_path(job[0], job[2]), cff_keys[job[0], job[2]])],
        cores,
        lambda job: mem.need(f"static_merge/{job[0]}", STATIC_MEMORY * size(job[1][0]) + (512 << 20)), memory,
        done=lambda job, result: (
            mem.saw(f"static_merge/{job[0]}", result),
            store.put(merged_path(job[0], job[2]), key=cff_keys[job[0], job[2]]),
        ),
    )
    run(
        static_subr, [job[:3] for job in work], cores,
        lambda job: mem.need(f"static_subr/{job[0]}", SUBR_MEMORY * merged_path(job[0], job[2]).stat().st_size),
        memory,
        done=lambda job, result: (
            mem.saw(f"static_subr/{job[0]}", result),
            store.put(cff_path(job[0], job[2]), key=cff_keys[job[0], job[2]]),
        ),
    )
    static_code = stamps.digest(
        meta_code, stamps.sources(static_font, _set_bounds, _save_pooled, stamps.save),
        stamps.versions("fonttools", "uharfbuzz"),
    )
    font_keys = {
        (v.key, w): stamps.digest(static_code, cff_keys[pool, w], stamps.file(pooled_path(v, None)))
        for pool, views in pools_
        for v in views
        for w in STATIC_WEIGHTS
    }
    work = [
        (pool, views, v, w)
        for pool, views in pools_
        for w in STATIC_WEIGHTS
        for v in views
        if not store.fresh(pooled_path(v, w), font_keys[v.key, w])
    ]
    run(
        static_font, work, cores,
        lambda job: mem.need(f"static_font/{job[2].key}", STATIC_FONT_MEMORY * size(job[2])), memory,
        done=lambda job, result: (
            mem.saw(f"static_font/{job[2].key}", result),
            store.put(pooled_path(job[2], job[3]), key=font_keys[job[2].key, job[3]]),
        ),
    )

    # Standalone fonts.
    cut_keys = {
        (v, w): cut.key(pooled_path(v, w), w is not None)
        for _, vs in pools_
        for v in vs
        for w in (None, *STATIC_WEIGHTS)
    }
    work = [job for job, key in cut_keys.items() if not store.fresh(dist_path(*job), key)]
    def cut_name(job) -> str:
        return f"cut/{job[0].key}/{job[1] or 'VF'}"

    run(
        cut_job, work, cores,
        lambda job: mem.need(cut_name(job), CUT_MEMORY * pooled_path(*job).stat().st_size), memory,
        done=lambda job, result: (mem.saw(cut_name(job), result), store.put(dist_path(*job), key=cut_keys[job])),
    )
    collections(store)
    write_manifest()


def write_manifest() -> None:
    """dist/pools.json: the fonts of each pool, which share their glyph tables."""
    from .build import pools

    manifest = {p: [v.key for v in vs] for p, vs in pools().items()}
    DIST.mkdir(parents=True, exist_ok=True)
    (DIST / "pools.json").write_text(json.dumps(manifest, indent=1) + "\n")
