"""Content keys (mapotofu.stamps) and the split between glyphs and metadata they rely on."""

from __future__ import annotations

import importlib
import re
from pathlib import Path

from mapotofu import config, stamps
from mapotofu.build import ASSEMBLE_MODULES


def test_assemble_code_reads_no_metadata_values():
    # build.fonts only finalizes the fonts again when values in config.META change, and does
    # nothing when values in config.PACKAGING do; that holds only while the code making glyphs
    # and layout does not read them.
    for name in ASSEMBLE_MODULES:
        source = Path(importlib.import_module(name).__file__).read_text()
        used = [m for m in config.META + config.PACKAGING if re.search(rf"\b{m}\b", source)]
        assert not used, (name, used)


def test_digest_is_stable_and_sensitive():
    a = stamps.digest({"b": 1, "a": [1, 2]}, b"x", "y")
    assert a == stamps.digest({"a": [1, 2], "b": 1}, b"x", "y")
    assert a != stamps.digest({"a": [1, 2], "b": 2}, b"x", "y")
    assert stamps.digest(b"ab", b"c") != stamps.digest(b"a", b"bc")


def test_stamps_forget_missing_files(tmp_path):
    out = tmp_path / "out.bin"
    out.write_bytes(b"1")
    store = stamps.Stamps(tmp_path / "stamps.json")
    store._name = lambda p: p.name  # outside the checkout
    store.put(out, key="k", hint="h")
    assert store.fresh(out, "k") and store.fresh(out, "h", "hint")
    out.unlink()
    assert not store.fresh(out, "k")
