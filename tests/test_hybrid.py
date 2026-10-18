import pytest

from ai_engine.lang import LANGUAGES
from ai_engine.radio import RadioConfig, RadioRules
from hub_core.ac.receiver import sample_from_pages, session_info_from_static
from hub_core.ac.shared_memory import SPageFileGraphic, SPageFilePhysics, SPageFileStatic
from hub_core.analysis import car_status as cs
from hub_core.demo_source import DemoSource
from tests.conftest import make_sample

HYBRID = {"has_ers": True, "has_kers": False, "ers_max_j": 4.0e6, "kers_max_j": 0.0, "ers_power_modes": 4}


def test_hybrid_fields_from_ac_pages():
    phy, gfx, st = SPageFilePhysics(), SPageFileGraphic(), SPageFileStatic()
    phy.kersCharge, phy.kersInput, phy.kersCurrentKJ = 0.42, 1.0, 812.5
    phy.ersRecoveryLevel, phy.ersPowerLevel, phy.ersHeatCharging, phy.ersIsCharging = 3, 2, 1, 0
    st.hasERS, st.hasKERS, st.ersMaxJ, st.ersPowerControllerCount = 1, 0, 4.0e6, 5
    s, info = sample_from_pages(phy, gfx, 0.0), session_info_from_static(st, "AC")
    assert s.kers_charge == pytest.approx(0.42) and s.kers_lap_kj == pytest.approx(812.5)
    assert (s.ers_recovery, s.ers_power, s.ers_heat_charging, s.ers_charging) == (3, 2, True, False)
    assert info["has_ers"] and not info["has_kers"] and info["ers_power_modes"] == 5

    h = cs.hybrid_state(s, info)
    assert h.deploying and h.mode_text == "in spinta"
    assert h.lap_limit_kj == pytest.approx(4000) and h.lap_left_kj == pytest.approx(3187.5)
    assert cs.hybrid_dict(h)["batteria_pct"] == 42.0


def test_not_hybrid_without_kers_or_ers():
    s = make_sample(kers_charge=0.0)
    assert cs.hybrid_state(s, {"damage_rate": 1.0}) is None
    assert cs.status_dict(s, {})["ibrido"] is None
    assert not any(a.key == "battery" for a in cs.car_alerts(s, {}))   # carica 0 ma non è ibrida


def test_kers_only_car_uses_kers_limit():
    info = {"has_kers": True, "has_ers": False, "kers_max_j": 400e3, "ers_max_j": 0.0}
    h = cs.hybrid_state(make_sample(kers_charge=0.8, kers_lap_kj=100.0), info)
    assert h.lap_limit_kj == pytest.approx(400) and h.lap_used_fraction == pytest.approx(0.25)


def test_battery_alerts():
    keys = lambda s: {a.key: a.level for a in cs.car_alerts(s, HYBRID)}   # noqa: E731
    assert "battery" not in keys(make_sample(kers_charge=0.6))
    assert keys(make_sample(kers_charge=0.15))["battery"] == cs.WARN
    assert keys(make_sample(kers_charge=0.02))["battery"] == cs.CRIT
    assert keys(make_sample(kers_charge=0.6, kers_lap_kj=4000.0))["lap_energy"] == cs.WARN


def test_radio_battery_once_until_recharged():
    r = RadioRules(RadioConfig(flags=False), LANGUAGES["it"])
    said = lambda **kw: [m.text for m in r.on_sample(make_sample(**kw), HYBRID)]   # noqa: E731
    assert said(kers_charge=0.5) == []
    assert said(kers_charge=0.18) == ["Batteria al 18 per cento."]
    assert said(kers_charge=0.17) == []
    assert said(kers_charge=0.03) == ["Batteria scarica."]
    assert said(kers_charge=0.5) == []                       # ricaricata: niente da dire
    assert said(kers_charge=0.19) == ["Batteria al 19 per cento."]
    assert said(kers_charge=0.6, kers_lap_kj=4000.0, completed_laps=3) == ["Energia elettrica del giro finita."]
    assert said(kers_charge=0.6, kers_lap_kj=4000.0, completed_laps=3) == []
    assert RadioRules(RadioConfig(flags=False, hybrid=False)).on_sample(make_sample(kers_charge=0.03), HYBRID) == []
    assert r.on_sample(make_sample(kers_charge=0.03), {}) == []   # auto non ibrida


def test_battery_phrases_in_every_language():
    for lang in LANGUAGES.values():
        assert "{n}" in lang.phrases["battery_low"]
        assert lang.phrases["battery_empty"] and lang.phrases["lap_energy"]


def test_demo_is_a_hybrid():
    d = DemoSource(seed=1)
    d.connect()
    info = d.session_info()
    charges, deployed = [], False
    for _ in range(4000):
        d._advance(0.02)
        s = d.sample()
        h = cs.hybrid_state(s, info)
        charges.append(h.charge)
        deployed |= h.deploying
    assert deployed and min(charges) < max(charges) and 0 < min(charges) and max(charges) <= 1
