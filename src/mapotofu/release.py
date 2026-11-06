"""The files of a release: dist/ packed into zip files by family and region, for people to take
only what they use.

    STEM-VERSION-VF.zip       the variable fonts of a family and region (upright and italic)
    STEM-VERSION-static.zip   its static weights
    COLLECTION-VERSION-OTC-VF.zip, COLLECTION-VERSION-OTC.zip, and the same for COLLECTIONExt:
                              the collections, variable and static (config.COLLECTION)

Each zip carries the license (OFL.txt at the top of the project); without it nothing is packed,
so that fonts never go out without their license.
"""

from __future__ import annotations

import zipfile
from pathlib import Path

from .config import COLLECTION, ROOT, VERSION

RELEASE = ROOT / "dist" / "release"
LICENSE_FILE = ROOT / "OFL.txt"
# Zip entries carry this time, not the files', so that the same fonts give the same zip.
ZIP_TIME = (2026, 1, 1, 0, 0, 0)


def _zip(path: Path, files: list[Path], license_text: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    part = path.with_name(path.name + ".part")
    with zipfile.ZipFile(part, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        for f in [*sorted(files)]:
            info = zipfile.ZipInfo(f.name, ZIP_TIME)
            info.compress_type = zipfile.ZIP_DEFLATED
            z.writestr(info, f.read_bytes(), compresslevel=9)
        info = zipfile.ZipInfo(LICENSE_FILE.name, ZIP_TIME)
        info.compress_type = zipfile.ZIP_DEFLATED
        z.writestr(info, license_text)
    part.replace(path)


def groups(version: str = VERSION) -> dict[str, list[Path]]:
    """Zip name -> the files of dist/ that go into it."""
    from .build import pools
    from .config import STATIC_WEIGHTS
    from .package import DIST, dist_path, stem

    out: dict[str, list[Path]] = {}
    for views in pools().values():
        for v in views:
            out.setdefault(f"{stem(v)}-{version}-VF.zip", []).append(dist_path(v, None))
            out.setdefault(f"{stem(v)}-{version}-static.zip", []).extend(dist_path(v, w) for w in STATIC_WEIGHTS)
    for otc in sorted((DIST / "otc").glob("*.otc")):
        family = f"{COLLECTION}Ext" if otc.name.startswith(f"{COLLECTION}Ext-") else COLLECTION
        kind = "OTC-VF" if otc.stem.endswith("-VF") else "OTC"
        out.setdefault(f"{family}-{version}-{kind}.zip", []).append(otc)
    return out


def release(version: str = VERSION) -> list[Path]:
    """Pack dist/ into RELEASE; every font of every pool must be there."""
    if not LICENSE_FILE.exists():
        raise SystemExit(f"{LICENSE_FILE.name} is missing: the fonts may not go out without their license")
    license_text = LICENSE_FILE.read_bytes()
    table = groups(version)
    missing = [str(f) for files in table.values() for f in files if not f.exists()]
    if missing:
        raise SystemExit("not built: " + ", ".join(missing[:10]) + (" ..." if len(missing) > 10 else ""))
    if not any(name.startswith(f"{COLLECTION}-") and "OTC" in name for name in table):
        raise SystemExit("no collections in dist/otc")
    out = []
    for name, files in sorted(table.items()):
        _zip(RELEASE / name, files, license_text)
        out.append(RELEASE / name)
    return out
