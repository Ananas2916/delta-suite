from hub_core.analysis import race_strategy as rs
from hub_core.analysis.lap_recorder import LapData
from ai_engine.lang import LANGUAGES, KOKORO_VOICES, is_supported, language_of, speak_delta, speak_lap_time, speak_number
from ai_engine.radio import RadioConfig, RadioRules

IT, EN, ES = LANGUAGES["it"], LANGUAGES["en-us"], LANGUAGES["es"]


def lap(n, ms, valid=True, fuel_start=50.0, fuel_end=47.0, wear=(99.0,) * 4, temps=(85.0,) * 4,
        press=(27.0,) * 4):
    return LapData(n, ms, valid, [30000, 30000, ms - 60000], fuel_start, fuel_end, list(temps), list(press),
                   list(wear), [400.0] * 4, 250.0)


def test_stint_resets_on_tyre_change_without_fuel():
    laps = [lap(1, 90000, wear=(99,) * 4), lap(2, 90100, wear=(98,) * 4),
            lap(3, 120000, valid=False, wear=(100,) * 4),       # stop: tyres only
            lap(4, 89900, wear=(99.5,) * 4)]
    assert [l.lap_no for l in rs.current_stint(laps)] == [4]


def test_stint_resets_on_refuel():
    laps = [lap(1, 90000), lap(2, 120000, valid=False, fuel_start=10, fuel_end=60), lap(3, 90000)]
    assert [l.lap_no for l in rs.current_stint(laps)] == [3]


def test_speech_formatting():
    assert speak_lap_time(90461, IT) == "1, 30 e 5"
    assert speak_lap_time(90000, IT) == "1, 30"
    assert speak_lap_time(59900, IT) == "59 e 9"
    assert speak_delta(0.21, IT) == "più 2 decimi"
    assert speak_delta(-0.1, IT) == "meno un decimo"
    assert speak_delta(1.0, IT) == "più 1 secondo"
    assert speak_delta(1.34, IT) == "più 1 e 3"
    assert speak_delta(0.02, IT) == "stesso tempo"
    assert speak_number(29.14, IT) == "29 e 1"
    assert speak_lap_time(90461, EN) == "1 30 point 5"
    assert speak_lap_time(61000, EN) == "1 01"
    assert speak_delta(0.3, EN) == "plus 3 tenths"
    assert speak_delta(-1.2, ES) == "menos 1 coma 2"


def test_voice_picks_language():
    assert language_of("im_nicola").code == "it"
    assert language_of("bm_george").kokoro == "en-gb"
    assert language_of("am_michael").kokoro == "en-us"
    assert language_of("ff_siwis").name == "français"
    assert language_of("pm_alex").kokoro == "pt-br"
    assert all(is_supported(v) for v in KOKORO_VOICES)
    assert not is_supported("jf_alpha")
    keys = set(LANGUAGES["it"].phrases)
    for lg in LANGUAGES.values():           # every language has every phrase
        assert set(lg.phrases) == keys, lg.name


def test_radio_speaks_voice_language():
    r = RadioRules(RadioConfig(tyres=False, gaps=False, fuel=False), EN)
    laps = [lap(1, 90500, fuel_start=15.0, fuel_end=12.0), lap(2, 90800, fuel_start=12.0, fuel_end=9.0)]
    r.on_lap(laps[0], laps[:1])
    assert [m.text for m in r.on_lap(laps[1], laps)] == ["1 30 point 8, plus 3 tenths."]


def test_radio_lap_and_fuel():
    r = RadioRules(RadioConfig(tyres=False, gaps=False), IT)
    laps = [lap(1, 90500, fuel_start=15.0, fuel_end=12.0)]
    msgs = r.on_lap(laps[0], laps)
    assert msgs[0].text.startswith("Miglior giro personale")
    laps.append(lap(2, 90700, fuel_start=12.0, fuel_end=9.0))
    texts = [m.text for m in r.on_lap(laps[1], laps)]
    assert texts[0] == "1, 30 e 7, più 2 decimi."
    assert "Carburante per 3 giri." in texts
    laps.append(lap(3, 90600, fuel_start=9.0, fuel_end=2.9))
    texts = [m.text for m in r.on_lap(laps[2], laps)]
    assert "Box, box. Carburante per un giro." in texts


def test_radio_laps_to_go():
    r = RadioRules(RadioConfig(tyres=False, gaps=False, fuel=False), IT)
    laps = [lap(1, 90500), lap(2, 90700)]
    said = lambda to_go, race=True: [m.text for m in r.on_lap(laps[1], laps, race=race, to_go=to_go)][1:]  # noqa: E731
    assert said(5) == ["Mancano 5 giri."]
    assert said(4) == [] and said(None) == [] and said(5, race=False) == []
    assert said(1) == ["Ultimo giro, spingi."]


def test_radio_tyres_once_per_stint():
    r = RadioRules(RadioConfig(lap_times=False, fuel=False, gaps=False), IT)
    cold = (60.0, 61.0, 85.0, 85.0)
    laps = [lap(1, 90000, temps=cold)]
    assert r.on_lap(laps[0], laps) == []          # first stint lap: tyres still cold, stay quiet
    laps.append(lap(2, 90000, temps=cold))
    assert [m.text for m in r.on_lap(laps[1], laps)] == ["Anteriori fredde, 60 gradi."]
    laps.append(lap(3, 90000, temps=cold))
    assert r.on_lap(laps[2], laps) == []          # already said in this stint
