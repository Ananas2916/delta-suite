"""AC setup files: Documents\\Assetto Corsa\\setups\\<car>\\<track>\\*.ini."""

from __future__ import annotations

import configparser
import ctypes
from ctypes import wintypes
from pathlib import Path


def documents_dir() -> Path:
    """The real Documents folder (often redirected to OneDrive), as AC uses it."""
    if hasattr(ctypes, "windll"):
        buf = ctypes.create_unicode_buffer(wintypes.MAX_PATH)
        if ctypes.windll.shell32.SHGetFolderPathW(None, 5, None, 0, buf) == 0:   # CSIDL_PERSONAL
            return Path(buf.value)
    return Path.home() / "Documents"


def setups_dir(car_id: str | None = None) -> Path:
    base = documents_dir() / "Assetto Corsa" / "setups"
    return base / car_id if car_id else base


def read_setup(path: str | Path) -> dict[str, int]:
    """{SECTION: VALUE} for the numeric entries of the file."""
    cp = configparser.ConfigParser(strict=False, interpolation=None)
    cp.optionxform = str
    cp.read(path, encoding="utf-8")
    out = {}
    for sec in cp.sections():
        v = cp[sec].get("VALUE")
        if v is None:
            continue
        try:
            out[sec] = int(float(v))
        except ValueError:
            pass
    return out


def latest_setup(car_id: str) -> Path | None:
    """Most recently saved setup for the car (AC writes 'last.ini' every time you leave the pits)."""
    d = setups_dir(car_id)
    files = list(d.rglob("*.ini")) if d.is_dir() else []
    return max(files, key=lambda f: f.stat().st_mtime) if files else None


def write_setup(path: str | Path, base: str | Path | None, changes: dict[str, int], car_id: str) -> Path:
    """Write a setup: a copy of `base` with the entries in `changes` modified (AC INI format)."""
    cp = configparser.ConfigParser(strict=False, interpolation=None)
    cp.optionxform = str
    if base:
        cp.read(base, encoding="utf-8")
    for sec, val in changes.items():
        if not cp.has_section(sec):
            cp.add_section(sec)
        cp[sec]["VALUE"] = str(int(val))
    if not cp.has_section("CAR"):
        cp.add_section("CAR")
    cp["CAR"]["MODEL"] = car_id
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        for sec in cp.sections():
            f.write(f"[{sec}]\n")
            for k, v in cp[sec].items():
                f.write(f"{k}={v}\n")
            f.write("\n")
    return path
