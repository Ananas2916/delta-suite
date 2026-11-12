"""
Current lap: sector splits as they close and live delta against the reference lap (the
session's best valid lap), like broadcast timing.

Sector colours as on TV, but with the driver's own times only (AC does not give opponents' sectors): "best" if
it is a personal best (purple), "slower" if slower (yellow), "current" for the one in progress.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from hub_core.model import ACStatus

LAST_LAP_SHOW_MS = 6000      # at lap start the sectors of the lap just closed are still shown


@dataclass(frozen=True)
class SectorView:
    label: str               # "S1", "S2", ...
    ms: int | None           # sector time; for the current one, the time elapsing
    state: str               # "best", "slower", "current", "empty"
    delta_ms: int | None     # against the personal best (None if there is none)


class LiveLap:
    """Splits and delta of the current lap, from TelemetrySample (60 Hz)."""

    def __init__(self, sectors: int = 3):
        self.count = max(1, sectors)
        self._ref_dist: np.ndarray | None = None
        self._ref_t: np.ndarray | None = None
        self.reset()

    def reset(self, sectors: int | None = None) -> None:
        if sectors:
            self.count = max(1, sectors)
        self.current: list[int | None] = [None] * self.count
        self.sector = 0
        self.sector_start_ms = 0
        self._lap: int | None = None
        self.delta_s: float | None = None
        self._ref_dist = self._ref_t = None

    def set_reference(self, lap) -> None:
        """Reference lap for the delta: a LapData with "t" and "dist" channels (usually the best)."""
        ch = getattr(lap, "channels", None) or {}
        d, t = ch.get("dist"), ch.get("t")
        if d is None or t is None or len(d) < 10:
            self._ref_dist = self._ref_t = None
            return
        self._ref_dist, self._ref_t = np.maximum.accumulate(np.asarray(d, float)), np.asarray(t, float)

    def feed(self, s, track_length: float) -> None:
        if s.status != ACStatus.LIVE:
            return
        if self._lap is None or s.completed_laps != self._lap:
            self.current = [None] * self.count       # new lap (or session restarted): splits from scratch
            self._lap, self.sector, self.sector_start_ms = s.completed_laps, s.sector_index, 0
        elif s.sector_index != self.sector:
            prev = self.sector
            if 0 <= prev < self.count and s.sector_index > prev and s.last_sector_ms > 0:
                self.current[prev] = s.last_sector_ms
                self.sector_start_ms = sum(v for v in self.current[:prev + 1] if v)
            self.sector = s.sector_index
        self.delta_s = self._delta(s, track_length)

    def _delta(self, s, track_length: float) -> float | None:
        if self._ref_dist is None or track_length <= 0 or s.lap_time_ms < 1500:
            return None
        if s.lap_time_ms < 5000 and s.lap_position > 0.5:
            return None                      # spline not yet back to zero after the line
        dist = s.lap_position * track_length
        if not self._ref_dist[0] <= dist <= self._ref_dist[-1]:
            return None
        return s.lap_time_ms / 1000.0 - float(np.interp(dist, self._ref_dist, self._ref_t))

    def views(self, s, last_lap_sectors: list[int] | None, best: list[int | None]) -> list[SectorView]:
        """S1..Sn boxes to show: at lap start those of the lap just closed, then those of the current lap."""
        labels = [f"S{i + 1}" for i in range(self.count)]
        if s is not None and s.lap_time_ms < LAST_LAP_SHOW_MS and self.sector == 0 and last_lap_sectors:
            return [_view(labels[i], last_lap_sectors[i] if i < len(last_lap_sectors) else None, best, i)
                    for i in range(self.count)]
        out = []
        for i in range(self.count):
            if self.current[i] is not None:
                out.append(_view(labels[i], self.current[i], best, i))
            elif s is not None and i == self.sector:
                out.append(SectorView(labels[i], max(0, s.lap_time_ms - self.sector_start_ms), "current", None))
            else:
                out.append(SectorView(labels[i], None, "empty", None))
        return out


def _view(label: str, ms: int | None, best: list[int | None], i: int) -> SectorView:
    if ms is None:
        return SectorView(label, None, "empty", None)
    ref = best[i] if i < len(best) else None
    if ref is None:
        return SectorView(label, ms, "best", None)
    return SectorView(label, ms, "best" if ms <= ref else "slower", ms - ref)
