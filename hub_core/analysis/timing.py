"""
Live standings with gap and interval from the data of all cars (CSP app).

For each car a (time, progress) history is kept, where progress = completed laps + position
on the spline. B's gap to A is the time elapsed since A was where B is now:
like real timing loops, but with a loop at every point of the track.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass

import numpy as np

from hub_core.model import CarEntry
from hub_core.i18n import tr

HISTORY_S = 400.0      # enough for a lapping on long tracks


@dataclass
class StandingRow:
    pos: int
    index: int
    driver: str
    model: str
    laps: int
    last_ms: int
    best_ms: int
    gap_s: float | None         # to the leader (race) or to the best lap (practice/qualifying)
    interval_s: float | None    # to the car ahead
    laps_down: int
    in_pit: bool
    is_player: bool

    def as_dict(self) -> dict:
        return {"pos": self.pos, "driver": self.driver, "car": self.model, "laps": self.laps,
                "last_ms": self.last_ms, "best_ms": self.best_ms,
                "gap_s": None if self.gap_s is None else round(self.gap_s, 3),
                "interval_s": None if self.interval_s is None else round(self.interval_s, 3),
                "laps_down": self.laps_down, "in_pit": self.in_pit, "is_you": self.is_player}


def fmt_gap(r: StandingRow) -> str:
    """Gap as on TV: laps behind, otherwise seconds; the leader has none."""
    if r.laps_down >= 1:
        return "+" + (tr("1 lap") if r.laps_down == 1 else tr("{n} laps", n=r.laps_down))
    return "-" if not r.gap_s else f"+{r.gap_s:.1f}"


class TimingTower:
    def __init__(self):
        self._hist: dict[int, deque] = {}

    def reset(self):
        self._hist.clear()

    def update(self, now: float, cars: list[CarEntry]) -> None:
        for c in cars:
            if not c.connected:
                continue
            h = self._hist.setdefault(c.index, deque())
            p = c.progress
            if h and p < h[-1][1]:
                if h[-1][1] - p > 0.5:
                    h.clear()           # session restarted or car sent back to the pits
                else:
                    continue            # spline jump at the line before the lap count: wait
            h.append((now, p))
            while h and now - h[0][0] > HISTORY_S:
                h.popleft()

    def time_at(self, index: int, progress: float) -> float | None:
        """When car `index` was at the given progress (None if outside the history)."""
        h = self._hist.get(index)
        if not h or len(h) < 2 or progress < h[0][1] or progress > h[-1][1]:
            return None
        t = np.fromiter((a for a, _ in h), float, len(h))
        p = np.fromiter((b for _, b in h), float, len(h))
        return float(np.interp(progress, p, t))

    def gap(self, now: float, ahead: CarEntry, behind: CarEntry) -> float | None:
        t = self.time_at(ahead.index, behind.progress)
        return None if t is None else max(0.0, now - t)

    def standings(self, now: float, cars: list[CarEntry], race: bool, player_index: int = 0) -> list[StandingRow]:
        live = [c for c in cars if c.connected]
        if race:
            order = sorted(live, key=lambda c: (c.race_pos if c.race_pos > 0 else 999, -c.progress))
        else:
            order = sorted(live, key=lambda c: (c.best_lap_ms if c.best_lap_ms > 0 else 1 << 30, -c.progress))
        rows: list[StandingRow] = []
        leader = order[0] if order else None
        for i, c in enumerate(order):
            gap = interval = None
            laps_down = 0
            if race and leader is not None and c is not leader:
                laps_down = int(leader.progress - c.progress)
                gap = self.gap(now, leader, c) if laps_down < 1 else None
                interval = self.gap(now, order[i - 1], c)
            elif not race and leader is not None and c is not leader and c.best_lap_ms > 0 and leader.best_lap_ms > 0:
                gap = (c.best_lap_ms - leader.best_lap_ms) / 1000.0
                prev = order[i - 1] if i else None
                interval = (c.best_lap_ms - prev.best_lap_ms) / 1000.0 if prev is not None and prev.best_lap_ms > 0 else None
            rows.append(StandingRow(i + 1, c.index, c.driver, c.model, c.lap_count, c.last_lap_ms, c.best_lap_ms,
                                    gap, interval, laps_down, c.in_pitlane, c.index == player_index))
        return rows


def neighbours(rows: list[StandingRow]) -> tuple[StandingRow | None, StandingRow | None, StandingRow | None]:
    """(car ahead, you, car behind) in the standings."""
    for i, r in enumerate(rows):
        if r.is_player:
            return (rows[i - 1] if i else None, r, rows[i + 1] if i + 1 < len(rows) else None)
    return None, None, None
