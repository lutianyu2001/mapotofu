"""Command line entry point: mapo (or mapotofu, python -m mapotofu.build), run in a font project
(the directory of its mapotofu.toml, see mapotofu.config).

    python -m mapotofu.build fetch                            download the sources of sources.toml
    python -m mapotofu.build fonts [-j N] [--only KEY ...]    first step: build/fonts/*.otf
    python -m mapotofu.build desktop [-j N] [--only KEY ...]  second step: dist/ (OTF, OTC)
    python -m mapotofu.build all [-j N]
    python -m mapotofu.build prune-hints [-j N]               drop hint cache entries no font uses
    python -m mapotofu.build collections                      the OTCs of the pooled fonts there are
    python -m mapotofu.build release                          dist/ packed into dist/release/*.zip

The first step writes each complete, unhinted variable font with a JSON file of the metadata a
web package will need (PLAN 10). Fonts of one pool (see pools()) share their glyph tables and
hold every glyph of the pool; packaging cuts standalone fonts from them. Packaging steps read
only these files.

Both steps redo only work whose key changed (mapotofu.stamps): what it is made from, by which
code, configuration and library versions. An interrupted or failed run is resumed by running
it again.
"""

from __future__ import annotations

import argparse
import contextlib
import json
import logging
import os
import re
import signal
import sys
import time
from concurrent.futures import FIRST_COMPLETED, ProcessPoolExecutor, wait
from pathlib import Path

from . import stamps
from .assemble import View
from .shards import memory_available
from .config import AXIS_MAX, AXIS_MIN, BUILD, DATA, FAMILIES, HINT_GROUPS, HINT_OWN, ITALIC, META, PACKAGING, REGIONS, ROOT

log = logging.getLogger("mapotofu")

FONTS = BUILD / "fonts"
MEMORY_RESERVE = 2 << 30  # memory left free for the system when starting a job
RAMP = 60  # seconds a job may take to reach the memory it needs


def all_views() -> list[View]:
    views = [View(f, r, i) for i in ITALIC for f in FAMILIES for r in REGIONS]
    views += [View("Ext", r, i) for i in ITALIC for r in (*REGIONS, "CJK")]
    return views


def pools() -> dict[str, list[View]]:
    """Fonts that share one glyph pool and go into one collection: the upright main fonts all
    together; the italic ones by region, since the regular-script glyphs of all three regions
    would not fit in 65535 glyphs; each extension on its own."""
    out = {"Upright": [View(f, r, False) for f in FAMILIES for r in REGIONS]}
    for r in REGIONS:
        out[f"Italic-{r}"] = [View(f, r, True) for f in FAMILIES]
    for i in ITALIC:
        for r in (*REGIONS, "CJK"):
            v = View("Ext", r, i)
            out[v.key] = [v]
    return out


def by_key(keys: list[str] | None) -> dict[str, list[View]]:
    """The pools holding the given fonts (or pool names), or all pools."""
    table = pools()
    if not keys:
        return table
    known = {v.key for vs in table.values() for v in vs} | set(table)
    missing = [k for k in keys if k not in known]
    if missing:
        raise SystemExit(f"unknown fonts: {', '.join(missing)}; known: {', '.join(sorted(known))}")
    return {p: vs for p, vs in table.items() if p in keys or any(v.key in keys for v in vs)}


def _ranges(cps: list[int]) -> list[list[int]]:
    out: list[list[int]] = []
    for cp in sorted(cps):
        if out and cp == out[-1][1] + 1:
            out[-1][1] = cp
        else:
            out.append([cp, cp])
    return out


# Modules whose code makes the glyphs and layout of the first step; the metadata (meta.py and
# the values in config.META) is set apart, so that changing it only finalizes the fonts again.
ASSEMBLE_MODULES = (
    "mapotofu.assemble", "mapotofu.glyphs", "mapotofu.sources", "mapotofu.parts", "mapotofu.charsets",
    "mapotofu.layout", "mapotofu.tiers",
)


def assemble_key(pool: str, views: list[View]) -> str:
    data = sorted(DATA.glob("*.txt"))
    return stamps.digest(
        [v.key for v in views], stamps.modules(*ASSEMBLE_MODULES),
        stamps.settings(exclude=META + PACKAGING), stamps.file(ROOT / "sources.toml"),
        {p.name: stamps.file(p) for p in data}, stamps.versions("fonttools", "unicodedata2"),
    )


