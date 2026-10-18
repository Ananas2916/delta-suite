import numpy as np
import pytest

from hub_core.analysis.lap_recorder import LapData
from hub_core.analysis.live_lap import LiveLap
from tests.conftest import make_sample

LENGTH = 3000.0


def ref_lap():
    """Giro di riferimento: 3000 m in 90 s a velocità costante."""
    d = np.linspace(0, LENGTH, 300)
    return LapData(1, 90000, True, [30000, 30000, 30000], 50, 48, [85] * 4, [27] * 4, [99] * 4, [500] * 4, 200,
                   channels={"t": d / LENGTH * 90.0, "dist": d})


def test_sectors_fill_as_they_close_and_reset_each_lap():
    live = LiveLap(3)
    live.feed(make_sample(completed_laps=2, sector_index=0, lap_time_ms=10000), LENGTH)
    live.feed(make_sample(completed_laps=2, sector_index=1, lap_time_ms=31000, last_sector_ms=31000), LENGTH)
    live.feed(make_sample(completed_laps=2, sector_index=2, lap_time_ms=62000, last_sector_ms=31500), LENGTH)
    assert live.current == [31000, 31500, None] and live.sector == 2 and live.sector_start_ms == 62500
    live.feed(make_sample(completed_laps=3, sector_index=0, lap_time_ms=200), LENGTH)
    assert live.current == [None, None, None]


def test_sector_views_colors():
    live = LiveLap(3)
    best = [30000, 30000, 30000]
    live.feed(make_sample(completed_laps=2, sector_index=0, lap_time_ms=10000), LENGTH)
    live.feed(make_sample(completed_laps=2, sector_index=1, lap_time_ms=29900, last_sector_ms=29900), LENGTH)
    s = make_sample(completed_laps=2, sector_index=1, lap_time_ms=40000)
    v = live.views(s, [30500, 30500, 30500], best)
    assert [x.state for x in v] == ["best", "current", "empty"]
    assert v[0].delta_ms == -100 and v[1].ms == 10100
    live.feed(make_sample(completed_laps=2, sector_index=2, lap_time_ms=60500, last_sector_ms=30600), LENGTH)
    assert live.views(make_sample(completed_laps=2, sector_index=2, lap_time_ms=61000), None, best)[1].state == "slower"
    # a inizio giro si vedono ancora i tre settori del giro appena chiuso
    live.feed(make_sample(completed_laps=3, sector_index=0, lap_time_ms=1000), LENGTH)
    v = live.views(make_sample(completed_laps=3, sector_index=0, lap_time_ms=1000), [29900, 30600, 29000], best)
    assert [x.ms for x in v] == [29900, 30600, 29000] and [x.state for x in v] == ["best", "slower", "best"]


def test_live_delta_against_reference_lap():
    live = LiveLap(3)
    live.set_reference(ref_lap())
    live.feed(make_sample(completed_laps=1, lap_time_ms=46000, lap_position=0.5), LENGTH)
    assert live.delta_s == pytest.approx(1.0)                  # a metà giro: 46 s contro 45 s
    live.feed(make_sample(completed_laps=1, lap_time_ms=44500, lap_position=0.5), LENGTH)
    assert live.delta_s == pytest.approx(-0.5)
    live.feed(make_sample(completed_laps=2, lap_time_ms=300, lap_position=0.999), LENGTH)
    assert live.delta_s is None                                # appena passato il traguardo: niente salti
    live.reset()
    live.feed(make_sample(completed_laps=1, lap_time_ms=46000, lap_position=0.5), LENGTH)
    assert live.delta_s is None                                # senza riferimento
