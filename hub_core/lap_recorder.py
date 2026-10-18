"""Segmenta il flusso di TelemetrySample in giri completi con canali e statistiche."""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from hub_core.model import ACStatus, TelemetrySample

CHANNELS = ("t", "dist", "speed", "gas", "brake", "rpm", "gear", "steer", "x", "z", "lat_g", "lon_g")


@dataclass
class LapData:
    lap_no: int
    lap_time_ms: int
    valid: bool
    sectors_ms: list[int]
    fuel_start: float
    fuel_end: float
    tyre_temp_avg: list[float]
    tyre_press_avg: list[float]
    tyre_wear_end: list[float]
    brake_temp_max: list[float]
    max_speed: float
    channels: dict[str, np.ndarray] = field(repr=False, default_factory=dict)

    @property
    def fuel_used(self) -> float:
        return max(0.0, self.fuel_start - self.fuel_end)


class LapRecorder:
    """Riceve campioni e restituisce un LapData a ogni giro completato."""

    def __init__(self, track_length: float, sector_count: int = 3):
        self.track_length = track_length
        self.sector_count = max(1, sector_count)
        self._laps_done: int | None = None
        self.session_reset = False

    def _start_lap(self, s: TelemetrySample):
        self._buf = {c: [] for c in CHANNELS}
        # giro completo solo se l'abbiamo visto partire: lo dice il cronometro di AC, non la spline
        # (su alcune piste lo zero della spline non coincide con la linea del traguardo)
        self._valid = bool(s.lap_time_ms < 2000 and not s.is_in_pit)
        self._sectors: list[int] = []
        self._sector = s.sector_index
        self._fuel_start = s.fuel
        self._temps: list[tuple] = []
        self._press: list[tuple] = []
        self._brake_max = [0.0] * 4
        self._max_speed = 0.0

    def feed(self, s: TelemetrySample) -> LapData | None:
        self.session_reset = False
        if s.status != ACStatus.LIVE:
            return None

        if self._laps_done is None or s.completed_laps < self._laps_done:
            self.session_reset = self._laps_done is not None
            self._laps_done = s.completed_laps
            self._start_lap(s)
            self._append(s)
            return None

        t_prev = self._buf["t"][-1] if self._buf["t"] else None
        if (s.completed_laps == self._laps_done and t_prev is not None
                and s.lap_time_ms / 1000.0 < t_prev - 1.0):
            if s.lap_time_ms < 500:
                # AC azzera il cronometro ~5 ms prima di incrementare completedLaps:
                # il campione appartiene già al giro nuovo, che parte al prossimo campione.
                return None
            # cronometro ripartito senza giro completato (ritorno ai box, reset): giro buttato
            self._start_lap(s)
            self._valid = False

        finished = None
        if s.completed_laps > self._laps_done:
            lap_ms = s.last_lap_ms if s.last_lap_ms > 0 else int((t_prev or 0.0) * 1000)
            if len(self._sectors) == self.sector_count - 1:
                derived = lap_ms - sum(self._sectors)
                # lastSectorTime può arrivare in ritardo di un aggiornamento: se non torna, vale la differenza
                last = s.last_sector_ms if abs(s.last_sector_ms - derived) <= 5 else derived
                if last > 0:
                    self._sectors.append(last)
            finished = self._finish(s, lap_ms)
            self._laps_done = s.completed_laps
            self._start_lap(s)
        elif s.sector_index != self._sector:
            if s.last_sector_ms > 0:
                self._sectors.append(s.last_sector_ms)
            self._sector = s.sector_index

        self._append(s)
        return finished

    def _append(self, s: TelemetrySample):
        b = self._buf
        dist = s.lap_position * self.track_length
        if b["dist"] and s.lap_time_ms > 10000 and dist < b["dist"][-1] - 0.5 * self.track_length:
            # la spline torna a 0 qualche ms prima che AC chiuda il giro: è ancora fine giro
            # (a inizio giro succede il contrario, e lo sistema clean_lap in analisi)
            dist += self.track_length
        b["t"].append(s.lap_time_ms / 1000.0)
        b["dist"].append(dist)
        b["speed"].append(s.speed_kmh)
        b["gas"].append(s.gas)
        b["brake"].append(s.brake)
        b["rpm"].append(s.rpm)
        b["gear"].append(s.gear - 1)
        b["steer"].append(s.steer_angle)
        b["x"].append(s.car_x)
        b["z"].append(s.car_z)
        b["lat_g"].append(s.acc_g[0])
        b["lon_g"].append(s.acc_g[2])
        if s.is_in_pit or s.tyres_out > 2:
            self._valid = False
        self._temps.append(s.tyre_core_temp)
        self._press.append(s.tyre_pressure)
        self._brake_max = [max(a, b) for a, b in zip(self._brake_max, s.brake_temp)]
        self._max_speed = max(self._max_speed, s.speed_kmh)
        self._last = s

    def _finish(self, s: TelemetrySample, lap_ms: int) -> LapData | None:
        if len(self._buf["t"]) < 10:
            return None
        channels = {c: np.asarray(v, dtype=np.float64) for c, v in self._buf.items()}
        temps = np.asarray(self._temps)
        press = np.asarray(self._press)
        return LapData(
            lap_no=s.completed_laps,
            lap_time_ms=lap_ms,
            valid=self._valid,
            sectors_ms=list(self._sectors[: self.sector_count]),
            fuel_start=self._fuel_start,
            fuel_end=self._last.fuel,
            tyre_temp_avg=[float(v) for v in temps.mean(axis=0)],
            tyre_press_avg=[float(v) for v in press.mean(axis=0)],
            tyre_wear_end=[float(v) for v in self._last.tyre_wear],
            brake_temp_max=[float(v) for v in self._brake_max],
            max_speed=self._max_speed,
            channels=channels,
        )
