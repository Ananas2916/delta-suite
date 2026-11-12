from ai_engine.lang import LANGUAGES, speak_amount
from ai_engine.phrases_race import RACE_PHRASES
from ai_engine.race_calls import RaceContext
from ai_engine.radio import RadioConfig, RadioRules
from hub_core.analysis.lap_recorder import LapData
from hub_core.analysis.timing import StandingRow
from hub_core.analysis.track_status import Zone
from hub_core.model import ACFlag, ACSessionType
from tests.conftest import make_sample

IT = LANGUAGES["it"]
ARGS = dict(pos=4, n=2, places="posizioni", g="0 e 8", d="3 decimi", wheel="anteriore sinistra",
            zone="all'anteriore")


def texts(msgs):
    return [m.text for m in msgs]


def row(pos, index, interval=None, in_pit=False, me=False):
    return StandingRow(pos, index, f"P{index}", "lmh", 5, 90000, 89000, None, interval, 0, in_pit, me)


def race_sample(**kw):
    return make_sample(**{"session_type": ACSessionType.RACE, "completed_laps": 3, "position": 4, **kw})


def ctx(now, **kw):
    return RaceContext(now=now, race=True, cars_known=True, **kw)


def lap(no, ms, fuel_start=50.0, fuel_end=48.0, valid=True):
    return LapData(no, ms, valid, [30000, 30000, ms - 60000], fuel_start, fuel_end, [85.0] * 4, [27.0] * 4,
                   [99.0] * 4, [500.0] * 4, 250.0)


def test_every_phrase_in_every_language_takes_its_placeholders():
    for key, langs in RACE_PHRASES.items():
        assert set(langs) == {"it", "en", "es", "fr", "pt"}, key
        for code, text in langs.items():
            if isinstance(text, tuple):
                continue
            for variant in text.split("|"):
                variant.format(**ARGS)          # no unknown or missing placeholder
    for lg in LANGUAGES.values():
        assert len(lg.phrases["zones"]) == 5 and len(lg.phrases["places"]) == 2


def test_variants_change_between_calls():
    r = RadioRules(lang=IT, seed=3)
    said = {r._p("pos_gained", pos=4) for _ in range(30)}
    assert said == set(RACE_PHRASES["pos_gained"]["it"].format(pos=4).split("|"))


def test_speak_amount():
    assert speak_amount(0.3, IT) == "3 decimi" and speak_amount(-0.1, IT) == "un decimo"
    assert speak_amount(1.4, IT) == "1 e 4" and speak_amount(0.02, IT) == ""


def test_lap_one_report_from_grid_position():
    r = RadioRules(lang=IT, seed=1)
    r.on_sample(make_sample(session_type=ACSessionType.RACE, completed_laps=0, position=8), None, ctx(0.0))
    msgs = texts(r.on_lap(lap(1, 92000), [lap(1, 92000)], race=True, position=5))
    assert any("P5, guadagni 3 posizioni" in t for t in msgs)
    r.race.start_pos = 4
    assert any("perdi 1 posizione" in t for t in texts(r.on_lap(lap(1, 92000), [lap(1, 92000)], race=True,
                                                                  position=5)))


def test_position_changes_are_confirmed_and_not_repeated():
    r = RadioRules(lang=IT, seed=1)
    said = lambda t, pos, **kw: texts(r.on_sample(race_sample(**{**kw, "position": pos}), None, ctx(t)))  # noqa: E731
    assert said(0.0, 4) == []
    assert said(1.0, 3) == []                 # just changed: wait for it to hold
    assert any("P3" in t for t in said(4.0, 3))
    assert said(5.0, 2) == [] and said(8.0, 2) == []     # confirmed but too soon after the last call
    assert said(20.0, 3) == [] and any("P3" in t for t in said(23.0, 3))   # from P2 to P3: position lost
    pit = dict(is_in_pit=True, pit_limiter=True)
    assert said(31.0, 5, **pit) == [] and said(40.0, 5, **pit) == []   # pit stops: quiet


def test_rivals_close_and_pitting():
    r = RadioRules(lang=IT, seed=1)
    rows = [row(3, 7), row(4, 0, interval=1.8, me=True), row(5, 9, interval=0.8)]
    msgs = texts(r.on_sample(race_sample(), None, ctx(0.0, rows=rows)))
    assert any("0 e 8" in t for t in msgs)                 # car behind within a second
    assert r.on_sample(race_sample(), None, ctx(10.0, rows=rows)) == []      # already said
    rows[2] = row(5, 9, interval=2.0)
    r.on_sample(race_sample(), None, ctx(20.0, rows=rows))                   # it drops back...
    rows[2] = row(5, 9, interval=0.7)
    assert texts(r.on_sample(race_sample(), None, ctx(30.0, rows=rows))) == []   # ...but less than 45 s ago
    assert any("0 e 7" in t for t in texts(r.on_sample(race_sample(), None, ctx(80.0, rows=rows))))
    rows[0] = row(3, 7, in_pit=True)
    assert any("ai box" in t for t in texts(r.on_sample(race_sample(), None, ctx(81.0, rows=rows))))
    assert not any("ai box" in t for t in texts(r.on_sample(race_sample(), None, ctx(82.0, rows=rows))))


