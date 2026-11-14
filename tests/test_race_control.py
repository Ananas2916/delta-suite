"""Race control: automatic director, radio calls on the state changes, link encoding, neutralised laps."""

from __future__ import annotations

from dataclasses import replace

from ai_engine.lang import LANGUAGES
from ai_engine.race_control_calls import OVER_REPEAT_S, RaceControlCalls
from ai_engine.radio import RadioRules
from hub_core.ac import race_link as rl
from hub_core.analysis.race_director import (CLEAR_S, COOLDOWN_S, MIN_ACTIVE_S, REQUEST_TIMEOUT_S, STOP_CONFIRM_S,
                                             RaceDirector)
from hub_core.model import CarEntry

EN = LANGUAGES["en-us"]


def car(i, kmh, pitlane=False, laps=3):
    return CarEntry(i, True, i + 1, laps, 0.1 * i, 0, 0, 0, pitlane, False, kmh, True, f"Driver {i}", "gt3")


def field(stopped=(), n=10):
    return [car(i, 0.0 if i in stopped else 180.0) for i in range(n)]


def run(d, cars, t0, t1, active, step=0.1):
    """Feed the director from t0 to t1; returns the decisions with their time."""
    out, t = [], t0
    while t <= t1 + 1e-9:
        dec = d.update(cars, t, True, active(t) if callable(active) else active)
        if dec:
            out.append((round(t, 1), dec))
        t += step
    return out


# ------------------------------------------------------------------ director

def test_stopped_car_neutralises_after_confirmation_and_ends_when_clear():
    d = RaceDirector("vsc")
    assert run(d, field(), 0, 5, False) == []
    dec = run(d, field(stopped={3}), 5, 5 + STOP_CONFIRM_S + 1, False)
    assert len(dec) == 1 and dec[0][1].action == "vsc" and dec[0][1].car == 3
    assert dec[0][0] >= 5 + STOP_CONFIRM_S - 0.1
    t_start = dec[0][0]
    # still stopped: no end, however long
    assert run(d, field(stopped={3}), t_start, t_start + 60, True) == []
    # car recovered: ends after CLEAR_S (and at least MIN_ACTIVE_S after the start)
    t = t_start + 60
    dec = run(d, field(), t, t + CLEAR_S + 1, True)
    assert [x[1].action for x in dec] == ["end"]


def test_end_waits_for_the_minimum_duration():
    d = RaceDirector("fcy")
    dec = run(d, field(stopped={2}), 0, STOP_CONFIRM_S + 0.5, False)
    t_start = dec[0][0]
    # the car moves off at once: the end still waits MIN_ACTIVE_S
    dec = run(d, field(), t_start, t_start + MIN_ACTIVE_S + 1, True)
    assert dec and dec[0][1].action == "end" and dec[0][0] >= t_start + MIN_ACTIVE_S - 0.1


def test_short_spin_and_pit_lane_do_not_neutralise():
    d = RaceDirector("vsc")
    assert run(d, field(stopped={1}), 0, STOP_CONFIRM_S - 1, False) == []
    assert run(d, field(), STOP_CONFIRM_S - 1, 20, False) == []                 # it rejoined
    pit = [car(i, 0.0, pitlane=(i == 4)) if i == 4 else car(i, 180.0) for i in range(10)]
    assert run(d, pit, 20, 40, False) == []


def test_grid_and_mass_stop_are_not_incidents():
    d = RaceDirector("vsc")
    assert run(d, field(stopped=set(range(10))), 0, 30, False) == []


def test_off_mode_and_non_race_do_nothing():
    d = RaceDirector("off")
    assert run(d, field(stopped={1}), 0, 30, False) == []
    d = RaceDirector("vsc")
    t, decisions = 0.0, []
    while t < 30:
        decisions.append(d.update(field(stopped={1}), t, False, False))
        t += 0.1
    assert not any(decisions)


def test_manual_neutralisation_is_left_alone_and_cooldown_after_green():
    d = RaceDirector("vsc")
    # someone else started one: the director neither starts another nor ends it
    assert run(d, field(stopped={1}), 0, 60, True) == []
    # after green, a new incident waits for the cooldown
    d2 = RaceDirector("vsc")
    t_start = run(d2, field(stopped={1}), 0, STOP_CONFIRM_S + 0.5, False)[0][0]
    t_end = run(d2, field(), t_start, t_start + MIN_ACTIVE_S + CLEAR_S + 1, True)[0][0]
    early = run(d2, field(stopped={5}), t_end, t_end + COOLDOWN_S - 1, False)
    assert early == []
    later = run(d2, field(stopped={5}), t_end + COOLDOWN_S - 1, t_end + COOLDOWN_S + 1, False)
    assert later and later[0][1].action == "vsc"


def test_request_not_taken_up_times_out():
    d = RaceDirector("fcy")
    t_start = run(d, field(stopped={1}), 0, STOP_CONFIRM_S + 0.5, False)[0][0]
    # the app never shows it active (not available): after the timeout the director is free again
    assert run(d, field(stopped={1}), t_start, t_start + REQUEST_TIMEOUT_S + 1, False) == []
    assert d._active_since is None


# ------------------------------------------------------------------ radio calls

