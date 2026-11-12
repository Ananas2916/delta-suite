"""Corner-by-corner analysis between laps: where time is lost, braking, minimum speed, throttle."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np


def clean_lap(ch: dict, track_len: float) -> dict:
    """Drop lap-start samples still at the end of the track and make the distance monotonic."""
    d, t = ch["dist"], ch["t"]
    keep = ~((d > 0.5 * track_len) & (t < 5.0)) & ~((d < 0.1 * track_len) & (t > 20.0))
    out = {k: v[keep] for k, v in ch.items()}
    if len(out["dist"]) == 0:
        return out
    out["dist"] = np.maximum.accumulate(out["dist"])
    d0, t0 = out["dist"][0], out["t"][0]
    if d0 > 0:   # synthetic point on the start line, otherwise the Delta-T starts with a step
        out = {k: np.concatenate([v[:1], v]) for k, v in out.items()}
        out["dist"][0] = 0.0
        out["t"][0] = max(0.0, t0 - d0 / max(out["speed"][1] / 3.6, 1.0))
    return out


def resample(ch: dict, grid: np.ndarray) -> dict:
    d = ch["dist"]
    _, idx = np.unique(d, return_index=True)
    return {k: np.interp(grid, d[idx], v[idx]) for k, v in ch.items() if k != "dist"}


@dataclass
class Corner:
    number: int
    apex_m: float
    start_m: float
    end_m: float


def find_corners(speed: np.ndarray, grid: np.ndarray, min_drop_kmh: float = 12.0,
                 min_gap_m: float = 120.0) -> list[Corner]:
    """Corners = local speed minima with braking/acceleration of at least `min_drop_kmh` around them."""
    step = float(grid[1] - grid[0])
    k = max(1, int(25.0 / step))
    v = np.convolve(np.pad(speed, k, mode="edge"), np.ones(2 * k + 1) / (2 * k + 1), mode="valid")
    w = max(1, int(250.0 / step))
    apexes: list[int] = []
    for i in range(1, len(v) - 1):
        if not (v[i] <= v[i - 1] and v[i] < v[i + 1]):
            continue
        before = v[max(0, i - w):i]
        after = v[i + 1:i + 1 + w]
        if before.size and after.size and before.max() - v[i] >= min_drop_kmh and after.max() - v[i] >= min_drop_kmh:
            if apexes and (i - apexes[-1]) * step < min_gap_m:
                if v[i] < v[apexes[-1]]:
                    apexes[-1] = i
                continue
            apexes.append(i)
    corners = []
    for n, i in enumerate(apexes):
        prev_apex = grid[apexes[n - 1]] if n else 0.0
        next_apex = grid[apexes[n + 1]] if n + 1 < len(apexes) else grid[-1]
        start = max(grid[i] - 300.0, (prev_apex + grid[i]) / 2)
        end = min(grid[i] + 200.0, (grid[i] + next_apex) / 2)
        corners.append(Corner(n + 1, float(grid[i]), float(start), float(end)))
    return corners


def _first(mask: np.ndarray) -> int | None:
    idx = np.flatnonzero(mask)
    return int(idx[0]) if idx.size else None


def corner_stats(r: dict, grid: np.ndarray, c: Corner) -> dict:
    m = (grid >= c.start_m) & (grid <= c.end_m)
    g, t, v, brake, gas = grid[m], r["t"][m], r["speed"][m], r["brake"][m], r["gas"][m]
    apex_i = int(np.argmin(v))
    b = _first(brake[:apex_i + 1] > 0.15)
    th = _first(gas[apex_i:] > 0.9)
    return {
        "time_s": float(t[-1] - t[0]),
        "v_min_kmh": float(v[apex_i]),
        "v_entry_kmh": float(v[0]),
        "v_exit_kmh": float(v[-1]),
        "braking_at_m": None if b is None else float(g[b]),
        "brake_max": float(brake.max()),
        "full_throttle_at_m": None if th is None else float(g[apex_i + th]),
    }


def compare_laps(ref: dict, other: dict, track_len: float, step_m: float = 5.0) -> dict:
    """Corner-by-corner comparison of `other` against `ref` (channels from LapData/DB, cleaned or not)."""
    ref, other = clean_lap(ref, track_len), clean_lap(other, track_len)
    end = min(ref["dist"][-1], other["dist"][-1], track_len)
    grid = np.arange(0.0, end, step_m)
    r, o = resample(ref, grid), resample(other, grid)
    delta = o["t"] - r["t"]
    corners = find_corners(r["speed"], grid)
    out = []
    for c in corners:
        a, b = corner_stats(r, grid, c), corner_stats(o, grid, c)

        def diff(key):
            return None if a[key] is None or b[key] is None else round(b[key] - a[key], 3)

        out.append({
            "corner": c.number, "apex_m": round(c.apex_m), "from_m": round(c.start_m), "to_m": round(c.end_m),
            "time_lost_s": round(b["time_s"] - a["time_s"], 3),
            "v_min_kmh": [round(a["v_min_kmh"], 1), round(b["v_min_kmh"], 1)],
            "braking_at_m": [a["braking_at_m"], b["braking_at_m"]],
            "braking_earlier_m": None if diff("braking_at_m") is None else -diff("braking_at_m"),
            "full_throttle_at_m": [a["full_throttle_at_m"], b["full_throttle_at_m"]],
            "v_exit_kmh": [round(a["v_exit_kmh"], 1), round(b["v_exit_kmh"], 1)],
        })
    worst = sorted(out, key=lambda x: x["time_lost_s"], reverse=True)
    return {
        "final_delta_s": round(float(delta[-1]), 3),
        "corners": out,
        "where_you_lose_most": [w["corner"] for w in worst[:3] if w["time_lost_s"] > 0.02],
        "note": "paired values: [reference, compared lap]; time_lost_s > 0 = the compared lap is slower",
    }
