"""Hints per glyph, kept with the font's sources in HINTS, so that each glyph is hinted once.

An entry is keyed by everything otfautohint's result for the glyph depends on: its outline in
every master (the charstring with each segment a command of its own, so that the encoding does
not matter), the variation regions those masters sit at, the hinting values of its Private DICT
(the zones and stems mapotofu.hint sets) and the hinter (afdko's version, mapotofu.hint's patches
and HINTER_REVISION). A glyph whose key is found takes its hints from the entry; the others are
hinted and added.

An entry holds only the hints, as they are put into the glyph's own charstring. Each is a line
of JSON:

    ["KEY", "h", HEAD, MASKS]   the stem hints and initial masks (HEAD: commands, each an
                                operator and its arguments), and the masks otfautohint put
                                before segments of the outline (MASKS: [segment, operator, mask])
    ["KEY", "r", PROGRAM]       the whole hinted charstring, where otfautohint changed the
                                outline (it joins collinear lines, for one)
    ["KEY", "-", "REASON"]      left unhinted, and why

A varying argument is written as its default value followed by its deltas, a mask as a string
of hex starting with "#".

Entries are kept by the source their glyph comes from (one directory per group of
config.HINT_GROUPS, so that updating a source changes only its own files) and, within it, by
the first hex digits of their keys: an entry's file depends on its key alone, so that adding
entries never moves others. A group starts as one file, all.jsonl; when a file would pass
MAX_FILE bytes, the group is split once more by one more hex digit (0.jsonl to f.jsonl, then
00.jsonl to ff.jsonl). Lines are sorted by key, so that a change shows as the lines of the
glyphs it touches. Entries are facts about their keys and are never changed in place; those no
font uses any more stay until pruned.

Reading leaves the work to C: the files are split into lines, a line is found by the key at its
start, and only the lines of the glyphs being built are parsed (json).
"""

from __future__ import annotations

import fcntl
import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

from fontTools.cffLib.specializer import (
    commandsToProgram,
    generalizeCommands,
    programToCommands,
    specializeCommands,
)

from . import stamps
from .config import ROOT

HINTS = ROOT / "hints"
# Bump when mapotofu.hint changes how glyphs are hinted in a way PATCHES and afdko's version do
# not show (the guard, the timeout, the emptying of other glyphs): all glyphs are then hinted
# again.
HINTER_REVISION = 1

STEMS = {"hstem", "hstemhm", "vstem", "vstemhm"}
MASKS = {"hintmask", "cntrmask"}
PRIVATE = (
    "BlueValues", "OtherBlues", "FamilyBlues", "FamilyOtherBlues", "BlueScale", "BlueShift",
    "BlueFuzz", "StdHW", "StdVW", "StemSnapH", "StemSnapV", "LanguageGroup",
)
TOLERANCE = 0.05  # otfautohint merges the masters again in 16.16 fixed point
MAXSTACK = 513  # CFF2
MAX_FILE = 8 << 20  # far below GitHub's warning (50 MB), and diffs still shown on its pages


def hinter() -> str:
    from importlib.metadata import version

    from . import hint

    return stamps.digest(version("afdko"), hint.PATCHES, hint.GLYPH_SECONDS, HINTER_REVISION)


# Charstrings as commands.


def _vsindex(cs) -> int:
    return getattr(cs.private, "vsindex", 0) or 0


def commands(cs) -> list[tuple[str, list]]:
    """The charstring with each segment a command of its own, blends written out."""
    cs.decompile()
    return generalizeCommands(programToCommands(cs.program, cs.private.getNumRegions, _vsindex(cs)))


def split(cmds: list) -> tuple[list, list, list, list]:
    """(vsindex commands, stem hints and initial masks, later masks as (position in the
    outline, operator, mask), outline)."""
    vs, head, masks, path = [], [], [], []
    i = 0
    while i < len(cmds):
        op, args = cmds[i]
        if op == "vsindex":
            vs.append((op, args))
        elif op in STEMS or (op == "" and not path and i + 1 < len(cmds) and cmds[i + 1][0] in MASKS):
            head.append((op, args))
        elif op in MASKS:
            mask = cmds[i + 1][1][0]
            if path:
                masks.append((len(path), op, mask))
            else:
                head += [(op, []), ("", [mask])]
            i += 1
        else:
            path.append((op, args))
        i += 1
    return vs, head, masks, path


def canonical(head: list) -> list:
    """Stem hints written one way: the specializer may leave out a vstemhm operator before the
    first mask, or write hstem for hstemhm."""
    out = []
    for i, (op, args) in enumerate(head):
        if op == "" and args and not isinstance(args[0], bytes) and i + 1 < len(head) and head[i + 1][0] in MASKS:
            op = "vstemhm"
        out.append(({"hstem": "hstemhm", "vstem": "vstemhm"}.get(op, op), args))
    return out


