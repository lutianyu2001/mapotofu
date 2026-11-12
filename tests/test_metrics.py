"""Bounding boxes and Windows metrics (mapotofu.assemble, mapotofu.meta, mapotofu.package)."""

from __future__ import annotations

from fontTools.fontBuilder import FontBuilder
from fontTools.pens.t2CharStringPen import T2CharStringPen
from fontTools.ttLib import TTFont

from mapotofu import assemble, meta, package


def _glyph(bottom: int | None, top: int | None = None):
    """A triangle from bottom to top, or a glyph without an outline."""
    pen = T2CharStringPen(600, None)
    if bottom is not None:
        pen.moveTo((100, bottom))
        pen.lineTo((500, bottom))
        pen.lineTo((300, top))
        pen.closePath()
    return pen.getCharString()


def _font(glyphs: dict) -> TTFont:
    fb = FontBuilder(1000, isTTF=False)
    fb.setupGlyphOrder(list(glyphs))
    fb.setupCharacterMap({})
    fb.setupCFF("Test-Regular", {"FullName": "Test Regular"}, glyphs, {})
    fb.setupHorizontalMetrics({name: (600, 100) for name in glyphs})
    fb.setupHorizontalHeader(ascent=800, descent=-200)
    fb.setupNameTable({"familyName": "Test", "styleName": "Regular"})
    fb.setupOS2()
    fb.setupPost()
    return fb.font


def test_the_extent_covers_every_master():
    # A glyph is highest at one master and lowest at another; a master that does not hold a
    # glyph (an empty charstring) says nothing about it.
    masters = [
        _font({".notdef": _glyph(0, 700), "a": _glyph(-120, 900)}),
        _font({".notdef": _glyph(None), "a": _glyph(-100, 950)}),
        _font({".notdef": _glyph(-300, 700), "a": _glyph(None)}),
    ]
    assert assemble._extent(masters) == (-300, 950)


def test_windows_metrics_cover_the_extent_and_the_line():
    view = assemble.View("Gothic", "SC", False)
    asc, desc = meta.LINE_DEFAULT
    for extent, expected in (((-600, 1400), (1400, 600)), ((-100, 900), (asc, -desc))):
        font = _font({".notdef": _glyph(0, 700)})
        meta._os2(font, view, None, extent)
        os2 = font["OS/2"]
        assert (os2.usWinAscent, os2.usWinDescent) == expected


def _vertical(font: TTFont, origins: dict[str, int]) -> None:
    """Vertical metrics with a top side bearing of 0, as a font arrives that has not been measured."""
    from fontTools.ttLib import newTable

    font["vhea"] = vhea = newTable("vhea")
    vhea.tableVersion, vhea.ascent, vhea.descent, vhea.lineGap = 0x00011000, 500, -500, 0
    vhea.advanceHeightMax = vhea.minTopSideBearing = vhea.minBottomSideBearing = vhea.yMaxExtent = 0
    vhea.caretSlopeRise, vhea.caretSlopeRun, vhea.caretOffset = 0, 1, 0
    vhea.reserved1 = vhea.reserved2 = vhea.reserved3 = vhea.reserved4 = 0
    vhea.metricDataFormat, vhea.numberOfVMetrics = 0, len(origins)
    font["vmtx"] = vmtx = newTable("vmtx")
    vmtx.metrics = {name: (1000, 0) for name in origins}
    font["VORG"] = vorg = newTable("VORG")
    vorg.majorVersion, vorg.minorVersion, vorg.defaultVertOriginY = 1, 0, 880
    vorg.VOriginRecords = {name: y for name, y in origins.items() if y != 880}
    vorg.numVertOriginYMetrics = len(vorg.VOriginRecords)


def test_a_static_font_is_measured_at_its_own_weight(tmp_path):
    # The font arrives with the side bearings, extremes and box of the variable font (the
    # default weight's) and with Windows metrics that this weight, reaching further, passes.
    heavy = _font({".notdef": _glyph(0, 700), "a": _glyph(-250, 1010)})
    cff = heavy["CFF "].compile(heavy)
    font = _font({".notdef": _glyph(0, 700), "a": _glyph(-200, 1000)})
    font["hmtx"].metrics = {".notdef": (600, 90), "a": (600, 80)}
    _vertical(font, {".notdef": 880, "a": 900})
    head, os2, hhea, vhea = font["head"], font["OS/2"], font["hhea"], font["vhea"]
    head.xMin, head.yMin, head.xMax, head.yMax = 100, -200, 500, 1000
    os2.usWinAscent, os2.usWinDescent = 1005, 300
    package._set_bounds(font, cff)
    assert (head.xMin, head.yMin, head.xMax, head.yMax) == (100, -250, 500, 1010)
    assert (os2.usWinAscent, os2.usWinDescent) == (1010, 300)
    assert font["hmtx"].metrics == {".notdef": (600, 100), "a": (600, 100)}
    assert font["vmtx"].metrics == {".notdef": (1000, 180), "a": (1000, -110)}
    mine = (
        hhea.advanceWidthMax, hhea.minLeftSideBearing, hhea.minRightSideBearing, hhea.xMaxExtent,
        vhea.advanceHeightMax, vhea.minTopSideBearing, vhea.minBottomSideBearing, vhea.yMaxExtent,
    )
    assert mine == (600, 100, 100, 500, 1000, -110, -150, 1150)
    # fontTools, saving the font with its glyphs, works the same extremes out of the bearings.
    font["CFF "] = heavy["CFF "]
    font.save(tmp_path / "static.otf")
    saved = TTFont(tmp_path / "static.otf")
    hhea, vhea = saved["hhea"], saved["vhea"]
    assert mine == (
        hhea.advanceWidthMax, hhea.minLeftSideBearing, hhea.minRightSideBearing, hhea.xMaxExtent,
        vhea.advanceHeightMax, vhea.minTopSideBearing, vhea.minBottomSideBearing, vhea.yMaxExtent,
    )


def test_a_glyph_without_width_takes_no_cell():
    # Mono rounds the widths of unencoded glyphs up to half an em; a combining mark has none.
    from mapotofu import glyphs

    masters = len(glyphs.MASTERS)
    assert glyphs.resolve(glyphs.Rule("ceil"), [0.0] * masters) is None
    assert glyphs.resolve(glyphs.Rule("ceil"), [10.0] * masters) == glyphs.Rule("center", 500)
