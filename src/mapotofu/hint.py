"""Run otfautohint with a fix for afdko 5.0.1.

Three failures of afdko 5.0.1 when hinting CFF2 variable fonts are patched here before hinting:

- dimensionHinter.calcInstanceStems raises AssertionError on every "high" ghost stem: the branch
  asserts that `lo` is set although only `hi` is computed for such stems. afdko's develop branch
  asserts only `hi`.
- dimensionHinter.bestLocation raises TypeError when a stem's segment carries a hint value
  without an index (seen in regular-script glyphs); such a segment is skipped, which leads to
  the method's own fallback, the stem's location in the default master. Not fixed upstream as
  of 2026-11.
- dimensionHinter.closeSegs raises AssertionError when its walk around a subpath reaches a
  point with no neighbour (seen in the italic extension fonts); the segments are then taken as
  not close, the answer the method gives when the walk leaves the merge distance.

Any other exception while hinting one glyph (afdko has more assertions of this kind, e.g. in
glyphData.associatePath) leaves that glyph unhinted, with a warning naming it, instead of
failing the whole font. Returning nothing for the glyph, as afdko does for incompatible paths,
would empty it in a variable font, so its outlines are given back as they came. A glyph that
takes longer than GLYPH_SECONDS (afdko can loop without end on some regular-script glyphs, which
hangs the whole pool) is treated the same way.

    python -m mapotofu.hint IN.otf -o OUT.otf [otfautohint options]
    python -m mapotofu.hint --shard GLYPHS IN.otf OUT.otf

hint_font() runs it on a font from the build, split by glyph (see shards.by_glyph), and key()
digests what decides its output, for build.stamps.
"""

from __future__ import annotations

import copy
import inspect
import logging
import re
import signal
import sys
import tempfile
import textwrap
from pathlib import Path

log = logging.getLogger(__name__)

HINT_MEMORY = 32  # memory of hinting a font, in multiples of its file's size
HINT_RUN = 150 << 20  # memory of one otfautohint process beyond its share of the font

PATCHES = {
    "calcInstanceStems": (
        r"(elif isG == 'high':\n\s+)assert lo is not None and hi is not None",
        r"\1assert hi is not None",
    ),
    "bestLocation": (
        r"if seg\.hintval\.idx != sidx:",
        r"if seg.hintval.idx is not None and seg.hintval.idx != sidx:",
    ),
    "closeSegs": (
        r"( *)assert n and p\n",
        r"\1if not n or not p:\n\1    return False\n",
    ),
}


def _patch() -> None:
    from afdko.otfautohint import hinter

    cls = hinter.dimensionHinter
    for method, (pattern, repl) in PATCHES.items():
        src = textwrap.dedent(inspect.getsource(getattr(cls, method)))
        fixed, n = re.subn(pattern, repl, src)
        if n == 0:
            continue  # a release with the fix
        ns: dict = {}
        exec(compile(fixed, hinter.__file__, "exec"), hinter.__dict__, ns)
        setattr(cls, method, ns[method])


GLYPH_SECONDS = 60


class GlyphTimeout(Exception):
    pass


def _alarm(signum, frame):
    raise GlyphTimeout(f"over {GLYPH_SECONDS} s")


def _guard() -> None:
    from afdko.otfautohint import hinter

    hint = hinter.glyphHinter._hint

    def guarded(self, name, glyphTuple, fdKey):
        backup = copy.deepcopy(glyphTuple)
        previous = signal.signal(signal.SIGALRM, _alarm)
        signal.alarm(GLYPH_SECONDS)
        try:
            return hint(self, name, glyphTuple, fdKey)
        except Exception as ex:  # noqa: BLE001
            hinter.log.warning("mapotofu: %s left unhinted: %s %s", name, type(ex).__name__, ex)
            return name, backup
        finally:
            signal.alarm(0)
            signal.signal(signal.SIGALRM, previous)

    hinter.glyphHinter._hint = guarded