def rc(state, mode=rl.MODE_VSC, over=False, limit=0.0):
    return rl.RaceControlState(True, state, mode, 0.0, 0.0, 0.0, limit, 100.0, over, 0.0, 0, 0, 0)


def calls():
    return RaceControlCalls(RadioRules(lang=EN, seed=1))


def say(c, states, t0=0.0, step=0.1):
    out = []
    for k, st in enumerate(states):
        out += [m.text for m in c.update(st, t0 + k * step, 80, 10)]
    return out


def test_fcy_sequence_is_called_once_per_change():
    c = calls()
    seq = [rc(rl.GREEN, rl.MODE_NONE)] + [rc(rl.PENDING, rl.MODE_FCY)] * 3 + [rc(rl.ACTIVE, rl.MODE_FCY, limit=80)] * 3 \
        + [rc(rl.ENDING, rl.MODE_FCY)] * 2 + [rc(rl.GREEN_FLASH, rl.MODE_FCY)] * 2 + [rc(rl.GREEN, rl.MODE_NONE)]
    texts = say(c, seq)
    assert len(texts) == 4
    assert "10 seconds" in texts[0] and "80" in texts[0]
    assert "80" in texts[1]
    assert "FCY" in texts[2] and "Green" in texts[3]


def test_first_state_seen_is_not_called():
    # Delta Suite started mid-VSC: no "VSC deployed" out of the blue
    assert say(calls(), [rc(rl.ACTIVE)] * 5) == []


def test_over_limit_warns_after_confirmation_and_repeats_slowly():
    c = calls()
    say(c, [rc(rl.GREEN, rl.MODE_NONE), rc(rl.ACTIVE)])
    over = [rc(rl.ACTIVE, over=True)] * 300           # 30 s over the delta
    texts = say(c, over, t0=1.0)
    assert 2 <= len(texts) <= 1 + 30 / OVER_REPEAT_S + 1
    assert all("elta" in t for t in texts)
    # a moment over is not worth a call
    c2 = calls()
    say(c2, [rc(rl.GREEN, rl.MODE_NONE), rc(rl.ACTIVE)])
    assert say(c2, [rc(rl.ACTIVE, over=True)] * 5 + [rc(rl.ACTIVE)] * 5, t0=1.0) == []


def test_cancelled_countdown_is_called():
    texts = say(calls(), [rc(rl.GREEN, rl.MODE_NONE), rc(rl.PENDING, rl.MODE_FCY), rc(rl.GREEN, rl.MODE_NONE)])
    assert len(texts) == 2 and "ancel" in texts[1]


def test_unavailable_race_control_is_silent():
    c = calls()
    off = replace(rc(rl.ACTIVE), available=False)
    assert say(c, [off, rc(rl.GREEN, rl.MODE_NONE), off]) == []


# ------------------------------------------------------------------ link

def test_text_encoding_fits_and_never_splits_a_character():
    raw = rl._enc("è" * 200, 160)
    assert len(raw) <= 159
    raw.decode("utf-8")                                  # still valid UTF-8
    assert rl._enc("", 96) == b""


def test_state_flags():
    assert rc(rl.ACTIVE).neutralised and rc(rl.ENDING).neutralised
    assert not rc(rl.PENDING).neutralised and rc(rl.PENDING).active
    assert not rc(rl.GREEN_FLASH).active


def test_safety_car_sequence_and_overtake_warning():
    c = calls()
    seq = [rc(rl.GREEN, rl.MODE_NONE), rc(rl.ACTIVE, rl.MODE_SC, limit=120)]
    texts = say(c, seq)
    assert len(texts) == 1 and "afety car" in texts[0]
    over = say(c, [rc(rl.ACTIVE, rl.MODE_SC, over=True, limit=120)] * 30, t0=1.0)
    assert len(over) == 1 and "overtak" in over[0].lower()
    ending = say(c, [rc(rl.ENDING, rl.MODE_SC), rc(rl.GREEN_FLASH, rl.MODE_SC)], t0=10.0)
    assert len(ending) == 2 and "this lap" in ending[0] and "Green" in ending[1]


def test_safety_car_fields_in_the_layout():
    names = [n for n, _ in rl.RaceOut._fields_]
    assert names[-4:] == ["scCar", "scPhase", "scGapM", "endMarker"]
    assert "scCarId" in [n for n, _ in rl.RaceIn._fields_]


def test_pit_exit_is_where_the_pit_lane_rejoins_the_track():
    import math
    from hub_core.analysis.track_status import TrackWatch
    lap = [(100 * math.cos(2 * math.pi * k / 400), 100 * math.sin(2 * math.pi * k / 400)) for k in range(400)]
    # pit spline: on the track from 0.80, 20 m inside it from 0.85 to 0.05 of the lap, back on the track to 0.15
    pit = []
    for k in range(320, 460):
        a = 2 * math.pi * (k % 400) / 400
        inside = 340 <= k <= 420
        r = 80 if inside else 100
        pit.append((r * math.cos(a), r * math.sin(a)))
    exit_pos = TrackWatch(lap, pit).pit_exit_position()
    assert exit_pos is not None and abs(exit_pos - 0.0525) < 0.01
    assert TrackWatch(lap, []).pit_exit_position() is None
