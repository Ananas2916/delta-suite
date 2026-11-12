"""The chatty engineer (ai_engine.race_chatter): calls between the important ones, with cooldowns."""

from ai_engine.lang import LANGUAGES
from ai_engine.phrases_chatter import CHATTER_PHRASES
from ai_engine.race_calls import RaceContext
from ai_engine.race_chatter import surname
from ai_engine.radio import RadioConfig, RadioRules
from hub_core.analysis.lap_recorder import LapData
from hub_core.analysis.timing import StandingRow
from hub_core.model import ACSessionType
from tests.conftest import make_sample

IT = LANGUAGES["it"]
ARGS = dict(who="Leclerc", pos=4, t="1, 32 e 4", g="0 e 8", d="3 decimi", n=2, temp="85", temp2="88")


def texts(msgs):
    return [m.text for m in msgs]


def row(pos, index, driver="", interval=None, last_ms=90000, best_ms=89000, in_pit=False, me=False):
    return StandingRow(pos, index, driver, "lmh", 5, last_ms, best_ms, None, interval, 0, in_pit, me)


def lap(no, ms, valid=True, temps=85.0, fuel_start=50.0, fuel_end=48.0):
    return LapData(no, ms, valid, [30000, 30000, ms - 60000], fuel_start, fuel_end, [temps] * 4, [27.0] * 4,
                   [99.0] * 4, [500.0] * 4, 250.0)


def race_sample(**kw):
    return make_sample(**{"session_type": ACSessionType.RACE, "completed_laps": 3, "position": 4, **kw})


def ctx(now, **kw):
    return RaceContext(now=now, race=True, cars_known=True, **kw)


def rules(level=2, **cfg):
    return RadioRules(RadioConfig(chatter=level, tyres=False, gaps=False, **cfg), IT, seed=1)


def test_every_chatter_phrase_in_every_language_takes_its_placeholders():
    for key, langs in CHATTER_PHRASES.items():
        assert set(langs) == {"it", "en", "es", "fr", "pt"}, key
        for text in langs.values():
            for variant in text.split("|"):
                variant.format(**ARGS)
    for lg in LANGUAGES.values():
        assert "race_start" in lg.phrases and "lap" in lg.phrases     # both phrase files merged


def test_surname():
    assert surname("Max Verstappen") == "Verstappen" and surname("lewis_hamilton") == "hamilton"
    assert surname("") is None and surname(None) is None


def test_race_start_once_and_not_when_quiet():
    r = rules()
    assert texts(r.on_sample(race_sample(completed_laps=0, speed_kmh=0.0), None, ctx(0.0))) == []
    assert any("curva uno" in t.lower() or "via" in t.lower()
               for t in texts(r.on_sample(race_sample(completed_laps=0, speed_kmh=60.0), None, ctx(1.0))))
    assert r.on_sample(race_sample(completed_laps=0, speed_kmh=80.0), None, ctx(2.0)) == []
    q = rules(level=0)
    assert q.on_sample(race_sample(completed_laps=0, speed_kmh=60.0), None, ctx(1.0)) == []


def test_overtake_by_name_and_pitting_rival_by_name():
    r = rules()
    rows = [row(3, 7, "Charles Leclerc"), row(4, 0, me=True, interval=0.5), row(5, 9, "Lando Norris")]
    said = lambda t, pos, rows: texts(r.on_sample(race_sample(position=pos), None, ctx(t, rows=rows)))  # noqa: E731
    said(0.0, 4, rows)
    said(0.5, 4, rows)
    after = [row(3, 0, me=True), row(4, 7, "Charles Leclerc", interval=0.4), row(5, 9, "Lando Norris")]
    said(1.0, 3, after)
    msgs = said(4.0, 3, after)
    assert any("Leclerc" in t and "P3" in t for t in msgs), msgs
    after[1] = row(4, 7, "Charles Leclerc", interval=0.4, in_pit=True)
    assert any("Leclerc" in t and "undercut" in t for t in said(5.0, 3, after))


def test_without_chatter_positions_stay_generic():
    r = rules(level=0)
    rows = [row(3, 7, "Charles Leclerc"), row(4, 0, me=True)]
    after = [row(3, 0, me=True), row(4, 7, "Charles Leclerc")]
    for t, pos, rw in ((0.0, 4, rows), (0.5, 4, rows), (1.0, 3, after)):
        r.on_sample(race_sample(position=pos), None, ctx(t, rows=rw))
    msgs = texts(r.on_sample(race_sample(position=3), None, ctx(4.0, rows=after)))
    assert msgs and not any("Leclerc" in t for t in msgs)


def test_purple_sector_once_per_lap():
    r = rules()
    laps = [lap(1, 92000), lap(2, 91000)]
    r.on_lap(laps[1], laps, [], race=True, to_go=10)
    assert r.chatter.best_sectors[0] == 30000
    r.on_sample(race_sample(sector_index=0, completed_laps=2), None, ctx(0.0))
    msgs = texts(r.on_sample(race_sample(sector_index=1, completed_laps=2, last_sector_ms=29700), None, ctx(30.0)))
    assert any("viola" in t.lower() and "3 decimi" in t for t in msgs), msgs
    assert r.on_sample(race_sample(sector_index=2, completed_laps=2, last_sector_ms=29000), None, ctx(60.0)) == []
    # at chattiness 1 a tiny gain is not worth a call
    n = rules(level=1)
    n.on_lap(laps[1], laps, [], race=True, to_go=10)
    n.on_sample(race_sample(sector_index=0, completed_laps=2), None, ctx(0.0))
    assert n.on_sample(race_sample(sector_index=1, completed_laps=2, last_sector_ms=29950), None, ctx(30.0)) == []