def test_leader_last_lap_only_if_not_leading():
    r = RadioRules(lang=IT, seed=1)
    assert texts(r.on_sample(race_sample(), None, ctx(0.0, to_go=2))) == []
    assert texts(r.on_sample(race_sample(), None, ctx(1.0, to_go=1))) == ["Il leader è all'ultimo giro."]
    assert texts(r.on_sample(race_sample(), None, ctx(2.0, to_go=1))) == []
    r2 = RadioRules(lang=IT, seed=1)
    assert texts(r2.on_sample(race_sample(position=1), None, ctx(1.0, to_go=1))) == []


def test_puncture_worn_tyres_and_limiter():
    r = RadioRules(lang=IT, seed=1)
    flat = race_sample(tyre_pressure=(27.0, 5.0, 27.0, 27.0))
    assert "Foratura anteriore destra! Box, box." in texts(r.on_sample(flat, {}, ctx(0.0)))
    assert r.on_sample(flat, {}, ctx(1.0)) == []
    worn = race_sample(tyre_wear=(91.0, 91.0, 99.0, 99.0))
    assert len([t for t in texts(r.on_sample(worn, {}, ctx(2.0))) if "gomme" in t.lower()]) == 1   # only one
    pit = dict(is_in_pit=True, speed_kmh=90.0, pit_limiter=False)
    r.on_sample(race_sample(**pit), {}, ctx(10.0))
    assert any("imitatore" in t for t in texts(r.on_sample(race_sample(**pit), {}, ctx(12.0))))
    assert r.on_sample(race_sample(**pit), {}, ctx(13.0)) == []


def test_yellow_ahead_then_track_clear():
    r = RadioRules(lang=IT, seed=1)
    zone = Zone(0.3, 0.33, "red", 7)
    msgs = texts(r.on_sample(race_sample(), None, ctx(0.0, zone_ahead=(zone, 337.0))))
    assert msgs == ["Doppia gialla, auto ferma a 350 metri. Rallenta."]
    assert r.on_sample(race_sample(), None, ctx(1.0, zone_ahead=(zone, 200.0))) == []
    assert r.on_sample(race_sample(), None, ctx(2.0)) == []
    assert any("Pista libera" in t or "pista libera" in t for t in texts(r.on_sample(race_sample(), None, ctx(7.0))))
    # AC's yellow is not repeated by voice when the cars are known: the call is the one with the distance
    assert texts(r.on_sample(race_sample(flag=ACFlag.YELLOW), None, ctx(8.0))) == []
    assert texts(RadioRules(lang=IT).on_sample(race_sample(flag=ACFlag.YELLOW), None, None)) == ["Bandiera gialla."]


def test_finish_by_position_and_session_time():
    for pos, start in ((1, "Bandiera a scacchi! Vittoria"), (2, "Bandiera a scacchi, P2! Podio"),
                       (7, "Bandiera a scacchi, P7")):
        r = RadioRules(lang=IT, seed=1)
        msgs = texts(r.on_sample(race_sample(flag=ACFlag.CHECKERED, position=pos), None, ctx(0.0)))
        assert any(t.startswith(start) or t.startswith("Fine gara, P7") for t in msgs), (pos, msgs)
    r = RadioRules(lang=IT, seed=1)
    practice = lambda left: make_sample(session_time_left=left)   # noqa: E731
    quali = RaceContext(now=0.0)
    assert r.on_sample(practice(310_000), None, quali) == []
    assert texts(r.on_sample(practice(299_000), None, quali)) == ["Mancano 5 minuti alla fine della sessione."]
    assert r.on_sample(practice(200_000), None, quali) == []


def test_gap_trend_fastest_lap_and_fuel():
    r = RadioRules(RadioConfig(tyres=False), IT, seed=1)
    laps = [lap(1, 91000, 50.0, 47.0)]
    rows = (row(3, 7), row(4, 0, interval=1.5, me=True), row(5, 9, interval=2.0))
    r.on_lap(laps[0], laps, rows, race=True, to_go=10)
    laps.append(lap(2, 90000, 47.0, 44.0))
    rows = (row(3, 7), row(4, 0, interval=1.2, me=True), row(5, 9, interval=2.4))
    msgs = texts(r.on_lap(laps[1], laps, rows, race=True, to_go=20, field_best_ms=90500))
    assert any("Giro più veloce" in t or "giro più veloce" in t for t in msgs)
    gaps = next(t for t in msgs if t.startswith("Distacchi"))
    assert "recuperi 3 decimi al giro" in gaps and "guadagni 4 decimi al giro" in gaps
    assert any("risparmia" in t or "risparmiare" in t for t in msgs)       # 44 L for 20 laps at 3 L: not enough
    laps.append(lap(3, 90800, 44.0, 41.0))
    assert any("a posto" in t for t in texts(r.on_lap(laps[2], laps, rows, race=True, to_go=12)))
