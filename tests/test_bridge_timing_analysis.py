import ctypes

import numpy as np
import pytest

from hub_core.ac import csp_bridge as cb
from hub_core.analysis.lap_analysis import compare_laps, find_corners
from hub_core.analysis.timing import TimingTower
from hub_core.model import CarEntry
from tests.conftest import create_mapping, windows_only
from ui.hub_data import validate_proposal


def test_bridge_layout_has_no_padding():
    # same structure as declared in DeltaSuiteBridge.lua: only 4-byte fields and char[] multiples of 4
    fields = cb.BridgeOut._fields_
    expected = sum(ctypes.sizeof(t) for _, t in fields)
    assert ctypes.sizeof(cb.BridgeOut) == expected
    assert cb.BridgeOut.endMarker.offset == expected - 4
    assert ctypes.sizeof(cb.BridgeIn) == sum(ctypes.sizeof(t) for _, t in cb.BridgeIn._fields_)


def test_lua_layout_matches_python():
    lua = (cb.bundled_app_dir() / "DeltaSuiteBridge.lua").read_text(encoding="utf-8")
    for name, _ in cb.BridgeOut._fields_ + cb.BridgeIn._fields_:
        assert f" {name};" in lua or f" {name}[" in lua, name


def _fake_lua_app():
    """The two mappings as the Lua app creates them."""
    return [(None, create_mapping(tag, st)) for tag, st in ((cb.OUT_TAG, cb.BridgeOut), (cb.IN_TAG, cb.BridgeIn))]


@windows_only
def test_bridge_roundtrip_with_fake_app():
    (h1, out), (h2, inp) = _fake_lua_app()
    out.version, out.endMarker = cb.VERSION, cb.END_MARKER
    out.brakeBias, out.absModes, out.setupCount, out.carsCount = 0.58, 4, 1, 2
    out.setupName[0].value = b"CAMBER_LF"
    out.setupLabel[0].value = b"Camber FL"
    out.setupValue[0], out.setupMin[0], out.setupMax[0], out.setupMult[0] = -39, -50, 0, 0.1
    out.carDriver[1].value = "Pàolo".encode()
    bridge = cb.CSPBridge()
    st = bridge.read()
    assert st is not None and st.brake_bias == pytest.approx(0.58)
    assert st.setup[0].name == "CAMBER_LF" and st.setup[0].display == pytest.approx(-3.9)
    assert st.cars[1].driver == "Pàolo"
    seq = bridge.send(cb.CMD_SETUP, -35, "CAMBER_LF")
    assert inp.seq == seq and inp.cmd == cb.CMD_SETUP and inp.name == b"CAMBER_LF" and inp.value == -35
    assert inp.hostBeat > 0

    p, why = validate_proposal("setup", -60, "camber_lf", st)
    assert p is None and "from -50 to 0" in why
    p, _ = validate_proposal("setup", -35, "camber_lf", st)
    assert p.name == "CAMBER_LF" and p.label == "Camber FL"
    p, _ = validate_proposal("brake_bias", 57.5, "", None)
    assert p.value == pytest.approx(0.575)
    out.endMarker = 0
    assert bridge.read() is None and bridge.layout_error
    bridge.disconnect()


def _car(i, progress, best=0, pos=0):
    return CarEntry(i, True, pos, int(progress), progress % 1, 0, 0, best, False, False, 150.0, True,
                       f"P{i}", "gt3")


def test_gap_is_time_since_leader_was_here():
    tt = TimingTower()
    for k in range(0, 101):              # 10 s, 100 s lap: 0.01 laps per second
        t = k * 0.1
        tt.update(t, [_car(0, 1.0 + t * 0.01, pos=1), _car(1, 1.0 + (t - 2.0) * 0.01 if t >= 2 else 0.99, pos=2)])
    rows = tt.standings(10.0, [_car(0, 1.10, pos=1), _car(1, 1.08, pos=2)], race=True, player_index=1)
    assert rows[1].gap_s == pytest.approx(2.0, abs=0.05)
    assert rows[1].interval_s == pytest.approx(2.0, abs=0.05) and rows[1].is_player


def _synthetic_lap(slow_corner=False):
    d = np.arange(0, 3000, 2.0)
    v = np.full_like(d, 220.0)
    for apex, vmin in ((800, 80.0), (2000, 120.0)):
        if slow_corner and apex == 2000:
            vmin = 110.0
        v = np.minimum(v, vmin + np.abs(d - apex) * 0.6)
    t = np.concatenate([[0], np.cumsum(np.diff(d) / (v[1:] / 3.6))])
    brake = np.where(np.gradient(v) < -0.05, 1.0, 0.0)
    gas = np.where(np.gradient(v) >= 0, 1.0, 0.0)
    return {"t": t, "dist": d, "speed": v, "gas": gas, "brake": brake, "rpm": v * 30, "gear": v / 50,
            "steer": v * 0, "x": d, "z": d * 0, "lat_g": v * 0, "lon_g": v * 0}


def test_corner_analysis_finds_slow_corner():
    ref, slow = _synthetic_lap(), _synthetic_lap(slow_corner=True)
    corners = find_corners(ref["speed"], ref["dist"])
    assert [round(c.apex_m) for c in corners] == [800, 2000]
    res = compare_laps(ref, slow, 3000.0)
    assert res["where_you_lose_most"] == [2]
    assert res["corners"][1]["v_min_kmh"] == [120.0, 110.0]
    assert res["final_delta_s"] > 0.1
