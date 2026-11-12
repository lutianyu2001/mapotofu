"""A font with TrueType outlines made into an OTF with PostScript outlines (CFF).

    mapo tool ttf2otf FONT OUT.otf [--tolerance UNITS] [--no-subroutines]

    from fontTools.ttLib import TTFont
    from mapotofu.tools.ttf2otf import to_otf

    font = TTFont("Font.ttf")
    to_otf(font)                       # in place
    font.save("Font.otf")

Every glyph is drawn anew: runs of quadratic curves are joined into cubic ones to within the
tolerance, coordinates are rounded to whole units, and composite glyphs become plain outlines
(CFF has none). The CFF table is written from the font's name table and holds the glyphs by
name (it is not CID-keyed). With vertical metrics, a VORG table keeps each glyph's vertical
origin, which TrueType takes from the glyph's top. The outlines are then subroutinized (AFDKO's
tx, through cffsubr), which takes about a hundred times the font's size in memory. Hints are
not made: otfautohint adds them to the result.

The other direction is AFDKO's: otf2ttf FONT, or afdko.otf2ttf.otf_to_ttf(font).

A variable font is refused: its outlines are those of one master, and a CFF table cannot hold
the others. Instance it first (fonttools varLib.instancer).
"""

from __future__ import annotations

import argparse

from fontTools.fontBuilder import FontBuilder
from fontTools.pens.qu2cuPen import Qu2CuPen
from fontTools.pens.t2CharStringPen import T2CharStringPen
from fontTools.ttLib import TTFont, newTable

TOLERANCE = 0.3        # font units: quadratic curves are joined into cubic ones to within this
TRUETYPE_ONLY = ("glyf", "loca", "cvt ", "fpgm", "prep", "gasp", "hdmx", "LTSH", "VDMX")


def to_otf(font: TTFont, tolerance: float = TOLERANCE, subroutinize: bool = True) -> None:
    """Turn a font with TrueType outlines into one with CFF outlines, in place."""
    if "glyf" not in font:
        raise ValueError("the font has no TrueType outlines (glyf)")
    if "gvar" in font or "fvar" in font:
        raise ValueError("a variable font: instance it first (fonttools varLib.instancer)")
    order, glyphs = font.getGlyphOrder(), font.getGlyphSet()
    glyf, hmtx = font["glyf"], font["hmtx"]
    em = font["head"].unitsPerEm
    drawn = {}
    for name in order:
        advance = hmtx[name][0]
        pen = T2CharStringPen(None if advance == em else advance, glyphs)
        # (PostScript contours run the other way round)
        glyphs[name].draw(Qu2CuPen(pen, tolerance, all_cubic=True, reverse_direction=True))
        drawn[name] = pen.getCharString()
    if "vmtx" in font:
        top = {n: font["vmtx"][n][1] + glyf[n].yMax for n in order if getattr(glyf[n], "numberOfContours", 0)}
        if top:
            common = max(set(top.values()), key=list(top.values()).count)
            font["VORG"] = vorg = newTable("VORG")
            vorg.majorVersion, vorg.minorVersion, vorg.defaultVertOriginY = 1, 0, common
            vorg.VOriginRecords = {n: v for n, v in top.items() if v != common}
            vorg.numVertOriginYMetrics = len(vorg.VOriginRecords)
    names = font["name"]
    builder = FontBuilder(font=font)
    builder.isTTF = False
    family = names.getDebugName(16) or names.getDebugName(1)
    style = names.getDebugName(17) or names.getDebugName(2)
    # the PostScript name; a font without one is named as that name is made, Family-Style
    ps = names.getDebugName(6) or "-".join(part.replace(" ", "") for part in (family, style) if part) or "Font"
    info = {"FullName": names.getDebugName(4) or " ".join(part for part in (family, style) if part), "FamilyName": family}
    builder.setupCFF(ps, {k: v for k, v in info.items() if v}, drawn, {"defaultWidthX": em, "nominalWidthX": 0})
    for tag in TRUETYPE_ONLY:
        if tag in font:
            del font[tag]
    font["maxp"] = maxp = newTable("maxp")
    maxp.tableVersion, maxp.numGlyphs = 0x00005000, len(order)
    post = font["post"]
    post.formatType, post.extraNames, post.mapping = 3.0, [], {}
    if subroutinize:
        import cffsubr

        cffsubr.subroutinize(font)


def parser(prog: str = "mapo tool ttf2otf") -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        prog=prog, description="Make a font with TrueType outlines into an OTF with PostScript outlines (CFF).",
        epilog="The other direction is AFDKO's otf2ttf.",
    )
    ap.add_argument("font", metavar="FONT", help="a font file with TrueType outlines, not variable")
    ap.add_argument("out", metavar="OUT.otf")
    ap.add_argument("--tolerance", type=float, default=TOLERANCE, metavar="UNITS",
                    help=f"how far a cubic curve may run from the quadratic ones it replaces, in font units (default: {TOLERANCE})")
    ap.add_argument("--no-subroutines", action="store_true",
                    help="leave the outlines unsubroutinized: a larger file, made with little memory")
    return ap


def main(argv: list[str] | None = None) -> None:
    args = parser().parse_args(argv)
    font = TTFont(args.font)
    try:
        to_otf(font, args.tolerance, not args.no_subroutines)
    except ValueError as ex:
        raise SystemExit(f"{args.font}: {ex}") from None
    font.save(args.out)


if __name__ == "__main__":
    main()
