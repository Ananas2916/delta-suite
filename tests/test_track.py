import math
import struct

import pytest

from hub_core.ac.track_map import find_ai_lines, read_ai_line
from hub_core.analysis import car_status as cs
from hub_core.analysis import race_strategy as rs
from hub_core.analysis import track_status as ts
from hub_core.model import ACFlag, CarEntry
from tests.conftest import make_sample

R = 300.0      # pista di prova: un cerchio di 300 m di raggio, ~1885 m


def circle(n=2000, r=R):
    return [(r * math.cos(2 * math.pi * i / n), r * math.sin(2 * math.pi * i / n)) for i in range(n)]


def write_ai(path, pts):
    path.parent.mkdir(parents=True, exist_ok=True)
    data = struct.pack("<4i", 7, len(pts), 0, 0)
    for i, (x, z) in enumerate(pts):
        data += struct.pack("<4fi", x, 1.5, z, float(i), i)
    path.write_bytes(data + b"\x00" * 64)       # dopo i punti AC mette altri dati


def car(i, pos, kmh, laps=3, pitlane=False, connected=True):
    return CarEntry(i, connected, i + 1, laps, pos, 0, 0, 0, pitlane, False, kmh, True, f"P{i}", "lmh")


def test_ai_line_from_track_folder(tmp_path):
    layout = tmp_path / "content" / "tracks" / "ks_barcelona" / "layout_moto" / "ai"
    write_ai(layout / "fast_lane.ai", circle(500))
    write_ai(layout / "pit_lane.ai", [(280.0 - i * 4.0, 10.0) for i in range(50)])   # tratto aperto
    lap, pit = find_ai_lines(tmp_path, "ks_barcelona", "layout_moto")
    assert len(lap) == 500 and len(pit) == 50
    assert lap[0] == pytest.approx((R, 0.0), abs=1e-3)
    # layout senza cartella ai: si usa quella del tracciato, se c'è
    write_ai(tmp_path / "content" / "tracks" / "ks_barcelona" / "ai" / "fast_lane.ai", circle(100))
    assert len(find_ai_lines(tmp_path, "ks_barcelona", "layout_gp")[0]) == 100
    assert find_ai_lines(tmp_path, "nessuna") == ([], [])
    assert find_ai_lines(None, "ks_barcelona") == ([], [])
    (layout / "fast_lane.ai").write_bytes(b"\x07\x00\x00\x00\xff\xff\xff\x7f")
    assert read_ai_line(layout / "fast_lane.ai") == []
    write_ai(layout / "fast_lane.ai", [(i * 500.0, 0.0) for i in range(20)])     # punti lontani: non è un giro
    assert read_ai_line(layout / "fast_lane.ai") == []


def test_track_line_by_lap_position():
    line = ts.TrackLine.from_points(circle())
    assert line.length == pytest.approx(2 * math.pi * R, rel=1e-3)
    assert line.point(0.0) == pytest.approx((R, 0.0), abs=0.5)
    assert line.point(0.25) == pytest.approx((0.0, R), abs=1.0)
    assert line.point(1.25) == pytest.approx(line.point(0.25))
    pts = line.points(0.95, 1.05)       # a cavallo del traguardo
    assert pts[0] == pytest.approx(line.point(0.95)) and pts[-1] == pytest.approx(line.point(0.05))


def test_line_learned_from_positions():
    learner = ts.LineLearner()
    for i, (x, z) in enumerate(circle(3000)):
        learner.add(i / 3000, x, z)
        if i == 1000:
            assert learner.line() is None           # un terzo di giro: ancora niente
    line = learner.line()
    assert line is not None and line.length == pytest.approx(2 * math.pi * R, rel=0.01)
    assert line.point(0.5) == pytest.approx((-R, 0.0), abs=2.0)
    # campioni radi (demo a 30x): un punto ogni ~4 celle basta, i buchi si interpolano
    sparse = ts.LineLearner()
    for i, (x, z) in enumerate(circle(120)):
        sparse.add(i / 120, x, z)
    assert sparse.max_gap() <= 4 and sparse.line().length == pytest.approx(2 * math.pi * R, rel=0.01)


def watch_with_typical_speed():
    w = ts.TrackWatch(circle(), track_length=2 * math.pi * R)
    for k in range(200):                       # dieci auto che girano a 180 km/h: velocità tipiche imparate
        w.update_cars([car(i, (i / 10 + k / 200) % 1, 180.0) for i in range(10)], now=k * 0.1)
    return w