def test_pit_exit_then_tyres_warm():
    r = rules()
    r.on_sample(race_sample(is_in_pit=True, pit_limiter=True), None, ctx(0.0))
    r.on_sample(race_sample(position=6), None, ctx(1.0))
    assert r.on_sample(race_sample(position=6), None, ctx(3.0)) == []
    assert any("P6" in t for t in texts(r.on_sample(race_sample(position=6), None, ctx(7.0))))
    laps = [lap(1, 90000), lap(2, 90500), lap(3, 112000, valid=False, fuel_start=46.0, fuel_end=60.0), lap(4, 90400)]
    assert any("temperatura" in t for t in texts(r.on_lap(laps[3], laps, [], race=True, to_go=10)))


def test_pace_drop_consistency_and_fastest_on_track():
    r = rules()
    laps = [lap(1, 90200), lap(2, 90000), lap(3, 90100), lap(4, 90050)]
    rows = [row(3, 7, "Charles Leclerc", last_ms=90600), row(4, 0, me=True), row(5, 9, "Lando Norris", last_ms=90900)]
    msgs = texts(r.on_lap(laps[3], laps, rows=rows, race=True, to_go=30, position=4))
    assert any("più veloce in pista" in t or "più forte di te" in t for t in msgs)
    assert any("costante" in t.lower() for t in msgs)
    assert any("Leclerc" in t for t in msgs)                       # rival's lap time
    laps.append(lap(5, 91500))
    msgs = texts(r.on_lap(laps[4], laps, rows=rows, race=True, to_go=29, position=4))
    assert any("perso 1 e 5" in t for t in msgs), msgs           # 1.5 s off the stint average


def test_half_distance_and_bring_home():
    r = rules()
    laps = [lap(i, 90000) for i in range(1, 11)]
    assert not any("metà" in t.lower() for t in texts(r.on_lap(laps[3], laps[:4], [], race=True, to_go=7,
                                                                position=4)))
    assert any("metà" in t.lower() for t in texts(r.on_lap(laps[4], laps[:5], [], race=True, to_go=5, position=4)))
    assert any("P4" in t and "Due giri" in t or "Ultimi due" in t
               for t in texts(r.on_lap(laps[8], laps[:9], [], race=True, to_go=2, position=4)))


def test_timesheet_in_practice():
    r = rules()
    rows = [row(1, 3, "A", best_ms=89500), row(2, 0, me=True), row(3, 5, "B", best_ms=90800)]
    laps = [lap(1, 91000), lap(2, 90000)]
    msgs = texts(r.on_lap(laps[1], laps, rows=rows, race=False))
    assert any("P2" in t and "0 e 5" in t for t in msgs), msgs
    laps.append(lap(3, 89000))
    assert any("più veloce della sessione" in t or "P1" in t for t in texts(r.on_lap(laps[2], laps, rows=rows)))
    laps.append(lap(4, 89900))                                     # not a personal best: nothing new
    assert not any("P" in t and "dal primo" in t for t in texts(r.on_lap(laps[3], laps, rows=rows)))


def test_periodic_update_only_after_silence():
    r = rules()
    rows = [row(3, 7, "Charles Leclerc"), row(4, 0, me=True, interval=1.4), row(5, 9, "Lando Norris", interval=2.2)]
    s = race_sample(tyre_core_temp=(85.0, 85.0, 88.0, 88.0))
    r.on_sample(s, None, ctx(0.0, rows=rows))
    assert r.on_sample(s, None, ctx(30.0, rows=rows)) == []
    msgs = texts(r.on_sample(s, None, ctx(75.0, rows=rows)))
    assert len(msgs) == 1
    assert r.on_sample(s, None, ctx(80.0, rows=rows)) == []        # the update itself resets the silence
    said = set(msgs)
    for t in range(1, 8):
        said |= set(texts(r.on_sample(s, None, ctx(80.0 + 75.0 * t, rows=rows))))
    assert len(said) >= 3                                          # topics take turns
    assert rules(level=1).on_sample(s, None, ctx(500.0, rows=rows)) == []


def test_battery_to_attack():
    r = rules()
    info = {"has_kers": True, "kers_max_j": 0.0}
    rows = [row(3, 7, "Charles Leclerc"), row(4, 0, me=True, interval=0.7), row(5, 9, "Lando Norris", interval=3.0)]
    msgs = texts(r.on_sample(race_sample(kers_charge=0.9), info, ctx(0.0, rows=rows)))
    assert any("Leclerc" in t and "0 e 7" in t for t in msgs), msgs
    assert not any("batteria" in t.lower() for t in texts(r.on_sample(race_sample(kers_charge=0.9), info,
                                                                     ctx(10.0, rows=rows))))


def test_slow_rival_ahead():
    r = rules()
    rows = [row(3, 7, "Charles Leclerc"), row(4, 0, me=True, interval=4.0)]
    assert any("Leclerc" in t and "lento" in t
               for t in texts(r.on_sample(race_sample(), None, ctx(0.0, rows=rows, slow_cars={7}))))
    assert r.on_sample(race_sample(), None, ctx(1.0, rows=rows, slow_cars={7})) == []
