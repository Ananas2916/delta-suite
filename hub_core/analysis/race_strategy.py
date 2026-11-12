"""Strategy: fuel, pit window, sector timing, tyre degradation forecast."""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

from hub_core.analysis.lap_recorder import LapData


def fmt_ms(ms: float | None) -> str:
    if ms is None or ms <= 0 or not math.isfinite(ms):
        return "--:--.---"
    ms = int(round(ms))
    return f"{ms // 60000}:{(ms % 60000) / 1000:06.3f}"


# ----------------------------------------------------------------------- fuel

def fuel_per_lap(laps: list[LapData]) -> float | None:
    """Robust average fuel use over valid laps (drops outliers beyond ±25% of the median)."""
    used = np.array([l.fuel_used for l in laps if l.valid and l.fuel_used > 0.05])
    if used.size == 0:
        return None
    med = np.median(used)
    close = used[np.abs(used - med) <= 0.25 * med]
    return float(close.mean()) if close.size else float(med)


@dataclass
class FuelPlan:
    laps_remaining: int
    fuel_needed: float          # to reach the end with a margin
    fuel_to_add: float
    laps_on_current_fuel: float
    stops_needed: int
    pit_window: tuple[int, int] | None   # (first, last) race lap on which to stop
    laps_per_tank: float


def race_laps_remaining(race_laps: int | None, laps_done: int, time_left_s: float | None,
                        avg_lap_s: float | None) -> int:
    if race_laps:
        return max(0, race_laps - laps_done)
    if time_left_s is not None and avg_lap_s:
        # when time runs out the current lap is completed
        return int(math.ceil(time_left_s / avg_lap_s)) + 1
    return 0


@dataclass(frozen=True)
class RaceProgress:
    """How far the race has got, from the leader's lap (like TV graphics)."""

    lap: int                    # leader's current lap (1 = first)
    total: int | None           # race laps; None if timed or unlimited
    to_go: int | None           # laps to go including the current one (estimated if timed); None if unknown
    time_left_s: float | None   # session time left, if it has a limit
    estimated: bool = False

    @property
    def lap_text(self) -> str:
        return f"{self.lap}/{self.total}" if self.total else str(self.lap)

    @property
    def to_go_text(self) -> str:
        if self.to_go is None:
            return "—"
        if self.to_go == 0:
            return "FINISHED"
        if self.to_go == 1:
            return "FINAL LAP"
        return f"{'~' if self.estimated else ''}{self.to_go} laps"


def race_progress(race_laps: int, leader_done: int, time_left_ms: float | None, lap_s: float | None,
                  is_race: bool, extra_lap: bool = False) -> RaceProgress:
    """Race laps (AC's numberOfLaps) or, for timed races, an estimate from the average lap: when time runs out
    the current lap is completed, plus one if the server has the extra lap."""
    time_left = time_left_ms / 1000 if time_left_ms is not None and time_left_ms > 0 else None
    lap = leader_done + 1
    if is_race and race_laps > 0:
        return RaceProgress(min(lap, race_laps), race_laps, max(0, race_laps - leader_done), time_left)
    if is_race and time_left is not None and lap_s:
        to_go = int(math.ceil(time_left / lap_s)) + (1 if extra_lap else 0)
        return RaceProgress(lap, None, max(1, to_go), time_left, estimated=True)
    return RaceProgress(lap, None, None, time_left)


def race_progress_for(s, cars, is_race: bool, extra_lap: bool = False) -> RaceProgress:
    """RaceProgress from a sample and the CSP app cars: the lap is the leader's, if known."""
    leader_done, lap_ms = s.completed_laps, s.last_lap_ms or s.best_lap_ms
    leader = min((c for c in cars or [] if c.connected and c.race_pos > 0), key=lambda c: c.race_pos, default=None)
    if leader is not None:
        leader_done = leader.lap_count
        lap_ms = leader.last_lap_ms or leader.best_lap_ms or lap_ms
    return race_progress(s.session_laps, leader_done, s.session_time_left, lap_ms / 1000 if lap_ms > 0 else None,
                         is_race, extra_lap)


def fuel_plan(fuel_now: float, per_lap: float, laps_remaining: int, tank: float,
              laps_done: int, margin_laps: float = 1.0) -> FuelPlan:
    needed = (laps_remaining + margin_laps) * per_lap
    to_add = max(0.0, needed - fuel_now)
    laps_now = fuel_now / per_lap if per_lap > 0 else float("inf")
    laps_per_tank = tank / per_lap if per_lap > 0 else float("inf")
    stops = 0 if to_add <= 0 else int(math.ceil(to_add / tank))
    window = None
    if stops >= 1:
        latest = laps_done + int(math.floor(laps_now - margin_laps))
        # as early as possible: after the stop the rest must be covered with (stops) full tanks
        earliest = laps_done + max(0, int(math.ceil(laps_remaining + margin_laps - stops * laps_per_tank)))
        window = (min(earliest, latest), latest)
    return FuelPlan(laps_remaining, needed, to_add, laps_now, stops, window, laps_per_tank)


