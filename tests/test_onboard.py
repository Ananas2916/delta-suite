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
    assert (f"ONBOARD_VERSION, ONBOARD_END, ONBOARD_SLOTS, ONBOARD_DATA_MAX = {ob.ONBOARD_VERSION}, "
            f"0x{ob.END_MARKER:08X}, {ob.SLOTS}, {ob.DATA_MAX}") in lua
    assert (f"TONEMAP_YEBIS, TRANSPORT_MEMORY, TRANSPORT_SHARED = {ob.TONEMAP_YEBIS}, {ob.TRANSPORT_MEMORY}, "
            f"{ob.TRANSPORT_SHARED}") in lua
    assert ob.DATA_MAX >= 128 + 1280 * 720 * 4 and ob.DATA_MAX % 4 == 0
    assert f"'DeltaSuite_Onboard_v{ob.ONBOARD_VERSION}'" in lua and ob.ONBOARD_TAG.endswith(f"_v{ob.ONBOARD_VERSION}")
    assert f"data[{ob.SLOTS}][{ob.DATA_MAX}]" in block
    # un'etichetta per ogni telecamera gestita in cameraFor (0 = T-cam ... 7 = inseguimento)
    assert len(ob.CAMERAS) == 8


def test_lua_local_functions_defined_before_use():
    # una local function chiamata prima della sua definizione in Lua è una globale nil: errore solo in AC
    lua = (cb.bundled_app_dir() / "DeltaSuiteBridge.lua").read_text(encoding="utf-8")
    code = "\n".join(line.split("--", 1)[0] for line in lua.splitlines())
    for m in re.finditer(r"^local function (\w+)", code, re.M):
        first_use = re.search(rf"(?<![\w.:]){m.group(1)}\(", code)
        assert first_use.start() > m.start(), f"{m.group(1)} usata prima di essere definita"


def test_shared_handle_is_cross_process():
    # sharedHandle(false) è un id interno agli script di AC; per Delta Suite serve crossProcess = true
    lua = (cb.bundled_app_dir() / "DeltaSuiteBridge.lua").read_text(encoding="utf-8")
    assert "pcall(fn, c, true)" in lua and "pcall(fn, c, false)" not in lua


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
    assert feed.request(True, 3, -1, 640, 360, 15, 1.5, ob.TONEMAP_GAMMA, ob.TRANSPORT_MEMORY)
    assert app.enabled == 1 and app.camera == 3 and app.carIndex == -1 and app.fps == 15
    assert app.exposure == 1.5 and app.tonemap == ob.TONEMAP_GAMMA and app.transport == ob.TRANSPORT_MEMORY
    assert app.folder.decode() == str(tmp_path / "onboard") and app.hostBeat == 1
    assert feed.new_frame() is None                     # nessun fotogramma ancora
    # fotogramma 6 nella mapping (posto 0) come DDS, 7 pubblicato per ultimo
    dds = _dds(2, 1, 0x000000FF, b"\x01\x02\x03\xff\x04\x05\x06\xff")
    ctypes.memmove(ctypes.addressof(app) + ob.OnboardShared.data.offset, dds, len(dds))
    app.dataSize[0] = len(dds)
    app.frame, app.shotWidth, app.shotHeight, app.status, app.gameFps = 7, 640, 360, b"in diretta", 118.5
    f = feed.new_frame()
    assert (f.kind, f.width, f.height, f.data) == ("rgba", 2, 1, b"\x01\x02\x03\xff\x04\x05\x06\xff")
    assert feed.new_frame() is None
    assert feed.info().status == "in diretta" and feed.info().game_fps == 118.5
    # fotogramma 7 su file (posto 1): CSP che non sa codificare in memoria
    (tmp_path / "onboard" / "onboard_1.jpg").write_bytes(b"da file")
    app.dataSize[1] = 0
    app.frame = 8
    assert feed.new_frame() == ob.Frame("jpg", b"da file")
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

            def __setattr__(self, name, value):
                setattr(st, name, value)
        self.struct = Struct()
        self.raw = st

    def close(self):
        pass


def _dds(width, height, rmask, pixels, dx10=None):
    """DDS non compresso a 32 bit come quello di ExtraCanvas:encode()."""
    h = bytearray(128)
    h[:4] = b"DDS "
    for off, v in ((4, 124), (8, 0x100F), (12, height), (16, width), (20, width * 4), (76, 32), (80, 0x41),
                   (88, 32), (92, rmask), (96, 0x0000FF00), (100, 0x00FF0000 if rmask == 0xFF else 0xFF),
                   (104, 0xFF000000)):
        h[off:off + 4] = v.to_bytes(4, "little")
    if dx10 is not None:
        h[84:88] = b"DX10"
        h += dx10.to_bytes(4, "little") + bytes(16)
    return bytes(h) + pixels


def test_decode_dds_byte_orders():
    px = bytes(range(16))
    assert ob.decode_dds(_dds(2, 2, 0x000000FF, px)) == ob.Frame("rgba", px, 2, 2, 8)
    assert ob.decode_dds(_dds(2, 2, 0x00FF0000, px)).kind == "bgra"
    assert ob.decode_dds(_dds(2, 2, 0, px, dx10=28)).kind == "rgba"
    assert ob.decode_dds(_dds(2, 2, 0, px, dx10=87)).kind == "bgra"
    for bad in (b"JPEG" + bytes(200), _dds(2, 2, 0x000000FF, px[:8]), _dds(2, 2, 0, px, dx10=10)):
        try:
            ob.decode_dds(bad)
            raise AssertionError("doveva fallire")
        except ValueError:
            pass


def test_frame_overwritten_while_copying_is_dropped(tmp_path):
    dds = _dds(1, 1, 0x000000FF, b"\x10\x20\x30\xff")
    feed = ob.OnboardFeed(tmp_path)
    for frames, ok in (([5, 5], True), ([5, 7], False)):   # 7: l'app sta già riscrivendo il posto 4 % 3
        view = _FakeView(frames)
        ctypes.memmove(view.ptr + ob.OnboardShared.data.offset + (4 % ob.SLOTS) * ob.DATA_MAX, dds, len(dds))
        view.raw.dataSize[4 % ob.SLOTS] = len(dds)
        feed._view, feed._last_read = view, None
        f = feed.new_frame()
        assert (f is not None and f.data == b"\x10\x20\x30\xff") if ok else f is None


def test_shared_texture_failure_falls_back_to_memory(tmp_path, monkeypatch):
    feed = ob.OnboardFeed(tmp_path)
    view = _FakeView([3, 3, 3])
    view.raw.sharedHandleLo = 0x1234
    feed._view = view

    class Broken:
        handle = 0

        def open(self, handle):
            raise OSError("OpenSharedResource non riuscita")

        def close(self):
            pass
    feed._shared = Broken()
    assert feed.new_frame() is None and "OpenSharedResource" in feed.shared_error
    feed.request(True, 0, -1, 640, 360, 15, transport=ob.TRANSPORT_SHARED)
    assert view.raw.transport == ob.TRANSPORT_MEMORY


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
