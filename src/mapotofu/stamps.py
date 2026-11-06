"""Content keys deciding which build work is to be redone.

A step's key digests what its output depends on: the code that makes it, the configuration it
reads, the versions of the libraries it runs and the content of its inputs. Each output file is
recorded in build/stamps.json with the key it was made with, and with the keys of the expensive
tables inside it (the hinted CFF2, a static CFF), so that a step whose key changed can still take
those tables from its previous output when their own keys did not.

Expensive steps digest only the functions and constants that decide their output (`sources`),
so that editing anything else, a comment included, does not throw away hours of hinting.
"""

from __future__ import annotations

import hashlib
import importlib
import importlib.metadata
import inspect
import json
from dataclasses import fields, is_dataclass
from pathlib import Path

from . import config
from .config import BUILD, ROOT

STAMPS = BUILD / "stamps.json"


def _update(h, value) -> None:
    if isinstance(value, bytes):
        h.update(b"b%d:" % len(value) + value)
    elif isinstance(value, str):
        data = value.encode()
        h.update(b"s%d:" % len(data) + data)
    elif isinstance(value, Path):
        _update(h, value.resolve().relative_to(ROOT).as_posix() if value.is_relative_to(ROOT) else str(value))
    elif isinstance(value, dict):
        h.update(b"d%d:" % len(value))
        for k in sorted(value, key=repr):
            _update(h, k)
            _update(h, value[k])
    elif isinstance(value, (list, tuple)):
        h.update(b"l%d:" % len(value))
        for v in value:
            _update(h, v)
    elif is_dataclass(value):
        _update(h, type(value).__name__)
        _update(h, {f.name: getattr(value, f.name) for f in fields(value)})
    else:
        _update(h, repr(value))


def digest(*parts) -> str:
    h = hashlib.sha256()
    _update(h, parts)
    return h.hexdigest()


def modules(*names: str) -> str:
    """The source of whole modules."""
    return digest(*(Path(importlib.import_module(n).__file__).read_bytes() for n in names))


def sources(*objects) -> str:
    """The source of single functions or classes, and the values of plain constants."""
    return digest(*(inspect.getsource(o) if callable(o) else o for o in objects))


def versions(*dists: str) -> str:
    return digest(*(f"{d}=={importlib.metadata.version(d)}" for d in dists))


def settings(exclude: tuple[str, ...] = ()) -> str:
    """The values in config, but for the paths of the project and those excluded."""
    skip = {"ROOT", "PROJECT_NAME", "PROJECT_FILE", "SOURCES", "DATA", "BUILD", *exclude}
    return digest({k: v for k, v in vars(config).items() if k.isupper() and k not in skip})


_files: dict[tuple[str, int, int], str] = {}


def file(path: Path) -> str:
    """Digest of a file's content, remembered while its size and mtime stay."""
    st = path.stat()
    memo = (str(path), st.st_size, st.st_mtime_ns)
    if memo not in _files:
        h = hashlib.sha256()
        with path.open("rb") as f:
            while chunk := f.read(1 << 22):
                h.update(chunk)
        _files[memo] = h.hexdigest()
    return _files[memo]


class Stamps:
    """build/stamps.json: per output file (relative to the project), the keys it was made with.
    Only the main process reads and writes it."""

    def __init__(self, path: Path = STAMPS):
        self.path = path
        self.data: dict[str, dict[str, str]] = json.loads(path.read_text()) if path.exists() else {}

    @staticmethod
    def _name(path: Path) -> str:
        return path.resolve().relative_to(ROOT).as_posix()

    def get(self, path: Path, part: str = "key") -> str | None:
        """The recorded key, if the file still exists."""
        if not path.exists():
            return None
        return self.data.get(self._name(path), {}).get(part)

    def fresh(self, path: Path, key: str, part: str = "key") -> bool:
        return self.get(path, part) == key

    def put(self, path: Path, **keys: str) -> None:
        self.data[self._name(path)] = keys
        self.save()

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        part = self.path.with_name(self.path.name + ".part")
        part.write_text(json.dumps(self.data, indent=1, sort_keys=True) + "\n")
        part.replace(self.path)


def save(font, path: Path) -> None:
    """Save through a temporary file, so that an interrupted run leaves no partial file that
    would pass for done, and without a new modification time, so that the same content gives
    the same bytes (meta.finalize sets the dates)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    part = path.with_name(path.name + ".part")
    font.recalcTimestamp = False
    font.save(part)
    part.replace(path)
