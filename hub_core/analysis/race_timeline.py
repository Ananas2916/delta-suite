"""
The race lap by lap for the Race view timeline: what happened (position changes, pit stops, best and invalid laps,
fuel) and, past the current lap, the forecast (tyre stint with the planned stop, fuel to the finish, lap times from
the degradation fit). Pure data: the widget draws it, the scrubber reads one lap with `describe`.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from hub_core.analysis import race_strategy as rs
from hub_core.analysis.lap_recorder import LapData

FUTURE_LAPS_PRACTICE = 10        # without a race length, the forecast looks this far ahead


@dataclass
class LapMark:
    lap: int
    position: int | None
    time_ms: int
    valid: bool
    fuel_end: float
    pit: bool


class RaceLog:
    """What the hub saw at the end of each lap (position is not in LapData)."""

    def __init__(self):
        self.marks: list[LapMark] = []

    def reset(self):
        self.marks.clear()

    def add(self, lap: LapData, position: int | None, previous: LapData | None) -> None:
        pit = previous is not None and rs.is_pit_stop_lap(lap, previous)
        self.marks.append(LapMark(lap.lap_no, position or None, lap.lap_time_ms, lap.valid, lap.fuel_end, pit))


@dataclass
class Timeline:
    total: int                                   # laps shown (race length, or done + a look-ahead)
    done: int                                    # laps completed: right of this is the forecast
    positions: list[tuple[int, str, str]] = field(default_factory=list)   # (lap, "P4", "gain"|"lose"|"")
    stints: list[tuple[int, int, bool]] = field(default_factory=list)     # (first lap, last lap, forecast)
    boxes: list[tuple[int, bool]] = field(default_factory=list)           # (lap, planned)
    fuel: list[tuple[int, float, bool]] = field(default_factory=list)     # (lap, litres at its end, forecast)
    events: list[tuple[int, str, str]] = field(default_factory=list)      # (lap, text, kind)
    forecast_ms: dict[int, int] = field(default_factory=dict)             # lap -> forecast lap time
    marks: dict[int, LapMark] = field(default_factory=dict)


def build_timeline(log: RaceLog, laps: list[LapData], to_go: int | None, fuel_now: float | None,
                   tank: float | None, pit_loss_s: float = 25.0) -> Timeline:
    done = laps[-1].lap_no if laps else 0
    total = done + to_go if to_go else max(done + FUTURE_LAPS_PRACTICE, 1)
    tl = Timeline(total=total, done=done, marks={m.lap: m for m in log.marks})

    prev_pos = None
    best_ms = None
    stint_start = 1
    for m in log.marks:
        if m.position and prev_pos and m.position != prev_pos:
            tl.positions.append((m.lap, f"P{m.position}", "gain" if m.position < prev_pos else "lose"))
        elif m.position and prev_pos is None:
            tl.positions.append((m.lap, f"P{m.position}", ""))
        prev_pos = m.position or prev_pos
        if m.pit:
            tl.boxes.append((m.lap, False))
            tl.stints.append((stint_start, m.lap - 1, False))
            stint_start = m.lap
            tl.events.append((m.lap, "pit", "pit"))
        if m.valid and m.time_ms > 0 and (best_ms is None or m.time_ms < best_ms):
            if best_ms is not None:
                tl.events.append((m.lap, "best", "best"))
            best_ms = m.time_ms
        if not m.valid:
            tl.events.append((m.lap, "invalid", "invalid"))
        tl.fuel.append((m.lap, m.fuel_end, False))

    # forecast: this stint until the planned stop, then a new one to the finish
    fpl = rs.fuel_per_lap(laps) if laps else None
    stint = rs.current_stint(laps) if laps else []
    fc = rs.forecast_degradation(stint) if stint else None
    remaining = total - done
    planned = None
    if fc is not None and to_go:
        k = rs.optimal_pit_lap(fc, to_go, pit_loss_s)
        if k is not None:
            planned = done + (k - len(stint))
    if planned is None and fpl and fuel_now is not None and tank and to_go:
        plan = rs.fuel_plan(fuel_now, fpl, to_go, tank, done)
        if plan.pit_window:
            planned = plan.pit_window[1]
    if planned is not None and not done < planned <= total:
        planned = None
    tl.stints.append((stint_start, done if planned is None else planned - 1, False))
    if planned is not None:
        tl.boxes.append((planned, True))
        tl.stints[-1] = (stint_start, planned - 1, False)
        tl.stints.append((planned, total, True))
    elif total > done:
        tl.stints[-1] = (stint_start, total, False)
    if fc is not None:
        for i, t in enumerate(fc.forecast_times[:remaining]):
            tl.forecast_ms[done + 1 + i] = int(t * 1000)
    if fpl and fuel_now is not None:
        fuel = fuel_now
        for lap in range(done + 1, total + 1):
            fuel -= fpl
            if planned is not None and lap == planned and tank:
                fuel = min(tank, fuel + max(0.0, (total - lap) * fpl + fpl - fuel))
            tl.fuel.append((lap, round(fuel, 2), True))
    return tl


def describe(tl: Timeline, lap: int, fmt=rs.fmt_ms) -> tuple[bool, dict]:
    """What happened on `lap` (False, ...) or what is forecast for it (True, ...)."""
    future = lap > tl.done
    fuel = next((f for l, f, _fc in tl.fuel if l == lap), None)
    if not future:
        m = tl.marks.get(lap)
        return False, {"lap": lap, "time": fmt(m.time_ms) if m else None, "valid": m.valid if m else None,
                       "position": m.position if m else None, "fuel": fuel, "pit": bool(m and m.pit)}
    box = any(l == lap and planned for l, planned in tl.boxes)
    t = tl.forecast_ms.get(lap)
    return True, {"lap": lap, "time": fmt(t) if t else None, "fuel": fuel, "pit": box}