def meta_key() -> str:
    return stamps.digest(
        stamps.modules("mapotofu.meta"), stamps.sources(_write), stamps.settings(exclude=PACKAGING),
        stamps.file(ROOT / "sources.toml"), stamps.versions("fonttools"),
    )


def _write(pool: str, view: View, vf) -> None:
    from . import meta

    stamps.save(vf, FONTS / f"{view.key}.otf")
    en, _ = meta.families(view)
    info = {
        "pool": pool,
        "family": en,
        "style": "italic" if view.italic else "normal",
        "weight": [AXIS_MIN, AXIS_MAX],
        "unicode_ranges": _ranges(list(vf.getBestCmap())),
    }
    (FONTS / f"{view.key}.json").write_text(json.dumps(info) + "\n")


def group(name: str) -> str:
    """The source a glyph of the first step comes from, by its name there (see HINT_GROUPS)."""
    prefix = re.match(r"[A-Za-z]*", name).group()
    if prefix not in HINT_GROUPS and prefix[:-1] in HINT_GROUPS and prefix[-1:].isupper():
        prefix = prefix[:-1]  # a regular-script source's weight letter
    return HINT_GROUPS.get(prefix, HINT_OWN)


def groups_path(view: View) -> Path:
    return FONTS / f"{view.key}.glyphs.json"


def glyph_groups(view: View) -> list[str]:
    """The source group of each glyph of a font of the first step, by glyph index."""
    out: list[str] = []
    for name, count in json.loads(groups_path(view).read_text())["groups"]:
        out += [name] * count
    return out


def build_pool(item: tuple[str, list[View]]) -> str:
    from . import assemble

    pool, views = item
    FONTS.mkdir(parents=True, exist_ok=True)
    for view, vf in assemble.build_group(views):
        # The fonts keep no glyph names (post format 3): record where each glyph comes from.
        runs: list[list] = []
        for name in vf.getGlyphOrder():
            g = group(name)
            if runs and runs[-1][0] == g:
                runs[-1][1] += 1
            else:
                runs.append([g, 1])
        groups_path(view).write_text(json.dumps({"groups": runs}) + "\n")
        _write(pool, view, vf)
    return pool


def finalize_pool(item: tuple[str, list[View]]) -> str:
    """Set the metadata of a pool's fonts again, their glyphs and layout being up to date."""
    from fontTools.ttLib import TTFont

    from . import meta

    pool, views = item
    for view in views:
        vf = TTFont(FONTS / f"{view.key}.otf", recalcBBoxes=False)
        meta.finalize(vf, view)
        _write(pool, view, vf)
    return f"{pool} metadata"


def fonts(selected: dict[str, list[View]], jobs: int) -> None:
    """The first step, for the pools whose glyphs and layout or whose metadata changed."""
    store = stamps.Stamps()
    mkey = meta_key()
    keys = {pool: assemble_key(pool, views) for pool, views in selected.items()}

    def path(v: View) -> Path:
        return FONTS / f"{v.key}.otf"

    def done(item, _) -> None:
        pool, views = item
        for v in views:
            store.put(path(v), key=stamps.digest(keys[pool], mkey), assemble=keys[pool], meta=mkey)

    build, refinalize = [], []
    for pool, views in selected.items():
        if not all(store.fresh(path(v), keys[pool], "assemble") and groups_path(v).exists() for v in views):
            build.append((pool, views))
        elif not all(store.fresh(path(v), mkey, "meta") for v in views):
            refinalize.append((pool, views))
    # The biggest pools first, so that they do not finish last alone.
    build.sort(key=lambda kv: -len(kv[1]))
    run(build_pool, build, jobs, done=done)
    run(finalize_pool, refinalize, jobs, done=done)


def _pool_keys(item: tuple[str, list[View]]) -> list[str]:
    from fontTools.ttLib import TTFont

    from . import hint, hintcache

    _, views = item
    font = TTFont(FONTS / f"{views[0].key}.otf")
    hint.set_zones(font)
    return hintcache.keys(font, font.getGlyphOrder())


