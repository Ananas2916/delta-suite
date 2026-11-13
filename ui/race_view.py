"""
What the "pit wall" pages (Onboard and Overview) show: standings, cars on the GPS, TV graphics, car status.

Only data ready for the widgets in ui/widgets; the pages decide where to put it. The onboard video goes through
`hub.onboard_feed`, a single one for the whole app: the visible page uses it.
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
from hub_core.i18n import tr

STALE_S = 2.0          # no new frames for this long: the video is no longer live


def live_state(hub):
    """(sample, session info, fuel per lap, alerts) of the player's car."""
    s, info, laps = hub.last_sample, hub.session_info, hub.laps
    fpl = fuel_per_lap(laps) if laps else None
    alerts = cs.car_alerts(s, info, fpl) if s is not None and s.status == ACStatus.LIVE else []
    return s, info, fpl, alerts


def sector_views(hub, s):
    """Sector boxes of the current lap (or of the lap just closed, at lap start)."""
    laps = hub.laps
    best = best_sectors(laps, hub.live_lap.count) if laps else [None] * hub.live_lap.count
    return hub.live_lap.views(s, laps[-1].sectors_ms if laps else None, best)


def progress(hub, s) -> RaceProgress | None:
    """Lap and laps to go (from the leader), or None without data."""
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
    """View colour for every car on screen (0 = yours), in view order."""
    rings = {}
    for k, idx in enumerate(car_indexes):
        rings.setdefault(0 if idx < 0 else idx, VIEW_COLORS[k])
    return rings


def timing_rows(hub, s, rings: dict[int, str]) -> list[tuple]:
    rows = [(r.index, str(r.pos), r.driver or tr("car {n}", n=r.index), fmt_gap(r), _interval(r),
             tr("PIT") if r.in_pit else fmt_ms(r.last_ms), r.is_player, rings.get(r.index))
            for r in hub.standings_rows]
    if not rows and s is not None and s.status == ACStatus.LIVE:     # without the CSP app or in demo: just you
        rows = [(0, str(s.position), hub.session_info.get("player") or tr("You"), "-", "-",
                 fmt_ms(s.last_lap_ms), True, rings.get(0))]
    return rows


def _interval(r) -> str:
    """Gap to the car ahead (in a race), "-" for the leader."""
    return "-" if r.pos == 1 or r.interval_s is None else f"+{r.interval_s:.1f}"


def gps_cars(hub, s, rings: dict[int, str]) -> list[dict]:
    """Cars for the GPS: lap position (from the CSP app; yours from the shared memory, which is fresher) and, if
    available, the coordinates (needed until the track line is ready)."""
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
    if not cars and live:                  # without the CSP app or in demo: only your car
        cars.append({"idx": 0, "pos": s.lap_position, "x": s.car_x, "z": s.car_z,
                     "num": str(s.position) if s.position else "", "me": True, "leader": s.position == 1,
                     "ring": rings.get(0), "pit": s.is_in_pit})
    return cars


def update_gps(hub, gps, s, rings: dict[int, str]) -> None:
    """Track line, coloured zones and cars on the GPS widget (Onboard and Overview pages)."""
    track = hub.track
    if s is not None and s.status == ACStatus.LIVE:
        gps.add_trail(s.car_x, s.car_z)
    gps.set_track(track.line, track.pit)
    gps.set_zones(track.display_zones(_player_pos(s), s.flag if s is not None else 0))
    gps.set_cars(gps_cars(hub, s, rings))


def car_info_html(hub, s, fpl) -> str:
    """Fuel, battery, aids, bias, ride heights: the lines below the car diagram."""
    if s is None:
        return tr("No data: start the acquisition.")
    b = hub.bridge_state
    aids = f"ABS {b.abs_mode}/{b.abs_modes}  ·  TC {b.tc_mode}/{b.tc_modes}" if b else \
        f"ABS {s.abs:.1f}  ·  TC {s.tc:.1f}"
    fuel = tr("fuel {fuel} L", fuel=f"{s.fuel:.1f}") + (" (~" + tr("{n} laps", n=f"{s.fuel / fpl:.1f}") + ")"
                                                        if fpl else "")
    h = cs.hybrid_state(s, hub.session_info)
    hybrid = ""
    if h is not None:
        lap = "  ·  " + tr("lap {used}/{limit} kJ", used=f"{h.lap_used_kj:.0f}", limit=f"{h.lap_limit_kj:.0f}") \
            if h.lap_limit_kj > 0 else ""
        hybrid = (f"<br><span style='color:{battery_color(h.charge)}'>"
                  + tr("battery {pct}%", pct=f"{h.charge * 100:.0f}") + f"</span>  ·  {h.mode_text}{lap}")
    return (f"{fuel}{hybrid}<br>{aids}  ·  "
            + tr("bias {pct}%", pct=f"{s.brake_bias * 100:.1f}") + "  ·  "
            + tr("engine brake {n}", n=s.engine_brake) + "<br>"
            + tr("ride height front {f} mm  ·  rear {r} mm", f=f"{s.ride_height[0] * 1000:.0f}",
                 r=f"{s.ride_height[1] * 1000:.0f}")
            + ("<br>" + tr("pit limiter on") if s.pit_limiter else ""))