# ------------------------------------------------------------------- timing

def best_sectors(laps: list[LapData], count: int = 3) -> list[int | None]:
    best: list[int | None] = [None] * count
    for lap in laps:
        if not lap.valid or len(lap.sectors_ms) != count:
            continue
        for i, s in enumerate(lap.sectors_ms):
            if s > 0 and (best[i] is None or s < best[i]):
                best[i] = s
    return best


def theoretical_best(laps: list[LapData], count: int = 3) -> int | None:
    b = best_sectors(laps, count)
    return sum(b) if all(v is not None for v in b) else None


# ---------------------------------------------------------- tyre degradation

@dataclass
class DegradationForecast:
    stint_laps: np.ndarray      # stint laps used for the fit (1 = first lap)
    lap_times: np.ndarray       # s, fuel corrected
    coeffs: np.ndarray          # polynomial in stint laps
    deg_per_lap: float          # current s/lap (derivative at end of stint)
    forecast_laps: np.ndarray
    forecast_times: np.ndarray
    cliff_lap: int | None       # first forecast lap losing > threshold vs best


def is_pit_stop_lap(lap: LapData, previous: LapData | None) -> bool:
    """Pit stop lap: refuelling, or new tyres (wear in AC only goes down, 100 = new)."""
    if lap.valid:
        return False
    refuel = lap.fuel_end > lap.fuel_start + 0.5
    new_tyres = previous is not None and bool(lap.tyre_wear_end) and bool(previous.tyre_wear_end) and \
        max(e - p for e, p in zip(lap.tyre_wear_end, previous.tyre_wear_end)) > 0.5
    return refuel or new_tyres


def current_stint(laps: list[LapData]) -> list[LapData]:
    """Laps since the last stop (refuel or tyre change)."""
    stint: list[LapData] = []
    previous = None
    for lap in laps:
        if is_pit_stop_lap(lap, previous):
            stint = []
        else:
            stint.append(lap)
        previous = lap
    return stint


def forecast_degradation(stint: list[LapData], horizon: int = 15, fuel_s_per_l: float = 0.025,
                         cliff_threshold_s: float = 1.5) -> DegradationForecast | None:
    """Robust polynomial fit of the stint lap times, corrected for the fuel burn-off."""
    pts = [(i + 1, l) for i, l in enumerate(stint) if l.valid and l.lap_time_ms > 0]
    if len(pts) < 3:
        return None
    x = np.array([p[0] for p in pts], dtype=float)
    t = np.array([p[1].lap_time_ms / 1000.0 for p in pts])
    fuel = np.array([p[1].fuel_start for p in pts])
    t_corr = t + (fuel - fuel[-1]) * -fuel_s_per_l    # bring all of them to the end-of-stint fuel load

    med = np.median(t_corr)
    keep = t_corr < med * 1.03
    x, t_corr = x[keep], t_corr[keep]
    if len(x) < 3:
        return None
    deg = 2 if len(x) >= 6 else 1
    coeffs = np.polyfit(x, t_corr, deg)
    if deg == 2 and coeffs[0] < 0:     # a concave parabola makes no physical sense: fall back to linear
        coeffs = np.polyfit(x, t_corr, 1)
    poly = np.poly1d(coeffs)
    last = int(x[-1])
    fx = np.arange(last + 1, last + horizon + 1, dtype=float)
    # in the forecast the fuel keeps dropping: gain per lap
    per_lap_fuel = float(np.mean([l.fuel_used for _, l in pts])) if pts else 0.0
    ft = poly(fx) - (fx - last) * per_lap_fuel * fuel_s_per_l
    best = float(np.min(poly(x)))
    cliff = next((int(l) for l, v in zip(fx, ft) if v - best > cliff_threshold_s), None)
    return DegradationForecast(x, t_corr, coeffs, float(np.polyder(poly)(last)), fx, ft, cliff)


def optimal_pit_lap(fc: DegradationForecast, laps_remaining: int, pit_loss_s: float) -> int | None:
    """Stint lap on which to stop to minimise total time (one stop, new tyres = stint start)."""
    if laps_remaining <= 1:
        return None
    poly = np.poly1d(fc.coeffs)
    last = int(fc.stint_laps[-1])
    best_total, best_k = None, None
    for k in range(0, laps_remaining):   # k more laps on this set
        old = poly(np.arange(last + 1, last + k + 1)).sum() if k else 0.0
        new = poly(np.arange(1, laps_remaining - k + 1)).sum()
        total = old + pit_loss_s + new
        if best_total is None or total < best_total:
            best_total, best_k = total, k
    no_stop = poly(np.arange(last + 1, last + laps_remaining + 1)).sum()
    if best_total is None or no_stop <= best_total:
        return None
    return last + best_k
