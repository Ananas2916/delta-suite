"""
Cosa mostrano le pagine "da muretto" (Onboard e Generale): classifica, auto sul GPS, grafica TV, stato vettura.

Solo dati pronti per i widget di ui/widgets; le pagine decidono dove metterli. Il video onboard passa da
`hub.onboard_feed`, uno solo per tutta l'app: lo usa la pagina visibile.
"""

from __future__ import annotations

import time

from hub_core.analysis import car_status as cs
from hub_core.analysis.race_strategy import RaceProgress, best_sectors, fmt_ms, fuel_per_lap, race_progress_for
from hub_core.analysis.track_status import FlagStatus
from hub_core.analysis.timing import fmt_gap
from hub_core.model import ACStatus, gear_label
from ui.theme import C
from ui.widgets.car_status import LEVEL_COLORS
from ui.widgets.hybrid import battery_color
from ui.widgets.sectors import SECTOR_COLORS, fmt_sector
from ui.widgets.view_panel import VIEW_COLORS

STALE_S = 2.0          # senza fotogrammi nuovi da tanto: il video non è più in diretta


def live_state(hub):
    """(campione, info sessione, carburante per giro, avvisi) dell'auto del giocatore."""
    s, info, laps = hub.last_sample, hub.session_info, hub.laps
    fpl = fuel_per_lap(laps) if laps else None
    alerts = cs.car_alerts(s, info, fpl) if s is not None and s.status == ACStatus.LIVE else []
    return s, info, fpl, alerts


def sector_views(hub, s):
    """Riquadri dei settori del giro in corso (o di quello appena chiuso, a inizio giro)."""
    laps = hub.laps
    best = best_sectors(laps, hub.live_lap.count) if laps else [None] * hub.live_lap.count
    return hub.live_lap.views(s, laps[-1].sectors_ms if laps else None, best)


def progress(hub, s) -> RaceProgress | None:
    """Giro e giri che mancano (dal leader), o None senza dati."""
    if s is None:
        return None
    b = hub.bridge_state
    return race_progress_for(s, b.cars if b else [], hub.is_race, hub.session_info.get("extra_lap", False))


def _player_pos(s):
    return s.lap_position if s is not None and s.status == ACStatus.LIVE else None


def flag_status(hub, s) -> FlagStatus | None:
    if s is None or s.status != ACStatus.LIVE:
        return None
    b = hub.bridge_state
    return hub.track.player_flag(_player_pos(s), s.flag, time.monotonic(), cars_known=bool(b and len(b.cars) > 1))


def car_entry(hub, idx: int):
    b = hub.bridge_state
    return next((c for c in (b.cars if b else []) if c.index == idx), None)


def view_rings(car_indexes: list[int]) -> dict[int, str]:
    """Colore del riquadro per ogni auto inquadrata (0 = la tua), nell'ordine dei riquadri."""
    rings = {}
    for k, idx in enumerate(car_indexes):
        rings.setdefault(0 if idx < 0 else idx, VIEW_COLORS[k])
    return rings


def timing_rows(hub, s, rings: dict[int, str]) -> list[tuple]:
    rows = [(r.index, str(r.pos), r.driver or f"auto {r.index}", fmt_gap(r), _interval(r),
             "BOX" if r.in_pit else fmt_ms(r.last_ms), r.is_player, rings.get(r.index))
            for r in hub.standings_rows]
    if not rows and s is not None and s.status == ACStatus.LIVE:     # senza app CSP o in demo: solo tu
        rows = [(0, str(s.position), hub.session_info.get("player") or "Tu", "-", "-",
                 fmt_ms(s.last_lap_ms), True, rings.get(0))]
    return rows


def _interval(r) -> str:
    """Distacco dall'auto davanti (in gara), "-" per il primo."""
    return "-" if r.pos == 1 or r.interval_s is None else f"+{r.interval_s:.1f}"


