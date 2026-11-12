from hub_core.ac.recording import RecordingReader, ReplaySource, SessionRecorder, read_samples
from hub_core.ac.shared_memory import SPageFileGraphic, SPageFilePhysics, SPageFileStatic, put_wstr
from hub_core.model import CarEntry
from tests.conftest import REAL_LAP


def car(i, pos, spline):
    return CarEntry(i, True, pos, 3, spline, 1000, 90000, 89000, False, i == 2, 180.5, True, f"Driver {i}", "gt3")


def test_recording_keeps_rivals_and_replays_them(tmp_path):
    st = SPageFileStatic()
    put_wstr(st, "carModel", "gt3")
    path = tmp_path / "race.dsr"
    rec = SessionRecorder(path, st)
    for k in range(5):
        phy, gfx = SPageFilePhysics(), SPageFileGraphic()
        phy.speedKmh, gfx.status = 100.0 + k, 2
        rec.write(phy, gfx, rec._t0 + k * 0.15)
        rec.write_cars([car(0, 2, 0.1 * k), car(2, 1, 0.2 + 0.1 * k)], rec._t0 + k * 0.15)
    rec.close()

    kinds = [r[0] for r in RecordingReader(path).records()]
    assert kinds.count("sample") == 5 and kinds.count("cars") == 3      # cars at most every 0.2 s
    info, samples = read_samples(path)
    assert info["car"] == "gt3" and [round(s.speed_kmh) for s in samples] == [100, 101, 102, 103, 104]

    src = ReplaySource(path, speed_factor=1000)
    assert src.connect()
    src.sample()
    state = src.bridge_state()
    assert [c.driver for c in state.cars] == ["Driver 0", "Driver 2"] and state.cars[1].in_pit
    assert state.cars[1].speed_kmh == 180.5 and state.cars[0].race_pos == 2


def test_old_recordings_without_rivals_still_replay():
    src = ReplaySource(REAL_LAP)
    assert src.connect() and src.sample() is not None and src.bridge_state() is None
    src.disconnect()
