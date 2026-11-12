"""
Car status for the onboard view: damage, tyres, brakes, suspension, fuel, hybrid battery.

Logic only (no Qt), so it can be tested and the MCP uses it too.
"""

from __future__ import annotations

from dataclasses import dataclass
from statistics import median

from hub_core.i18n import tr

CORNERS = ("front left", "front right", "rear left", "rear right")
DAMAGE_ZONES = ("front", "rear", "left", "right", "centre")

OK, WARN, CRIT = 0, 1, 2

# thresholds on raw carDamage values (the same CrewChief uses for AC); to be confirmed with a real crash
DAMAGE_THRESHOLDS = (0.05, 0.15, 0.4)       # minor, moderate, severe
TYRE_COLD, TYRE_HOT, TYRE_OVERHEAT = 60.0, 110.0, 125.0
WEAR_WARN, WEAR_CRIT = 96.0, 93.0            # AC tyreWear: 100 = new tyre
BRAKE_WARN, BRAKE_CRIT = 750.0, 850.0
DIRT_WARN = 0.5
DEFAULT_SUSP_TRAVEL = 0.12                   # m, if the shared memory does not give the max travel
BATTERY_WARN, BATTERY_CRIT = 0.20, 0.05      # hybrid battery charge (0..1)
MAX_LAP_LIMIT_KJ = 50_000.0                  # beyond this is AC's "no limit" (e.g. 9.99e16 J on the 499P)


@dataclass(frozen=True)
class Alert:
    level: int
    text: str
    key: str


def damage_level(v: float) -> int:
    """0 none, 1 minor, 2 moderate, 3 severe."""
    return sum(v >= t for t in DAMAGE_THRESHOLDS)


def damage_enabled(info: dict) -> bool:
    return (info or {}).get("damage_rate", 1.0) > 0


def suspension_fraction(s, info: dict) -> tuple[float, ...]:
    """Suspension travel as a fraction of max travel (0..1)."""
    max_travel = list((info or {}).get("suspension_max_travel") or [])
    out = []
    for i, v in enumerate(s.suspension_travel):
        m = max_travel[i] if i < len(max_travel) and max_travel[i] > 0 else DEFAULT_SUSP_TRAVEL
        out.append(max(0.0, min(1.0, v / m)))
    return tuple(out)


def punctured(pressures) -> list[int]:
    """Wheels with much lower pressure than the others (or near zero)."""
    ref = median(pressures)
    return [i for i, p in enumerate(pressures) if p < 8.0 or (ref > 5.0 and p < 0.75 * ref)]


def is_hybrid(info: dict | None) -> bool:
    return bool((info or {}).get("has_ers") or (info or {}).get("has_kers"))


@dataclass(frozen=True)
class HybridState:
    """Battery and ERS/KERS of a hybrid car, as AC provides them."""

    charge: float               # 0..1
    deploying: bool             # electric deploy in progress
    charging: bool
    lap_used_kj: float          # energy used this lap
    lap_limit_kj: float         # per-lap limit (0 = unknown)
    power_mode: int
    power_modes: int            # power maps available (0 = unknown)
    recovery: int
    heat_to_battery: bool

    @property
    def lap_left_kj(self) -> float | None:
        return max(0.0, self.lap_limit_kj - self.lap_used_kj) if self.lap_limit_kj > 0 else None

    @property
    def lap_used_fraction(self) -> float | None:
        return min(1.0, self.lap_used_kj / self.lap_limit_kj) if self.lap_limit_kj > 0 else None

    @property
    def mode_text(self) -> str:
        return tr("deploying") if self.deploying else tr("charging") if self.charging else tr("idle")


def hybrid_state(s, info: dict | None) -> HybridState | None:
    """None if the car is not hybrid. The per-lap limit is the ERS one if present, otherwise KERS."""
    info = info or {}
    if not is_hybrid(info):
        return None
    ers_j, kers_j = (v if 0 < v <= MAX_LAP_LIMIT_KJ * 1000 else 0.0
                     for v in (info.get("ers_max_j", 0.0), info.get("kers_max_j", 0.0)))
    limit_j = (ers_j or kers_j) if info.get("has_ers") else (kers_j or ers_j)
    return HybridState(
        charge=max(0.0, min(1.0, s.kers_charge)),
        deploying=s.kers_input > 0.05,
        charging=s.ers_charging and s.kers_input <= 0.05,
        lap_used_kj=max(0.0, s.kers_lap_kj),
        lap_limit_kj=max(0.0, limit_j / 1000.0),
        power_mode=s.ers_power,
        power_modes=int(info.get("ers_power_modes", 0) or 0),
        recovery=s.ers_recovery,
        heat_to_battery=s.ers_heat_charging,
    )


def _sentence(text: str) -> str:
    return text[:1].upper() + text[1:]


def corner_name(i: int) -> str:
    """Translated wheel name ("front left"...)."""
    return tr(CORNERS[i])


def _brakes_simulated(s) -> bool:
    # some cars do not simulate brake temperature: it stays at air temperature
    return max(s.brake_temp) > s.air_temp + 5.0