def _blank_others(src: str, keep: set[int], dst: str) -> None:
    """Copy src with the charstrings of all glyphs outside keep emptied, so that a run hinting
    only keep holds no more of the font than it needs."""
    from fontTools.ttLib import TTFont

    font = TTFont(src, recalcBBoxes=False, recalcTimestamp=False)
    tag = "CFF2" if "CFF2" in font else "CFF "
    charstrings = font[tag].cff.topDictIndex[0].CharStrings
    empty = [] if tag == "CFF2" else ["endchar"]
    for g, name in enumerate(font.getGlyphOrder()):
        if g not in keep:
            cs = charstrings[name]
            cs.program, cs.bytecode = list(empty), None
    font.save(dst)


def set_zones(font) -> None:
    """Alignment zones for otfautohint, which refuses a CFF without four BlueValues: baseline,
    x-height and cap height of the Latin part, the top of the ideographic em box, and the
    bottom of the em box among the OtherBlues."""
    os2 = font["OS/2"]
    x, cap = os2.sxHeight or 536, os2.sCapHeight or 714
    blues = [-14, 0, x, x + 14, cap, cap + 14, 880, 894]
    other = [-134, -120]
    cff = (font["CFF2"] if "CFF2" in font else font["CFF "]).cff
    top = cff.topDictIndex[0]
    privates = [fd.Private for fd in top.FDArray] if hasattr(top, "FDArray") and top.FDArray else [top.Private]
    vw, hw = stems(font)
    for pd in privates:
        for key, value in (("BlueValues", blues), ("OtherBlues", other), ("StdVW", vw), ("StdHW", hw)):
            setattr(pd, key, value)
            pd.rawDict[key] = value


def stems(font) -> tuple[int, int]:
    """Dominant vertical and horizontal stem: the width of "l" (or 丨) and the height of 一 (or
    the hyphen), at the default instance."""
    from fontTools.pens.boundsPen import BoundsPen

    cmap = font.getBestCmap()
    gs = font.getGlyphSet()

    def box(cps):
        for cp in cps:
            if cp in cmap:
                pen = BoundsPen(gs)
                gs[cmap[cp]].draw(pen)
                if pen.bounds:
                    return pen.bounds
        return None

    v = box([ord("l"), 0x4E28])
    h = box([0x4E00, ord("-")])
    return (round(v[2] - v[0]) if v else 80), (round(h[3] - h[1]) if h else 60)


def key(path: Path) -> str:
    """What decides the hinted CFF2 of a font of the first step: its outlines, cmap and the
    heights the zones come from, and the code and versions that hint them. (Entries of the hint
    cache are facts about their own keys, so the cache's content does not enter.)"""
    from fontTools.ttLib import TTFont

    from . import shards, stamps

    font = TTFont(path, lazy=True)
    os2 = font["OS/2"]
    return stamps.digest(
        font.reader["CFF2"], font.reader["cmap"], os2.sxHeight, os2.sCapHeight,
        stamps.sources(PATCHES, _patch, GLYPH_SECONDS, _guard, _blank_others, main, set_zones, stems,
                       hint_font, _keys_part, _apply_part, _by_part, shards.by_glyph),
        stamps.modules("mapotofu.hintcache"), stamps.versions("afdko", "fonttools"),
    )


def _keys_part(job: tuple[Path, list[int]]) -> list[str]:
    from fontTools.ttLib import TTFont

    from . import hintcache

    raw, indexes = job
    font = TTFont(raw)
    order = font.getGlyphOrder()
    return hintcache.keys(font, [order[i] for i in indexes])


def _apply_part(job: tuple[Path, list[int], list[str]]) -> list[list]:
    from fontTools.ttLib import TTFont

    from . import hintcache

    raw, indexes, lines = job
    font = TTFont(raw)
    order = font.getGlyphOrder()
    charstrings = font["CFF2"].cff.topDictIndex[0].CharStrings
    return [hintcache.apply(hintcache.loads(line), charstrings[order[i]]) for i, line in zip(indexes, lines)]


