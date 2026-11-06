"""Instance one static weight of a CFF2 variable font for a share of its glyphs.

    python -m mapotofu.instance GLYPHS IN.otf OUT.otf WEIGHT

GLYPHS is a file of comma-separated glyph indexes. The other glyphs are emptied before
instancing, so that the process holds only its share of the outlines; OUT holds a static CFF
in which only the listed glyphs are drawn. merge() runs several of these at once and puts
their glyphs together, subroutinize() makes the static CFF of the result; fontTools needs
memory of about 60 times the font file's size to instance all its glyphs in one process.
key() digests what decides the result.
"""

from __future__ import annotations

import sys
from pathlib import Path

from fontTools.ttLib import TTFont
from fontTools.varLib.instancer import instantiateVariableFont

# Tables the static CFF does not depend on.
DROP = ("GSUB", "GPOS", "GDEF", "BASE", "JSTF", "STAT", "meta", "vhea", "vmtx", "VVAR", "VORG")


def main(argv: list[str]) -> int:
    glyphs, src, out, weight = argv
    keep = {int(g) for g in open(glyphs).read().split(",")}
    font = TTFont(src, recalcBBoxes=False, recalcTimestamp=False)
    for tag in DROP:
        if tag in font:
            del font[tag]
    charstrings = font["CFF2"].cff.topDictIndex[0].CharStrings
    for g, name in enumerate(font.getGlyphOrder()):
        if g not in keep:
            cs = charstrings[name]
            cs.program, cs.bytecode = [], None
    font = instantiateVariableFont(font, {"wght": float(weight)}, inplace=True, downgradeCFF2=True, static=True)
    font.recalcBBoxes = False
    font.save(out)
    return 0


def key(vf: Path, value: float) -> str:
    """What decides the static CFF of a weight: the hinted CFF2, the advance widths and the axis
    normalization of the variable font, the weight, the code and the versions."""
    from . import shards, stamps

    font = TTFont(vf, lazy=True)
    axes = [(a.axisTag, a.minValue, a.defaultValue, a.maxValue) for a in font["fvar"].axes]
    return stamps.digest(
        *(font.reader[t] for t in ("CFF2", "hmtx", "HVAR", "avar") if t in font.reader), axes, value,
        stamps.sources(DROP, main, merge, subroutinize, shards.by_glyph),
        stamps.versions("fonttools", "cffsubr"),
    )


def merge(vf: Path, order: list[str], value: float, shards: int) -> bytes:
    """The static weight `value` of the variable font's CFF2, as a font whose CFF is to be
    used alone, instanced in `shards` processes: the part that needs much memory."""
    import io

    from .shards import by_glyph

    font = by_glyph(
        vf, order, shards,
        lambda glyphs, out: [sys.executable, "-m", "mapotofu.instance", str(glyphs), str(vf), str(out), str(value)],
        "instancing",
    )
    buf = io.BytesIO()
    font.save(buf)
    return buf.getvalue()


def subroutinize(merged: bytes) -> bytes:
    """The CFF table of a merged font, subroutinized by AFDKO tx: long, in one thread, with
    little memory. cffsubr.subroutinize would parse tx's table and compile it again; this calls
    the function under it, cffsubr._tx_subroutinize (cffsubr 0.4.0), and keeps tx's bytes."""
    from cffsubr import _tx_subroutinize

    return _tx_subroutinize(merged, "CFF ")


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