def test_slow_and_stopped_cars_make_zones():
    w = watch_with_typical_speed()
    cars = [car(i, i / 10 + 0.003, 180.0) for i in range(1, 10)]
    w.update_cars(cars + [car(0, 0.0, 180.0)], now=100.0)
    assert w.zones == []
    cars[2] = car(3, 0.303, 60.0)              # un terzo della velocità tipica: lenta
    cars[5] = car(6, 0.603, 2.0)               # ferma
    w.update_cars(cars + [car(0, 0.0, 180.0)], now=101.0)
    kinds = {z.car: z.kind for z in w.zones}
    assert kinds == {3: "yellow", 6: "red"}
    assert w.zones[0].contains(0.29) and not w.zones[0].contains(0.32)
    # la zona resta qualche secondo dopo la ripartenza, poi sparisce
    cars[2], cars[5] = car(3, 0.31, 180.0), car(6, 0.61, 180.0)
    w.update_cars(cars + [car(0, 0.0, 180.0)], now=102.0)
    assert len(w.zones) == 2
    w.update_cars(cars + [car(0, 0.0, 180.0)], now=105.0)
    assert w.zones == []


def test_no_zones_at_start_in_pits_or_after_finish():
    w = watch_with_typical_speed()
    w.update_cars([car(i, 0.98 - i * 0.002, 0.0) for i in range(10)], now=50.0)    # griglia: tutte ferme
    assert w.zones == []
    others = [car(i, i / 10, 180.0) for i in range(1, 10)]
    w.update_cars(others + [car(0, 0.1, 40.0, pitlane=True)], now=60.0)             # corsia box
    assert w.zones == []
    w.update_cars(others + [car(0, 0.1, 40.0, laps=20)], now=61.0, race_laps=20)    # ha finito la gara
    assert w.zones == []
    w.update_cars(others + [car(0, 0.1, 2.0, connected=False)], now=62.0)
    assert w.zones == []


def test_player_flags():
    w = watch_with_typical_speed()
    others = [car(i, i / 10 + 0.003, 180.0) for i in range(1, 10)]
    others[0] = car(1, 0.103, 3.0)                                     # ferma a 0.103
    w.update_cars(others + [car(0, 0.0, 180.0)], now=100.0)
    f = w.player_flag(0.0, ACFlag.NONE, 100.0, cars_known=True)
    assert f.kind == "red" and "DOPPIA GIALLA" in f.text and "a 147 m" in f.text   # (0.103-0.025)*1885
    assert w.player_flag(0.5, ACFlag.NONE, 100.0, cars_known=True) is None   # zona lontana dietro
    # gialla di AC senza auto lente: vale qualche secondo, poi si spegne (era rimasta accesa in gara)
    w.update_cars([car(i, i / 10, 180.0) for i in range(10)], now=110.0)
    assert w.player_flag(0.5, ACFlag.YELLOW, 110.0, cars_known=True).kind == "yellow"
    assert w.player_flag(0.5, ACFlag.YELLOW, 125.0, cars_known=True) is None
    assert w.player_flag(0.5, ACFlag.YELLOW, 125.0, cars_known=False).kind == "yellow"   # senza app CSP
    assert w.player_flag(0.5, ACFlag.BLUE, 126.0, cars_known=True).kind == "blue"
    assert [z.kind for z in w.display_zones(0.5, ACFlag.BLUE)] == ["blue"]


def test_race_progress():
    p = rs.race_progress(25, 9, -1, 97.0, is_race=True)
    assert (p.lap_text, p.to_go, p.to_go_text) == ("10/25", 16, "16 giri")
    assert rs.race_progress(25, 24, -1, 97.0, is_race=True).to_go_text == "ULTIMO GIRO"
    assert rs.race_progress(25, 25, -1, 97.0, is_race=True).to_go_text == "FINITA"
    timed = rs.race_progress(0, 9, 300_000, 97.0, is_race=True, extra_lap=True)
    assert timed.to_go == 5 and timed.to_go_text == "~5 giri" and timed.time_left_s == 300   # ceil(3.09) + 1
    practice = rs.race_progress(0, 3, 1_200_000, 97.0, is_race=False)
    assert practice.to_go is None and practice.time_left_s == 1200 and practice.to_go_text == "—"


def test_hybrid_without_lap_limit():
    # la 499P (mod) dichiara 9.99e16 J: è "nessun limite", non un limite da mostrare
    info = {"has_ers": True, "ers_max_j": 9.99e16, "kers_max_j": 0.0}
    h = cs.hybrid_state(make_sample(kers_charge=1.0, kers_lap_kj=19.0), info)
    assert h.lap_limit_kj == 0 and h.lap_left_kj is None
