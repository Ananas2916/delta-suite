"""Dati dell'hub per l'agente (strumenti MCP) e proposte di modifica da confermare."""

from __future__ import annotations

import itertools
import threading
import time
from dataclasses import dataclass

from hub_core import race_strategy as rs
from hub_core.csp_bridge import (
    CMD_ABS, CMD_BRAKE_BIAS, CMD_ENGINE_BRAKE, CMD_SETUP, CMD_TC, BridgeState,
)
from hub_core.lap_analysis import compare_laps
from hub_core.lap_recorder import LapData
from hub_core.setup_files import latest_setup, read_setup
from ai_engine.lang import Language, speak_number

KIND_LABELS = {"bias_freni": "Bias freni", "abs": "ABS", "tc": "TC", "freno_motore": "Freno motore",
               "setup": "Setup"}
KIND_CMD = {"bias_freni": CMD_BRAKE_BIAS, "abs": CMD_ABS, "tc": CMD_TC, "freno_motore": CMD_ENGINE_BRAKE,
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
    status: str = "in attesa"     # in attesa | ai box | inviata | applicata | errore | scartata
    result: str = ""
    seq: int | None = None

    def describe(self) -> str:
        if self.kind == "bias_freni":
            return f"Bias freni {self.value * 100:.1f}%"
        if self.kind == "setup":
            return f"{self.label or self.name} → {int(self.value)}"
        return f"{KIND_LABELS.get(self.kind, self.kind)} {int(self.value)}"

    def spoken(self, lang: Language) -> str:
        to = lang.phrases["to"]
        if self.kind == "bias_freni":
            return to.format(what=lang.phrases["kinds"]["bias_freni"], v=speak_number(self.value * 100, lang))
        if self.kind == "setup":
            return to.format(what=(self.label or self.name).lower(), v=int(self.value))
        return to.format(what=lang.phrases["kinds"][self.kind], v=int(self.value))

    def as_dict(self) -> dict:
        return {"id": self.id, "descrizione": self.describe(), "motivo": self.reason, "stato": self.status,
                "esito": self.result}


_ids = itertools.count(1)
_ids_lock = threading.Lock()


def validate_proposal(kind: str, value: float, name: str, bridge: BridgeState | None) -> tuple[Proposal | None, str]:
    """Crea la proposta se ha senso per l'auto attuale; altrimenti (None, motivo)."""
    if kind not in KIND_CMD:
        return None, f"tipo sconosciuto: {kind}"
    label = ""
    if kind == "bias_freni":
        if value > 1.0:
            value = value / 100.0          # l'agente ha scritto 58 invece di 0.58
        lo, hi = (bridge.brake_bias_min, bridge.brake_bias_max) if bridge and bridge.brake_bias_max > 0 else (0.3, 0.8)
        if not lo <= value <= hi:
            return None, f"bias fuori dai limiti dell'auto ({lo * 100:.1f}-{hi * 100:.1f}%)"
    elif kind in ("abs", "tc"):
        modes = (bridge.abs_modes if kind == "abs" else bridge.tc_modes) if bridge else None
        if modes == 0:
            return None, f"questa auto non ha {kind.upper()} regolabile"
        if modes is not None and not 0 <= value <= modes:
            return None, f"{kind.upper()} va da 0 a {modes}"
    elif kind == "freno_motore":
        if bridge and bridge.engine_brake_count and not 0 <= value < bridge.engine_brake_count + 1:
            return None, f"freno motore va da 0 a {bridge.engine_brake_count}"
    elif kind == "setup":
        if not name:
            return None, "per il setup serve il nome della voce (da setup_attuale)"
        if bridge and bridge.setup:
            item = next((s for s in bridge.setup if s.name.upper() == name.upper()), None)
            if item is None:
                return None, f"voce di setup sconosciuta: {name}"
            if item.read_only:
                return None, f"{name} non è modificabile su questa auto"
            if not item.min <= value <= item.max:
                return None, f"{name} va da {item.min} a {item.max} (click)"
            name, label = item.name, item.label
    with _ids_lock:
        pid = next(_ids)
    return Proposal(pid, kind, float(value), name, "", label, time.time()), ""


def _lap_dict(l: LapData) -> dict:
    return {"giro": l.lap_no, "tempo": rs.fmt_ms(l.lap_time_ms), "tempo_ms": l.lap_time_ms, "valido": l.valid,
            "settori_ms": l.sectors_ms, "carburante_usato_l": round(l.fuel_used, 2),
            "carburante_fine_l": round(l.fuel_end, 1),
            "temp_gomme_medie_c": [round(v, 1) for v in l.tyre_temp_avg],
            "press_gomme_medie_psi": [round(v, 2) for v in l.tyre_press_avg],
            "usura_fine_giro_pct": [round(v, 2) for v in l.tyre_wear_end],
            "temp_freni_max_c": [round(v) for v in l.brake_temp_max], "vmax_kmh": round(l.max_speed, 1)}


class HubDataProvider:
    """Implementa ai_engine.mcp_server.DataProvider leggendo lo stato dell'hub (da thread HTTP)."""

    def __init__(self, hub):
        self.hub = hub

    def _laps(self, session_id):
        if session_id is None or session_id == self.hub.session_id:
            return dict(self.hub.session_info), list(self.hub.laps), True
        db = self.hub.db.thread_view()
        info = next((s for s in db.sessions() if s["id"] == session_id), None)
        if info is None:
            raise ValueError(f"sessione {session_id} non trovata")
        return info, db.laps(session_id), False

    def live_state(self) -> dict:
        s, b, info = self.hub.last_sample, self.hub.bridge_state, self.hub.session_info
        if s is None:
            return {"in_pista": False, "nota": "nessun dato: acquisizione ferma o AC nei menu"}
        out = {
            "in_pista": True, "auto": info.get("car"), "pista": info.get("track"),
            "sessione": s.session_type.name, "giro_in_corso": s.completed_laps + 1,
            "tempo_giro_in_corso": rs.fmt_ms(s.lap_time_ms), "ultimo_giro": rs.fmt_ms(s.last_lap_ms),
            "miglior_giro": rs.fmt_ms(s.best_lap_ms), "posizione_in_giro_pct": round(s.lap_position * 100, 1),
            "settore": s.sector_index + 1, "ai_box": s.is_in_pit, "velocita_kmh": round(s.speed_kmh),
            "marcia": s.gear - 1, "rpm": s.rpm, "carburante_l": round(s.fuel, 2),
            "temp_gomme_c": [round(v, 1) for v in s.tyre_core_temp],
            "press_gomme_psi": [round(v, 2) for v in s.tyre_pressure],
            "usura_gomme_pct": [round(v, 2) for v in s.tyre_wear],
            "temp_freni_c": [round(v) for v in s.brake_temp],
            "aria_c": round(s.air_temp, 1), "asfalto_c": round(s.road_temp, 1),
            "bias_freni_pct": round(s.brake_bias * 100, 1), "freno_motore": s.engine_brake,
        }
        laps = list(self.hub.laps)
        fpl = rs.fuel_per_lap(laps)
        if fpl:
            out["consumo_medio_l_giro"] = round(fpl, 3)
            out["giri_di_carburante"] = round(s.fuel / fpl, 1)
        if b is not None:
            out.update({"abs": b.abs_mode, "abs_livelli": b.abs_modes, "tc": b.tc_mode, "tc_livelli": b.tc_modes,
                        "freno_motore_livelli": b.engine_brake_count, "setup_modificabile_ora": b.setup_editable})
        else:
            out["nota"] = "app CSP non collegata: niente ABS/TC/setup live né avversari"
        return out

    def session_laps(self, session_id) -> dict:
        info, laps, live = self._laps(session_id)
        res = {"sessione": "live" if live else session_id, "auto": info.get("car"), "pista": info.get("track"),
               "lunghezza_m": info.get("track_length"), "giri": [_lap_dict(l) for l in laps]}
        if not laps:
            return res
        valid = [l for l in laps if l.valid]
        if valid:
            best = min(valid, key=lambda l: l.lap_time_ms)
            res["miglior_giro"] = {"giro": best.lap_no, "tempo": rs.fmt_ms(best.lap_time_ms)}
        theo = rs.theoretical_best(laps)
        res["giro_ideale"] = rs.fmt_ms(theo) if theo else None
        res["migliori_settori_ms"] = rs.best_sectors(laps)
        fpl = rs.fuel_per_lap(laps)
        res["consumo_medio_l_giro"] = round(fpl, 3) if fpl else None
        stint = rs.current_stint(laps)
        res["giri_nello_stint"] = len(stint)
        fc = rs.forecast_degradation(stint)
        if fc:
            res["degrado"] = {"s_per_giro": round(fc.deg_per_lap, 3),
                              "previsione_prossimi_giri": [rs.fmt_ms(t * 1000) for t in fc.forecast_times[:10]],
                              "crollo_al_giro_di_stint": fc.cliff_lap}
        return res

    def compare_laps(self, ref_lap: int, other_lap: int, session_id) -> dict:
        info, laps, live = self._laps(session_id)
        track_len = float(info.get("track_length") or 0) or 5000.0

        def channels(n):
            if live:
                lap = next((l for l in laps if l.lap_no == n), None)
                if lap is None:
                    raise ValueError(f"giro {n} non presente nella sessione")
                return lap.channels
            return self.hub.db.thread_view().lap_channels(session_id, n)

        return {"riferimento": ref_lap, "confronto": other_lap,
                **compare_laps(channels(ref_lap), channels(other_lap), track_len)}

    def current_setup(self) -> dict:
        b = self.hub.bridge_state
        if b is not None and b.setup:
            return {"fonte": "gioco (app CSP)", "modificabile_ora": b.setup_editable,
                    "nota": "valore = click; valore_mostrato = come appare nel menu setup",
                    "voci": [s.as_dict() for s in b.setup]}
        car = self.hub.session_info.get("car_id") or self.hub.session_info.get("car")
        path = latest_setup(car) if car else None
        if path is None:
            return {"fonte": None, "nota": "app CSP non collegata e nessun file di setup salvato per questa auto"}
        return {"fonte": f"file {path.name} (ultimo salvato)", "modificabile_ora": False,
                "nota": "app CSP non collegata: valori in click dal file, potrebbero differire da quelli in uso",
                "voci": read_setup(path)}

    def standings(self) -> dict:
        rows = list(self.hub.standings_rows)
        if not rows:
            return {"nota": "classifica non disponibile (serve l'app CSP e una sessione con altre auto)"}
        return {"gara": self.hub.is_race, "classifica": [r.as_dict() for r in rows]}

    def sessions(self) -> list[dict]:
        return [{**s, "started": str(s["started"])} for s in self.hub.db.thread_view().sessions()]

    def propose(self, kind: str, value: float, name: str, reason: str) -> dict:
        p, why = validate_proposal(kind, value, name, self.hub.bridge_state)
        if p is None:
            return {"accettata": False, "motivo": why}
        p.reason = reason
        self.hub.proposal_requested.emit(p)    # thread-safe: la UI la riceve nel suo thread
        return {"accettata": True, "id": p.id, "descrizione": p.describe(),
                "nota": "in attesa di conferma del pilota (tasto al volante o pulsante nell'hub)"}
