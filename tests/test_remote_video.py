"""Remote pit wall, hub side: the onboard is rendered only while the page asks for frames, adjustments are proposals."""

import os
import time

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtCore import QObject, QSettings, pyqtSignal  # noqa: E402
from PyQt6.QtGui import QGuiApplication  # noqa: E402

from hub_core.ac.onboard_feed import REMOTE_VIEW, Frame, OnboardInfo  # noqa: E402
from ui import remote_data  # noqa: E402
from ui.remote_data import RemoteAccess  # noqa: E402


@pytest.fixture(scope="module")
def qapp():
    return QGuiApplication.instance() or QGuiApplication([])


class FakeFeed:
    def __init__(self):
        self.reserved, self.beats, self.n = {}, 0, 0
        self.connected = True

    def reserve(self, view, req):
        self.reserved[view] = req

    def release(self, view):
        self.reserved.pop(view, None)

    def is_reserved(self, view):
        return view in self.reserved

    def heartbeat(self):
        self.beats += 1
        return True

    def info(self, view=0):
        return OnboardInfo(self.n, 64, 36, 0, 1.0, 120.0, "ok")

    def latest_frame(self, view):
        self.n += 1
        return self.n, Frame("rgba", bytes([200, 40, 40, 255]) * (64 * 36), 64, 36, 64 * 4)

    def f6_cameras(self):
        return []

    def car_positions(self):
        return {}


class FakeProvider:
    def __init__(self):
        self.proposed = []

    def propose(self, kind, value, name, reason):
        self.proposed.append((kind, value, name, reason))
        return {"accepted": True, "id": 7, "description": f"{kind} {value}"}


class FakeHub(QObject):
    radio_log = pyqtSignal(str, str)
    engineer_started = pyqtSignal(str, str)
    engineer_done = pyqtSignal(str)

    def __init__(self, tmp_path):
        super().__init__()
        self.settings = QSettings(str(tmp_path / "s.ini"), QSettings.Format.IniFormat)
        self.onboard_feed = FakeFeed()
        self.provider = FakeProvider()
        self.running = True
        self.ac_live = True

    def setting(self, key, default, typ=str):
        return self.settings.value(key, default, typ)


@pytest.fixture
def remote(qapp, tmp_path):
    hub = FakeHub(tmp_path)
    ra = RemoteAccess(hub)
    yield ra, hub
    ra.shutdown()


def test_no_request_no_render(remote):
    ra, hub = remote
    ra._video_tick(time.monotonic())
    assert hub.onboard_feed.reserved == {} and hub.onboard_feed.beats == 0


def test_frames_only_while_requested(remote):
    ra, hub = remote
    assert "status" in ra.video_frame(3, -1, 2, 0, 0.0)          # first call: nothing encoded yet
    ra._video_tick(time.monotonic())
    req = hub.onboard_feed.reserved[REMOTE_VIEW]
    assert (req.camera, req.car, req.width, req.height, req.fps) == (3, -1, 640, 360, 20)
    res = ra.video_frame(3, -1, 2, 0, 0.5)
    assert res["jpeg"][:2] == b"\xff\xd8" and res["seq"] >= 1     # a JPEG
    # same frame number already seen: waits, then says why there is nothing new
    assert "jpeg" not in ra.video_frame(3, -1, 2, res["seq"], 0.05)
    # the page stops asking: after the timeout the view is released in AC
    ra._video_t -= remote_data.VIDEO_TIMEOUT_S + 1
    ra._video_tick(time.monotonic())
    assert hub.onboard_feed.reserved == {}


def test_changing_camera_never_serves_the_old_frame(remote):
    ra, hub = remote
    ra.video_frame(0, -1, 1, 0, 0.0)
    ra._video_tick(time.monotonic())
    assert ra.video_frame(0, -1, 1, 0, 0.2).get("jpeg")
    assert "jpeg" not in ra.video_frame(5, -1, 1, 0, 0.0)        # new camera: old JPEG dropped


def test_without_ac_the_page_gets_the_reason(remote):
    ra, hub = remote
    hub.ac_live = False
    ra.video_frame(0, -1, 1, 0, 0.0)
    ra._video_tick(time.monotonic())
    assert hub.onboard_feed.reserved == {}
    assert "Assetto Corsa" in ra.video_frame(0, -1, 1, 0, 0.0)["status"]


def test_adjustments_become_proposals(remote):
    ra, hub = remote
    assert ra.action("Laptop", "adjust", {"what": "brake_bias", "value": 57.5})["ok"]
    kind, value, _name, reason = hub.provider.proposed[-1]
    assert kind == "brake_bias" and abs(value - 0.575) < 1e-9 and "Laptop" in reason
    assert not ra.action("Laptop", "adjust", {"what": "fuel", "value": 1})["ok"]
    assert not ra.action("Laptop", "adjust", {"what": "abs"})["ok"]


def test_radio_audio_kept_for_the_page(remote):
    ra, _hub = remote
    seq = ra.log("radio", "Box this lap", b"RIFF....WAVE")
    assert ra.audio(seq) == b"RIFF....WAVE"
    for i in range(remote_data.AUDIO_KEEP + 1):
        ra.log("radio", f"m{i}", b"x")
    assert ra.audio(seq) is None                                  # only the latest few