def _by_part(fn, raw: Path, parts: list[list[int]], extra=None) -> list:
    """fn over parts of the glyph indexes, each in a process of its own reading the font
    itself; results in glyph order of each part, joined part by part."""
    from concurrent.futures import ProcessPoolExecutor
    from multiprocessing import get_context

    jobs = [(raw, p) if extra is None else (raw, p, extra(p)) for p in parts]
    with ProcessPoolExecutor(len(parts), mp_context=get_context("spawn")) as pool:
        return list(pool.map(fn, jobs))


def hint_font(font, processes: int, memory: int, groups: list[str]):
    """Hint a CFF2 font: each glyph takes its hints from the hint cache (mapotofu.hintcache);
    the glyphs it lacks are hinted with otfautohint and added to it, by the source groups given
    per glyph index. Returns the font and the glyphs left unhinted, with the reasons.

    Keys and hints are worked out in `processes` processes, each over every n-th glyph. So is
    otfautohint: its own process pool keeps only about five cores busy, since its parent process
    merges every glyph alone, and a run that dies fails here instead of hanging a pool. Each run
    empties the glyphs it does not hint, so the runs together hold about HINT_MEMORY times the
    font file's size, plus HINT_RUN each; `memory` bytes bound the number of runs."""
    from . import hintcache
    from .shards import by_glyph

    set_zones(font)
    order = font.getGlyphOrder()
    n = len(order)
    charstrings = font["CFF2"].cff.topDictIndex[0].CharStrings
    cache = hintcache.Cache()
    with tempfile.TemporaryDirectory() as tmp:
        raw = Path(tmp) / "raw.otf"
        font.save(raw)
        parts = [list(range(i, n, processes)) for i in range(min(processes, n))]
        keys: list[str] = [""] * n
        for part, ks in zip(parts, _by_part(_keys_part, raw, parts)):
            for i, k in zip(part, ks):
                keys[i] = k
        missing = [i for i, k in enumerate(keys) if k not in cache.lines]
        log.info("%d of %d glyphs not in the hint cache", len(missing), n)
        if missing:
            warnings: dict[str, str] = {}
            spare = memory - HINT_MEMORY * raw.stat().st_size
            shards = max(1, min(processes, len(missing), spare // HINT_RUN))
            log.info("hinting %d glyphs in %d runs", len(missing), shards)
            hinted = by_glyph(
                raw, order, shards,
                lambda glyphs, out: [sys.executable, "-m", "mapotofu.hint", "--shard", str(glyphs), str(raw), str(out)],
                "otfautohint", glyphs=missing, warnings=warnings,
            )
            done = hinted["CFF2"].cff.topDictIndex[0].CharStrings
            for i in missing:
                name = order[i]
                cache.add(groups[i], keys[i], hintcache.extract(charstrings[name], done[name], warnings.get(name)))
            cache.save()
        programs = _by_part(_apply_part, raw, parts, lambda p: [cache.lines[keys[i]] for i in p])
    for part, progs in zip(parts, programs):
        for i, program in zip(part, progs):
            cs = charstrings[order[i]]
            cs.program, cs.bytecode = program, None
    unhinted = []
    for name, k in zip(order, keys):
        if cache.lines[k][37] == "-":  # ["KEY","-",...
            unhinted.append((name, cache.get(k).reason))
    return font, unhinted


def main(argv: list[str]) -> int:
    """`--shard GLYPHS IN OUT` hints only the glyph indexes listed in the file GLYPHS (comma
    separated) in one process; anything else is passed to otfautohint as it is."""
    _patch()
    _guard()
    from afdko.otfautohint.__main__ import main as otfautohint

    if argv[:1] == ["--shard"]:
        glyphs, src, out = argv[1:4]
        keep = {int(g) for g in open(glyphs).read().split(",")}
        blanked = out + ".in.otf"
        _blank_others(src, keep, blanked)
        argv = ["--traceback", "-p", "1", "--glyphs-file", glyphs, blanked, "-o", out]
    return otfautohint(argv) or 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
