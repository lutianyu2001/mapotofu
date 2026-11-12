"""The tools (mapotofu.tools) and the library they are made of, on a font drawn here."""

from __future__ import annotations

import math

import numpy as np
import pytest
from fontTools.fontBuilder import FontBuilder
from fontTools.pens.ttGlyphPen import TTGlyphPen
from fontTools.ttLib import TTFont, newTable
from PIL import Image

from mapotofu import tools
from mapotofu.tools import points, same, sheet, specimen, stems, ttf2otf
from mapotofu.tools.raster import FontSource, make_spec, parse_spec
from mapotofu.tools.skeleton import SkelGraph

V, H = 100, 60        # the widths of the vertical and the horizontal strokes of the font drawn


def _box(pen, x0, y0, x1, y1):
    pen.moveTo((x0, y0))
    pen.lineTo((x0, y1))
    pen.lineTo((x1, y1))
    pen.lineTo((x1, y0))
    pen.closePath()


DRAWN = {".notdef": [], "cross": [(450, -50, 450 + V, 850), (100, 370, 900, 370 + H)],
         "gong": [(450, 0, 450 + V, 800), (150, 740, 850, 740 + H), (100, 0, 900, H)]}


def _build(path, drawn, advances=None):
    """A TrueType font of 1000 units per em whose glyphs are the boxes given: 十 is `cross`, 工 `gong`."""
    builder = FontBuilder(1000, isTTF=True)
    builder.setupGlyphOrder(list(drawn))
    builder.setupCharacterMap({code: name for code, name in ((ord("十"), "cross"), (ord("工"), "gong")) if name in drawn})
    glyphs = {}
    for name, boxes in drawn.items():
        pen = TTGlyphPen(None)
        for box in boxes:
            _box(pen, *box)
        glyphs[name] = pen.glyph()
    builder.setupGlyf(glyphs)
    # (the left side bearing is where FreeType puts a TrueType glyph's left edge)
    builder.setupHorizontalMetrics({name: ((advances or {}).get(name, 1000), min((b[0] for b in boxes), default=0))
                                    for name, boxes in drawn.items()})
    builder.setupHorizontalHeader(ascent=880, descent=-120)
    builder.setupNameTable({"familyName": "Drawn", "styleName": "Regular"})
    builder.setupOS2()
    builder.setupPost()
    builder.save(path)
    return str(path)


@pytest.fixture(scope="module")
def font(tmp_path_factory):
    """A font of two glyphs: 十, a cross with a vertical stroke V wide and a horizontal one H
    wide, and 工, the same strokes as a 工."""
    return _build(tmp_path_factory.mktemp("font") / "Drawn-Regular.ttf", DRAWN)


def test_a_font_spec_names_a_face_and_a_place_on_the_axes():
    assert parse_spec("dir/Sans[wght].ttf@wght=500,wdth=87.5") == ("dir/Sans[wght].ttf", 0, {"wght": 500.0, "wdth": 87.5})
    assert parse_spec("Collection.ttc#2") == ("Collection.ttc", 2, {})
    assert make_spec("Collection.ttc", 2, {"wght": 500.0}) == "Collection.ttc#2@wght=500"


def test_a_glyph_is_rasterised_in_units_of_the_em(font):
    source = FontSource(font, 256)
    assert source.label == "Drawn Regular" and source.has("十") and source.glyph("永") is None
    glyph = source.glyph("十")
    assert glyph.ink.dtype == bool and glyph.advance == pytest.approx(1000)
    assert glyph.bbox() == pytest.approx((100, -50, 900, 850), abs=2 * glyph.px)
    grey, left, top, advance = source.gray("十")
    assert grey.dtype == np.uint8 and grey.max() == 255 and advance == pytest.approx(256)
    assert (left, top) == (math.floor(100 * 0.256), math.ceil(850 * 0.256))   # the box of whole pixels


