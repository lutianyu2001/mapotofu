from mapotofu.charsets import Cat, category, source_of


def test_categories():
    assert category(0x4E00) is Cat.IDEO
    assert category(0x2F00) is Cat.IDEO  # radicals overlap WS; ideographs win
    assert category(0xAC00) is Cat.HANGUL
    assert category(0x0041) is Cat.WESTERN
    assert category(0x00B7) is Cat.AS
    assert category(0x2014) is Cat.AS
    assert category(0x2192) is Cat.WS
    assert category(0xFF01) is Cat.AS  # varies by region
    assert category(0xFF03) is Cat.WS
    assert category(0x3042) is Cat.FEMISC
    assert category(0x2E3A) is Cat.LONGDASH


def test_sources():
    assert source_of(0x2014, "Gothic", True, True) == "cjk"  # AS beats Latin
    assert source_of(0x2014, "Mono", True, True) == "latin"  # Mono takes U+2000-209F from Latin
    assert source_of(0x2192, "Gothic", True, True) == "latin"  # WS: Latin wins
    assert source_of(0x2460, "Gothic", True, True) == "cjk"  # circled numbers (SPEC 2.9)
    assert source_of(0x2460, "Mono", True, True) == "latin"
    assert source_of(0x2E3A, "Mono", True, False) is None
    assert source_of(0xAC00, "Gothic", True, False) is None
