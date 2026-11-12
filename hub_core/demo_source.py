"""
Simulated telemetry source: lets you use the whole hub without Assetto Corsa.

Closed synthetic track with a speed profile computed from grip (cornering) and
acceleration/braking limits, plus simple models of fuel use, tyre temperature,
pressure and wear, and of a hybrid system (battery, deploy, harvesting under braking,
per-lap energy limit). Exposes the same interface as TelemetryReceiver.
"""

from __future__ import annotations

import math
import random
import time

import numpy as np

from hub_core.model import ACSessionType, ACStatus, TelemetrySample

G = 9.81
GEAR_TOP_KMH = (85.0, 125.0, 165.0, 205.0, 245.0, 290.0)
MAX_RPM = 8200
TANK_L = 70.0
# hybrid: 4 MJ battery, 160 kW deploy up to 3 MJ per lap, up to 260 kW harvest under braking
BATTERY_KJ, DEPLOY_KW, HARVEST_KW, LAP_LIMIT_KJ = 4000.0, 160.0, 260.0, 3000.0
ERS_POWER_MODES = 4


def _build_track(n: int = 2400, length_m: float = 4800.0):
    th = np.linspace(0.0, 2.0 * np.pi, n, endpoint=False)
    x = 900 * np.cos(th) + 260 * np.cos(2 * th) - 120 * np.sin(3 * th)
    z = 520 * np.sin(th) + 160 * np.sin(3 * th) + 90 * np.cos(5 * th)
    seg = np.hypot(np.diff(np.append(x, x[0])), np.diff(np.append(z, z[0])))
    scale = length_m / seg.sum()
    x, z, seg = x * scale, z * scale, seg * scale

    def periodic_grad(a):
        return (np.roll(a, -1) - np.roll(a, 1)) / 2.0

    dx, dz = periodic_grad(x), periodic_grad(z)
    ddx, ddz = periodic_grad(dx), periodic_grad(dz)
    k = (dx * ddz - dz * ddx) / np.power(dx * dx + dz * dz, 1.5)
    k = np.convolve(np.concatenate([k[-15:], k, k[:15]]), np.ones(31) / 31, mode="valid")
    s = np.concatenate([[0.0], np.cumsum(seg)[:-1]])
    return s, seg, x, z, k


def _speed_profile(seg, k, mu=1.75):
    n = len(k)
    v_corner = np.minimum(np.sqrt(mu * G / np.maximum(np.abs(k), 1e-6)), 82.0)
    v = v_corner.copy()
    for _ in range(2):   # two passes to close the lap periodically
        for i in range(n):  # acceleration
            j = (i + 1) % n
            a = max(0.5, 8.5 - 0.0011 * v[i] ** 2)
            v[j] = min(v_corner[j], math.sqrt(v[i] ** 2 + 2 * a * seg[i]))
        for i in range(n - 1, -1, -1):  # braking
            j = (i + 1) % n
            a = 13.0 + 0.0018 * v[j] ** 2
            v[i] = min(v[i], math.sqrt(v[j] ** 2 + 2 * a * seg[i]))
    ax = (np.roll(v, -1) ** 2 - v ** 2) / (2 * seg)
    return v, ax


