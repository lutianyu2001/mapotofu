"""Hinting values by source and master (mapotofu.zones)."""

from __future__ import annotations

from fontTools.varLib.models import VariationModel, supportScalar

from mapotofu import zones


def _box(x0: float, y0: float, x1: float, y1: float, slant: float = 0.0) -> list:
    """A bar as a recorded outline; slant moves its top to the right."""
    return [
        ("moveTo", ((x0, y0),)), ("lineTo", ((x1, y0),)), ("lineTo", ((x1 + slant, y1),)),
        ("lineTo", ((x0 + slant, y1),)), ("closePath", ()),
    ]


def test_a_stem_is_measured_where_a_line_cuts_it():
    assert zones.stem(_box(100, 0, 180, 700), vertical=True) == 80
    # A slanted stem is as wide as it stands on the line, whatever its box.
    assert zones.stem(_box(100, 0, 180, 700, slant=150), vertical=True) == 80
    # A letter like H: two stems and a bar; the line through the middle crosses the bar only.
    letter = _box(100, 0, 180, 700) + _box(180, 320, 520, 390) + _box(520, 0, 600, 700)
    assert zones.stem(letter, vertical=False) == 70
    assert zones.stem(letter, vertical=True) == 80
    assert zones.stem([], vertical=True) is None


def test_a_curved_stem_is_measured_on_the_curve():
    # A ring: the line through its middle crosses the left side of the stroke first.
    k = 0.5523
    def ring(r):
        return [
            ("moveTo", ((r, 0),)), ("curveTo", ((r, k * r), (k * r, r), (0, r))),
            ("curveTo", ((-k * r, r), (-r, k * r), (-r, 0))), ("curveTo", ((-r, -k * r), (-k * r, -r), (0, -r))),
            ("curveTo", ((k * r, -r), (r, -k * r), (r, 0))), ("closePath", ()),
        ]
    assert zones.stem(ring(300) + ring(240), vertical=True) == 60


def test_blended_values_are_the_masters_values_at_the_masters():
    # As a font with masters at five places of the axis writes them, the regions in an order of
    # its own; read back at each master (as the values of Source Han Sans are read), they are
    # what went in.
    coords = [0.0, -1.0, -0.4, 0.5, 1.0]
    model = VariationModel([{"wght": c} if c else {} for c in coords], ["wght"])
    order = [4, 1, 3, 2]  # the font's regions, as places among the model's
    supports = [model.supports[j] for j in order]
    at_masters = {
        "BlueValues": [[-14, 0, 536, 550, 714, 728], [-12, 0, 531, 545, 714, 726], [-13, 0, 533, 547, 714, 727],
                       [-14, 0, 541, 555, 714, 728], [-15, 0, 549, 563, 714, 729]],
        "StdVW": [88, 48, 70, 120, 169],
        "OtherBlues": [[-250, -240]] * 5,
        "BlueScale": [0.037] * 5,
    }
    for key, values in at_masters.items():
        blended = zones._blended(key, values, model, order)
        if key in ("OtherBlues", "BlueScale"):
            assert blended == values[0]  # nothing to blend where the masters agree
        for coord, value in zip(coords, values):
            scalars = [supportScalar({"wght": coord}, support) for support in supports]
            assert zones._absolute(key, blended, scalars) == value, (key, coord)
