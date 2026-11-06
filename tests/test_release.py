"""The zip files of a release (mapotofu.release)."""

from __future__ import annotations

import zipfile

import pytest

from mapotofu import release
from mapotofu.package import DIST


def test_every_font_goes_into_exactly_one_zip():
    table = release.groups("9.9.9")
    files = [f for fs in table.values() for f in fs]
    assert len(files) == len(set(files))
    built = [p for p in (DIST / "variable").glob("*.otf")] + [p for p in (DIST / "static").glob("*.otf")]
    built += list((DIST / "otc").glob("*.otc"))
    assert set(built) <= set(files)
    assert all("9.9.9" in name and name.endswith(".zip") for name in table)


def test_nothing_is_packed_without_the_license(monkeypatch, tmp_path):
    monkeypatch.setattr(release, "LICENSE_FILE", tmp_path / "OFL.txt")
    with pytest.raises(SystemExit, match="license"):
        release.release()


def test_zips_carry_the_license_and_the_same_bytes(tmp_path):
    files = []
    for name, data in (("B.otf", b"font b" * 100), ("A.otc", b"collection a")):
        files.append(tmp_path / name)
        files[-1].write_bytes(data)
    a, b = tmp_path / "a.zip", tmp_path / "b.zip"
    release._zip(a, files, b"license")
    files[0].touch()  # another time: the zip stays the same
    release._zip(b, files[::-1], b"license")
    assert a.read_bytes() == b.read_bytes()
    with zipfile.ZipFile(a) as z:
        assert z.read("OFL.txt") == b"license"
        assert z.namelist() == ["A.otc", "B.otf", "OFL.txt"]
        assert all(z.read(f.name) == f.read_bytes() for f in files)
