"""
Types shared by all of Delta Suite: AC status, telemetry sample, labels.

No Windows and no Qt: imported by data sources, analysis, UI and tests.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum


class ACStatus(IntEnum):
    OFF = 0
    REPLAY = 1
    LIVE = 2
    PAUSE = 3


class ACSessionType(IntEnum):
    UNKNOWN = -1
    PRACTICE = 0
    QUALIFY = 1
    RACE = 2
    HOTLAP = 3
    TIME_ATTACK = 4
    DRIFT = 5
    DRAG = 6


class ACFlag(IntEnum):
    NONE = 0
    BLUE = 1
    YELLOW = 2
    BLACK = 3
    WHITE = 4
    CHECKERED = 5
    PENALTY = 6


Quad = tuple[float, float, float, float]   # per-wheel values: FL, FR, RL, RR


@dataclass(frozen=True)
class TelemetrySample:
    """One telemetry sample, independent of the source (AC or simulator)."""

    t: float                    # time.perf_counter() at read time
    packet_id: int
    status: ACStatus
    session_type: ACSessionType
    # driving
    speed_kmh: float
    rpm: int
    gear: int                   # AC convention: 0=R, 1=N, 2=1st
    gas: float                  # 0..1
    brake: float                # 0..1
    clutch: float               # 0..1 (1 = clutch released)
    steer_angle: float
    fuel: float                 # litres
    acc_g: tuple[float, float, float]   # lateral, vertical, longitudinal
    # tyres / brakes / chassis
    tyre_core_temp: Quad        # °C
    tyre_pressure: Quad         # psi
    tyre_wear: Quad
    wheel_slip: Quad
    brake_temp: Quad            # °C
    suspension_travel: Quad     # m
    ride_height: tuple[float, float]    # front, rear (m)
    tc: float
    abs: float
    drs: float
    kers_charge: float
    tyres_out: int
    air_temp: float
    road_temp: float
    # timing
    lap_time_ms: int
    last_lap_ms: int
    best_lap_ms: int
    completed_laps: int
    lap_position: float         # 0..1 along the lap
    sector_index: int
    last_sector_ms: int
    is_in_pit: bool
    position: int
    car_x: float
    car_z: float
    # fields added later: they have a default so older sources (demo) stay valid
    flag: int = 0               # ACFlag
    session_time_left: float = -1.0   # ms, negative if the session has no time limit
    brake_bias: float = 0.0     # 0..1 front share
    engine_brake: int = 0
    car_damage: tuple[float, ...] = (0.0,) * 5   # zones: front, rear, left, right, centre
    tyre_dirt: Quad = (0.0,) * 4
    pit_limiter: bool = False
    # hybrids (only if the static page says hasKERS/hasERS)
    kers_input: float = 0.0     # electric deploy 0..1
    kers_lap_kj: float = 0.0    # energy used this lap (kJ)
    ers_recovery: int = 0       # recovery level
    ers_power: int = 0          # power level (deploy map)
    ers_heat_charging: bool = False   # MGU-H to the battery (otherwise to the engine)
    ers_charging: bool = False
    session_laps: int = 0       # session laps (numberOfLaps), 0 if timed or unlimited
    tyre_compound: str = ""     # fitted compound, as the car names it (e.g. "Medium (M)")


@dataclass
class CarEntry:
    """A car on track as described by the CSP app (standings and gaps)."""
    index: int
    connected: bool
    race_pos: int
    lap_count: int
    spline: float
    lap_time_ms: int
    last_lap_ms: int
    best_lap_ms: int
    in_pitlane: bool
    in_pit: bool
    speed_kmh: float
    last_lap_valid: bool
    driver: str
    model: str

    @property
    def progress(self) -> float:
        return self.lap_count + self.spline


def gear_label(gear: int) -> str:
    """Convert AC's gear (0=R, 1=N, 2=1st...) into a readable label."""
    if gear == 0:
        return "R"
    if gear == 1:
        return "N"
    return str(gear - 1)
