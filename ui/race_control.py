"""
Race control (FCY / VSC run by the CSP app) and the data for the in-game HUD, owned by HubState.

- Reads the race control state from the worker (~10 Hz) and re-emits it as HubState.race_changed.
- Sends FCY / VSC / end requests from the pages and from the automatic director (hub_core.analysis.race_director).
- Radio calls on every change (ai_engine.race_control_calls) and laps run neutralised marked, so they stay out of
  best laps, fuel averages and tyre wear.
- Writes the settings and, once a second, what the HUD shows: last radio message, proposal to confirm, fuel and
  strategy.
"""

from __future__ import annotations

import time

from ai_engine.race_control_calls import RaceControlCalls
from hub_core.ac import race_link as rl
from hub_core.analysis import race_strategy as rs
from hub_core.analysis.race_director import MODES, RaceDirector
from hub_core.i18n import tr

HUD_PERIOD_S = 1.0
_CMDS = {"fcy": rl.CMD_FCY, "vsc": rl.CMD_VSC, "sc": rl.CMD_SC, "end": rl.CMD_END, "cancel": rl.CMD_CANCEL}


class RaceControlController:
    def __init__(self, hub):
        self.hub = hub
        self.state: rl.RaceControlState | None = None
        self.settings = self.load_settings()
        self.director = RaceDirector(self.auto_mode)
        self.calls = RaceControlCalls(hub.radio_rules)
        self.lap_neutralised = False         # the lap in progress had (part of) a neutralisation
        self.last_decision = None            # last automatic decision (for the page)
        self._radio_text = ""
        self._hud_t = 0.0
        self._settings_sent = False
        hub.radio_log.connect(self._on_radio_log)

    # ----------------------------------------------------------- settings
    def load_settings(self) -> rl.RaceSettings:
        h, d = self.hub, rl.RaceSettings()
        return rl.RaceSettings(
            vsc_factor=h.setting("race/vsc_factor", d.vsc_factor, float),
            vsc_ai_kmh=h.setting("race/vsc_ai_kmh", d.vsc_ai_kmh, float),
            fcy_kmh=h.setting("race/fcy_kmh", d.fcy_kmh, float),
            countdown_s=h.setting("race/countdown_s", d.countdown_s, float),
            ending_s=h.setting("race/ending_s", d.ending_s, float),
            sc_kmh=h.setting("race/sc_kmh", d.sc_kmh, float),
            sc_car_id=h.setting("race/sc_car_id", d.sc_car_id, str),
            sc_wave_laps=h.setting("race/sc_wave_laps", d.sc_wave_laps, int))

    def save_settings(self, s: rl.RaceSettings) -> None:
        for key, value in (("vsc_factor", s.vsc_factor), ("vsc_ai_kmh", s.vsc_ai_kmh), ("fcy_kmh", s.fcy_kmh),
                           ("countdown_s", s.countdown_s), ("ending_s", s.ending_s), ("sc_kmh", s.sc_kmh),
                           ("sc_car_id", s.sc_car_id), ("sc_wave_laps", s.sc_wave_laps)):
            self.hub.settings.setValue(f"race/{key}", value)
        self.settings = s
        self._settings_sent = False

    @property
    def auto_mode(self) -> str:
        m = self.hub.setting("race/auto", "off", str)
        return m if m in MODES else "off"

    def set_auto_mode(self, mode: str) -> None:
        if mode in MODES:
            self.hub.settings.setValue("race/auto", mode)
            self.director.mode = mode

    # ----------------------------------------------------------- link
    @property
    def _link(self) -> rl.RaceLink | None:
        w = self.hub.worker
        return getattr(w, "race_link", None) if w is not None else None

    @property
    def available(self) -> bool:
        return self.state is not None and self.state.available

    def request(self, kind: str) -> bool:
        """"fcy", "vsc", "sc", "end" or "cancel"; False if the CSP app is not there."""
        link = self._link
        if link is None or kind not in _CMDS or link.send(_CMDS[kind]) is None:
            return False
        return True

    # ----------------------------------------------------------- per state (~10 Hz)
    def on_state(self, rc: rl.RaceControlState | None) -> None:
        self.state = rc
        now = time.monotonic()
        link = self._link
        if rc is None or link is None:
            self._settings_sent = False
            return
        if not self._settings_sent:
            link.write_settings(self.settings)
            track = self.hub.track
            link.write_pit_exit(track.pit_exit_position(), track.pit_lane_start_point())
            self._settings_sent = True
        if rc.neutralised:
            self.lap_neutralised = True
        hub = self.hub
        if hub.radio_active:
            self.calls.rules = hub.radio_rules
            for m in self.calls.update(rc, now, self.settings.fcy_kmh, self.settings.countdown_s):
                hub.radio.say_msg(m)
        b, s = hub.bridge_state, hub.last_sample
        decision = self.director.update(b.cars if b else [], now, hub.is_race, rc.active,
                                        s.session_laps if s is not None and hub.is_race else 0)
        if decision is not None:
            self.last_decision = decision
            self.request(decision.action)
        if now - self._hud_t >= HUD_PERIOD_S:
            self._hud_t = now
            link.write_hud(self.hud_info())

    def take_lap_flag(self) -> bool:
        """At the end of a lap: was it neutralised? The next lap starts clean (or neutralised if still on)."""
        flag = self.lap_neutralised
        self.lap_neutralised = self.state is not None and self.state.neutralised
        return flag

    def reset(self) -> None:
        self._settings_sent = False          # new session: new track, new pit exit
        self.director.reset()
        self.calls.reset()
        self.lap_neutralised = False

    # ----------------------------------------------------------- HUD data
    def _on_radio_log(self, who: str, text: str) -> None:
        if who in ("radio", "engineer") and text:
            self._radio_text = text

    def hud_info(self) -> rl.HudInfo:
        hub = self.hub
        s, b, info = hub.last_sample, hub.bridge_state, hub.session_info
        h = rl.HudInfo(radio_text=self._radio_text)
        pending = hub.pending()
        if pending:
            h.proposal_text = pending[-1].describe()
        h.engineer_text = tr("thinking…") if hub.engineer_busy else ""
        laps = list(hub.laps)
        fpl = rs.fuel_per_lap(laps)
        if s is None:
            return h
        prog = rs.race_progress_for(s, b.cars if b else [], hub.is_race, info.get("extra_lap", False))
        h.laps_to_go = prog.to_go or 0
        if fpl:
            h.fuel_per_lap = fpl
            h.fuel_laps_left = s.fuel / fpl
            if prog.to_go:
                h.fuel_to_end = s.fuel - prog.to_go * fpl
                tank = float(info.get("max_fuel") or 0)
                if tank > 0:
                    plan = rs.fuel_plan(s.fuel, fpl, prog.to_go, tank, s.completed_laps)
                    h.pit_stops_left = plan.stops_needed
                    if plan.pit_window:
                        h.pit_window_open, h.pit_window_close = plan.pit_window[0] + 1, plan.pit_window[1] + 1
        parts = []
        if prog.to_go:
            parts.append(prog.to_go_text)
        if h.pit_stops_left:
            parts.append(tr("{n} stop(s) to go", n=h.pit_stops_left))
        elif fpl and prog.to_go:
            parts.append(tr("no stop needed") if h.fuel_to_end >= 0 else tr("fuel short: save"))
        h.strategy_text = " · ".join(parts)
        return h
