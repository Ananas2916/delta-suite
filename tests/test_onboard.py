import ctypes
import re

from hub_core import car_status as cs
from hub_core import csp_bridge as cb
from hub_core import onboard_feed as ob
from hub_core.session_recording import read_samples
from tests.conftest import REAL_LAP

INFO = {"damage_rate": 1.0, "suspension_max_travel": [0.1] * 4}


def test_onboard_layout_matches_lua_in_order():
    lua = (cb.bundled_app_dir() / "DeltaSuiteBridge.lua").read_text(encoding="utf-8")
    block = re.search(r"ONBOARD_LAYOUT = \[\[(.*?)\]\]", lua, re.S).group(1)
    names = re.findall(r"\b(\w+)(?:\[\d+\])?;", block)
    assert names == [n for n, _ in ob.OnboardShared._fields_]
    assert ctypes.sizeof(ob.OnboardShared) == sum(ctypes.sizeof(t) for _, t in ob.OnboardShared._fields_)
    assert f"ONBOARD_VERSION, ONBOARD_END, ONBOARD_SLOTS = {ob.ONBOARD_VERSION}, 0x{ob.END_MARKER:08X}, {ob.SLOTS}" in lua
    # un'etichetta per ogni telecamera gestita in cameraFor (0 = T-cam ... 7 = inseguimento)
    assert len(ob.CAMERAS) == 8


def test_reads_the_frame_before_the_latest():
    assert ob.readable_frame(0) is None and ob.readable_frame(1) is None
    assert ob.readable_frame(5) == 4
    folder = ob.onboard_dir()
    # il file letto (n-1) non è né quello in scrittura (n) né il prossimo (n+1)
    for n in range(2, 10):
        read = ob.frame_file(folder, ob.readable_frame(n))
        assert read not in (ob.frame_file(folder, n), ob.frame_file(folder, n + 1))


def test_onboard_roundtrip_with_fake_app(tmp_path):
    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    k32.CreateFileMappingW.restype = ctypes.c_void_p
    k32.CreateFileMappingW.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_uint32, ctypes.c_uint32,
                                       ctypes.c_uint32, ctypes.c_wchar_p]
    k32.MapViewOfFile.restype = ctypes.c_void_p
    k32.MapViewOfFile.argtypes = [ctypes.c_void_p, ctypes.c_uint32, ctypes.c_uint32, ctypes.c_uint32,
                                  ctypes.c_size_t]
    h = k32.CreateFileMappingW(ctypes.c_void_p(-1), None, 0x04, 0, ctypes.sizeof(ob.OnboardShared), ob.ONBOARD_TAG)
    assert h
    app = ob.OnboardShared.from_address(k32.MapViewOfFile(h, 0xF001F, 0, 0, 0))

    feed = ob.OnboardFeed(tmp_path / "onboard")
    assert feed.request(True, 3, -1, 640, 360, 15)
    assert app.enabled == 1 and app.camera == 3 and app.carIndex == -1 and app.fps == 15
    assert app.folder.decode() == str(tmp_path / "onboard") and app.hostBeat == 1
    assert feed.new_frame() is None                     # nessun fotogramma ancora
    app.frame, app.shotWidth, app.shotHeight, app.status = 7, 640, 360, b"in diretta"
    assert feed.new_frame() == tmp_path / "onboard" / "onboard_0.jpg"     # fotogramma 6
    assert feed.new_frame() is None
    assert feed.info().status == "in diretta"
    feed.disconnect()
    assert app.enabled == 0


def test_healthy_car_has_no_alerts(sample):
    assert cs.car_alerts(sample(), INFO, 2.5) == []


def test_alerts_for_damage_puncture_and_fuel(sample):
    s = sample(car_damage=(0.3, 0.0, 0.0, 0.06, 0.0), tyre_pressure=(27.0, 11.0, 26.9, 27.2), fuel=3.0,
               tyre_dirt=(0.0, 0.0, 1.0, 0.0))
    alerts = cs.car_alerts(s, INFO, 2.5)
    texts = [a.text for a in alerts]
    assert alerts[0].level == cs.CRIT
    assert "Danno medio anteriore" in texts and "Danno lieve destra" in texts
    assert any(t.startswith("Foratura? Gomma ant. dx") for t in texts)
    assert "Carburante per 1.2 giri" in texts
    assert "Gomme sporche: post. sx" in texts
    # con i danni disattivati nel server/offline, carDamage non conta
    assert not any("Danno" in a.text for a in cs.car_alerts(s, {"damage_rate": 0.0}))


def test_brakes_without_temperature_model_are_ignored(sample):
    hot = sample(brake_temp=(900.0,) * 4)
    assert any(a.key.startswith("brake_") for a in cs.car_alerts(hot, INFO))
    flat = sample(brake_temp=(24.0,) * 4, air_temp=24.0)
    assert not any(a.key.startswith("brake_") for a in cs.car_alerts(flat, INFO))


def test_suspension_fraction_falls_back_without_max_travel(sample):
    s = sample(suspension_travel=(0.06,) * 4)
    assert cs.suspension_fraction(s, INFO) == (0.6,) * 4
    assert cs.suspension_fraction(s, {"suspension_max_travel": [0.0] * 4}) == (0.5,) * 4


def test_real_lap_reads_new_fields():
    info, samples = read_samples(REAL_LAP)
    assert "damage_rate" in info and len(info["suspension_max_travel"]) == 4
    s = samples[len(samples) // 2]
    assert len(s.car_damage) == 5 and len(s.tyre_dirt) == 4 and s.pit_limiter is False
    d = cs.status_dict(s, info)
    assert set(d["danni"]) == set(cs.DAMAGE_ZONES)
