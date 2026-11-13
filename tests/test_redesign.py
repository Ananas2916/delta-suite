"""Logic behind the redesigned views (no Qt windows): Home data, live strip, Ambient colours."""

import datetime as dt
from types import SimpleNamespace

from hub_core.analysis.timing import StandingRow
from hub_core.analysis.track_status import TrackWatch
from ui import race_view as rv
from ui.ambient import BAD_BG, CLOSE_BG, GOOD_BG, IDLE_BG, ambient_colors
from ui.pages.home_page import greeting, last_session, personal_bests


def _s(id_, car, track, laps, best, day):
    return {"id": id_, "car": car, "track": track, "laps": laps, "best_ms": best,
            "started": dt.datetime(2026, 11, day, 20, 0)}


def test_last_session_skips_the_running_one_and_empty_ones():
    sessions = [_s(3, "499p", "spa", 0, None, 13), _s(2, "499p", "spa", 8, 123_000, 12), _s(1, "m4", "rbr", 5, 90_000, 1)]
    assert last_session(sessions, current_id=None)["id"] == 2
    assert last_session(sessions, current_id=2)["id"] == 1
    assert last_session([sessions[1]], current_id=2)["id"] == 2      # the only one: shown anyway
    assert last_session([], None) is None


def test_personal_bests_per_car_and_track_most_recent_first():
    sessions = [_s(4, "499p", "spa", 9, 124_000, 13), _s(3, "499p", "spa", 8, 123_500, 10),
                _s(2, "m4", "rbr", 5, 90_000, 11), _s(1, "m4", "rbr", 5, None, 12)]
    bests = personal_bests(sessions)
    assert [(b["track"], b["best_ms"]) for b in bests] == [("spa", 123_500), ("rbr", 90_000)]
    assert bests[0]["set"].day == 10 and bests[0]["last"].day == 13


def test_greeting():
    assert greeting(8) == "Good morning" and greeting(15) == "Good afternoon" and greeting(23) == "Good evening"


def test_gap_trend_per_lap():
    t = rv.GapTrend()
    t.update(4, {"Leclerc": 1.4})
    t.update(4, {"Leclerc": 1.0})            # same lap: ignored
    assert t.trend == {}
    t.update(5, {"Leclerc": 1.1})
    assert abs(t.trend["Leclerc"] - (-0.3)) < 1e-9
    t.update(7, {"Leclerc": 0.9})            # a lap skipped: no trend rather than a wrong one
    assert t.trend == {}


def _row(pos, name, interval, me=False):
    return StandingRow(pos, pos, name, "car", 5, 0, 0, None, interval, 0, False, me)


def test_strip_values_gaps_trend_and_fuel(sample):
    hub = SimpleNamespace(
        last_sample=sample(position=3, completed_laps=5, lap_time_ms=61_234, fuel=20.0),
        standings_rows=[_row(1, "Verstappen", None), _row(2, "Leclerc", 2.0), _row(3, "You", 0.8, me=True),
                        _row(4, "Norris", 1.3)],
        live_lap=SimpleNamespace(delta_s=-0.21), is_race=False, bridge_state=None, session_info={}, laps=[],
        track=TrackWatch())
    trend = rv.GapTrend()
    trend.update(4, {"Leclerc": 1.1, "Norris": 1.3})
    v = rv.strip_values(hub, trend)
    assert v["pos"] == "P3" and v["lap_time"] == "1:01.2"
    assert v["delta"] == "-0.21 on best" and v["delta_kind"] == "good"
    assert v["ahead_title"] == "Ahead · Leclerc" and v["ahead"] == "+0.8" and v["ahead_sub"] == "closing 0.3 a lap"
    assert v["behind_title"] == "Behind · Norris" and v["behind"] == "−1.3" and v["behind_sub"] == "steady"
    assert v["fuel"] == "20.0 L" and v["battery"] is None and v["flag"][0] == "green"


def test_strip_without_data_is_dashes():
    hub = SimpleNamespace(last_sample=None)
    v = rv.strip_values(hub, rv.GapTrend())
    assert v["pos"] == "–" and v["flag"] is None


def test_ambient_colours():
    assert ambient_colors(-0.1, 2.0) == (GOOD_BG, IDLE_BG)
    assert ambient_colors(0.3, 0.6) == (BAD_BG, CLOSE_BG)
    assert ambient_colors(None, None) == (IDLE_BG, IDLE_BG)