def gps_cars(hub, s, rings: dict[int, str]) -> list[dict]:
    """Auto per il GPS: posizione sul giro (dall'app CSP; la tua dalla shared memory, più fresca) e, se ci sono,
    le coordinate (servono finché la linea della pista non è pronta)."""
    feed = hub.onboard_feed
    coords = feed.car_positions() if hub.ac_live and feed.connected else {}
    live = s is not None and s.status == ACStatus.LIVE
    if live:
        coords[0] = (s.car_x, s.car_z)
    b = hub.bridge_state
    cars = []
    for c in (b.cars if b else []):
        if not c.connected:
            continue
        me = c.index == 0
        x, z = coords.get(c.index, (None, None))
        cars.append({"idx": c.index, "pos": s.lap_position if me and live else c.spline, "x": x, "z": z,
                     "num": str(c.race_pos) if c.race_pos else "", "me": me, "leader": c.race_pos == 1,
                     "ring": rings.get(c.index), "pit": c.in_pitlane or c.in_pit})
    if not cars and live:                  # senza app CSP o in demo: solo la tua auto
        cars.append({"idx": 0, "pos": s.lap_position, "x": s.car_x, "z": s.car_z,
                     "num": str(s.position) if s.position else "", "me": True, "leader": s.position == 1,
                     "ring": rings.get(0), "pit": s.is_in_pit})
    return cars


def update_gps(hub, gps, s, rings: dict[int, str]) -> None:
    """Linea della pista, zone colorate e auto sul widget GPS (pagine Onboard e Generale)."""
    track = hub.track
    if s is not None and s.status == ACStatus.LIVE:
        gps.add_trail(s.car_x, s.car_z)
    gps.set_track(track.line, track.pit)
    gps.set_zones(track.display_zones(_player_pos(s), s.flag if s is not None else 0))
    gps.set_cars(gps_cars(hub, s, rings))


def car_info_html(hub, s, fpl) -> str:
    """Carburante, batteria, aiuti, bias, altezze: le righe sotto lo schema dell'auto."""
    if s is None:
        return "Nessun dato: avvia l'acquisizione."
    b = hub.bridge_state
    aids = f"ABS {b.abs_mode}/{b.abs_modes}  ·  TC {b.tc_mode}/{b.tc_modes}" if b else \
        f"ABS {s.abs:.1f}  ·  TC {s.tc:.1f}"
    fuel = f"carburante {s.fuel:.1f} L" + (f" (~{s.fuel / fpl:.1f} giri)" if fpl else "")
    h = cs.hybrid_state(s, hub.session_info)
    hybrid = ""
    if h is not None:
        lap = f"  ·  giro {h.lap_used_kj:.0f}/{h.lap_limit_kj:.0f} kJ" if h.lap_limit_kj > 0 else ""
        hybrid = (f"<br><span style='color:{battery_color(h.charge)}'>batteria {h.charge * 100:.0f}%</span>"
                  f"  ·  {h.mode_text}{lap}")
    return (f"{fuel}{hybrid}<br>{aids}  ·  bias {s.brake_bias * 100:.1f}%  ·  freno motore {s.engine_brake}<br>"
            f"altezza da terra ant. {s.ride_height[0] * 1000:.0f} mm  ·  post. {s.ride_height[1] * 1000:.0f} mm"
            + ("<br>limitatore pit inserito" if s.pit_limiter else ""))


def alerts_html(s, alerts, limit: int = 6) -> str:
    if s is None:
        return ""
    if not alerts:
        return f"<span style='color:{C['green']}'>●</span>  Tutto in ordine"
    return "<br>".join(f"<span style='color:{LEVEL_COLORS[a.level]}'>●</span>  {a.text}" for a in alerts[:limit])


def small_hud(hub, s, idx: int, camera: str, car_text: str) -> dict:
    """Riquadri secondari: chi, quale telecamera, distacco e ultimo giro."""
    if idx < 0:
        who = hub.session_info.get("player") or "La mia auto"
        row = next((r for r in hub.standings_rows if r.is_player), None)
        if s is not None:
            who = f"P{s.position}  {who}"
        last = s.last_lap_ms if s is not None else 0
    else:
        entry = car_entry(hub, idx)
        row = next((r for r in hub.standings_rows if r.index == idx), None)
        who = f"P{entry.race_pos}  {entry.driver or 'auto ' + str(idx)}" if entry else car_text
        last = entry.last_lap_ms if entry else 0
    times = [("DISTACCO", fmt_gap(row), None)] if row is not None else []
    times.append(("ULTIMO", fmt_ms(last), None))
    return {"title": who, "camera": camera, "times": times}


