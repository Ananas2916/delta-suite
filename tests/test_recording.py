import time

import pytest

from hub_core.ac_shared_memory import SPageFileGraphic, SPageFilePhysics, SPageFileStatic, put_wstr
from hub_core.model import ACStatus
from hub_core.session_recording import ReplaySource, SessionRecorder, read_samples


def _pages(i):
    phy, gfx = SPageFilePhysics(), SPageFileGraphic()
    phy.packetId, phy.speedKmh, phy.fuel = i, 100.0 + i, 50.0 - i * 0.01
    gfx.status, gfx.iCurrentTime, gfx.normalizedCarPosition = int(ACStatus.LIVE), i * 16, i / 1000
    return phy, gfx


def test_roundtrip(tmp_path):
    st = SPageFileStatic()
    put_wstr(st, "carModel", "car_x")
    put_wstr(st, "track", "track_y")
    st.trackSPlineLength, st.sectorCount = 3000.0, 3
    path = tmp_path / "s.dsr"
    rec = SessionRecorder(path, st)
    for i in range(500):
        rec.write(*_pages(i), t=rec._t0 + i / 60)
    rec.close()
    info, samples = read_samples(path)
    assert info["car"] == "car_x" and info["track_length"] == 3000.0
    assert len(samples) == 500
    assert samples[123].speed_kmh == 223.0
    assert samples[123].lap_time_ms == 123 * 16
    assert samples[-1].t == pytest.approx(499 / 60)


def test_replay_source_plays_fast_and_ends(tmp_path):
    rec = SessionRecorder(tmp_path / "r.dsr", SPageFileStatic())
    for i in range(120):        # 2 s di dati
        rec.write(*_pages(i), t=rec._t0 + i / 60)
    rec.close()
    src = ReplaySource(tmp_path / "r.dsr", speed_factor=20.0)
    assert src.connect()
    seen = []
    deadline = time.perf_counter() + 2.0
    while not src.finished and time.perf_counter() < deadline:
        seen.append(src.sample())
        time.sleep(0.005)
    assert src.finished
    assert seen[-1].status == ACStatus.OFF
    assert seen[-1].packet_id == 119
    assert not src.connect()
