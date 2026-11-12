import ctypes
import re

from hub_core.ac import csp_bridge as cb
from hub_core.ac import onboard_feed as ob
from hub_core.ac.recording import read_samples
from hub_core.analysis import car_status as cs
from tests.conftest import REAL_LAP, create_mapping, windows_only

INFO = {"damage_rate": 1.0, "suspension_max_travel": [0.1] * 4}


def _lua(name: str) -> str:
    return (cb.bundled_app_dir() / name).read_text(encoding="utf-8")


def test_onboard_layout_matches_lua_in_order():
    lua = _lua("DeltaSuiteOnboard.lua")
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
    assert (f"local ONBOARD_VIEWS, MAX_CAR_CAMERAS, MAX_CARS_POS = {ob.VIEWS}, {ob.MAX_CAR_CAMERAS}, "
            f"{ob.MAX_CARS}") in lua
    # one label per camera handled in localCamera (0 = T-cam ... 7 = chase), then the F6 ones
    assert len(ob.CAMERAS) == 8 and sorted(i for _g, ids in ob.CAMERA_GROUPS for i in ids) == list(range(8))
    assert f"local CAR_CAMERA_BASE = {ob.CAR_CAMERA_BASE} " in lua


def _lua_names_used_before_declaration(lua: str) -> list[str]:
    """Module locals (functions and variables) used above where they are declared: in Lua they are
    nil globals there, and the error only shows up in AC."""
    code = re.sub(r"\[\[.*?\]\]", "", lua, flags=re.S)                  # long strings (layout, shader)
    code = re.sub(r"'(?:[^'\\\n]|\\.)*'|\"(?:[^\"\\\n]|\\.)*\"", "''", code)    # strings
    code = "\n".join(line.split("--", 1)[0] for line in code.splitlines())
    late = []
    for m in re.finditer(r"^local (?:function (\w+)|([\w, ]+?)\s*=)", code, re.M):
        names = [m.group(1)] if m.group(1) else [n.strip() for n in m.group(2).split(",")]
        for name in names:
            first = re.search(rf"(?<![\w.:]){re.escape(name)}\b", code)
            if first.start() < m.start():
                late.append(name)
    return late


def test_lua_locals_declared_before_use():
    for name in ("DeltaSuiteBridge.lua", "DeltaSuiteOnboard.lua"):
        assert _lua_names_used_before_declaration(_lua(name)) == [], name
    # the check really finds the two bugs that already happened (field and carNodes)
    bad = "local function a()\n  return field(1) + #carNodes\nend\nlocal function field(x) return x end\nlocal carNodes = {}\n"
    assert _lua_names_used_before_declaration(bad) == ["field", "carNodes"]


def test_shared_handle_is_cross_process():
    # sharedHandle(false) is an id internal to AC scripts; Delta Suite needs crossProcess = true
    lua = _lua("DeltaSuiteOnboard.lua")
    assert "pcall(fn, c, true)" in lua and "pcall(fn, c, false)" not in lua


def test_bridge_loads_onboard_module_safely():
    # the video lives in a separate module: an error there must not stop the bridge (setup, radio, confirmations)
    bridge, onboard = _lua("DeltaSuiteBridge.lua"), _lua("DeltaSuiteOnboard.lua")
    assert "pcall(require, 'DeltaSuiteOnboard')" in bridge
    assert "if onboard then onboard.update(dt, sim) end" in bridge
    assert "ONBOARD" not in bridge and "DeltaSuite_Onboard_v" not in bridge
    assert onboard.rstrip().endswith("return M")
    assert "function M.update(dt, sim)" in onboard and "pcall(updateOnboard, dt, sim)" in onboard


def test_app_update_checks_every_file(tmp_path, monkeypatch):
    target = tmp_path / "apps" / "lua" / cb.APP_NAME
    monkeypatch.setattr(cb, "find_ac_root", lambda: tmp_path)
    assert cb.app_needs_update()
    cb.install_app()
    assert not cb.app_needs_update()
    (target / "DeltaSuiteOnboard.lua").write_text("-- old", encoding="utf-8")
    assert cb.app_needs_update()