def prune_hints(jobs: int) -> None:
    """Drop from the hint cache the entries no pool uses (after a source changed); needs the
    first step of every pool built."""
    from . import hintcache

    with ProcessPoolExecutor(jobs, max_tasks_per_child=1, initializer=_worker) as pool:
        used = set().union(*pool.map(_pool_keys, list(pools().items())))
    log.info("%d entries dropped", hintcache.Cache().prune(used))


def _logging() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
    logging.getLogger("fontTools").setLevel(logging.WARNING)


def _worker() -> None:
    """Workers are spawned: they lead their own process group and set up logging anew."""
    os.setpgrp()
    _logging()


def _label(result) -> str:
    return result[0] if isinstance(result, tuple) else result


def run(fn, items: list, jobs: int, cost=None, budget: int | None = None, done=None) -> None:
    """Run fn over items in up to `jobs` worker processes, calling done(item, result) in this
    process after each item succeeds. With cost (item -> bytes of memory it needs) and budget, an item
    starts only while the items running fit in the budget (one always runs). After a failure no
    item starts; those running finish, so that their work is kept for a resumed run, and the
    first failure is raised. On an interrupt the workers are killed together with the processes
    they started (each leads its own process group).

    With a budget, an item also waits until the memory the system has free, less what the items
    started in the last RAMP seconds are still to take, covers its cost and MEMORY_RESERVE:
    estimates can fall short, and other programs use memory too."""
    if jobs <= 1:
        for it in items:
            result = fn(it)
            log.info("done %s", _label(result))
            if done:
                done(it, result)
        return
    pending = list(items)
    running: dict = {}
    failure: BaseException | None = None
    with ProcessPoolExecutor(jobs, max_tasks_per_child=1, initializer=_worker) as pool:
        try:
            while running or (pending and failure is None):
                used = sum(need for need, _, _ in running.values())
                now = time.monotonic()
                ramping = sum(need for need, _, t in running.values() if now - t < RAMP)
                for it in list(pending) if failure is None else []:
                    if len(running) >= jobs:
                        break
                    need = cost(it) if cost else 0
                    if running and budget is not None and (
                        used + need > budget or memory_available() - ramping < need + MEMORY_RESERVE
                    ):
                        continue
                    pending.remove(it)
                    running[pool.submit(fn, it)] = (need, it, now)
                    used += need
                    ramping += need
                # Wake now and then to see whether memory came free outside.
                finished, _ = wait(running, timeout=10, return_when=FIRST_COMPLETED)
                for fut in finished:
                    _, it, _ = running.pop(fut)
                    try:
                        result = fut.result()
                    except Exception as ex:
                        log.error("failed: %r", ex)
                        failure = failure or ex
                        continue
                    log.info("done %s", _label(result))
                    if done:
                        done(it, result)
        except BaseException:
            for pid in list(pool._processes or {}):
                with contextlib.suppress(ProcessLookupError, PermissionError):
                    os.killpg(pid, signal.SIGKILL)
            for fut in running:
                fut.cancel()
            raise
    if failure is not None:
        raise failure


def main(argv: list[str] | None = None) -> None:
    name = Path(sys.argv[0]).name
    ap = argparse.ArgumentParser(prog=name if name in ("mapotofu", "mapo") else "python -m mapotofu.build")
    ap.add_argument("step", choices=("fetch", "fonts", "desktop", "all", "prune-hints", "collections", "release"))
    ap.add_argument(
        "-j", "--jobs", type=int, default=4,
        help="parallel processes; for desktop, the pools hinted at once, each over cores/N runs",
    )
    ap.add_argument("--only", nargs="*", help="fonts such as Gothic-SC-Upright, or pools such as Italic-SC")
    args = ap.parse_args(argv)
    _logging()
    if args.step == "fetch":
        from . import fetch

        fetch.main()
        return
    if args.step == "prune-hints":
        prune_hints(args.jobs)
        return
    if args.step == "collections":
        from . import package

        package.collections(stamps.Stamps())
        package.write_manifest()
        return
    if args.step == "release":
        from . import release

        for path in release.release():
            log.info("packed %s", path.name)
        return
    selected = by_key(args.only)
    if args.step in ("fonts", "all"):
        fonts(selected, args.jobs)
    if args.step in ("desktop", "all"):
        from . import package

        package.desktop(selected, args.jobs)


if __name__ == "__main__":
    main(sys.argv[1:])