def test_the_skeleton_of_a_cross_is_four_strokes_about_a_junction(font):
    graph = SkelGraph(FontSource(font, 256).glyph("十").ink)
    assert sorted(graph.node_kind) == ["end"] * 4 + ["junction"]
    points, body = graph.body_mask()
    assert 0 < body.sum() < len(points)                      # the junction's surroundings are left out
    pixels, masked, nodes = graph.trace_from(graph.node_kind.index("end"))
    assert len(nodes) == 3 and masked.any() and not masked.all()   # through the junction to the far end


def test_stems_reads_the_widths_of_the_strokes(font):
    one = stems.glyph_stems(FontSource(font).glyph("十"))
    assert one["stem_v"] == pytest.approx(V, abs=4) and one["stem_h"] == pytest.approx(H, abs=4)
    assert one["face"] == pytest.approx(900, abs=4)
    found = stems.font_stems(FontSource(font))
    assert found["glyphs"] == 2                              # of the default characters, those the font has
    assert found["stem_v"] == pytest.approx(V, abs=4) and found["stem_h"] == pytest.approx(H, abs=4)
    assert found["hv"] == pytest.approx(H / V, abs=0.05)
    assert stems.font_stems(FontSource(font), "十")["glyphs"] == 1


def test_stems_prints_a_line_a_font(font, capsys):
    tools.main(["stems", font, font, "--chars", "十工", "--res", "256"])
    lines = capsys.readouterr().out.splitlines()
    assert lines[0].split() == ["font", "glyphs", "stem_v", "stem_h", "hv", "weight", "spread", "face"]
    assert len(lines) == 3 and lines[1].split()[:3] == ["Drawn", "Regular", "2"]


def test_sheet_draws_a_row_a_font_and_a_row_a_spot(font, tmp_path):
    out = tmp_path / "sheet.png"
    tools.main(["sheet", str(out), "十工", font, font, "--size", "100"])
    img = np.asarray(Image.open(out))
    cell = round(100 * (1 + 2 * sheet.MARGIN))
    assert img.shape == (2 * (cell + 17) + 1, 2 * (cell + 1) + 1) and img.min() < 40   # ink in it
    assert (img[1:cell + 1] == img[cell + 18:2 * cell + 18]).all()                    # the same font twice
    tools.main(["sheet", str(out), "", font, "--zoom", "十", "500", "400", "200", "--zoom", "工", "500", "30", "200", "--size", "90"])
    img = np.asarray(Image.open(out))
    assert img.shape == (2 * (90 + 17) + 1, 90 + 2)
    assert img[46, 46] < 40 and img[3, 3] > 200            # the middle of the cross is ink, the corner of its spot is not


def test_specimen_renders_the_lines(font, tmp_path):
    out = tmp_path / "specimen.png"
    tools.main(["specimen", font, str(out), "--weights", "400", "--size", "20"])
    # (the font drawn here has none of the sample's characters: each is its .notdef, an em wide)
    longest = max(len(line) for line in specimen.LINES)
    assert np.asarray(Image.open(out)).shape == (len(specimen.LINES) * 32 + 20, longest * 20 + 70)
    # a font without a weight axis is set once, whatever weights are asked for
    tools.main(["specimen", font, str(out), "--size", "20"])
    assert np.asarray(Image.open(out)).shape == (len(specimen.LINES) * 32 + 20, longest * 20 + 70)


def test_specimen_sets_the_lines_given(font, tmp_path):
    out = tmp_path / "specimen.png"
    tools.main(["specimen", font, str(out), "--size", "20", "--text", "十工", "--text", "工"])
    img = np.asarray(Image.open(out))
    assert img.shape == (2 * 32 + 20, 680)
    first, second = img[10:42] < 128, img[42:74] < 128
    assert first[:, 10:30].any() and first[:, 30:50].any()          # two glyphs, an em each
    assert second[:, 10:30].any() and not second[:, 30:].any()      # one
    # a line longer than the picture's least width makes it longer: nothing is cut off
    tools.main(["specimen", font, str(out), "--size", "20", "--text", "十" * 40])
    img = np.asarray(Image.open(out))
    assert img.shape == (32 + 20, 40 * 20 + 70) and (img[:, 39 * 20 + 10:40 * 20 + 10] < 128).any()


