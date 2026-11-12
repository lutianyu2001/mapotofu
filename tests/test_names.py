"""The name table and the dates (mapotofu.meta), with the configuration of tests/project."""

from __future__ import annotations

import pytest
from fontTools.ttLib import TTFont, newTable

from mapotofu import assemble, meta

EN, SC, TC, J = 0x409, 0x804, 0x404, 0x411


@pytest.fixture
def names(monkeypatch):
    # The copyright notice is read from the sources, which are not fetched here.
    monkeypatch.setattr(meta, "copyright", lambda view: "Copyright")

    def get(family: str, region: str, italic: bool, weight: str | None) -> dict[tuple[int, int], str]:
        font = TTFont()
        font["name"] = newTable("name")
        meta.set_names(font, assemble.View(family, region, italic), weight)
        return {(n.nameID, n.langID): n.toUnicode() for n in font["name"].names}

    return get


def test_a_linked_style_has_its_local_name(names):
    bold = names("Gothic", "SC", False, "Bold")
    assert (bold[1, EN], bold[2, EN], bold[4, EN]) == ("Momoka Gothic SC", "Bold", "Momoka Gothic SC Bold")
    assert (bold[1, SC], bold[2, SC], bold[4, SC]) == ("桃华黑体", "粗体", "桃华黑体 粗体")
    regular = names("Gothic", "TC", False, None)
    assert (regular[2, TC], regular[4, TC]) == ("標準", "桃華黑體")
    italic = names("Mono", "J", True, "Bold")
    assert (italic[2, J], italic[4, J]) == ("太字 斜体", "桃華ゴシック Mono 太字 斜体")


def test_another_weight_joins_the_family_name_in_every_language(names):
    light = names("UI", "SC", True, "ExtraLight")
    assert (light[1, EN], light[2, EN], light[4, EN]) == ("Momoka UI SC XLight", "Italic", "Momoka UI SC XLight Italic")
    assert (light[1, SC], light[2, SC], light[4, SC]) == ("桃华黑体 UI XLight", "斜体", "桃华黑体 UI XLight 斜体")
    # The full style name has no translation: the project names only the four linked styles.
    assert light[17, EN] == light[17, SC] == "ExtraLight Italic"


def test_the_shared_extension_names_the_style_in_each_language(names):
    bold = names("Ext", "CJK", False, "Bold")
    assert (bold[2, EN], bold[2, SC], bold[2, TC], bold[2, J]) == ("Bold", "粗体", "粗體", "太字")


def test_the_date_is_fixed_unless_the_environment_gives_one(monkeypatch):
    monkeypatch.delenv("SOURCE_DATE_EPOCH", raising=False)
    assert meta.date() == 3850070400  # 2026-01-01, in seconds since 1904
    monkeypatch.setenv("SOURCE_DATE_EPOCH", "86400")
    assert meta.date() == 2082844800 + 86400


def test_the_prefix_of_instance_names_has_letters_and_digits_only(names):
    assert names("Gothic", "SC", False, None)[25, EN] == "MomokaGothicSC"
    assert (25, EN) not in names("Gothic", "SC", False, "Bold")


def _with_stylistic_set(name_id: int) -> TTFont:
    """A font whose GSUB has a stylistic set named by `name_id`."""
    from fontTools.ttLib.tables import otTables as ot

    font = TTFont()
    font["name"] = newTable("name")
    font["GSUB"] = gsub = newTable("GSUB")
    gsub.table = table = ot.GSUB()
    table.Version = 0x00010000
    table.ScriptList, table.LookupList, table.FeatureList = ot.ScriptList(), ot.LookupList(), ot.FeatureList()
    table.ScriptList.ScriptRecord, table.LookupList.Lookup = [], []
    record, record.FeatureTag, record.Feature = ot.FeatureRecord(), "ss01", ot.Feature()
    record.Feature.LookupListIndex, record.Feature.FeatureParams = [], ot.FeatureParamsStylisticSet()
    record.Feature.FeatureParams.Version, record.Feature.FeatureParams.UINameID = 0, name_id
    table.FeatureList.FeatureRecord = [record]
    return font


def test_the_names_of_layout_features_stay_under_their_ids(monkeypatch):
    # The layout comes from the Latin source with the IDs of that source's names; naming the
    # font anew once gave those IDs to the names of the weights.
    source = TTFont()
    source["name"] = newTable("name")
    source["name"].setName("Classic construction", 256, 3, 1, EN)
    source["name"].setName("Something else", 257, 3, 1, EN)
    monkeypatch.setattr(meta, "copyright", lambda view: "Copyright")
    monkeypatch.setattr(meta.sources, "latin", lambda src: type("Latin", (), {"font": source}))
    font = _with_stylistic_set(256)
    font["name"].setName("Weight", 256, 3, 1, EN)  # as varLib names the axis, under the first free ID
    view = assemble.View("Mono", "SC", False)
    for _ in range(2):  # naming again keeps them
        meta.set_names(font, view, "Bold")
        meta._stat(font, view, "Bold")
        name = font["name"]
        assert name.getDebugName(256) == "Classic construction"
        assert name.getName(257, 3, 1, EN) is None or name.getDebugName(257) != "Something else"
        values = font["STAT"].table.AxisValueArray.AxisValue
        assert all(v.ValueNameID != 256 for v in values)


def test_a_static_font_states_its_own_weight_only(names):
    font = TTFont()
    font["name"] = newTable("name")
    view = assemble.View("Gothic", "SC", True)
    meta._stat(font, view, "Bold")
    name = font["name"]
    assert [name.getDebugName(v.ValueNameID) for v in font["STAT"].table.AxisValueArray.AxisValue] == ["Bold", "Italic"]
    assert {n.platformID for n in name.names} == {3}
    meta._stat(font, view, None)
    assert len(font["STAT"].table.AxisValueArray.AxisValue) == len(meta.STATIC_WEIGHTS) + 1
