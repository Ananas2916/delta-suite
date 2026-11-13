"""Race view data: where the lap is gained or lost along the track, and the race timeline."""

import numpy as np

from hub_core.analysis.lap_analysis import delta_profile
from hub_core.analysis.lap_recorder import LapData
from hub_core.analysis.race_timeline import RaceLog, build_timeline, describe


def _channels(slow_from: float, slow_to: float, loss_s: float, length: float = 1000.0) -> dict:
    d = np.linspace(0, length, 501)
    speed = np.full_like(d, 50.0)                       # 50 m/s → 20 s a lap
    t = d / 50.0
    stretch = (d > slow_from) & (d < slow_to)
    extra = np.cumsum(stretch.astype(float))
    extra = extra / max(extra[-1], 1) * loss_s
    return {"dist": d, "t": t + extra, "speed": speed * 3.6, "gas": np.ones_like(d), "brake": np.zeros_like(d),
            "steer": np.zeros_like(d), "gear": np.full_like(d, 4.0), "rpm": np.full_like(d, 7000.0),
            "x": d, "z": np.zeros_like(d)}


def test_delta_profile_puts_the_loss_where_it_happens():
    ref = _channels(0, 0, 0.0)
    other = _channels(400, 500, 0.3)
    prof = delta_profile(ref, other, 1000.0, bins=10)
    assert len(prof) == 10
    assert abs(sum(prof) - 0.3) < 0.02
    assert max(range(10), key=lambda i: prof[i]) == 4          # 400-500 m
    assert all(abs(v) < 0.01 for i, v in enumerate(prof) if i not in (3, 4, 5))


def _lap(n, ms, valid=True, fuel_start=50.0, fuel_end=48.0, wear=99.0):
    return LapData(n, ms, valid, [ms // 3] * 3, fuel_start, fuel_end, [85.0] * 4, [27.0] * 4, [wear] * 4,
                   [400.0] * 4, 250.0)


def test_timeline_past_and_forecast():
    log = RaceLog()
    laps, prev = [], None
    fuel = 60.0
    for n, (ms, pos) in enumerate([(80_000, 5), (79_500, 4), (79_800, 4), (79_900, 5), (80_100, 5)], start=1):
        lap = _lap(n, ms, fuel_start=fuel, fuel_end=fuel - 2.5, wear=100 - n)
        fuel -= 2.5
        log.add(lap, pos, prev)
        laps.append(lap)
        prev = lap
    tl = build_timeline(log, laps, to_go=25, fuel_now=fuel, tank=70.0)
    assert tl.total == 30 and tl.done == 5
    assert tl.positions == [(1, "P5", ""), (2, "P4", "gain"), (4, "P5", "lose")]
    assert (2, "best", "best") in tl.events
    # 25 laps at 2.5 L need more than the 47.5 L left: a stop is planned in the future
    planned = [lap for lap, p in tl.boxes if p]
    assert len(planned) == 1 and 5 < planned[0] <= 30
    assert tl.stints[-1][2] and tl.stints[-1][1] == 30
    future_fuel = [f for lap, f, fc in tl.fuel if fc]
    assert len(future_fuel) == 25 and min(future_fuel) >= -0.01      # never runs dry with the stop
    past, info = describe(tl, 2)
    assert past is False and info["position"] == 4 and info["time"] == "1:19.500"
    future, info = describe(tl, 12)
    assert future is True and info["fuel"] is not None


def test_timeline_records_pit_stops_and_practice_lookahead():
    log = RaceLog()
    a = _lap(1, 80_000, fuel_start=30, fuel_end=28)
    b = _lap(2, 95_000, valid=False, fuel_start=28, fuel_end=60)       # refuelled
    log.add(a, None, None)
    log.add(b, None, a)
    tl = build_timeline(log, [a, b], to_go=None, fuel_now=60.0, tank=70.0)
    assert tl.total == 12 and (2, False) in tl.boxes and (2, "pit", "pit") in tl.events
    assert tl.stints[0] == (1, 1, False)


def test_compare_plans_one_stop_wins_with_strong_degradation():
    from hub_core.analysis import race_strategy as rs
    stint = [_lap(n, 80_000 + 600 * n * n // 4) for n in range(1, 8)]     # times growing faster and faster
    fc = rs.forecast_degradation(stint, fuel_s_per_l=0.0)
    plans = rs.compare_plans(fc, laps_remaining=20, pit_loss_s=60.0, laps_done=7)   # 0.9 s/lap: one stop pays
    assert [p.name.split(" ·")[0] for p in plans][0] == "1 stop"
    assert plans[0].delta_s == 0 and all(p.delta_s >= 0 for p in plans)
    assert all(sum(p.stints) == 20 for p in plans)
    # not enough fuel for a no-stop run: that plan is marked and goes last
    plans = rs.compare_plans(fc, 20, 20.0, 7, laps_on_fuel=12, laps_per_tank=30)
    assert plans[-1].name == "No stop" and not plans[-1].feasible
