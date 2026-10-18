import ctypes
import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("DELTA_MUTE", "1")

from hub_core.model import ACSessionType, ACStatus, TelemetrySample  # noqa: E402

DATA = ROOT / "tests" / "data"

# prove con file mapping vere (come quelle di AC e dell'app CSP): solo su Windows
windows_only = pytest.mark.skipif(sys.platform != "win32", reason="file mapping di Windows")


def create_mapping(tag: str, struct_type):
    """Crea una mapping come farebbe l'app Lua (INVALID_HANDLE_VALUE = file di paging) e la restituisce
    come struttura ctypes. Resta aperta fino alla fine del processo di test."""
    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    k32.CreateFileMappingW.restype = ctypes.c_void_p
    k32.CreateFileMappingW.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_uint32, ctypes.c_uint32,
                                       ctypes.c_uint32, ctypes.c_wchar_p]
    k32.MapViewOfFile.restype = ctypes.c_void_p
    k32.MapViewOfFile.argtypes = [ctypes.c_void_p, ctypes.c_uint32, ctypes.c_uint32, ctypes.c_uint32,
                                  ctypes.c_size_t]
    h = k32.CreateFileMappingW(ctypes.c_void_p(-1), None, 0x04, 0, ctypes.sizeof(struct_type), tag)
    assert h
    return struct_type.from_address(k32.MapViewOfFile(h, 0xF001F, 0, 0, 0))


REAL_LAP = DATA / "redbullring_bmw_m4_gt3_1lap.dsr"

_BASE = dict(
    t=0.0, packet_id=0, status=ACStatus.LIVE, session_type=ACSessionType.PRACTICE, speed_kmh=150.0, rpm=6000,
    gear=4, gas=1.0, brake=0.0, clutch=1.0, steer_angle=0.0, fuel=50.0, acc_g=(0.0, 1.0, 0.0),
    tyre_core_temp=(85.0,) * 4, tyre_pressure=(27.0,) * 4, tyre_wear=(100.0,) * 4, wheel_slip=(0.0,) * 4,
    brake_temp=(300.0,) * 4, suspension_travel=(0.05,) * 4, ride_height=(0.06, 0.07), tc=0.0, abs=0.0,
    drs=0.0, kers_charge=0.0, tyres_out=0, air_temp=24.0, road_temp=32.0, lap_time_ms=0, last_lap_ms=0,
    best_lap_ms=0, completed_laps=0, lap_position=0.0, sector_index=0, last_sector_ms=0, is_in_pit=False,
    position=1, car_x=0.0, car_z=0.0,
)


def make_sample(**kw) -> TelemetrySample:
    return TelemetrySample(**{**_BASE, **kw})


@pytest.fixture
def sample():
    return make_sample
