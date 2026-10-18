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
    names = re.findall(r"\b(\w+)(?:\[\d+\])*;", block)
    assert names == [n for n, _ in ob.OnboardShared._fields_]
    assert ctypes.sizeof(ob.OnboardShared) == sum(ctypes.sizeof(t) for _, t in ob.OnboardShared._fields_)
    assert (f"ONBOARD_VERSION, ONBOARD_END, ONBOARD_SLOTS, ONBOARD_JPEG_MAX = {ob.ONBOARD_VERSION}, "
            f"0x{ob.END_MARKER:08X}, {ob.SLOTS}, {ob.JPEG_MAX}") in lua
    assert f"'DeltaSuite_Onboard_v{ob.ONBOARD_VERSION}'" in lua and ob.ONBOARD_TAG.endswith(f"_v{ob.ONBOARD_VERSION}")
    assert f"jpeg[{ob.SLOTS}][{ob.JPEG_MAX}]" in block
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
    assert feed.request(True, 3, -1, 640, 360, 15, 1.5, ob.TONEMAP_GAMMA)
    assert app.enabled == 1 and app.camera == 3 and app.carIndex == -1 and app.fps == 15
    assert app.exposure == 1.5 and app.tonemap == ob.TONEMAP_GAMMA
    assert app.folder.decode() == str(tmp_path / "onboard") and app.hostBeat == 1
    assert feed.new_frame() is None                     # nessun fotogramma ancora
    # fotogramma 6 nella mapping (posto 0), 7 pubblicato per ultimo
    jpg = b"\xff\xd8 fotogramma 6 \xff\xd9"
    ctypes.memmove(ctypes.addressof(app) + ob.OnboardShared.jpeg.offset, jpg, len(jpg))
    app.jpegSize[0] = len(jpg)
    app.frame, app.shotWidth, app.shotHeight, app.status, app.gameFps = 7, 640, 360, b"in diretta", 118.5
    assert feed.new_frame() == jpg
    assert feed.new_frame() is None
    assert feed.info().status == "in diretta" and feed.info().game_fps == 118.5
    # fotogramma 7 su file (posto 1): CSP che non sa codificare in memoria
    (tmp_path / "onboard" / "onboard_1.jpg").write_bytes(b"da file")
    app.jpegSize[1] = 0
    app.frame = 8
    assert feed.new_frame() == b"da file"
    feed.disconnect()
    assert app.enabled == 0


class _FakeView:
    """Vista finta: la mapping è un buffer qui, e frame avanza a ogni lettura come farebbe l'app."""

    def __init__(self, frames):
        self.buf = ctypes.create_string_buffer(ctypes.sizeof(ob.OnboardShared))
        self.ptr = ctypes.addressof(self.buf)
        st = ob.OnboardShared.from_address(self.ptr)
        st.version = ob.ONBOARD_VERSION
        frames = iter(frames)

        class Struct:
            def __getattr__(self, name):
                return next(frames) if name == "frame" else getattr(st, name)
        self.struct = Struct()
        self.raw = st

    def close(self):
        pass


def test_frame_overwritten_while_copying_is_dropped(tmp_path):
    jpg = b"\xff\xd8 fotogramma 4 \xff\xd9"
    feed = ob.OnboardFeed(tmp_path)
    for frames, expected in (([5, 5], jpg), ([5, 7], None)):   # 7: l'app sta già riscrivendo il posto 4 % 3
        view = _FakeView(frames)
        ctypes.memmove(view.ptr + ob.OnboardShared.jpeg.offset + (4 % ob.SLOTS) * ob.JPEG_MAX, jpg, len(jpg))
        view.raw.jpegSize[4 % ob.SLOTS] = len(jpg)
        feed._view, feed._last_read = view, None
        assert feed.new_frame() == expected


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
