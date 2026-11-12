"""Work on a font split by glyph over processes (hinting, instancing)."""

from __future__ import annotations

import io
import logging
import subprocess
import tempfile
from pathlib import Path

from fontTools.ttLib import TTFont

log = logging.getLogger(__name__)


def memory_available() -> int:
    for line in Path("/proc/meminfo").read_text().splitlines():
        if line.startswith("MemAvailable:"):
            return int(line.split()[1]) * 1024
    return 8 << 30


def peak(concurrent: int = 1) -> int:
    """Bytes of memory this process and its children took at most, the children counted as
    `concurrent` of the largest of them running at once (an upper bound for shards)."""
    import resource

    own = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    child = resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss
    return (own + concurrent * child) * 1024  # kilobytes on Linux


def by_glyph(
    src: Path, order: list[str], shards: int, command, what: str, glyphs: list[int] | None = None,
    warnings: dict[str, str] | None = None,
) -> TTFont:
    """Run command(glyphs, out) as `shards` processes at once, each over every n-th of the given
    glyph indexes of src (all by default; glyphs names a file of their indexes), and put
    together the charstrings each one wrote for its own glyphs. A process that fails fails the
    whole, without waiting on the rest. Lines "mapotofu: NAME MESSAGE" the processes write are
    logged and, with `warnings`, collected by glyph name."""
    todo = list(range(len(order))) if glyphs is None else list(glyphs)
    assert todo, "no glyphs"
    shards = max(1, min(shards, len(todo)))
    parts = [todo[i::shards] for i in range(shards)]
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        runs = []
        for i in range(shards):
            listing = tmp / f"glyphs{i}.txt"
            listing.write_text(",".join(str(g) for g in parts[i]))
            out, err = tmp / f"out{i}.otf", tmp / f"log{i}.txt"
            with err.open("w") as f:
                proc = subprocess.Popen(command(listing, out), stdout=subprocess.DEVNULL, stderr=f)
            runs.append((proc, out, err))
        failed = None
        for proc, _, err in runs:
            if proc.wait() and failed is None:
                failed = err
                for other, _, _ in runs:
                    other.kill()
        if failed is not None:
            errors = [line for line in failed.read_text().splitlines() if "WARNING" not in line]
            raise RuntimeError(f"{what} failed:\n" + "\n".join(errors[-30:]))
        for _, _, err in runs:
            for line in err.read_text().splitlines():
                if "mapotofu:" in line:
                    message = line.split("mapotofu:", 1)[1].strip()
                    log.warning("%s", message)
                    if warnings is not None:
                        name, _, rest = message.partition(" ")
                        warnings[name] = rest
        whole = TTFont(io.BytesIO(runs[0][1].read_bytes()), recalcBBoxes=False)
        whole.setGlyphOrder(order)
        tag = "CFF2" if "CFF2" in whole else "CFF "
        # By index: a CFF with several font DICTs names its glyphs by number, whatever the
        # font calls them.
        charstrings = whole[tag].cff.topDictIndex[0].CharStrings.charStringsIndex
        for i in range(1, shards):
            part = TTFont(io.BytesIO(runs[i][1].read_bytes()))
            source = part[tag].cff.topDictIndex[0].CharStrings.charStringsIndex
            for g in parts[i]:
                cs = source[g]
                cs.decompile()
                target = charstrings[g]
                target.program, target.bytecode = list(cs.program), None
        return whole