def test_reads_the_frame_before_the_latest():
    assert ob.readable_frame(0) is None and ob.readable_frame(1) is None
    assert ob.readable_frame(5) == 4
    folder = ob.onboard_dir()
    # the file read (n-1) is neither the one being written (n) nor the next (n+1)
    for n in range(2, 10):
        read = ob.frame_file(folder, ob.readable_frame(n))
        assert read not in (ob.frame_file(folder, n), ob.frame_file(folder, n + 1))
    assert ob.frame_file(folder, 4, 2).name == "onboard_v2_1.jpg"


# wheels of a GT3 in car space, with left towards +x as in AC (FL, FR, RL, RR)
WHEELS = [(0.8, 0.33, 1.3), (-0.8, 0.33, 1.3), (0.8, 0.33, -1.4), (-0.8, 0.33, -1.4)]


def test_f6_cameras_get_readable_names():
    cams = [
        ((0.35, 0.95, -0.6), (0.0, -0.05, 1.0)),   # behind the helmet, looking forward
        ((0.0, 0.75, 0.55), (0.0, 0.0, 1.0)),      # on the dashboard
        ((-0.4, 0.9, -0.1), (0.9, -0.1, 0.2)),     # passenger side, towards the driver
        ((0.0, 1.45, 0.0), (0.0, -0.1, 1.0)),      # above the roof
        ((1.1, 0.6, 0.0), (0.0, 0.0, -1.0)),       # left side, looking back
        ((0.0, 0.5, 2.6), (0.0, 0.0, -1.0)),       # in front of the nose, facing the car
        ((0.0, 0.75, 0.6), (0.0, 0.0, 1.0)),       # another dashboard
    ]
    assert ob.f6_names(cams, WHEELS) == [
        "Cockpit · behind the driver", "Dashboard", "Cockpit · side", "Roof",
        "Side left · rear-facing", "Nose · facing the car", "Dashboard 2"]
    # same cameras with left towards -x: only the side changes
    mirrored = [(-x, y, z) for x, y, z in WHEELS]
    assert ob.f6_names([cams[4]], mirrored) == ["Side right · rear-facing"]
    assert ob.f6_names(cams[:2], None) == ["Camera 1", "Camera 2"]


def test_camera_menu_groups_and_indices():
    menu = ob.camera_menu(["Dashboard", "Roof"])
    headers = [t for t, idx in menu if idx is None]
    assert headers == ["Exterior", "Wheels", "Car (F6)"]
    assert ("T-cam", 0) in menu and ("Chase", 7) in menu and ("Front left wheel", 3) in menu
    assert menu[-2:] == [("Dashboard", ob.CAR_CAMERA_BASE), ("Roof", ob.CAR_CAMERA_BASE + 1)]
    assert "Car (F6)" not in [t for t, _ in ob.camera_menu([])]


@windows_only
def test_onboard_roundtrip_with_fake_app(tmp_path):
    app = create_mapping(ob.ONBOARD_TAG, ob.OnboardShared)

    feed = ob.OnboardFeed(tmp_path / "onboard")
    views = [ob.ViewRequest(True, 3, -1, 640, 360, 15), None, ob.ViewRequest(True, 9, 4, 480, 270, 10)]
    assert feed.request(views, 1.5, ob.TONEMAP_GAMMA, ob.TRANSPORT_MEMORY)
    assert list(app.viewEnabled) == [1, 0, 1, 0] and app.viewCamera[0] == 3 and app.viewCar[0] == -1
    assert (app.viewCamera[2], app.viewCar[2], app.viewWidth[2], app.viewFps[2]) == (9, 4, 480, 10)
    assert app.exposure == 1.5 and app.tonemap == ob.TONEMAP_GAMMA and app.transport == ob.TRANSPORT_MEMORY
    assert app.folder.decode() == str(tmp_path / "onboard") and app.hostBeat == 1
    assert feed.new_frame() is None                     # no frame yet
    # main view: frame 6 in the mapping (slot 0) as DDS, 7 published last
    dds = _dds(2, 1, 0x000000FF, b"\x01\x02\x03\xff\x04\x05\x06\xff")
    ctypes.memmove(ctypes.addressof(app) + ob.OnboardShared.data.offset, dds, len(dds))
    app.dataSize[0] = len(dds)
    app.frame[0], app.shotWidth[0], app.status[0].value, app.gameFps = 7, 640, b"live", 118.5
    f = feed.new_frame()
    assert (f.kind, f.width, f.height, f.data) == ("rgba", 2, 1, b"\x01\x02\x03\xff\x04\x05\x06\xff")
    assert feed.new_frame() is None
    assert feed.info().status == "live" and feed.info().game_fps == 118.5
    # view 2 on file: onboard_v2_<slot>.jpg
    (tmp_path / "onboard" / "onboard_v2_1.jpg").write_bytes(b"view 2")
    app.frame[2] = 5
    assert feed.new_frame(2) == ob.Frame("jpg", b"view 2")
    # car positions for the GPS
    app.carCount, app.carPosX[1], app.carPosZ[1] = 2, 12.5, -40.0
    assert feed.car_positions()[1] == (12.5, -40.0) and len(feed.car_positions()) == 2
    feed.disconnect()
    assert list(app.viewEnabled) == [0, 0, 0, 0]


