"""Lap splitting: cases seen live in AC (Red Bull Ring, 15/10/2026)."""

import pytest

from hub_core.ac.recording import read_samples
from hub_core.analysis.lap_recorder import LapRecorder
from tests.conftest import REAL_LAP, make_sample

L = 4000.0


def drive_lap(rec, lap_no, lap_ms, sectors, hz=60, start_fuel=50.0, glitch="timer_first", **kw):
    """Simulate a full lap followed by the line crossing with AC's update order."""
    out = []
    n = int(lap_ms / 1000 * hz)
    bounds = [sum(sectors[:i + 1]) for i in range(len(sectors))]
    fuel = start_fuel
    for i in range(n):
        ms = int(i * 1000 / hz)
        sec = next(k for k, b in enumerate(bounds) if ms < b)
        last_sec = sectors[sec - 1] if sec else 0
        fuel -= 2.5 / n
        out.append(rec.feed(make_sample(lap_time_ms=ms, completed_laps=lap_no, lap_position=ms / lap_ms,
                                        sector_index=sec, last_sector_ms=last_sec, fuel=fuel,
                                        last_lap_ms=kw.get("prev_lap_ms", 0))))
    # finish line, as recorded live
    if glitch == "spline_first":   # the position wraps to 0 before the timer
        out.append(rec.feed(make_sample(lap_time_ms=lap_ms - 3, completed_laps=lap_no, lap_position=0.0004,
                                        sector_index=2, last_sector_ms=sectors[1], fuel=fuel)))
    # timer reset ~5 ms before completedLaps changes
    out.append(rec.feed(make_sample(lap_time_ms=3, completed_laps=lap_no, lap_position=0.0004, sector_index=2,
                                    last_sector_ms=sectors[1], last_lap_ms=lap_ms, fuel=fuel)))
    out.append(rec.feed(make_sample(lap_time_ms=9, completed_laps=lap_no + 1, lap_position=0.0005, sector_index=0,
                                    last_sector_ms=sectors[2], last_lap_ms=lap_ms, fuel=fuel)))
    return [x for x in out if x is not None], fuel


@pytest.mark.parametrize("glitch", ["timer_first", "spline_first"])
def test_full_lap_valid_with_sectors(glitch):
    rec = LapRecorder(L, 3)
    rec.feed(make_sample(lap_time_ms=0, completed_laps=0, lap_position=0.0))
    laps, _ = drive_lap(rec, 0, 90000, [30000, 35000, 25000], glitch=glitch)
    assert len(laps) == 1
    lap = laps[0]
    assert lap.valid
    assert lap.lap_time_ms == 90000
    assert lap.sectors_ms == [30000, 35000, 25000]
    t, d = lap.channels["t"], lap.channels["dist"]
    assert t[-1] > 89.0, "the sample with the reset timer must not end up at the end of the lap"
    assert d[-1] > 0.99 * L, "the spline already at 0 at the end of the lap counts as the end of the lap"


def test_last_sector_derived_when_ac_is_late():
    rec = LapRecorder(L, 3)
    rec.feed(make_sample(lap_time_ms=0, completed_laps=0, lap_position=0.0))
    for i in range(1, 300):
        ms = i * 300
        sec = 0 if ms < 30000 else 1 if ms < 65000 else 2
        last = 0 if sec == 0 else 30000 if sec == 1 else 35000
        rec.feed(make_sample(lap_time_ms=ms, lap_position=ms / 90000, sector_index=sec, last_sector_ms=last))
    # lastSectorTime not updated yet when the lap arrives: the difference is used
    lap = rec.feed(make_sample(lap_time_ms=10, completed_laps=1, lap_position=0.001, sector_index=0,
                               last_sector_ms=35000, last_lap_ms=90000))
    assert lap.sectors_ms == [30000, 35000, 25000]


def test_lap_validity_follows_ac_timer_not_spline():
    rec = LapRecorder(L, 3)
    rec.feed(make_sample(lap_time_ms=50, completed_laps=0, lap_position=0.995))   # offset spline
    assert rec._valid
    rec = LapRecorder(L, 3)
    rec.feed(make_sample(lap_time_ms=88000, completed_laps=0, lap_position=0.98))  # acquisition started at the end of a lap
    assert not rec._valid


def test_return_to_pits_discards_lap():
    rec = LapRecorder(L, 3)
    rec.feed(make_sample(lap_time_ms=0, completed_laps=0, lap_position=0.0))
    for i in range(1, 200):
        rec.feed(make_sample(lap_time_ms=i * 200, lap_position=i * 200 / 90000))
    rec.feed(make_sample(lap_time_ms=600, lap_position=0.95, is_in_pit=True))   # timer restarted in the pits
    assert not rec._valid
    assert max(rec._buf["t"]) < 1.0


@pytest.mark.skipif(not REAL_LAP.is_file(), reason="test recording missing")
def test_real_recording_red_bull_ring():
    info, samples = read_samples(REAL_LAP)
    assert info["car"] == "trr_gt3_bmw_m4_gt3"
    assert info["track_length"] == pytest.approx(4286.79, abs=0.01)
    rec = LapRecorder(info["track_length"], info["sector_count"])
    laps = [lap for s in samples if (lap := rec.feed(s))]
    full = [lap for lap in laps if lap.valid]
    assert len(full) == 1
    lap = full[0]
    assert lap.lap_time_ms == 90486
    assert lap.sectors_ms == [20704, 37350, 32432]
    assert sum(lap.sectors_ms) == lap.lap_time_ms
    assert lap.channels["t"][-1] == pytest.approx(90.48, abs=0.05)
    assert lap.channels["dist"][-1] > 0.99 * info["track_length"]
    assert lap.fuel_used == pytest.approx(2.97, abs=0.02)
