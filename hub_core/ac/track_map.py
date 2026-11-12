"""
Track line for the GPS: the AI line of the AC track (`ai/fast_lane.ai`, and `pit_lane.ai` for the pit
lane).

It is the same spline AC uses to compute each car's position on the lap (normalizedCarPosition, splinePosition
of the CSP app): the distance along the line divided by its length. So every car is placed on the map from its
lap position, even without coordinates, and track segments (yellows, stopped cars) are coloured by
position. The (x, z) coordinates are AC world coordinates, like carCoordinates.

fast_lane.ai format: 4 int32 (version, number of points, lap time, samples), then for each point
x, y, z, length (float32) and id (int32); other data follows that is not needed here.
"""

from __future__ import annotations

import math
import struct
from pathlib import Path

POINT = struct.Struct("<4fi")
HEADER = struct.Struct("<4i")
MAX_POINTS = 200_000
MAX_COORD = 50_000.0        # m: beyond this it is not a track (unexpected file)
MAX_STEP = 100.0            # m between two consecutive points (usually ~1 m)


def read_ai_line(path: Path, closed: bool = True) -> list[tuple[float, float]]:
    """(x, z) points of the AI line, in lap order (the first is on the finish line). [] if the file is unusable.
    `closed=False` for the pit lane, which is not a loop."""
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
    """Points close together (and a closed lap): otherwise the line learned while driving beats a wrong map."""
    steps = [math.dist(a, b) for a, b in zip(pts, pts[1:] + (pts[:1] if closed else []))]
    return max(steps) <= MAX_STEP and sum(steps) >= 100.0


def ai_dirs(ac_root: Path, track_id: str, config: str = "") -> list[Path]:
    """Where to look for the ai folder: first the layout's, then the track's."""
    base = ac_root / "content" / "tracks" / track_id
    return ([base / config / "ai"] if config else []) + [base / "ai"]


def find_ai_lines(ac_root: Path | None, track_id: str, config: str = "") \
        -> tuple[list[tuple[float, float]], list[tuple[float, float]]]:
    """(lap line, pit lane) of the track; empty lists if missing (track not installed, demo)."""
    if ac_root is None or not track_id:
        return [], []
    for folder in ai_dirs(ac_root, track_id, config):
        lap = read_ai_line(folder / "fast_lane.ai")
        if lap:
            return lap, read_ai_line(folder / "pit_lane.ai", closed=False)
    return [], []
