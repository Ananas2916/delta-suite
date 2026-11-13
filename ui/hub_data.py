"""Hub data for the agent (MCP tools) and change proposals awaiting confirmation."""

from __future__ import annotations

import itertools
import threading
import time
from dataclasses import dataclass

from hub_core.ac.csp_bridge import (
    CMD_ABS, CMD_BRAKE_BIAS, CMD_ENGINE_BRAKE, CMD_SETUP, CMD_TC, BridgeState,
)
from hub_core.ac.setup_files import latest_setup, read_setup
from hub_core.analysis import race_strategy as rs
from hub_core.analysis.car_status import status_dict
from hub_core.analysis.lap_analysis import compare_laps
from hub_core.analysis.lap_recorder import LapData
from ai_engine.lang import Language, speak_number
from hub_core.i18n import tr

KIND_LABELS = {"brake_bias": "Brake bias", "abs": "ABS", "tc": "TC", "engine_brake": "Engine brake",
               "setup": "Setup"}
KIND_CMD = {"brake_bias": CMD_BRAKE_BIAS, "abs": CMD_ABS, "tc": CMD_TC, "engine_brake": CMD_ENGINE_BRAKE,
            "setup": CMD_SETUP}


@dataclass
class Proposal:
    id: int
    kind: str
    value: float
    name: str
    reason: str
    label: str = ""
    created: float = 0.0
    status: str = "pending"       # pending | in pits | sent | applied | error | discarded
    result: str = ""
    seq: int | None = None

    def describe(self) -> str:
        if self.kind == "brake_bias":
            return tr("Brake bias {pct}%", pct=f"{self.value * 100:.1f}")
        if self.kind == "setup":
            return f"{self.label or self.name} → {int(self.value)}"
        return f"{tr(KIND_LABELS.get(self.kind, self.kind))} {int(self.value)}"

    def spoken(self, lang: Language) -> str:
        to = lang.phrases["to"]
        if self.kind == "brake_bias":
            return to.format(what=lang.phrases["kinds"]["brake_bias"], v=speak_number(self.value * 100, lang))
        if self.kind == "setup":
            return to.format(what=(self.label or self.name).lower(), v=int(self.value))
        return to.format(what=lang.phrases["kinds"][self.kind], v=int(self.value))

    def as_dict(self) -> dict:
        return {"id": self.id, "description": self.describe(), "reason": self.reason, "status": self.status,
                "outcome": self.result}


_ids = itertools.count(1)
_ids_lock = threading.Lock()


def validate_proposal(kind: str, value: float, name: str, bridge: BridgeState | None) -> tuple[Proposal | None, str]:
    """Create the proposal if it makes sense for the current car; otherwise (None, reason)."""
    if kind not in KIND_CMD:
        return None, f"unknown kind: {kind}"
    label = ""
    if kind == "brake_bias":
        if value > 1.0:
            value = value / 100.0          # the agent wrote 58 instead of 0.58
        lo, hi = (bridge.brake_bias_min, bridge.brake_bias_max) if bridge and bridge.brake_bias_max > 0 else (0.3, 0.8)
        if not lo <= value <= hi:
            return None, f"bias outside the car's limits ({lo * 100:.1f}-{hi * 100:.1f}%)"
    elif kind in ("abs", "tc"):
        modes = (bridge.abs_modes if kind == "abs" else bridge.tc_modes) if bridge else None
        if modes == 0:
            return None, f"this car has no adjustable {kind.upper()}"
        if modes is not None and not 0 <= value <= modes:
            return None, f"{kind.upper()} goes from 0 to {modes}"
    elif kind == "engine_brake":
        if bridge and bridge.engine_brake_count and not 0 <= value < bridge.engine_brake_count + 1:
            return None, f"engine brake goes from 0 to {bridge.engine_brake_count}"
    elif kind == "setup":
        if not name:
            return None, "a setup change needs the item name (from current_setup)"
        if bridge and bridge.setup:
            item = next((s for s in bridge.setup if s.name.upper() == name.upper()), None)
            if item is None:
                return None, f"unknown setup item: {name}"
            if item.read_only:
                return None, f"{name} cannot be changed on this car"
            if not item.min <= value <= item.max:
                return None, f"{name} goes from {item.min} to {item.max} (clicks)"
            name, label = item.name, item.label
    with _ids_lock:
        pid = next(_ids)
    return Proposal(pid, kind, float(value), name, "", label, time.time()), ""


