"""The hint cache (mapotofu.hintcache): its file format and its split into files. That hints put
back into a glyph's own charstring are those otfautohint gave it is checked on built fonts, in
the font projects."""

from __future__ import annotations

import pytest

from mapotofu import hintcache
from mapotofu.hintcache import Entry

KEY = "0123456789abcdef0123456789abcdef"


@pytest.mark.parametrize(
    "entry",
    [
        Entry(
            "h",
            (("hstemhm", [[9, 26, -34, 1], -21, 4.5]), ("vstemhm", [70, [42, 41, -51, 1]]),
             ("hintmask", []), ("", [b"\x09\x00"])),
            ((4, "hintmask", b"\x43\x00"), (8, "cntrmask", b"\x0a")),
        ),
        Entry("h"),
        Entry("r", (1, 2, "rmoveto", 3, "hlineto", "hintmask", b"\xff", 0.25, -7, "rlineto")),
        Entry("-", reason="GlyphTimeout over 60 s; 字"),
    ],
)
def test_entries_read_back_as_written(entry):
    line = hintcache.dumps(KEY, entry)
    assert line[hintcache.KEY] == KEY
    assert hintcache.loads(line) == entry
    assert "\n" not in line


def test_groups_split_by_key_digits(monkeypatch):
    monkeypatch.setattr(hintcache, "MAX_FILE", 2000)
    lines = {f"{i:032x}"[::-1]: f'["{f"{i:032x}"[::-1]}","-","{"x" * 40}"]' for i in range(300)}
    files = hintcache._split(lines)
    assert len(files) > 1 and all(len(name) == len(next(iter(files))) for name in files)
    assert sorted(x for rows in files.values() for x in rows) == sorted(lines.values())
    for name, rows in files.items():
        assert all(r[hintcache.KEY].startswith(name) for r in rows)
        assert rows == sorted(rows)
        assert sum(len(r) + 1 for r in rows) <= 2000


def test_one_file_while_small():
    assert list(hintcache._split({KEY: f'["{KEY}","-","x"]'})) == ["all"]


def test_prune_keeps_only_used_entries(tmp_path):
    cache = hintcache.Cache(tmp_path)
    keys = [f"{i:032x}" for i in range(6)]
    for i, k in enumerate(keys):
        cache.add("a" if i < 3 else "b", k, Entry("-", reason=str(i)))
    cache.save()
    assert hintcache.Cache(tmp_path).lines.keys() == set(keys)
    assert cache.prune(set(keys[:2])) == 4
    assert hintcache.Cache(tmp_path).lines.keys() == set(keys[:2])
    assert not (tmp_path / "b").exists()