def car_alerts(s, info: dict | None = None, fuel_per_lap: float | None = None) -> list[Alert]:
    """Car status alerts, most severe first."""
    info = info or {}
    out: list[Alert] = []

    if damage_enabled(info):
        for zone, v in zip(DAMAGE_ZONES, s.car_damage):
            lvl = damage_level(v)
            if lvl:
                word = tr(("minor", "moderate", "severe")[lvl - 1])
                text = _sentence(tr("{word} {zone} damage", word=word, zone=tr(zone)))
                out.append(Alert(CRIT if lvl >= 2 else WARN, text, f"damage_{zone}"))

    flat = punctured(s.tyre_pressure)
    for i in flat:
        out.append(Alert(CRIT, _sentence(tr("Puncture? {corner} tyre at {p} psi", corner=corner_name(i),
                                            p=f"{s.tyre_pressure[i]:.1f}")), f"flat_{i}"))

    for i, t in enumerate(s.tyre_core_temp):
        if t >= TYRE_OVERHEAT:
            out.append(Alert(CRIT, _sentence(tr("{corner} tyre overheating ({t}°)", corner=corner_name(i),
                                                t=f"{t:.0f}")), f"tyre_hot_{i}"))
        elif t >= TYRE_HOT:
            out.append(Alert(WARN, _sentence(tr("{corner} tyre hot ({t}°)", corner=corner_name(i), t=f"{t:.0f}")),
                             f"tyre_hot_{i}"))
        elif t < TYRE_COLD and s.speed_kmh > 30:
            out.append(Alert(WARN, _sentence(tr("{corner} tyre cold ({t}°)", corner=corner_name(i), t=f"{t:.0f}")),
                             f"tyre_cold_{i}"))

    for i, w in enumerate(s.tyre_wear):
        if i in flat or w <= 0:
            continue
        if w < WEAR_CRIT:
            out.append(Alert(CRIT, _sentence(tr("{corner} tyre worn out ({w}%)", corner=corner_name(i),
                                                w=f"{w:.1f}")), f"wear_{i}"))
        elif w < WEAR_WARN:
            out.append(Alert(WARN, _sentence(tr("{corner} tyre wear ({w}%)", corner=corner_name(i), w=f"{w:.1f}")),
                             f"wear_{i}"))

    if _brakes_simulated(s):
        for i, t in enumerate(s.brake_temp):
            if t >= BRAKE_CRIT:
                out.append(Alert(CRIT, _sentence(tr("{corner} brake overheating ({t}°)", corner=corner_name(i),
                                                    t=f"{t:.0f}")), f"brake_{i}"))
            elif t >= BRAKE_WARN:
                out.append(Alert(WARN, _sentence(tr("{corner} brake very hot ({t}°)", corner=corner_name(i),
                                                    t=f"{t:.0f}")), f"brake_{i}"))

    dirty = [corner_name(i) for i, d in enumerate(s.tyre_dirt) if d >= DIRT_WARN]
    if dirty:
        out.append(Alert(WARN, tr("Dirty tyres: {wheels}", wheels=", ".join(dirty)), "dirt"))

    for i, f in enumerate(suspension_fraction(s, info)):
        if f >= 0.97 and (info.get("suspension_max_travel") or [0])[0] > 0:
            out.append(Alert(WARN, _sentence(tr("{corner} suspension bottoming out", corner=corner_name(i))),
                             f"susp_{i}"))

    if fuel_per_lap and fuel_per_lap > 0:
        laps_left = s.fuel / fuel_per_lap
        if laps_left < 1.0:
            out.append(Alert(CRIT, tr("Fuel for less than a lap ({fuel} L)", fuel=f"{s.fuel:.1f}"), "fuel"))
        elif laps_left < 2.0:
            out.append(Alert(WARN, tr("Fuel for {n} laps", n=f"{laps_left:.1f}"), "fuel"))

    h = hybrid_state(s, info)
    if h is not None:
        if h.charge < BATTERY_CRIT:
            out.append(Alert(CRIT, tr("Battery empty ({pct}%)", pct=f"{h.charge * 100:.0f}"), "battery"))
        elif h.charge < BATTERY_WARN:
            out.append(Alert(WARN, tr("Battery low ({pct}%)", pct=f"{h.charge * 100:.0f}"), "battery"))
        if h.lap_left_kj is not None and h.lap_left_kj <= 0.5:
            out.append(Alert(WARN, tr("Lap electric energy used up"), "lap_energy"))

    if s.tyres_out >= 3:
        out.append(Alert(WARN, tr("Off track"), "off_track"))
    if s.pit_limiter and not s.is_in_pit:
        out.append(Alert(WARN, tr("Pit limiter on"), "limiter"))

    out.sort(key=lambda a: -a.level)
    return out


def status_dict(s, info: dict | None = None, fuel_per_lap: float | None = None) -> dict:
    """Summary for the MCP."""
    info = info or {}
    return {
        "damage_enabled": damage_enabled(info),
        "damage": {z: round(v, 3) for z, v in zip(DAMAGE_ZONES, s.car_damage)},
        "tyre_dirt": [round(v, 2) for v in s.tyre_dirt],
        "suspension_travel_pct": [round(f * 100, 1) for f in suspension_fraction(s, info)],
        "pit_limiter": s.pit_limiter,
        "hybrid": hybrid_dict(hybrid_state(s, info)),
        "alerts": [{"level": ("ok", "warning", "critical")[a.level], "text": a.text}
                   for a in car_alerts(s, info, fuel_per_lap)],
    }


def hybrid_dict(h: HybridState | None) -> dict | None:
    """Battery and ERS for the MCP (None if the car is not hybrid)."""
    if h is None:
        return None
    return {
        "battery_pct": round(h.charge * 100, 1),
        "state": h.mode_text,
        "lap_energy_kj": round(h.lap_used_kj, 1),
        "lap_limit_kj": round(h.lap_limit_kj, 1) or None,
        "power_map": h.power_mode,
        "power_maps": h.power_modes or None,
        "recovery": h.recovery,
        "mguh_to": "battery" if h.heat_to_battery else "engine",
    }