class _FakeView:
    """Fake view: the mapping is a buffer here, and frame advances at every read as the app would do."""

    def __init__(self, frames):
        self.buf = ctypes.create_string_buffer(ctypes.sizeof(ob.OnboardShared))
        self.ptr = ctypes.addressof(self.buf)
        st = ob.OnboardShared.from_address(self.ptr)
        st.version = ob.ONBOARD_VERSION
        frames = iter(frames)

        class Frames:
            def __getitem__(self, view):
                return next(frames)

        class Struct:
            def __getattr__(self, name):
                return Frames() if name == "frame" else getattr(st, name)

            def __setattr__(self, name, value):
                setattr(st, name, value)
        self.struct = Struct()
        self.raw = st

    def close(self):
        pass


def _dds(width, height, rmask, pixels, dx10=None):
    """Uncompressed 32-bit DDS like the one from ExtraCanvas:encode()."""
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
            raise AssertionError("should have failed")
        except ValueError:
            pass


def test_frame_overwritten_while_copying_is_dropped(tmp_path):
    dds = _dds(1, 1, 0x000000FF, b"\x10\x20\x30\xff")
    feed = ob.OnboardFeed(tmp_path)
    for frames, ok in (([5, 5], True), ([5, 7], False)):   # 7: the app is already rewriting slot 4 % 3
        view = _FakeView(frames)
        ctypes.memmove(view.ptr + ob.OnboardShared.data.offset + (4 % ob.SLOTS) * ob.DATA_MAX, dds, len(dds))
        view.raw.dataSize[4 % ob.SLOTS] = len(dds)
        feed._view, feed._last_read = view, [None] * ob.VIEWS
        f = feed.new_frame()
        assert (f is not None and f.data == b"\x10\x20\x30\xff") if ok else f is None


def test_shared_texture_failure_falls_back_to_memory(tmp_path, monkeypatch):
    feed = ob.OnboardFeed(tmp_path)
    view = _FakeView([3, 3, 3])
    view.raw.sharedHandleLo[0] = 0x1234
    feed._view = view

    class Broken:
        handle = 0

        def open(self, handle):
            raise OSError("OpenSharedResource failed")

        def close(self):
            pass
    feed._shared[0] = Broken()
    assert feed.new_frame() is None and "OpenSharedResource" in feed.shared_error
    feed.request([ob.ViewRequest(True, 0, -1, 640, 360, 15)], transport=ob.TRANSPORT_SHARED)
    assert view.raw.transport == ob.TRANSPORT_MEMORY


def test_healthy_car_has_no_alerts(sample):
    assert cs.car_alerts(sample(), INFO, 2.5) == []


def test_alerts_for_damage_puncture_and_fuel(sample):
    s = sample(car_damage=(0.3, 0.0, 0.0, 0.06, 0.0), tyre_pressure=(27.0, 11.0, 26.9, 27.2), fuel=3.0,
               tyre_dirt=(0.0, 0.0, 1.0, 0.0))
    alerts = cs.car_alerts(s, INFO, 2.5)
    texts = [a.text for a in alerts]
    assert alerts[0].level == cs.CRIT
    assert "Moderate front damage" in texts and "Minor right damage" in texts
    assert any(t.startswith("Puncture? Front right tyre") for t in texts)
    assert "Fuel for 1.2 laps" in texts
    assert "Dirty tyres: rear left" in texts
    # with damage disabled on the server/offline, carDamage does not count
    assert not any("damage" in a.text for a in cs.car_alerts(s, {"damage_rate": 0.0}))


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
    assert set(d["damage"]) == set(cs.DAMAGE_ZONES)