class DemoSource:
    """Hybrid hypercar simulator on a synthetic track (same interface as TelemetryReceiver)."""

    name = "Demo (simulatore)"
    waiting_message = "Starting the simulator..."
    finished = False

    def __init__(self, speed_factor: float = 1.0, seed: int | None = None):
        self.speed_factor = speed_factor
        self._rng = random.Random(seed)
        self._s, self._seg, self._x, self._z, self._k = _build_track()
        self._length = float(self._s[-1] + self._seg[-1])
        self._v, self._ax = _speed_profile(self._seg, self._k)
        self._connected = False

    # ---- common interface
    def connect(self) -> bool:
        if not self._connected:
            self._reset_session()
            self._connected = True
        return True

    def disconnect(self) -> None:
        self._connected = False

    def session_info(self) -> dict:
        return {
            "source": self.name,
            "car": "demo_hypercar",
            "track": "Demo Circuit",
            "track_length": self._length,
            "max_rpm": MAX_RPM,
            "max_fuel": TANK_L,
            "sector_count": 3,
            "player": "Demo Driver",
            "damage_rate": 1.0,
            "suspension_max_travel": [0.10, 0.10, 0.12, 0.12],
            "has_kers": False,
            "has_ers": True,
            "kers_max_j": 0.0,
            "ers_max_j": LAP_LIMIT_KJ * 1000,
            "ers_power_modes": ERS_POWER_MODES,
        }

    def car_and_track(self) -> tuple[str, str]:
        info = self.session_info()
        return info["car"], info["track"]

    # ---- simulation
    def _reset_session(self):
        self._wall = time.perf_counter()
        self._pos = 0.0
        self._lap_t = 0.0
        self._laps = 0
        self._last_lap_ms = 0
        self._best_lap_ms = 0
        self._sector = 0
        self._last_sector_ms = 0
        self._sector_start = 0.0
        self._fuel = 42.0
        self._tyre_t = [70.0] * 4
        self._brake_t = [250.0] * 4
        self._wear = [100.0] * 4
        self._stint_laps = 0
        self._pit_flag = False
        self._lap_pace = self._new_lap_pace()
        self._packet = 0
        self._battery_kj = BATTERY_KJ * 0.8
        self._lap_kj = 0.0
        self._deploy = 0.0
        self._harvest = 0.0

    def _new_lap_pace(self) -> float:
        # driver variability + tyre degradation + fuel weight effect
        deg = 0.0016 * self._stint_laps + 0.00012 * self._stint_laps ** 2
        fuel_eff = 0.0003 * self._fuel
        return max(0.80, 1.0 - deg - fuel_eff + self._rng.gauss(0.0, 0.0025))

    def _advance(self, dt: float):
        n = len(self._s)
        i = int(np.searchsorted(self._s, self._pos, side="right") - 1) % n
        v = self._v[i] * self._lap_pace
        self._pos += v * dt
        self._lap_t += dt

        # fuel use proportional to throttle
        gas = self._gas(i)
        self._fuel = max(0.0, self._fuel - (0.00055 + 0.0042 * gas) * v * dt / 10.0)

        # hybrid: deploy at full throttle above 120 km/h while there is charge and lap energy left, harvest under braking
        brake_now = self._brake(i)
        can_deploy = self._battery_kj > 20.0 and self._lap_kj < LAP_LIMIT_KJ
        self._deploy = 1.0 if gas >= 0.9 and v > 33.0 and can_deploy else 0.0
        self._harvest = brake_now
        used = DEPLOY_KW * self._deploy * dt
        self._battery_kj = min(BATTERY_KJ, max(0.0, self._battery_kj - used + HARVEST_KW * self._harvest * dt))
        self._lap_kj += used

        # tyre temperatures: tend to a target driven by lateral/braking loads
        ay = v * v * self._k[i] / G
        brake = self._brake(i)
        for w in range(4):
            outside = (ay > 0 and w in (1, 3)) or (ay < 0 and w in (0, 2))
            front = w < 2
            target = 72 + 9 * abs(ay) * (1.5 if outside else 0.6) + (12 * brake if front else 5 * brake)
            target += 0.25 * self._stint_laps
            self._tyre_t[w] += (target - self._tyre_t[w]) * min(1.0, dt / 18.0)
            heat = (110 if front else 75) * brake   # °C/s under braking
            self._brake_t[w] += (heat - (self._brake_t[w] - 150) * 0.035 * (1 + v / 60)) * dt
            self._wear[w] = max(0.0, self._wear[w] - (0.00008 + 0.00025 * abs(ay)) * v * dt / 10.0)

        # sectors at 1/3 and 2/3 of the lap
        frac = (self._pos % self._length) / self._length
        sector = min(2, int(frac * 3))
        if sector != self._sector and self._pos < self._length:
            self._last_sector_ms = int((self._lap_t - self._sector_start) * 1000)
            self._sector_start = self._lap_t
            self._sector = sector

        if self._pos >= self._length:
            self._pos -= self._length
            self._laps += 1
            self._stint_laps += 1
            self._last_lap_ms = int(self._lap_t * 1000)
            self._last_sector_ms = int((self._lap_t - self._sector_start) * 1000)
            if self._best_lap_ms == 0 or self._last_lap_ms < self._best_lap_ms:
                self._best_lap_ms = self._last_lap_ms
            self._lap_t = 0.0
            self._lap_kj = 0.0
            self._sector_start = 0.0
            self._sector = 0
            self._pit_flag = False
            if self._fuel < 6.0 or min(self._wear) < 88.0:
                # simulated pit stop: refuel and new tyres, the next lap is an out-lap
                self._fuel = TANK_L * 0.6
                self._wear = [100.0] * 4
                self._tyre_t = [55.0] * 4
                self._stint_laps = 0
                self._pit_flag = True
            self._lap_pace = self._new_lap_pace()
            if self._pit_flag:
                self._lap_pace *= 0.93

    def _gas(self, i: int) -> float:
        a = self._ax[i]
        if a > 0.3:
            return min(1.0, 0.55 + a / 9.0)
        if a < -1.0:
            return 0.0
        return 0.62

    def _brake(self, i: int) -> float:
        a = self._ax[i]
        return min(1.0, -a / 16.0) if a < -1.0 else 0.0

    def sample(self) -> TelemetrySample:
        now = time.perf_counter()
        dt = min(0.1, now - self._wall) * self.speed_factor
        self._wall = now
        # integrate in small steps even with a high speed_factor
        steps = max(1, int(dt / 0.02))
        for _ in range(steps):
            self._advance(dt / steps)

        n = len(self._s)
        i = int(np.searchsorted(self._s, self._pos, side="right") - 1) % n
        v = self._v[i] * self._lap_pace
        kmh = v * 3.6
        gear = next((g for g, top in enumerate(GEAR_TOP_KMH) if kmh <= top * 0.97), 5)
        rpm = int(max(3200, MAX_RPM * kmh / GEAR_TOP_KMH[gear]))
        ay = v * v * self._k[i] / G
        ax = self._ax[i] / G
        gas, brake = self._gas(i), self._brake(i)
        pressures = tuple(21.2 + (t - 25.0) * 0.10 for t in self._tyre_t)
        downforce = 0.0007 * v * v
        self._packet += 1

        return TelemetrySample(
            t=now,
            packet_id=self._packet,
            status=ACStatus.LIVE,
            session_type=ACSessionType.PRACTICE,
            speed_kmh=kmh,
            rpm=rpm,
            gear=gear + 2,
            gas=gas,
            brake=brake,
            clutch=1.0,
            steer_angle=float(np.clip(self._k[i] * 95.0, -1.0, 1.0)),
            fuel=self._fuel,
            acc_g=(float(ay), 1.0, float(ax)),
            tyre_core_temp=tuple(self._tyre_t),
            tyre_pressure=pressures,
            tyre_wear=tuple(self._wear),
            wheel_slip=tuple(abs(ay) * 0.05 + brake * 0.1 for _ in range(4)),
            brake_temp=tuple(self._brake_t),
            suspension_travel=(0.030 + downforce * 0.004, 0.030 + downforce * 0.004,
                               0.035 + downforce * 0.005, 0.035 + downforce * 0.005),
            ride_height=(0.062 - downforce * 0.0045, 0.078 - downforce * 0.0055),
            tc=0.0,
            abs=0.0,
            drs=0.0,
            kers_charge=self._battery_kj / BATTERY_KJ,
            tyres_out=0,
            air_temp=24.0,
            road_temp=33.0,
            lap_time_ms=int(self._lap_t * 1000),
            last_lap_ms=self._last_lap_ms,
            best_lap_ms=self._best_lap_ms,
            completed_laps=self._laps,
            lap_position=float((self._pos % self._length) / self._length),
            sector_index=self._sector,
            last_sector_ms=self._last_sector_ms,
            is_in_pit=self._pit_flag and self._lap_t < 20.0,
            position=1,
            car_x=float(self._x[i]),
            car_z=float(self._z[i]),
            kers_input=self._deploy,
            kers_lap_kj=self._lap_kj,
            ers_recovery=3,
            ers_power=2,
            ers_heat_charging=self._battery_kj < BATTERY_KJ * 0.6,
            ers_charging=self._harvest > 0.0,
            tyre_compound="Medium (M)",
        )