def _add(a, b):
    if isinstance(a, list) or isinstance(b, list):
        n = len(a) if isinstance(a, list) else len(b)
        a = a if isinstance(a, list) else [a] + [0] * (n - 2) + [1]
        b = b if isinstance(b, list) else [b] + [0] * (n - 2) + [1]
        return [x + y for x, y in zip(a[:-1], b[:-1])] + [1]
    return a + b


def normalize(path: list) -> tuple[list, list[int]]:
    """The outline as otfautohint writes it back: runs of movetos summed into one, a moveto
    ending the outline dropped; with the index in path of each command kept."""
    out, index = [], []
    for i, (op, args) in enumerate(path):
        if op == "rmoveto" and out and out[-1][0] == "rmoveto":
            out[-1] = ("rmoveto", [_add(a, b) for a, b in zip(out[-1][1], args)])
            continue
        out.append((op, args))
        index.append(i)
    if out and out[-1][0] == "rmoveto":
        out.pop()
        index.pop()
    return out, index


def _close(a, b) -> bool:
    if isinstance(a, list) or isinstance(b, list):
        if not (isinstance(a, list) and isinstance(b, list)) or len(a) != len(b):
            return False
        return all(abs(x - y) <= TOLERANCE for x, y in zip(a, b))
    return abs(a - b) <= TOLERANCE


def same(p: list, q: list) -> bool:
    return len(p) == len(q) and all(
        o1 == o2 and len(a1) == len(a2) and all(_close(x, y) for x, y in zip(a1, a2))
        for (o1, a1), (o2, a2) in zip(p, q)
    )


# Keys.


def _regions(font, vsindex: int) -> list:
    store = font["CFF2"].cff.topDictIndex[0].VarStore.otVarStore
    regions = store.VarRegionList.Region
    return [
        [(a.StartCoord, a.PeakCoord, a.EndCoord) for a in regions[r].VarRegionAxis]
        for r in store.VarData[vsindex].VarRegionIndex
    ]


def keys(font, order: list[str]) -> list[str]:
    """The key of each glyph of a CFF2 font whose zones and stems are set."""
    top = font["CFF2"].cff.topDictIndex[0]
    charstrings = top.CharStrings
    who = hinter()
    regions: dict[int, list] = {}
    privates: dict[int, list] = {}
    out = []
    for name in order:
        cs = charstrings[name]
        cmds = commands(cs)
        vs = next((args[0] for op, args in cmds if op == "vsindex"), _vsindex(cs))
        if vs not in regions:
            regions[vs] = _regions(font, vs)
        pid = id(cs.private)
        if pid not in privates:
            privates[pid] = [(k, cs.private.rawDict.get(k)) for k in PRIVATE]
        # repr and the hash run in C; the parts are lists of numbers and strings, whose repr
        # is exact and stable.
        data = repr((who, cmds, regions[vs], privates[pid])).encode()
        out.append(hashlib.blake2b(data, digest_size=16).hexdigest())
    return out


# Entries.


@dataclass(frozen=True)
class Entry:
    kind: str  # "h", "r" or "-"
    head: tuple = ()  # h: canonical commands; r: the whole charstring's tokens
    masks: tuple = ()  # h: (position, operator, mask)
    reason: str = ""  # -


def _out(a):
    if isinstance(a, list):  # default, deltas, and the 1 of a single blend
        return a[:-1]
    if isinstance(a, bytes):
        return "#" + a.hex()
    if isinstance(a, float) and a.is_integer():
        return int(a)
    return a


def _in(a):
    if isinstance(a, list):
        return a + [1]
    if isinstance(a, str) and a.startswith("#"):
        return bytes.fromhex(a[1:])
    return a


def dumps(key: str, entry: Entry) -> str:
    if entry.kind == "-":
        row = [key, "-", entry.reason]
    elif entry.kind == "r":
        row = [key, "r", [_out(t) for t in entry.head]]
    else:
        head = [[op, *map(_out, args)] for op, args in entry.head]
        row = [key, "h", head, [[p, op, m.hex()] for p, op, m in entry.masks]]
    return json.dumps(row, separators=(",", ":"), ensure_ascii=False)


def loads(line: str) -> Entry:
    row = json.loads(line)
    kind = row[1]
    if kind == "-":
        return Entry("-", reason=row[2])
    if kind == "r":
        return Entry("r", tuple(_in(t) for t in row[2]))
    head = tuple((c[0], [_in(a) for a in c[1:]]) for c in row[2])
    return Entry("h", head, tuple((p, op, bytes.fromhex(m)) for p, op, m in row[3]))


