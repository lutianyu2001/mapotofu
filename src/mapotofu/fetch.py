"""Download the upstream fonts listed in the project's sources.toml and place them under sources/."""

from __future__ import annotations

import hashlib
import shutil
import sys
import tomllib
import urllib.request
import zipfile
from pathlib import Path

from .config import ROOT, SOURCES

CACHE = SOURCES / "_cache"


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _download(url: str, sha256: str) -> Path:
    CACHE.mkdir(parents=True, exist_ok=True)
    dest = CACHE / url.rsplit("/", 1)[1]
    if dest.exists() and _sha256(dest) == sha256:
        return dest
    print(f"downloading {url}", file=sys.stderr)
    tmp = dest.with_suffix(dest.suffix + ".part")
    with urllib.request.urlopen(url) as r, tmp.open("wb") as f:
        shutil.copyfileobj(r, f)
    got = _sha256(tmp)
    if got != sha256:
        tmp.unlink()
        raise SystemExit(f"checksum mismatch for {url}: {got}")
    tmp.rename(dest)
    return dest


def main() -> None:
    spec = tomllib.loads((ROOT / "sources.toml").read_text())
    SOURCES.mkdir(exist_ok=True)
    for entry in spec.get("archive", []):
        path = _download(entry["url"], entry["sha256"])
        with zipfile.ZipFile(path) as z:
            for member, name in entry["members"].items():
                out = SOURCES / name
                if not out.exists():
                    with z.open(member) as src, out.open("wb") as dst:
                        shutil.copyfileobj(src, dst)
    for entry in spec.get("file", []):
        path = _download(entry["url"], entry["sha256"])
        out = SOURCES / path.name
        if not out.exists():
            shutil.copyfile(path, out)


if __name__ == "__main__":
    main()
