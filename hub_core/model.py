"""
Tipi comuni a tutto Delta Suite: stato di AC, campione di telemetria, etichette.

Niente Windows né Qt: lo importano sorgenti dati, analisi, interfaccia e test.
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


Quad = tuple[float, float, float, float]   # valori per ruota: FL, FR, RL, RR


@dataclass(frozen=True)
class TelemetrySample:
    """Un campione di telemetria, indipendente dalla sorgente (AC o simulatore)."""

    t: float                    # time.perf_counter() al momento della lettura
    packet_id: int
    status: ACStatus
    session_type: ACSessionType
    # guida
    speed_kmh: float
    rpm: int
    gear: int                   # convenzione AC: 0=R, 1=N, 2=1a
    gas: float                  # 0..1
    brake: float                # 0..1
    clutch: float               # 0..1 (1 = frizione rilasciata)
    steer_angle: float
    fuel: float                 # litri
    acc_g: tuple[float, float, float]   # laterale, verticale, longitudinale
    # gomme / freni / telaio
    tyre_core_temp: Quad        # °C
    tyre_pressure: Quad         # psi
    tyre_wear: Quad
    wheel_slip: Quad
    brake_temp: Quad            # °C
    suspension_travel: Quad     # m
    ride_height: tuple[float, float]    # anteriore, posteriore (m)
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
    lap_position: float         # 0..1 lungo il giro
    sector_index: int
    last_sector_ms: int
    is_in_pit: bool
    position: int
    car_x: float
    car_z: float
    # campi aggiunti dopo: hanno un default così le sorgenti più vecchie (demo) restano valide
    flag: int = 0               # ACFlag
    session_time_left: float = -1.0   # ms, negativo se la sessione non ha limite
    brake_bias: float = 0.0     # 0..1 quota anteriore
    engine_brake: int = 0
    car_damage: tuple[float, ...] = (0.0,) * 5   # zone: anteriore, posteriore, sinistra, destra, centro
    tyre_dirt: Quad = (0.0,) * 4
    pit_limiter: bool = False


@dataclass
class CarEntry:
    """Un'auto in pista come la descrive l'app CSP (classifica e gap)."""
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
    """Converte la marcia di AC (0=R, 1=N, 2=1a...) in etichetta leggibile."""
    if gear == 0:
        return "R"
    if gear == 1:
        return "N"
    return str(gear - 1)
