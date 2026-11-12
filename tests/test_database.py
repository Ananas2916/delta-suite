import numpy as np

from hub_core.analysis.lap_recorder import CHANNELS, LapData
from hub_core.database import TelemetryDB


def lap(no, ms, valid=True):
    n = 20
    ch = {c: np.linspace(0, 1, n) for c in CHANNELS}
    ch["t"] = np.linspace(0, ms / 1000, n)
    return LapData(no, ms, valid, [ms // 3] * 3, 50.0, 48.0, [85.0] * 4, [27.0] * 4, [99.0] * 4, [500.0] * 4,
                   250.0, ch)


def test_best_laps_across_sessions_for_car_and_track():
    db = TelemetryDB(":memory:")
    a = db.new_session({"car": "gt3", "track": "spa"})
    b = db.new_session({"car": "gt3", "track": "spa"})
    other = db.new_session({"car": "lmh", "track": "spa"})
    for sid, laps in ((a, [lap(1, 139000), lap(2, 137500, valid=False)]), (b, [lap(1, 138200), lap(2, 138900)]),
                      (other, [lap(1, 130000)])):
        for l in laps:
            db.save_lap(sid, l)
    best = db.best_laps("gt3", "spa")
    assert [(x["session_id"], x["lap_no"], x["lap_time_ms"]) for x in best] == [(b, 1, 138200), (b, 2, 138900),
                                                                                 (a, 1, 139000)]
    assert [x["session_id"] for x in db.best_laps("gt3", "spa", exclude_session=b)] == [a]
    assert db.best_laps("gt3", "monza") == []
    assert len(db.lap_channels(b, 1)["t"]) == 20