def apply(entry: Entry, cs) -> list:
    """The charstring program of the glyph with the entry's hints."""
    if entry.kind == "-":
        cs.decompile()
        return list(cs.program)
    if entry.kind == "r":
        return list(entry.head)
    vs, _, _, path = split(commands(cs))
    head = [(op, list(args)) for op, args in entry.head]
    at: dict[int, list] = {}
    for p, op, mask in entry.masks:
        at.setdefault(p, []).append((op, mask))
    out = list(vs) + head
    for i, c in enumerate([*path, None]):
        for op, mask in at.get(i, []):
            out += [(op, []), ("", [mask])]
        if c is not None:
            out.append(c)
    return commandsToProgram(specializeCommands(out, generalizeFirst=False, maxstack=MAXSTACK))


def _drawn(path: list) -> bool:
    return any(op != "rmoveto" for op, _ in path)


def extract(unhinted, hinted, reason: str | None = None) -> Entry:
    """The entry for a glyph, from its charstring before and after otfautohint."""
    _, _, _, pu = split(commands(unhinted))
    hcmds = commands(hinted)
    _, hh, mh, ph = split(hcmds)
    if not hh and not mh:
        if _drawn(pu):
            return Entry("-", reason=(reason or "otfautohint found no stems").replace("\n", " "))
        return Entry("h")
    raw = Entry("r", tuple(hinted.program))
    if pu == ph:
        masks = mh
    else:
        nu, index = normalize(pu)
        if not same(nu, ph):
            return raw
        masks = [(index[p] if p < len(index) else len(pu), op, m) for p, op, m in mh]
    entry = Entry("h", tuple(canonical(hh)), tuple(masks))
    # The entry must give back what otfautohint wrote, up to the outline's own encoding.
    probe = type(hinted)(program=apply(entry, unhinted), private=hinted.private, globalSubrs=hinted.globalSubrs)
    _, h2, m2, p2 = split(commands(probe))
    if canonical(h2) != canonical(hh) or m2 != list(masks) or p2 != pu:
        return raw
    return entry


# The store.

KEY = slice(2, 34)  # where a line's key is: ["<32 hex digits>",...


def _files(group: Path) -> list[Path]:
    return sorted(group.glob("*.jsonl"))


def _split(group_lines: dict[str, str]) -> dict[str, list[str]]:
    """The files of a group and their lines: as few hex digits of the key as keep each file
    within MAX_FILE."""
    digits = 0
    while True:
        files: dict[str, list[str]] = {}
        for key in sorted(group_lines):
            files.setdefault(key[:digits] or "all", []).append(group_lines[key])
        if digits == 4 or all(sum(len(x) + 1 for x in lines) <= MAX_FILE for lines in files.values()):
            return files
        digits += 1


class Cache:
    """The entries in HINTS. Processes hinting at once add to it under a lock."""

    def __init__(self, directory: Path = HINTS):
        self.dir = directory
        self.lines: dict[str, str] = {}
        self.new: dict[str, dict[str, str]] = {}  # group -> key -> line
        for f in sorted(directory.glob("*/*.jsonl")):
            for line in f.read_text().splitlines():
                self.lines[line[KEY]] = line

    def get(self, key: str) -> Entry | None:
        line = self.lines.get(key)
        return loads(line) if line is not None else None

    def add(self, group: str, key: str, entry: Entry) -> None:
        line = dumps(key, entry)
        self.new.setdefault(group, {})[key] = line
        self.lines[key] = line

    def save(self) -> None:
        if not self.new:
            return
        self.dir.mkdir(parents=True, exist_ok=True)
        with (self.dir / ".lock").open("w") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            for group, added in self.new.items():
                folder = self.dir / group
                folder.mkdir(exist_ok=True)
                old = _files(folder)
                lines: dict[str, str] = {}
                for f in old:  # as they are now: other processes may have added to them
                    for line in f.read_text().splitlines():
                        lines[line[KEY]] = line
                lines.update(added)
                written = set()
                for name, rows in _split(lines).items():
                    path = folder / f"{name}.jsonl"
                    part = path.with_name(path.name + ".part")
                    part.write_text("\n".join(rows) + "\n", encoding="utf-8")
                    part.replace(path)
                    written.add(path)
                for f in old:
                    if f not in written:
                        f.unlink()
        self.new = {}

    def prune(self, used: set[str]) -> int:
        """Drop the entries whose keys are not in used; returns how many went."""
        dropped = 0
        with (self.dir / ".lock").open("w") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            for folder in sorted(p for p in self.dir.iterdir() if p.is_dir()):
                old = _files(folder)
                if not old:
                    continue
                lines = {}
                for f in old:
                    for line in f.read_text().splitlines():
                        if line[KEY] in used:
                            lines[line[KEY]] = line
                        else:
                            dropped += 1
                for f in old:
                    f.unlink()
                if lines:
                    for name, rows in _split(lines).items():
                        (folder / f"{name}.jsonl").write_text("\n".join(rows) + "\n", encoding="utf-8")
                else:
                    folder.rmdir()
        self.lines = {k: v for k, v in self.lines.items() if k in used}
        return dropped
