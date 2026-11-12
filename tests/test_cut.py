"""Standalone fonts (mapotofu.cut)."""

from __future__ import annotations

import io

from fontTools.fontBuilder import FontBuilder
from fontTools.pens.t2CharStringPen import T2CharStringPen
from fontTools.ttLib import TTFont

from mapotofu import cut

DATE = 3850070400  # 2026-01-01, in seconds since 1904 as head counts them


def _triangle(left: int, bottom: int, right: int, top: int):
    pen = T2CharStringPen(600, None)
    pen.moveTo((left, bottom))
    pen.lineTo((right, bottom))
    pen.lineTo(((left + right) // 2, top))
    pen.closePath()
    return pen.getCharString()


def _font(path) -> None:
    """A static CFF font, as a pool-backed one is: its dates are DATE, it holds a glyph (B) that
    none of its characters reaches, and its head has another bounding box than its glyphs."""
    small, large = _triangle(100, 0, 500, 700), _triangle(-50, -200, 900, 950)
    fb = FontBuilder(1000, isTTF=False)
    fb.setupGlyphOrder([".notdef", "A", "B"])
    fb.setupCharacterMap({0x41: "A"})
    fb.setupCFF("CFF2Font", {}, {".notdef": small, "A": small, "B": large}, {})
    fb.setupHorizontalMetrics({".notdef": (600, 100), "A": (600, 100), "B": (1200, -50)})
    fb.setupHorizontalHeader(ascent=800, descent=-200)
    fb.setupNameTable({"familyName": "Test", "styleName": "Regular", "fullName": "Test Regular", "psName": "Test-Regular"})
    fb.setupOS2()
    fb.setupPost()
    fb.font["head"].created = fb.font["head"].modified = DATE
    fb.font.recalcTimestamp = False
    data = io.BytesIO()
    fb.save(data)
    font = TTFont(io.BytesIO(data.getvalue()), recalcBBoxes=False, recalcTimestamp=False)
    head = font["head"]
    head.xMin = head.yMin = head.xMax = head.yMax = 0
    font.save(path)


def test_cutting_keeps_the_dates(tmp_path):
    # meta.finalize gives the fonts a fixed date, so that the same sources build the same bytes;
    # a save that stamps the current time would undo it.
    src, out = tmp_path / "pooled.otf", tmp_path / "standalone.otf"
    _font(src)
    cut.cut_font(src, out, static=True)
    head = TTFont(out)["head"]
    assert (head.created, head.modified) == (DATE, DATE)
    assert list(TTFont(out).getBestCmap()) == [0x41]


def test_a_standalone_font_has_the_bounding_box_of_its_own_glyphs(tmp_path):
    # Not the pool's, which holds glyphs of the other fonts, and not what the file said.
    src, out = tmp_path / "pooled.otf", tmp_path / "standalone.otf"
    _font(src)
    cut.cut_font(src, out, static=True)
    font = TTFont(out)
    head = font["head"]
    assert font.getGlyphOrder() == [".notdef", "A"]
    assert (head.xMin, head.yMin, head.xMax, head.yMax) == (100, 0, 500, 700)
    assert font["CFF "].cff.topDictIndex[0].FontBBox == [100, 0, 500, 700]
    # So are the extremes of hhea and the average width of OS/2: the pool's came from B too.
    pool = TTFont(src)
    assert (pool["hhea"].minLeftSideBearing, font["hhea"].minLeftSideBearing) == (-50, 100)
    assert (pool["hhea"].advanceWidthMax, font["hhea"].advanceWidthMax) == (1200, 600)
    assert (pool["OS/2"].xAvgCharWidth, font["OS/2"].xAvgCharWidth) == (800, 600)


def test_the_cff_of_a_static_font_has_the_name_of_the_font(tmp_path):
    # Not the pool's, and with what post says of the font.
    src, out = tmp_path / "pooled.otf", tmp_path / "standalone.otf"
    _font(src)
    pooled = TTFont(src)
    pooled["post"].isFixedPitch, pooled["post"].italicAngle = 1, -9.0
    pooled["post"].underlinePosition, pooled["post"].underlineThickness = -100, 50
    pooled.save(src)
    cut.cut_font(src, out, static=True)
    cff = TTFont(out)["CFF "].cff
    top = cff.topDictIndex[0]
    assert cff.fontNames == ["Test-Regular"]
    assert (top.FullName, top.FamilyName, top.Weight) == ("Test Regular", "Test", "Regular")
    assert (top.isFixedPitch, top.ItalicAngle, top.UnderlinePosition, top.UnderlineThickness) == (1, -9, -125, 50)
