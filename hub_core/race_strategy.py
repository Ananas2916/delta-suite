"""Strategia: carburante, finestra pit, timing a settori, previsione degrado gomme."""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

from hub_core.lap_recorder import LapData


def fmt_ms(ms: float | None) -> str:
    if ms is None or ms <= 0 or not math.isfinite(ms):
        return "--:--.---"
    ms = int(round(ms))
    return f"{ms // 60000}:{(ms % 60000) / 1000:06.3f}"


# ----------------------------------------------------------------- carburante

def fuel_per_lap(laps: list[LapData]) -> float | None:
    """Media robusta del consumo sui giri validi (scarta outlier oltre ±25% dalla mediana)."""
    used = np.array([l.fuel_used for l in laps if l.valid and l.fuel_used > 0.05])
    if used.size == 0:
        return None
    med = np.median(used)
    close = used[np.abs(used - med) <= 0.25 * med]
    return float(close.mean()) if close.size else float(med)


@dataclass
class FuelPlan:
    laps_remaining: int
    fuel_needed: float          # per arrivare in fondo con margine
    fuel_to_add: float
    laps_on_current_fuel: float
    stops_needed: int
    pit_window: tuple[int, int] | None   # (primo, ultimo) giro di gara utile per fermarsi
    laps_per_tank: float


def race_laps_remaining(race_laps: int | None, laps_done: int, time_left_s: float | None,
                        avg_lap_s: float | None) -> int:
    if race_laps:
        return max(0, race_laps - laps_done)
    if time_left_s is not None and avg_lap_s:
        # a tempo scaduto si completa il giro in corso
        return int(math.ceil(time_left_s / avg_lap_s)) + 1
    return 0


def fuel_plan(fuel_now: float, per_lap: float, laps_remaining: int, tank: float,
              laps_done: int, margin_laps: float = 1.0) -> FuelPlan:
    needed = (laps_remaining + margin_laps) * per_lap
    to_add = max(0.0, needed - fuel_now)
    laps_now = fuel_now / per_lap if per_lap > 0 else float("inf")
    laps_per_tank = tank / per_lap if per_lap > 0 else float("inf")
    stops = 0 if to_add <= 0 else int(math.ceil(to_add / tank))
    window = None
    if stops >= 1:
        latest = laps_done + int(math.floor(laps_now - margin_laps))
        # il più presto possibile: dopo la sosta il resto va coperto con (stops) pieni
        earliest = laps_done + max(0, int(math.ceil(laps_remaining + margin_laps - stops * laps_per_tank)))
        window = (min(earliest, latest), latest)
    return FuelPlan(laps_remaining, needed, to_add, laps_now, stops, window, laps_per_tank)


# ------------------------------------------------------------------- timing

def best_sectors(laps: list[LapData], count: int = 3) -> list[int | None]:
    best: list[int | None] = [None] * count
    for lap in laps:
        if not lap.valid or len(lap.sectors_ms) != count:
            continue
        for i, s in enumerate(lap.sectors_ms):
            if s > 0 and (best[i] is None or s < best[i]):
                best[i] = s
    return best


def theoretical_best(laps: list[LapData], count: int = 3) -> int | None:
    b = best_sectors(laps, count)
    return sum(b) if all(v is not None for v in b) else None


# ---------------------------------------------------------- degrado gomme

@dataclass
class DegradationForecast:
    stint_laps: np.ndarray      # giri nello stint usati per il fit (1 = primo giro)
    lap_times: np.ndarray       # s, corretti per carburante
    coeffs: np.ndarray          # polinomio in giri-stint
    deg_per_lap: float          # s/giro attuale (derivata a fine stint)
    forecast_laps: np.ndarray
    forecast_times: np.ndarray
    cliff_lap: int | None       # primo giro previsto con perdita > soglia vs migliore


def is_pit_stop_lap(lap: LapData, previous: LapData | None) -> bool:
    """Giro con sosta: rifornimento, oppure gomme nuove (l'usura in AC scende sempre, 100 = nuova)."""
    if lap.valid:
        return False
    refuel = lap.fuel_end > lap.fuel_start + 0.5
    new_tyres = previous is not None and bool(lap.tyre_wear_end) and bool(previous.tyre_wear_end) and \
        max(e - p for e, p in zip(lap.tyre_wear_end, previous.tyre_wear_end)) > 0.5
    return refuel or new_tyres


def current_stint(laps: list[LapData]) -> list[LapData]:
    """Giri dall'ultima sosta (rifornimento o cambio gomme) in poi."""
    stint: list[LapData] = []
    previous = None
    for lap in laps:
        if is_pit_stop_lap(lap, previous):
            stint = []
        else:
            stint.append(lap)
        previous = lap
    return stint


def forecast_degradation(stint: list[LapData], horizon: int = 15, fuel_s_per_l: float = 0.025,
                         cliff_threshold_s: float = 1.5) -> DegradationForecast | None:
    """Fit polinomiale robusto dei tempi giro dello stint, corretti per l'alleggerimento carburante."""
    pts = [(i + 1, l) for i, l in enumerate(stint) if l.valid and l.lap_time_ms > 0]
    if len(pts) < 3:
        return None
    x = np.array([p[0] for p in pts], dtype=float)
    t = np.array([p[1].lap_time_ms / 1000.0 for p in pts])
    fuel = np.array([p[1].fuel_start for p in pts])
    t_corr = t + (fuel - fuel[-1]) * -fuel_s_per_l    # riporta tutti al carico di fine stint

    med = np.median(t_corr)
    keep = t_corr < med * 1.03
    x, t_corr = x[keep], t_corr[keep]
    if len(x) < 3:
        return None
    deg = 2 if len(x) >= 6 else 1
    coeffs = np.polyfit(x, t_corr, deg)
    if deg == 2 and coeffs[0] < 0:     # una parabola concava non ha senso fisico: ricado sul lineare
        coeffs = np.polyfit(x, t_corr, 1)
    poly = np.poly1d(coeffs)
    last = int(x[-1])
    fx = np.arange(last + 1, last + horizon + 1, dtype=float)
    # in previsione il carburante continua a calare: guadagno per giro
    per_lap_fuel = float(np.mean([l.fuel_used for _, l in pts])) if pts else 0.0
    ft = poly(fx) - (fx - last) * per_lap_fuel * fuel_s_per_l
    best = float(np.min(poly(x)))
    cliff = next((int(l) for l, v in zip(fx, ft) if v - best > cliff_threshold_s), None)
    return DegradationForecast(x, t_corr, coeffs, float(np.polyder(poly)(last)), fx, ft, cliff)


def optimal_pit_lap(fc: DegradationForecast, laps_remaining: int, pit_loss_s: float) -> int | None:
    """Giro di stint in cui fermarsi minimizzando il tempo totale (una sosta, gomme nuove = inizio stint)."""
    if laps_remaining <= 1:
        return None
    poly = np.poly1d(fc.coeffs)
    last = int(fc.stint_laps[-1])
    best_total, best_k = None, None
    for k in range(0, laps_remaining):   # k giri ancora su questo treno
        old = poly(np.arange(last + 1, last + k + 1)).sum() if k else 0.0
        new = poly(np.arange(1, laps_remaining - k + 1)).sum()
        total = old + pit_loss_s + new
        if best_total is None or total < best_total:
            best_total, best_k = total, k
    no_stop = poly(np.arange(last + 1, last + laps_remaining + 1)).sum()
    if best_total is None or no_stop <= best_total:
        return None
    return last + best_k
