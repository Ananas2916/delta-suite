"""
Track status for the GPS and flags: track line by lap position, slow or stopped cars, and yellow,
red (stopped car, double yellow) and blue zones.

AC does not say where a yellow is shown, and its `flag` sometimes stays yellow after the incident is over: the
zones are derived here from the speeds of the cars (CSP app), compared with the typical speed at that point of
the track, learned during the session.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

from hub_core.model import ACFlag

BINS = 500                       # line points and typical-speed cells, at a constant step along the lap
STOPPED_KMH = 8.0
SLOW_KMH = 30.0                  # slow anyway, even where the typical speed is not known yet
SLOW_FRACTION = 0.4              # slow if below 40% of the typical speed at that point
TYPICAL_MIN_KMH = 60.0           # typical speed considered known from here up
TYPICAL_DECAY = 0.9995           # the learned maximum decays slowly (worn tyres, rain...)
CROWD_FRACTION = 0.4             # beyond this share of slow cars it is a start or a neutralisation
ZONE_BEFORE, ZONE_AFTER = 0.025, 0.006      # coloured stretch around the car, as a fraction of the lap
ZONE_HOLD_S = 3.0                # the zone stays a little after the car moves off: no flicker
BLUE_BEHIND = 0.02
WARN_AHEAD_M = 800.0             # yellow for the driver if the zone is within this distance ahead
AC_FLAG_FRESH_S = 8.0            # AC yellow with no slow cars confirming it: valid only for a few seconds
GREEN_S = 5.0                    # after a yellow: green flag for a few seconds, as on TV

ZONE_COLORS = ("yellow", "red", "blue")


@dataclass(frozen=True)
class Zone:
    start: float        # lap position (may leave 0..1: wraps at the finish line)
    end: float
    kind: str           # "yellow", "red" or "blue"
    car: int = -1       # car that caused it

    def contains(self, pos: float) -> bool:
        return (pos - self.start) % 1.0 <= (self.end - self.start)


@dataclass(frozen=True)
class FlagStatus:
    kind: str           # "yellow", "red", "blue", "checkered", "black", "white", "penalty"
    text: str


class TrackLine:
    """Track points at a constant step along the lap: point i is at position i / n."""

    def __init__(self, xs: np.ndarray, zs: np.ndarray):
        self.xs, self.zs = np.asarray(xs, float), np.asarray(zs, float)
        seg = np.hypot(np.diff(np.append(self.xs, self.xs[0])), np.diff(np.append(self.zs, self.zs[0])))
        self.length = float(seg.sum())

    @classmethod
    def from_points(cls, pts: list[tuple[float, float]], n: int = BINS) -> TrackLine | None:
        """AI line (dense points in lap order) resampled at a constant step over distance travelled."""
        if len(pts) < 10:
            return None
        a = np.asarray(pts, float)
        closed = np.vstack([a, a[:1]])
        dist = np.concatenate([[0.0], np.cumsum(np.hypot(*np.diff(closed, axis=0).T))])
        if dist[-1] <= 0:
            return None
        t = np.linspace(0.0, dist[-1], n, endpoint=False)
        return cls(np.interp(t, dist, closed[:, 0]), np.interp(t, dist, closed[:, 1]))

    @property
    def n(self) -> int:
        return len(self.xs)

    def point(self, pos: float) -> tuple[float, float]:
        f = (pos % 1.0) * self.n
        i = int(f) % self.n
        j = (i + 1) % self.n
        k = f - int(f)
        return (self.xs[i] + (self.xs[j] - self.xs[i]) * k, self.zs[i] + (self.zs[j] - self.zs[i]) * k)

    def points(self, start: float, end: float, step: float | None = None) -> list[tuple[float, float]]:
        """Points of the stretch start → end (lap positions, end > start, also past the finish line)."""
        step = step or 1.0 / self.n
        count = max(2, int(math.ceil((end - start) / step)) + 1)
        return [self.point(start + (end - start) * i / (count - 1)) for i in range(count)]


class LineLearner:
    """Line learned from the car positions when the track AI line is missing (demo, track
    not installed): average (x, z) per lap-position cell."""

    def __init__(self, n: int = BINS):
        self.sx, self.sz, self.cnt = np.zeros(n), np.zeros(n), np.zeros(n)

    def add(self, pos: float, x: float, z: float) -> None:
        if not 0.0 <= pos <= 1.0:
            return
        b = int(pos * len(self.cnt)) % len(self.cnt)
        self.sx[b] += x
        self.sz[b] += z
        self.cnt[b] += 1

    @property
    def coverage(self) -> float:
        return float((self.cnt > 0).mean())

    def max_gap(self) -> int:
        """Longest run of empty cells (including across the finish line)."""
        known = np.flatnonzero(self.cnt > 0)
        if known.size == 0:
            return len(self.cnt)
        return int(np.diff(np.append(known, known[0] + len(self.cnt))).max()) - 1

    def line(self, max_gap: int = 8) -> TrackLine | None:
        """The line once the lap is covered except for short holes (sparse samples: sped-up demo, stutters)."""
        if self.max_gap() > max_gap:
            return None
        n = len(self.cnt)
        known = np.flatnonzero(self.cnt > 0)
        xs, zs = self.sx[known] / self.cnt[known], self.sz[known] / self.cnt[known]
        # empty cells: interpolate between neighbours, also across the finish line
        idx = np.arange(n)
        ext = np.concatenate([known - n, known, known + n])
        return TrackLine(np.interp(idx, ext, np.tile(xs, 3)), np.interp(idx, ext, np.tile(zs, 3)))


class TrackWatch:
    """Track line, typical speeds and incident zones for a session."""

    def __init__(self, ai_line: list[tuple[float, float]] | None = None,
                 pit_line: list[tuple[float, float]] | None = None, track_length: float = 0.0):
        self.ai = TrackLine.from_points(ai_line or [])
        self.pit = list(pit_line or [])
        self.learner = LineLearner()
        self._learned: TrackLine | None = None
        self._learn_count = 0
        self.typical = np.zeros(BINS)
        self.track_length = track_length or (self.ai.length if self.ai else 0.0)
        self.zones: list[Zone] = []
        self._slow_since: dict[int, tuple[float, str, float]] = {}   # car → (last time slow, kind, pos)
        self._ac_flag, self._ac_flag_t = ACFlag.NONE, -1e9
        self._warned_t = -1e9            # last time the driver had a yellow

    @property
    def line(self) -> TrackLine | None:
        return self.ai or self._learned

    # ------------------------------------------------------------- input data
    def feed_position(self, pos: float, x: float, z: float) -> None:
        """A car's position (lap pos and coordinates): only used to learn the line without an AI line."""
        if self.ai is not None:
            return
        self.learner.add(pos, x, z)
        self._learn_count += 1
        if self._learn_count % 200 == 0:        # recompute now and then: it is cheap but not needed every sample
            self._learned = self.learner.line() or self._learned

    def update_cars(self, cars, now: float, race_laps: int = 0, live: bool = True) -> None:
        """Typical speeds and zones from the cars on track (CSP app `CarEntry`, ~10 times per second)."""
        on_track = [c for c in cars if c.connected and not c.in_pitlane and not c.in_pit and 0.0 <= c.spline <= 1.0
                    and not (race_laps and c.lap_count >= race_laps)]
        slow_now = []
        for c in on_track:
            b = int(c.spline * BINS) % BINS
            typ = self.typical[b]
            stopped = c.speed_kmh < STOPPED_KMH
            slow = stopped or c.speed_kmh < SLOW_KMH or (typ >= TYPICAL_MIN_KMH and c.speed_kmh < SLOW_FRACTION * typ)
            if slow:
                slow_now.append((c, "red" if stopped else "yellow"))
            else:
                for k in (b - 1, b, (b + 1) % BINS):
                    self.typical[k] = max(self.typical[k] * TYPICAL_DECAY, c.speed_kmh)
        if not live or not on_track or len(slow_now) > CROWD_FRACTION * len(on_track):
            self._slow_since.clear()             # start, neutralisation, pause: no zones
            self.zones = []
            return
        for c, kind in slow_now:
            self._slow_since[c.index] = (now, kind, c.spline)
        self._slow_since = {i: v for i, v in self._slow_since.items() if now - v[0] <= ZONE_HOLD_S}
        self.zones = [Zone(pos - ZONE_BEFORE, pos + ZONE_AFTER, kind, i)
                      for i, (_t, kind, pos) in sorted(self._slow_since.items())]

    # ------------------------------------------------------------- outputs
    def display_zones(self, player_pos: float | None, ac_flag: int) -> list[Zone]:
        """Zones to colour on the GPS: incidents, plus the blue behind your car if AC shows it."""
        zones = list(self.zones)
        if ac_flag == ACFlag.BLUE and player_pos is not None:
            zones.append(Zone(player_pos - BLUE_BEHIND, player_pos + 0.002, "blue", 0))
        return zones

    def player_flag(self, player_pos: float | None, ac_flag: int, now: float, cars_known: bool) -> FlagStatus | None:
        """Flag for the driver. The yellow comes from the zones ahead; AC's counts on its own only when there is
        no data on the other cars, or for a few seconds after it appears. After the yellow, green for a moment."""
        flag = self._player_flag(player_pos, ac_flag, now, cars_known)
        if flag is not None and flag.kind in ("yellow", "red"):
            self._warned_t = now
        elif flag is None and now - self._warned_t < GREEN_S:
            return FlagStatus("green", "GREEN FLAG · track clear")
        return flag

    def _player_flag(self, player_pos: float | None, ac_flag: int, now: float, cars_known: bool) -> FlagStatus | None:
        if ac_flag != self._ac_flag:
            self._ac_flag, self._ac_flag_t = ac_flag, now
        fixed = {ACFlag.BLUE: ("blue", "BLUE FLAG · let them by"),
                 ACFlag.CHECKERED: ("checkered", "CHEQUERED FLAG"),
                 ACFlag.BLACK: ("black", "BLACK FLAG"), ACFlag.PENALTY: ("penalty", "PENALTY"),
                 ACFlag.WHITE: ("white", "WHITE FLAG")}
        if ac_flag in fixed:
            return FlagStatus(*fixed[ac_flag])
        ahead = self.zone_ahead(player_pos)
        if ahead is not None:
            zone, dist = ahead
            where = "in this sector" if dist <= 0 else f"in {dist:.0f} m"
            if zone.kind == "red":
                return FlagStatus("red", f"DOUBLE YELLOW · stopped car {where}")
            return FlagStatus("yellow", f"YELLOW FLAG · slow car {where}")
        if ac_flag == ACFlag.YELLOW and (not cars_known or now - self._ac_flag_t < AC_FLAG_FRESH_S):
            return FlagStatus("yellow", "YELLOW FLAG")
        return None

    def zone_ahead(self, player_pos: float | None) -> tuple[Zone, float] | None:
        """The nearest zone ahead of your car within WARN_AHEAD_M, with the distance (0 = you are in it)."""
        if player_pos is None or not self.zones or self.track_length <= 0:
            return None
        best = None
        for z in self.zones:
            if z.car == 0:          # your car does not give itself a yellow
                continue
            dist = 0.0 if z.contains(player_pos) else ((z.start - player_pos) % 1.0) * self.track_length
            if dist <= WARN_AHEAD_M and (best is None or dist < best[1]):
                best = (z, dist)
        return best
