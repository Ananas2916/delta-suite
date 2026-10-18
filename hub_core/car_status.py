"""
Stato della vettura per la vista onboard: danni, gomme, freni, sospensioni, carburante.

Solo logica (niente Qt), così si prova nei test e la usa anche l'MCP.
"""

from __future__ import annotations

from dataclasses import dataclass
from statistics import median

CORNERS = ("ant. sx", "ant. dx", "post. sx", "post. dx")
DAMAGE_ZONES = ("anteriore", "posteriore", "sinistra", "destra", "centro")

OK, WARN, CRIT = 0, 1, 2

# soglie sui valori grezzi di carDamage (le stesse usate da CrewChief per AC); da confermare con un urto vero
DAMAGE_THRESHOLDS = (0.05, 0.15, 0.4)       # lieve, medio, grave
TYRE_COLD, TYRE_HOT, TYRE_OVERHEAT = 60.0, 110.0, 125.0
WEAR_WARN, WEAR_CRIT = 96.0, 93.0            # tyreWear di AC: 100 = gomma nuova
BRAKE_WARN, BRAKE_CRIT = 750.0, 850.0
DIRT_WARN = 0.5
DEFAULT_SUSP_TRAVEL = 0.12                   # m, se la shared memory non dà la corsa massima


@dataclass(frozen=True)
class Alert:
    level: int
    text: str
    key: str


def damage_level(v: float) -> int:
    """0 nessuno, 1 lieve, 2 medio, 3 grave."""
    return sum(v >= t for t in DAMAGE_THRESHOLDS)


def damage_enabled(info: dict) -> bool:
    return (info or {}).get("damage_rate", 1.0) > 0


def suspension_fraction(s, info: dict) -> tuple[float, ...]:
    """Corsa delle sospensioni in frazione della corsa massima (0..1)."""
    max_travel = list((info or {}).get("suspension_max_travel") or [])
    out = []
    for i, v in enumerate(s.suspension_travel):
        m = max_travel[i] if i < len(max_travel) and max_travel[i] > 0 else DEFAULT_SUSP_TRAVEL
        out.append(max(0.0, min(1.0, v / m)))
    return tuple(out)


def punctured(pressures) -> list[int]:
    """Ruote con pressione molto più bassa delle altre (o quasi a zero)."""
    ref = median(pressures)
    return [i for i, p in enumerate(pressures) if p < 8.0 or (ref > 5.0 and p < 0.75 * ref)]


def _brakes_simulated(s) -> bool:
    # alcune auto non simulano la temperatura dei freni: resta ferma a quella dell'aria
    return max(s.brake_temp) > s.air_temp + 5.0


def car_alerts(s, info: dict | None = None, fuel_per_lap: float | None = None) -> list[Alert]:
    """Avvisi sullo stato della vettura, dal più grave."""
    info = info or {}
    out: list[Alert] = []

    if damage_enabled(info):
        for zone, v in zip(DAMAGE_ZONES, s.car_damage):
            lvl = damage_level(v)
            if lvl:
                word = ("lieve", "medio", "grave")[lvl - 1]
                out.append(Alert(CRIT if lvl >= 2 else WARN, f"Danno {word} {zone}", f"damage_{zone}"))

    flat = punctured(s.tyre_pressure)
    for i in flat:
        out.append(Alert(CRIT, f"Foratura? Gomma {CORNERS[i]} a {s.tyre_pressure[i]:.1f} psi", f"flat_{i}"))

    for i, t in enumerate(s.tyre_core_temp):
        if t >= TYRE_OVERHEAT:
            out.append(Alert(CRIT, f"Gomma {CORNERS[i]} surriscaldata ({t:.0f}°)", f"tyre_hot_{i}"))
        elif t >= TYRE_HOT:
            out.append(Alert(WARN, f"Gomma {CORNERS[i]} calda ({t:.0f}°)", f"tyre_hot_{i}"))
        elif t < TYRE_COLD and s.speed_kmh > 30:
            out.append(Alert(WARN, f"Gomma {CORNERS[i]} fredda ({t:.0f}°)", f"tyre_cold_{i}"))

    for i, w in enumerate(s.tyre_wear):
        if i in flat or w <= 0:
            continue
        if w < WEAR_CRIT:
            out.append(Alert(CRIT, f"Gomma {CORNERS[i]} consumata ({w:.1f}%)", f"wear_{i}"))
        elif w < WEAR_WARN:
            out.append(Alert(WARN, f"Usura gomma {CORNERS[i]} ({w:.1f}%)", f"wear_{i}"))

    if _brakes_simulated(s):
        for i, t in enumerate(s.brake_temp):
            if t >= BRAKE_CRIT:
                out.append(Alert(CRIT, f"Freno {CORNERS[i]} surriscaldato ({t:.0f}°)", f"brake_{i}"))
            elif t >= BRAKE_WARN:
                out.append(Alert(WARN, f"Freno {CORNERS[i]} molto caldo ({t:.0f}°)", f"brake_{i}"))

    dirty = [CORNERS[i] for i, d in enumerate(s.tyre_dirt) if d >= DIRT_WARN]
    if dirty:
        out.append(Alert(WARN, "Gomme sporche: " + ", ".join(dirty), "dirt"))

    for i, f in enumerate(suspension_fraction(s, info)):
        if f >= 0.97 and (info.get("suspension_max_travel") or [0])[0] > 0:
            out.append(Alert(WARN, f"Sospensione {CORNERS[i]} a fine corsa", f"susp_{i}"))

    if fuel_per_lap and fuel_per_lap > 0:
        laps_left = s.fuel / fuel_per_lap
        if laps_left < 1.0:
            out.append(Alert(CRIT, f"Carburante per meno di un giro ({s.fuel:.1f} L)", "fuel"))
        elif laps_left < 2.0:
            out.append(Alert(WARN, f"Carburante per {laps_left:.1f} giri", "fuel"))

    if s.tyres_out >= 3:
        out.append(Alert(WARN, "Fuori pista", "off_track"))
    if s.pit_limiter and not s.is_in_pit:
        out.append(Alert(WARN, "Limitatore pit inserito", "limiter"))

    out.sort(key=lambda a: -a.level)
    return out


def status_dict(s, info: dict | None = None, fuel_per_lap: float | None = None) -> dict:
    """Riassunto per l'MCP."""
    info = info or {}
    return {
        "danni_attivi": damage_enabled(info),
        "danni": {z: round(v, 3) for z, v in zip(DAMAGE_ZONES, s.car_damage)},
        "sporco_gomme": [round(v, 2) for v in s.tyre_dirt],
        "corsa_sospensioni_pct": [round(f * 100, 1) for f in suspension_fraction(s, info)],
        "limitatore_pit": s.pit_limiter,
        "avvisi": [{"livello": ("ok", "attenzione", "critico")[a.level], "testo": a.text}
                   for a in car_alerts(s, info, fuel_per_lap)],
    }
