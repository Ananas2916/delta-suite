"""
Mappa della pista per il GPS della pagina Onboard.

AC ha per ogni tracciato (o layout) un `map.png` con il disegno della pista e `data/map.ini` con scala
e spostamento: il punto (x, z) del mondo cade nel pixel ((x + X_OFFSET) / SCALE_FACTOR,
(z + Z_OFFSET) / SCALE_FACTOR). Se la mappa non c'è (demo, replay di un tracciato non installato) la
pagina disegna la pista dal percorso fatto dall'auto.
"""

from __future__ import annotations

import configparser
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class TrackMap:
    image: Path
    width: float
    height: float
    scale: float
    x_offset: float
    z_offset: float

    def to_map(self, x: float, z: float) -> tuple[float, float]:
        """Pixel della mappa per un punto (x, z) del mondo di AC."""
        return (x + self.x_offset) / self.scale, (z + self.z_offset) / self.scale


def parse_map_ini(text: str) -> dict[str, float]:
    cp = configparser.ConfigParser(strict=False, inline_comment_prefixes=(";", "#"))
    cp.read_string(text)
    if not cp.has_section("PARAMETERS"):
        return {}
    out = {}
    for key, value in cp.items("PARAMETERS"):
        try:
            out[key.upper()] = float(value)
        except ValueError:
            pass
    return out


def map_dirs(ac_root: Path, track_id: str, config: str = "") -> list[Path]:
    """Dove cercare map.png: prima la cartella del layout, poi quella del tracciato."""
    base = ac_root / "content" / "tracks" / track_id
    return ([base / config] if config else []) + [base]


def find_track_map(ac_root: Path | None, track_id: str, config: str = "") -> TrackMap | None:
    if ac_root is None or not track_id:
        return None
    for folder in map_dirs(ac_root, track_id, config):
        png, ini = folder / "map.png", folder / "data" / "map.ini"
        if not (png.is_file() and ini.is_file()):
            continue
        p = parse_map_ini(ini.read_text(encoding="utf-8", errors="replace"))
        if p.get("SCALE_FACTOR", 0) <= 0:
            continue
        return TrackMap(png, p.get("WIDTH", 0.0), p.get("HEIGHT", 0.0), p["SCALE_FACTOR"],
                        p.get("X_OFFSET", 0.0), p.get("Z_OFFSET", 0.0))
    return None