def main_hud(hub, s, alerts, idx: int, camera: str, car_text: str) -> dict:
    """Riquadro principale: grafica TV completa (velocità, marcia, giri, pedali, tempi, avviso)."""
    if idx >= 0:
        entry = car_entry(hub, idx)
        row = next((r for r in hub.standings_rows if r.index == idx), None)
        if entry is None:
            return {"title": car_text, "camera": camera}
        times = [("POSIZIONE", f"P{entry.race_pos}", None), ("GIRO", str(entry.lap_count + 1), None),
                 ("TEMPO", fmt_ms(entry.lap_time_ms), None), ("ULTIMO", fmt_ms(entry.last_lap_ms), None),
                 ("MIGLIORE", fmt_ms(entry.best_lap_ms), C["purple"])]
        if row is not None and row.interval_s is not None:
            times.append(("INTERVAL", f"+{row.interval_s:.1f}", None))
        return {"title": f"{entry.driver or 'Auto ' + str(idx)}  ·  {entry.model}", "camera": camera,
                "speed": entry.speed_kmh, "times": times}
    if s is None:
        return {}
    info = hub.session_info
    max_rpm = max(1000, int(info.get("max_rpm") or 9000))
    player = info.get("player") or "Tu"
    total = f"/{s.session_laps}" if hub.is_race and s.session_laps > 0 else ""
    hud = {
        "title": f"{player}  ·  {info.get('car', '')}", "camera": camera,
        "speed": s.speed_kmh, "gear": gear_label(s.gear), "rpm": s.rpm, "rpm_frac": s.rpm / max_rpm,
        "shift": s.rpm > 0.95 * max_rpm, "gas": s.gas, "brake": s.brake, "steer": s.steer_angle,
        "times": [("POSIZIONE", f"P{s.position}", None), ("GIRO", f"{s.completed_laps + 1}{total}"
                                                         + ("  PIT" if s.is_in_pit else ""), None),
                  ("TEMPO", fmt_ms(s.lap_time_ms), None), ("ULTIMO", fmt_ms(s.last_lap_ms), None),
                  ("MIGLIORE", fmt_ms(s.best_lap_ms), C["purple"])],
    }
    delta = hub.live_lap.delta_s
    if delta is not None:
        hud["times"].append(("DELTA", f"{delta:+.2f}",
                             C["red"] if delta > 0.05 else C["green"] if delta < -0.05 else None))
    hud["sectors"] = [(v.label, fmt_sector(v.ms), SECTOR_COLORS[v.state]) for v in sector_views(hub, s)]
    h = cs.hybrid_state(s, info)
    if h is not None:
        hud["battery"], hud["battery_deploy"] = h.charge, h.deploying
    if alerts:
        hud["alert"] = (alerts[0].level, alerts[0].text)
    return hud


def video_placeholder(hub, main: bool, has_image: bool, video_on: bool, view: int = 0) -> str:
    """Perché un riquadro non ha video (vuoto se il video c'è)."""
    if not hub.running:
        return "Acquisizione ferma: avvia la telemetria da Assetto Corsa." if main else ""
    if not hub.ac_live:
        return ("Il video onboard arriva solo da Assetto Corsa. In demo e replay restano grafica, GPS e "
                "stato vettura." if main else "Solo con Assetto Corsa")
    if not video_on:
        return "Video spento: in AC non si rendono le viste in più (più FPS in gioco)."
    feed = hub.onboard_feed
    if not feed.connected:
        return ("App CSP Delta Suite Bridge non collegata o da aggiornare: aggiornala da Box & Assetto."
                if main else "App CSP non collegata")
    inf = feed.info(view)
    if inf is not None and inf.status.startswith("errore"):
        return f"L'app CSP non riesce a rendere l'onboard: {inf.status}"
    if not has_image:
        return "In attesa del primo fotogramma…"
    return ""
