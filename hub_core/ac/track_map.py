"""
Linea della pista per il GPS: la linea AI del tracciato di AC (`ai/fast_lane.ai`, e `pit_lane.ai` per la corsia
box).

È la stessa spline con cui AC calcola la posizione sul giro delle auto (normalizedCarPosition, splinePosition
dell'app CSP): la distanza lungo la linea divisa per la sua lunghezza. Quindi ogni auto si mette sulla mappa dalla
sua posizione sul giro, anche senza le coordinate, e i tratti della pista (gialle, auto ferme) si colorano per
posizione. Le coordinate (x, z) sono quelle del mondo di AC, come carCoordinates.

Formato di fast_lane.ai: 4 int32 (versione, numero di punti, tempo sul giro, campioni), poi per ogni punto
x, y, z, lunghezza (float32) e id (int32); dopo vengono altri dati che qui non servono.
"""

from __future__ import annotations

import math
import struct
from pathlib import Path

POINT = struct.Struct("<4fi")
HEADER = struct.Struct("<4i")
MAX_POINTS = 200_000
MAX_COORD = 50_000.0        # m: oltre non è una pista (file diverso da quello atteso)
MAX_STEP = 100.0            # m tra due punti consecutivi (di solito ~1 m)


def read_ai_line(path: Path, closed: bool = True) -> list[tuple[float, float]]:
    """Punti (x, z) della linea AI, nell'ordine del giro (il primo è sul traguardo). [] se il file non va.
    `closed=False` per la corsia box, che non è un anello."""
    try:
        data = path.read_bytes()
    except OSError:
        return []
    if len(data) < HEADER.size:
        return []
    _version, count, _lap_time, _samples = HEADER.unpack_from(data, 0)
    if not 10 <= count <= MAX_POINTS or len(data) < HEADER.size + count * POINT.size:
        return []
    pts = []
    for i in range(count):
        x, _y, z, _length, _id = POINT.unpack_from(data, HEADER.size + i * POINT.size)
        if not (math.isfinite(x) and math.isfinite(z) and abs(x) < MAX_COORD and abs(z) < MAX_COORD):
            return []
        pts.append((x, z))
    return pts if _looks_like_a_line(pts, closed) else []


def _looks_like_a_line(pts: list[tuple[float, float]], closed: bool) -> bool:
    """Punti vicini tra loro (e giro chiuso): se no, meglio la linea imparata girando che una mappa sbagliata."""
    steps = [math.dist(a, b) for a, b in zip(pts, pts[1:] + (pts[:1] if closed else []))]
    return max(steps) <= MAX_STEP and sum(steps) >= 100.0


def ai_dirs(ac_root: Path, track_id: str, config: str = "") -> list[Path]:
    """Dove cercare la cartella ai: prima quella del layout, poi quella del tracciato."""
    base = ac_root / "content" / "tracks" / track_id
    return ([base / config / "ai"] if config else []) + [base / "ai"]


def find_ai_lines(ac_root: Path | None, track_id: str, config: str = "") \
        -> tuple[list[tuple[float, float]], list[tuple[float, float]]]:
    """(linea del giro, corsia box) del tracciato; liste vuote se non ci sono (tracciato non installato, demo)."""
    if ac_root is None or not track_id:
        return [], []
    for folder in ai_dirs(ac_root, track_id, config):
        lap = read_ai_line(folder / "fast_lane.ai")
        if lap:
            return lap, read_ai_line(folder / "pit_lane.ai", closed=False)
    return [], []
