"""
Hub side of the remote access (hub_core.remote): what the remote page sees and what it can do.

The page polls `snapshot()` a few times per second from the server's threads: everything is read from lists the
hub replaces rather than modifies (as for the MCP server). Actions arrive on those threads too and go to the Qt
thread through a signal: confirming a proposal, discarding it, a message read out to the driver by the radio
voice, a question to the AI engineer.
"""

from __future__ import annotations

import collections
import itertools
import json
import threading
import time

from PyQt6.QtCore import QObject, pyqtSignal

from ai_engine.voice import PRIO_HIGH
from hub_core.analysis import race_strategy as rs
from hub_core.remote.auth import Pairing
from hub_core.remote.server import RemoteServer
from ui.hub_data import _lap_dict
from hub_core.i18n import tr

LOG_SIZE = 200
SAY_MAX = 200
ASK_MAX = 1000


class RemoteAccess(QObject):
    action_requested = pyqtSignal(str, str, object)     # (device, kind, payload): handled in the Qt thread
    changed = pyqtSignal()                              # devices or server state changed (for the dialog)

    def __init__(self, hub):
        super().__init__()
        self.hub = hub
        self.pairing = Pairing()
        try:
            self.pairing.load(json.loads(hub.setting("remote/devices", "[]") or "[]"))
        except ValueError:
            pass
        self.pairing.on_change = self._save_devices
        self.server = RemoteServer(self, self.pairing, int(hub.setting("remote/port", 8790, int)))
        self._log: collections.deque = collections.deque(maxlen=LOG_SIZE)
        self._seq = itertools.count(1)
        self._log_lock = threading.Lock()

        hub.radio_log.connect(self._on_radio_log)
        hub.engineer_started.connect(lambda q, mode: self.log("question", q) if mode != "RADIO" else None)
        hub.engineer_done.connect(self._on_engineer_done)
        self.action_requested.connect(self._do_action)
        if hub.setting("remote/enabled", False, bool):
            self.set_enabled(True)

    # ----------------------------------------------------------- on/off
    @property
    def enabled(self) -> bool:
        return self.server.running

    def set_enabled(self, on: bool) -> bool:
        ok = self.server.start() if on else (self.server.stop() or True)
        self.hub.settings.setValue("remote/enabled", bool(on and ok))
        self.changed.emit()
        return ok

    def _save_devices(self):
        # called from the server's threads too: QSettings is thread-safe, the dialog is refreshed via signal
        self.hub.settings.setValue("remote/devices", json.dumps(self.pairing.export()))
        self.changed.emit()

    # ----------------------------------------------------------- radio log for the page
    def log(self, who: str, text: str):
        with self._log_lock:
            self._log.append({"seq": next(self._seq), "t": time.time(), "who": who, "text": text})

    def _on_radio_log(self, who: str, text: str):
        self.log(who, text)

    def _on_engineer_done(self, answer: str):
        if answer and getattr(self.hub, "_job_mode", "") != "RADIO":      # radio answers are logged when spoken
            self.log("engineer", answer)

    # ----------------------------------------------------------- RemoteProvider
    def snapshot(self, since: int, laps_known: int) -> dict:
        hub = self.hub
        s = hub.last_sample
        live = hub.provider.live_state()
        if s is not None:
            live["position"] = s.position
            live["delta_s"] = None if hub.live_lap.delta_s is None else round(hub.live_lap.delta_s, 2)
            live["current_lap_ms"] = s.lap_time_ms
            live["tyre_compound"] = s.tyre_compound
        with self._log_lock:
            radio = [e for e in self._log if e["seq"] > since]
        laps = list(hub.laps)
        out = {
            "time": time.time(),
            "running": hub.running,
            "race": hub.is_race,
            "live": live,
            "standings": [r.as_dict() for r in list(hub.standings_rows)],
            "proposals": [p.as_dict() for p in list(hub.proposals)[-12:]],
            "radio": radio,
            "engineer_busy": hub.engineer_busy,
            "laps_n": len(laps),
        }
        if laps_known != len(laps):
            valid = [l for l in laps if l.valid]
            out["laps"] = [_lap_dict(l) for l in laps[-60:]]
            out["best_lap"] = rs.fmt_ms(min(l.lap_time_ms for l in valid)) if valid else None
            out["theoretical_best"] = rs.fmt_ms(rs.theoretical_best(laps)) if laps else None
        return out

    def action(self, device: str, kind: str, payload: dict) -> dict:
        if kind in ("confirm", "discard"):
            try:
                pid = int(payload.get("id"))
            except (TypeError, ValueError):
                return {"ok": False, "error": "proposal id missing"}
            if not any(p.id == pid and p.status in ("pending", "in pits", "error") for p in list(self.hub.proposals)):
                return {"ok": False, "error": "the proposal is no longer pending"}
            self.action_requested.emit(device, kind, pid)
            return {"ok": True}
        if kind in ("say", "ask"):
            text = " ".join(str(payload.get("text", "")).split())[: SAY_MAX if kind == "say" else ASK_MAX]
            if not text:
                return {"ok": False, "error": "empty message"}
            if kind == "ask" and self.hub.engineer_busy:
                return {"ok": False, "error": "the engineer is still answering"}
            self.action_requested.emit(device, kind, text)
            return {"ok": True}
        return {"ok": False, "error": f"unknown action {kind!r}"}

    def _do_action(self, device: str, kind: str, payload):
        hub = self.hub
        if kind == "confirm":
            hub.apply_proposal(payload)
            hub.radio_log.emit("system", tr("Proposal confirmed from {device}", device=device))
        elif kind == "discard":
            hub.discard_proposal(payload)
            hub.radio_log.emit("system", tr("Proposal discarded from {device}", device=device))
        elif kind == "say":
            # the remote engineer talks to the driver through the radio voice (logged as "radio" when spoken)
            hub.radio_log.emit("remote", f"{device}: {payload}")
            hub.say(payload, PRIO_HIGH, 60)       # a person talking: before the scripted calls
        elif kind == "ask":
            if not hub.ask_engineer(f"[{device}, from the remote pit wall] {payload}", "ANALYSIS"):
                self.log("system", "The engineer is busy or not available")

    def shutdown(self):
        self.server.stop()