def test_same_tells_the_glyphs_that_differ(font, tmp_path, capsys):
    assert same.compare(font, _build(tmp_path / "again.ttf", DRAWN)).same
    moved = {**DRAWN, "gong": [(450, 0, 450 + V, 800), (150, 740, 850, 740 + H), (100, 0, 901, H)], "more": [(0, 0, 10, 10)]}
    del moved["cross"]
    other = _build(tmp_path / "other.ttf", moved, {".notdef": 500})
    found = same.compare(font, other)
    assert not found.same and found.common == [".notdef", "gong"] and found.different == [".notdef", "gong"]
    assert found.outline == {"gong"} and found.advance == {".notdef"}          # one unit of one point; an advance
    assert found.only_first == ["cross"] and found.only_second == ["more"] and found.chars["gong"] == "工"
    with pytest.raises(SystemExit) as stop:
        tools.main(["same", font, other])
    out = capsys.readouterr().out
    assert stop.value.code == 1 and "different: 2 (outline 1, advance 1)" in out and "only in the first: cross 十" in out
    with pytest.raises(SystemExit) as stop:
        tools.main(["same", font, font, "--list", "0"])
    assert stop.value.code == 0 and capsys.readouterr().out.splitlines()[-1] == "the same"


def test_points_lists_an_outline_as_the_font_stores_it(font, capsys):
    cross = points.contours(font, "十")
    assert [len(c) for c in cross] == [4, 4] and all(on for c in cross for _, _, on in c)
    assert sorted((x, y) for x, y, _ in cross[1]) == [(100, 370), (100, 370 + H), (900, 370), (900, 370 + H)]
    assert points.contours(font, glyph="gong") == points.contours(font, "工")
    with pytest.raises(KeyError):
        points.contours(font, "永")
    tools.main(["points", font, "十永", "--glyph", "gong", "--box", "0", "0", "200", "1000"])
    lines = capsys.readouterr().out.splitlines()
    assert lines[0] == "十  U+5341  cross  advance 1000  2 contours, 8 points"
    assert lines[1] == "  contour 1: 4 points"                       # the vertical stroke has no point in the box
    assert [line.split() for line in lines[2:4]] == [["4", "100", "370", "on"], ["5", "100", str(370 + H), "on"]]
    assert lines[4] == "永  U+6C38: not in the font" and lines[5].startswith("gong  advance 1000  3 contours")


def test_ttf2otf_keeps_the_shapes_and_the_advances(font, tmp_path):
    out = tmp_path / "Drawn-Regular.otf"
    tools.main(["ttf2otf", font, str(out)])
    made, was = TTFont(out), TTFont(font)
    assert made.sfntVersion == "OTTO" and "CFF " in made and "glyf" not in made and made["post"].formatType == 3.0
    assert made.getGlyphOrder() == was.getGlyphOrder() and made["CFF "].cff.fontNames == ["Drawn-Regular"]
    for name in was.getGlyphOrder():
        assert made.getGlyphSet()[name].width == was.getGlyphSet()[name].width
    before, after = FontSource(font, 256).glyph("十"), FontSource(str(out), 256).glyph("十")
    assert (before.ink == after.ink).all() and before.bbox() == after.bbox()
    flat = tmp_path / "flat.otf"
    tools.main(["ttf2otf", font, str(flat), "--no-subroutines"])
    assert same.compare(str(out), str(flat)).same
    variable = TTFont(font)
    variable["fvar"] = newTable("fvar")
    with pytest.raises(ValueError, match="variable"):
        ttf2otf.to_otf(variable)
    with pytest.raises(ValueError, match="no TrueType outlines"):
        ttf2otf.to_otf(made)
