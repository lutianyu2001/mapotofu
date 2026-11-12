"""The tools that look at a font across its weights (change, weights) and at all its glyphs
(proof), on fonts drawn here."""

from __future__ import annotations

import re

import numpy as np
import pytest
from PIL import Image

from mapotofu import tools
from mapotofu.tools import change, proof, weights
from mapotofu.tools.raster import FontSource

from .test_tools import H, V, _build

HV, HH = 160, 78      # the widths of the strokes of the heavy font
COPIES = ["cross.a", "cross.b", "cross.c"]


def _cross(v, h):
    return [(500 - v // 2, -50, 500 + v // 2, 850), (100, 400 - h // 2, 900, 400 + h // 2)]


def _drawn(v, h, odd=None, copies=COPIES):
    """The glyphs of test_tools with strokes v and h wide, and copies of the cross no character
    leads to; the horizontal stroke of `cross.c` is `odd` wide if given."""
    drawn = {".notdef": [], "cross": _cross(v, h), "gong": [(500 - v // 2, 0, 500 + v // 2, 800), (150, 800 - h, 850, 800), (100, 0, 900, h)]}
    drawn.update({name: _cross(v, odd if odd and name == "cross.c" else h) for name in copies})
    return drawn


@pytest.fixture(scope="module")
def fonts(tmp_path_factory):
    """A light font and a heavy one whose `cross.c` gained too much in its thin stroke, and two
    weights of a reference family with more glyphs, all of them regular."""
    at = tmp_path_factory.mktemp("weights")
    more = [f"cross.{c}" for c in "abcdefgh"]
    return {"light": _build(at / "Light.ttf", _drawn(V, H)), "heavy": _build(at / "Heavy.ttf", _drawn(HV, HH, odd=120)),
            "ref_light": _build(at / "RefLight.ttf", _drawn(V, H, copies=more)),
            "ref_heavy": _build(at / "RefHeavy.ttf", _drawn(HV, HH, copies=more))}


def test_a_glyph_is_measured_on_its_ink(fonts):
    found = change.glyph_measures(FontSource(fonts["light"]).glyph("十"))
    assert found["thick"] == pytest.approx(V, abs=3) and found["thin"] == pytest.approx(H, abs=3)
    assert found["area"] == pytest.approx(V * 900 + (800 - V) * H, rel=0.02)
    assert (found["width"], found["height"], found["advance"]) == pytest.approx((800, 900, 1000), abs=4)


def test_change_is_the_heavy_glyph_against_the_light_one(fonts):
    light, heavy = FontSource(fonts["light"]), FontSource(fonts["heavy"])
    changed = change.changes(light, heavy)
    assert sorted(changed) == ["cross", *COPIES, "gong"]            # .notdef has no ink
    assert list(change.changes(light, heavy, ["gong", "nothing"])) == ["gong"]
    one = changed["cross"]
    assert one["thick"] == pytest.approx(HV / V, abs=0.05) and one["thin"] == pytest.approx(HH / H, abs=0.05)
    assert one["width"] == pytest.approx(1, abs=0.01) and one["advance"] == 1
    assert changed["cross.c"]["thin"] == pytest.approx(120 / H, abs=0.05)
    assert change.kinds(light) == dict.fromkeys(["cross", "gong", *COPIES], "letters")   # by character, then by name


def test_unlike_lists_the_glyph_outside_the_band(fonts):
    light, heavy = FontSource(fonts["light"]), FontSource(fonts["heavy"])
    changed, kind = change.changes(light, heavy), change.kinds(light)
    assert list(change.unlike(changed, kind).listed) == ["cross.c"]   # the font's own glyphs are the band
    found = change.unlike(changed, kind, tested=["cross.c"])         # the others set the change and the band
    assert found.level["letters", "thin"] == pytest.approx(HH / H, abs=0.05)
    assert found.band["letters", "thin"] == (1 - change.FLOOR["thin"], 1 + change.FLOOR["thin"])
    (name, (k, outside)), = found.listed.items()
    assert (name, k) == ("cross.c", "letters") and [key for key, _ in outside] == ["area", "thin"]
    assert dict(outside)["thin"] == pytest.approx(120 / HH, abs=0.05)
    assert re.fullmatch(r"area \+1\d%, thin \+5\d%", change.off(outside))
    a, b = FontSource(fonts["ref_light"]), FontSource(fonts["ref_heavy"])
    against = change.unlike(changed, kind, change.changes(a, b), change.kinds(a))
    assert list(against.listed) == ["cross.c"]                       # the reference's glyphs are the band


def test_change_prints_the_kinds_and_the_glyphs_listed(fonts, capsys):
    tools.main(["change", fonts["light"], fonts["heavy"], "--only", "cross.c", "--res", "256"])
    lines = capsys.readouterr().out.splitlines()
    assert lines[0] == "Drawn Regular to Drawn Regular" and lines[3].split()[:2] == ["letters", "area"]
    assert float(lines[3].split()[2]) == pytest.approx(1.45, abs=0.05)
    assert lines[5].startswith("1 of 1 glyphs") and lines[-1].split()[:2] == ["cross.c", "letters"]
    tools.main(["change", fonts["light"], fonts["heavy"], "--reference", fonts["ref_light"], fonts["ref_heavy"]])
    out = capsys.readouterr().out
    assert ", against Drawn Regular to Drawn Regular" in out and "1 of 5 glyphs" in out
    with pytest.raises(SystemExit, match="not a glyph both fonts draw: nothing"):
        tools.main(["change", fonts["light"], fonts["heavy"], "--only", "nothing"])


def test_weights_sets_each_font_against_the_base(fonts, capsys):
    rows = [weights.font_measures(FontSource(fonts[name]), "十工") for name in ("light", "heavy")]
    assert rows[0]["stem_v"] == pytest.approx(V, abs=4) and rows[0]["glyphs"] == 2
    assert (rows[0]["ink"], rows[0]["bearings"], rows[0]["advance"]) == pytest.approx((800, 200, 1000), abs=4)
    percent = weights.against(rows)
    assert percent[0]["stem_v"] == 100 and percent[1]["stem_v"] == pytest.approx(100 * HV / V, abs=6)
    assert percent[1]["stem_h"] == pytest.approx(100 * HH / H, abs=8) and percent[1]["advance"] == 100
    tools.main(["weights", fonts["light"], fonts["heavy"], "--chars", "十工", "--res", "256", "--base", "2"])
    lines = [line.split() for line in capsys.readouterr().out.splitlines()]
    assert lines[1] == ["glyphs", "2", "2"] and [line[0] for line in lines[2:]] == list(weights.KEYS)
    assert lines[2][1].endswith("%") and float(lines[2][2]) == pytest.approx(HV, abs=4)     # the second is the base
    with pytest.raises(SystemExit, match="--base 3"):
        tools.main(["weights", fonts["light"], fonts["heavy"], "--base", "3"])


def test_proof_draws_every_glyph_a_cell_a_font(fonts, tmp_path):
    (tmp_path / "proof-09.png").write_bytes(b"")                    # a page of an earlier, longer run
    tools.main(["proof", str(tmp_path / "proof"), fonts["light"], fonts["heavy"], "--size", "50",
                "--columns", "2", "--rows", "2", "--mark", "gong"])
    assert sorted(p.name for p in tmp_path.iterdir()) == ["proof-01.png", "proof-02.png"]    # five glyphs, four a page
    page = np.asarray(Image.open(tmp_path / "proof-01.png"))
    tile = (page.shape[1] - 4) // 2 - 4                              # two tiles across, each two cells
    assert tile % 2 == 0 and page[:, :, 0].min() < 40                # ink
    red = (page[:, :, 0] > 200) & (page[:, :, 1] < 60)
    assert red.any() and not red[:, :4 + tile].any()                 # gong, the second tile, is marked; cross is not
    cell = tile // 2
    row = page[proof.STRIP + 4 + proof.STRIP:proof.STRIP + 4 + proof.STRIP + 40, 4:4 + tile, 0] < 128
    assert row[:, cell:].sum() > 1.3 * row[:, :cell].sum()           # the heavy font's cell holds more ink
    last = np.asarray(Image.open(tmp_path / "proof-02.png"))
    assert last.shape == page.shape and (last[proof.STRIP + 2:, 4 + tile + 4:, 0] > 100).all()   # one glyph left