def alerts_html(s, alerts, limit: int = 6) -> str:
    if s is None:
        return ""
    if not alerts:
        return f"<span style='color:{C['green']}'>●</span>  " + tr("All good")
    return "<br>".join(f"<span style='color:{LEVEL_COLORS[a.level]}'>●</span>  {a.text}" for a in alerts[:limit])


def small_hud(hub, s, idx: int, camera: str, car_text: str) -> dict:
    """Secondary views: who, which camera, gap and last lap."""
    if idx < 0:
        who = hub.session_info.get("player") or tr("My car")
        row = next((r for r in hub.standings_rows if r.is_player), None)
        if s is not None:
            who = f"P{s.position}  {who}"
        last = s.last_lap_ms if s is not None else 0
    else:
        entry = car_entry(hub, idx)
        row = next((r for r in hub.standings_rows if r.index == idx), None)
        who = f"P{entry.race_pos}  {entry.driver or tr('car {n}', n=idx)}" if entry else car_text
        last = entry.last_lap_ms if entry else 0
    times = [(tr("GAP"), fmt_gap(row), None)] if row is not None else []
    times.append((tr("LAST"), fmt_ms(last), None))
    return {"title": who, "camera": camera, "times": times}


def main_hud(hub, s, alerts, idx: int, camera: str, car_text: str) -> dict:
    """Main view: full TV graphics (speed, gear, RPM, pedals, times, alert)."""
    if idx >= 0:
        entry = car_entry(hub, idx)
        row = next((r for r in hub.standings_rows if r.index == idx), None)
        if entry is None:
            return {"title": car_text, "camera": camera}
        times = [(tr("POSITION"), f"P{entry.race_pos}", None), (tr("LAP"), str(entry.lap_count + 1), None),
                 (tr("TIME"), fmt_ms(entry.lap_time_ms), None), (tr("LAST"), fmt_ms(entry.last_lap_ms), None),
                 (tr("BEST"), fmt_ms(entry.best_lap_ms), C["purple"])]
        if row is not None and row.interval_s is not None:
            times.append((tr("INTERVAL"), f"+{row.interval_s:.1f}", None))
        return {"title": f"{entry.driver or tr('Car {n}', n=idx)}  ·  {entry.model}", "camera": camera,
                "speed": entry.speed_kmh, "times": times}
    if s is None:
        return {}
    info = hub.session_info
    max_rpm = max(1000, int(info.get("max_rpm") or 9000))
    player = info.get("player") or tr("You")
    total = f"/{s.session_laps}" if hub.is_race and s.session_laps > 0 else ""
    hud = {
        "title": f"{player}  ·  {info.get('car', '')}", "camera": camera,
        "speed": s.speed_kmh, "gear": gear_label(s.gear), "rpm": s.rpm, "rpm_frac": s.rpm / max_rpm,
        "shift": s.rpm > 0.95 * max_rpm, "gas": s.gas, "brake": s.brake, "steer": s.steer_angle,
        "times": [(tr("POSITION"), f"P{s.position}", None), (tr("LAP"), f"{s.completed_laps + 1}{total}"
                                                            + ("  " + tr("PIT") if s.is_in_pit else ""), None),
                  (tr("TIME"), fmt_ms(s.lap_time_ms), None), (tr("LAST"), fmt_ms(s.last_lap_ms), None),
                  (tr("BEST"), fmt_ms(s.best_lap_ms), C["purple"])],
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
    """Why a view has no video (empty if there is video)."""
    if not hub.running:
        return tr("Acquisition stopped: start telemetry from Assetto Corsa.") if main else ""
    if not hub.ac_live:
        return (tr("Onboard video only comes from Assetto Corsa. In demo and replay you still get graphics, GPS "
                   "and car status.") if main else tr("Assetto Corsa only"))
    if not video_on:
        return tr("Video off: AC renders no extra views (more FPS in game).")
    feed = hub.onboard_feed
    if not feed.connected:
        return (tr("Delta Suite Bridge CSP app not connected or outdated: update it from Pit & Setup.")
                if main else tr("CSP app not connected"))
    inf = feed.info(view)
    if inf is not None and inf.status.startswith("error"):
        return tr("The CSP app cannot render the onboard: {status}", status=inf.status)
    if not has_image:
        return tr("Waiting for the first frame…")
    return ""


# ------------------------------------------------------------------ live strip (top of the live views)

class GapTrend:
    """Gap to the car ahead and behind lap by lap, to say whether it is closing ("-0.3/lap")."""

    def __init__(self):
        self._lap = -1
        self._prev: dict[str, float] = {}     # driver -> gap at the previous lap
        self.trend: dict[str, float] = {}     # driver -> change per lap (negative = closing)

    def reset(self):
        self.__init__()

    def update(self, lap: int, gaps: dict[str, float]) -> None:
        if lap == self._lap:
            return
        if self._lap >= 0 and lap == self._lap + 1:
            self.trend = {d: g - self._prev[d] for d, g in gaps.items() if d in self._prev}
        else:
            self.trend = {}
        self._lap, self._prev = lap, dict(gaps)


def _neighbours(rows):
    """(row ahead, my row, row behind) in the standings, or Nones."""
    me = next((i for i, r in enumerate(rows) if r.is_player), None)
    if me is None:
        return None, None, None
    return (rows[me - 1] if me > 0 else None, rows[me], rows[me + 1] if me + 1 < len(rows) else None)


def _trend_text(change: float | None, ahead: bool) -> str:
    if change is None or abs(change) < 0.05:
        return tr("steady") if change is not None else ""
    closing = change < 0
    if ahead:
        return tr("closing {s} a lap", s=f"{abs(change):.1f}") if closing else tr("losing {s} a lap", s=f"{abs(change):.1f}")
    return tr("he closes {s} a lap", s=f"{abs(change):.1f}") if closing else tr("you pull {s} a lap", s=f"{abs(change):.1f}")


def strip_values(hub, trend: GapTrend) -> dict:
    """What the live strip shows: position, lap and delta, gaps ahead/behind with the trend, fuel, battery, flag.
    Values are text plus a colour key ("good", "bad", "warn" or "")."""
    s = hub.last_sample
    out = {"pos": "–", "lap_title": tr("Lap"), "lap_time": "–", "delta": "", "delta_kind": "",
           "ahead_title": tr("Ahead"), "ahead": "–", "ahead_sub": "", "behind_title": tr("Behind"), "behind": "–",
           "behind_sub": "", "fuel": "–", "fuel_sub": "", "fuel_kind": "", "battery": None, "battery_sub": "",
           "flag": None}
    if s is None or s.status != ACStatus.LIVE:
        return out
    prog = progress(hub, s)
    out["pos"] = f"P{s.position}" if s.position else "–"
    lap_text = prog.lap_text if prog is not None and hub.is_race else str(s.completed_laps + 1)
    out["lap_title"] = tr("Lap {n}", n=lap_text)
    out["lap_time"] = fmt_ms(s.lap_time_ms)[:-2] if s.lap_time_ms > 0 else "–"
    d = hub.live_lap.delta_s
    if d is not None:
        out["delta"] = tr("{d} on best", d=f"{d:+.2f}")
        out["delta_kind"] = "good" if d <= 0 else "bad"

    ahead, me, behind = _neighbours(list(hub.standings_rows))
    gaps = {}
    if ahead is not None and me is not None and me.interval_s is not None:
        gaps[ahead.driver] = me.interval_s
    if behind is not None and behind.interval_s is not None:
        gaps[behind.driver] = behind.interval_s
    trend.update(s.completed_laps, gaps)
    if ahead is not None:
        out["ahead_title"] = tr("Ahead · {name}", name=ahead.driver)
        if me is not None and me.interval_s is not None:
            out["ahead"] = f"+{me.interval_s:.1f}"
        out["ahead_sub"] = _trend_text(trend.trend.get(ahead.driver), True)
    if behind is not None:
        out["behind_title"] = tr("Behind · {name}", name=behind.driver)
        if behind.interval_s is not None:
            out["behind"] = f"−{behind.interval_s:.1f}"
        out["behind_sub"] = _trend_text(trend.trend.get(behind.driver), False)

    out["fuel"] = f"{s.fuel:.1f} L"
    fpl = fuel_per_lap(hub.laps) if hub.laps else None
    if fpl:
        laps_left = s.fuel / fpl
        if prog is not None and prog.to_go:
            margin = laps_left - prog.to_go
            out["fuel_sub"] = tr("{n} laps of margin", n=f"{margin:+.1f}")
            out["fuel_kind"] = "good" if margin >= 1 else "warn" if margin >= 0 else "bad"
        else:
            out["fuel_sub"] = tr("{n} laps of fuel", n=f"{laps_left:.1f}")
    hy = cs.hybrid_state(s, hub.session_info)
    if hy is not None:
        out["battery"] = f"{hy.charge * 100:.0f}%"
        out["battery_sub"] = (tr("deploying") if hy.deploying else tr("charging") if hy.charging
                              else tr("full: ready to attack") if hy.charge > 0.8 else "")
    flag = flag_status(hub, s)
    out["flag"] = (flag.kind, flag.text) if flag is not None else ("green", tr("Green"))
    return out