def _lap_dict(l: LapData) -> dict:
    return {"lap": l.lap_no, "time": rs.fmt_ms(l.lap_time_ms), "time_ms": l.lap_time_ms, "valid": l.valid,
            "sectors_ms": l.sectors_ms, "fuel_used_l": round(l.fuel_used, 2),
            "fuel_end_l": round(l.fuel_end, 1),
            "avg_tyre_temp_c": [round(v, 1) for v in l.tyre_temp_avg],
            "avg_tyre_press_psi": [round(v, 2) for v in l.tyre_press_avg],
            "tyre_wear_end_pct": [round(v, 2) for v in l.tyre_wear_end],
            "max_brake_temp_c": [round(v) for v in l.brake_temp_max], "vmax_kmh": round(l.max_speed, 1)}


class HubDataProvider:
    """Implements ai_engine.mcp_server.DataProvider by reading the hub state (from HTTP threads)."""

    def __init__(self, hub):
        self.hub = hub

    def _laps(self, session_id):
        if session_id is None or session_id == self.hub.session_id:
            return dict(self.hub.session_info), list(self.hub.laps), True
        db = self.hub.db.thread_view()
        info = next((s for s in db.sessions() if s["id"] == session_id), None)
        if info is None:
            raise ValueError(f"session {session_id} not found")
        return info, db.laps(session_id), False

    def live_state(self) -> dict:
        s, b, info = self.hub.last_sample, self.hub.bridge_state, self.hub.session_info
        if s is None:
            return {"on_track": False, "note": "no data: acquisition stopped or AC in the menus"}
        out = {
            "on_track": True, "car": info.get("car"), "track": info.get("track"),
            "session": s.session_type.name, "current_lap": s.completed_laps + 1,
            "current_lap_time": rs.fmt_ms(s.lap_time_ms), "last_lap": rs.fmt_ms(s.last_lap_ms),
            "best_lap": rs.fmt_ms(s.best_lap_ms), "lap_position_pct": round(s.lap_position * 100, 1),
            "sector": s.sector_index + 1, "in_pit": s.is_in_pit, "speed_kmh": round(s.speed_kmh),
            "gear": s.gear - 1, "rpm": s.rpm, "fuel_l": round(s.fuel, 2),
            "tyre_temp_c": [round(v, 1) for v in s.tyre_core_temp],
            "tyre_press_psi": [round(v, 2) for v in s.tyre_pressure],
            "tyre_wear_pct": [round(v, 2) for v in s.tyre_wear],
            "brake_temp_c": [round(v) for v in s.brake_temp],
            "air_c": round(s.air_temp, 1), "track_c": round(s.road_temp, 1),
            "brake_bias_pct": round(s.brake_bias * 100, 1), "engine_brake": s.engine_brake,
        }
        prog = rs.race_progress_for(s, b.cars if b else [], self.hub.is_race, info.get("extra_lap", False))
        out["race"] = {"leader_lap": prog.lap, "total_laps": prog.total, "laps_to_go": prog.to_go,
                       "laps_to_go_estimated": prog.estimated,
                       "time_left_s": round(prog.time_left_s) if prog.time_left_s is not None else None}
        flag = self.hub.track.player_flag(s.lap_position, s.flag, time.monotonic(),
                                          cars_known=bool(b and len(b.cars) > 1))
        out["flag"] = flag.text if flag is not None else None
        laps = list(self.hub.laps)
        fpl = rs.fuel_per_lap(laps)
        if fpl:
            out["avg_fuel_l_per_lap"] = round(fpl, 3)
            out["laps_of_fuel"] = round(s.fuel / fpl, 1)
            if prog.to_go:
                out["fuel_at_finish_l"] = round(s.fuel - prog.to_go * fpl, 1)
        out["car_status"] = status_dict(s, info, fpl)
        if b is not None:
            out.update({"abs": b.abs_mode, "abs_levels": b.abs_modes, "tc": b.tc_mode, "tc_levels": b.tc_modes,
                        "engine_brake_levels": b.engine_brake_count, "setup_editable_now": b.setup_editable})
        else:
            out["note"] = "CSP app not connected: no live ABS/TC/setup and no rivals"
        return out

    def session_laps(self, session_id) -> dict:
        info, laps, live = self._laps(session_id)
        res = {"session": "live" if live else session_id, "car": info.get("car"), "track": info.get("track"),
               "length_m": info.get("track_length"), "laps": [_lap_dict(l) for l in laps]}
        if not laps:
            return res
        valid = [l for l in laps if l.valid]
        if valid:
            best = min(valid, key=lambda l: l.lap_time_ms)
            res["best_lap"] = {"lap": best.lap_no, "time": rs.fmt_ms(best.lap_time_ms)}
        theo = rs.theoretical_best(laps)
        res["ideal_lap"] = rs.fmt_ms(theo) if theo else None
        res["best_sectors_ms"] = rs.best_sectors(laps)
        fpl = rs.fuel_per_lap(laps)
        res["avg_fuel_l_per_lap"] = round(fpl, 3) if fpl else None
        stint = rs.current_stint(laps)
        res["stint_laps"] = len(stint)
        fc = rs.forecast_degradation(stint)
        if fc:
            res["degradation"] = {"s_per_lap": round(fc.deg_per_lap, 3),
                                  "next_laps_forecast": [rs.fmt_ms(t * 1000) for t in fc.forecast_times[:10]],
                                  "drop_off_at_stint_lap": fc.cliff_lap}
        return res

    def compare_laps(self, ref_lap: int, other_lap: int, session_id) -> dict:
        info, laps, live = self._laps(session_id)
        track_len = float(info.get("track_length") or 0) or 5000.0

        def channels(n):
            if live:
                lap = next((l for l in laps if l.lap_no == n), None)
                if lap is None:
                    raise ValueError(f"lap {n} is not in the session")
                return lap.channels
            return self.hub.db.thread_view().lap_channels(session_id, n)

        return {"reference": ref_lap, "compared": other_lap,
                **compare_laps(channels(ref_lap), channels(other_lap), track_len)}

    def current_setup(self) -> dict:
        b = self.hub.bridge_state
        if b is not None and b.setup:
            return {"source": "game (CSP app)", "editable_now": b.setup_editable,
                    "note": "value = clicks; display_value = as shown in the setup menu",
                    "items": [s.as_dict() for s in b.setup]}
        car = self.hub.session_info.get("car_id") or self.hub.session_info.get("car")
        path = latest_setup(car) if car else None
        if path is None:
            return {"source": None, "note": "CSP app not connected and no saved setup file for this car"}
        return {"source": f"file {path.name} (last saved)", "editable_now": False,
                "note": "CSP app not connected: click values from the file, they may differ from the ones in use",
                "items": read_setup(path)}

    def standings(self) -> dict:
        rows = list(self.hub.standings_rows)
        if not rows:
            return {"note": "standings not available (needs the CSP app and a session with other cars)"}
        return {"race": self.hub.is_race, "standings": [r.as_dict() for r in rows]}

    def sessions(self) -> list[dict]:
        return [{**s, "started": str(s["started"])} for s in self.hub.db.thread_view().sessions()]

    def propose(self, kind: str, value: float, name: str, reason: str) -> dict:
        p, why = validate_proposal(kind, value, name, self.hub.bridge_state)
        if p is None:
            return {"accepted": False, "reason": why}
        p.reason = reason
        self.hub.proposal_requested.emit(p)    # thread-safe: the UI receives it on its own thread
        return {"accepted": True, "id": p.id, "description": p.describe(),
                "note": "waiting for the driver to confirm (wheel button or hub button)"}
