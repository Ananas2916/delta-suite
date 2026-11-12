"""
Shared hub state: acquisition, session and laps, archive, CSP app, standings and track, MCP server.

The radio (rules, voice, push-to-talk), the engineer's proposals and the AI agent live in their own
controllers (ui/radio_controller.py, ui/proposals.py, ui/engineer_controller.py); HubState owns them, keeps
the signals the pages connect to and forwards the few methods the pages call.
"""

from __future__ import annotations

import os
import time

from PyQt6.QtCore import QObject, QSettings, pyqtSignal

from ai_engine.mcp_server import MCPServer
from ai_engine.race_calls import RaceContext
from ai_engine.radio import RadioConfig
from ai_engine.voice import PRIO_NORMAL
from hub_core.ac.csp_bridge import CMD_SETUP, BridgeState, find_ac_root
from hub_core.ac.onboard_feed import OnboardFeed
from hub_core.ac.track_map import find_ai_lines
from hub_core.analysis.lap_recorder import LapData
from hub_core.analysis.live_lap import LiveLap
from hub_core.analysis.race_strategy import race_progress_for
from hub_core.analysis.timing import TimingTower, neighbours
from hub_core.analysis.track_status import TrackWatch
from hub_core.database import TelemetryDB
from hub_core.i18n import language_name
from hub_core.model import ACSessionType, ACStatus
from ui.engineer_controller import EngineerController
from ui.hub_data import HubDataProvider, Proposal
from ui.proposals import ProposalController
from ui.radio_controller import RadioController
from ui.workers import SOURCE_AC, TelemetryWorker

MODES = {"driver": "Driver", "engineer": "Engineer", "analysis": "Analysis"}
_OLD_MODES = {"pilota": "driver", "ingegnere": "engineer", "analisi": "analysis"}   # settings saved before 0.5.9


class HubState(QObject):
    sample = pyqtSignal(object)
    lap_completed = pyqtSignal(object)
    session_changed = pyqtSignal(dict)
    status = pyqtSignal(str, bool)
    running_changed = pyqtSignal(bool)
    db_changed = pyqtSignal()
    mode_changed = pyqtSignal(str)
    bridge_changed = pyqtSignal(object)
    standings_changed = pyqtSignal(list)
    proposals_changed = pyqtSignal()
    proposal_requested = pyqtSignal(object)      # also emitted by the MCP server threads
    radio_log = pyqtSignal(str, str)             # (who, text): "radio", "driver", "engineer", "system"
    voice_error = pyqtSignal(str)
    engineer_text = pyqtSignal(str)
    engineer_started = pyqtSignal(str, str)      # (question, mode)
    engineer_done = pyqtSignal(str)
    engineer_failed = pyqtSignal(str)
    ptt_changed = pyqtSignal(bool)
    recording_started = pyqtSignal(str)

    def __init__(self, settings: QSettings | None = None):
        super().__init__()
        selftest = os.environ.get("DELTA_SELFTEST")
        if settings is not None:
            self.settings = settings
        elif selftest:      # self-test: fresh settings and an in-memory archive, the real ones stay untouched
            os.makedirs(selftest, exist_ok=True)
            self.settings = QSettings(os.path.join(selftest, "settings.ini"), QSettings.Format.IniFormat)
            self.settings.clear()
        else:
            self.settings = QSettings("DeltaSuite", "DeltaSuite")
        try:
            self.db = TelemetryDB(":memory:" if selftest else None)
            self.db_error = None
        except Exception as exc:   # e.g. DB locked by another hub instance
            self.db = TelemetryDB(":memory:")
            self.db_error = str(exc)
        self.session_info: dict = {}
        self.session_id: int | None = None
        self.laps: list[LapData] = []
        self.last_sample = None
        self.worker: TelemetryWorker | None = None
        self.recording_file: str | None = None

        mode = self.settings.value("mode", "driver", str)
        self.mode = _OLD_MODES.get(mode, mode if mode in MODES else "driver")
        self.bridge_state: BridgeState | None = None
        self.timing = TimingTower()
        self.standings_rows: list = []
        self.is_race = False
        self._bridge_counts: tuple[int, int] | None = None
        # onboard video from the CSP app: a single feed, used by the visible page (Onboard or Overview)
        self.onboard_feed = OnboardFeed()
        self.track = TrackWatch()           # track line and yellow/red/blue zones of the session
        self.live_lap = LiveLap()           # splits and live delta of the current lap
        self._archive_ref: LapData | None = None   # all-time best lap for this car and track (delta reference)
        self._closed = False

        self.radio = RadioController(self)
        self.proposal_ctl = ProposalController(self)
        self.engineer = EngineerController(self)
        self.provider = HubDataProvider(self)
        self.mcp = MCPServer(self.provider, int(self.settings.value("mcp_port", 8787)))
        self.mcp.start()

    # ----------------------------------------------------------- settings
    def setting(self, key: str, default, typ=str):
        return self.settings.value(key, default, typ)

    @property
    def ui_language_name(self) -> str:
        """Name of the interface language, as the agent is told to write the analysis."""
        return language_name(self.setting("ui/language", "en"))

    def set_mode(self, mode: str):
        if mode not in MODES or mode == self.mode:
            return
        self.mode = mode
        self.settings.setValue("mode", mode)
        self.mode_changed.emit(mode)

    @property
    def radio_active(self) -> bool:
        return self.mode == "driver" or self.setting("radio/always", False, bool)

    # ---------------------------------------------- forwarded to the controllers (used by the pages)
    @property
    def radio_rules(self):
        return self.radio.rules

    @property
    def stt(self):
        return self.radio.stt

    @property
    def lang(self):
        return self.radio.lang

    def phrase(self, key: str, **kw) -> str:
        return self.radio.phrase(key, **kw)

    def say(self, text: str, priority: int = PRIO_NORMAL, ttl_s: float = 30.0):
        self.radio.say(text, priority, ttl_s)

    def save_radio_config(self, c: RadioConfig):
        self.radio.save_config(c)

    def reload_voice(self):
        self.radio.reload_voice()

    def reload_stt(self):
        self.radio.reload_stt()

    def reload_mic(self):
        self.radio.reload_mic()

    def set_ptt(self, down: bool):
        self.radio.set_ptt(down)

    @property
    def proposals(self) -> list[Proposal]:
        return self.proposal_ctl.items

    def pending(self) -> list[Proposal]:
        return self.proposal_ctl.pending()

    def apply_proposal(self, pid: int):
        self.proposal_ctl.apply(pid)

    def discard_proposal(self, pid: int):
        self.proposal_ctl.discard(pid)

    def ask_engineer(self, question: str, mode: str = "ANALYSIS") -> bool:
        return self.engineer.ask(question, mode)

    @property
    def engineer_busy(self) -> bool:
        return self.engineer.busy

    def new_conversation(self):
        self.engineer.new_conversation()

    def reset_agent(self):
        self.engineer.reset()

    # ----------------------------------------------------------- acquisition
    @property
    def running(self) -> bool:
        return self.worker is not None and self.worker.isRunning()

    @property
    def ac_live(self) -> bool:
        """Acquisition from AC (not demo or replay): only then is there onboard video."""
        return self.running and self.worker.source == SOURCE_AC

    def start(self, source: str, hz: float = 60.0, speed: float = 1.0, replay_path: str | None = None,
              record: bool = False):
        self.stop()
        self.worker = TelemetryWorker(source, hz, speed, replay_path, record)
        self.worker.sample_ready.connect(self._on_sample)
        self.worker.lap_completed.connect(self._on_lap)
        self.worker.session_started.connect(self._on_session)
        self.worker.status.connect(self.status)
        self.worker.bridge_state.connect(self._on_bridge)
        self.worker.recording.connect(self._on_recording)
        w = self.worker
        w.finished.connect(lambda: self._on_worker_finished(w))
        self.worker.start()
        self.running_changed.emit(True)

    def stop(self):
        if self.worker is not None:
            self.worker.stop()
            self.worker = None
            self.running_changed.emit(False)

    def _on_worker_finished(self, w: TelemetryWorker):
        if self.worker is w:            # finished by itself (end of replay, invalid source)
            self.worker = None
            self.running_changed.emit(False)

    def _on_recording(self, path: str):
        self.recording_file = path
        self.recording_started.emit(path)

    def _on_session(self, info: dict):
        self.session_info = info
        self.session_id = None          # the archive row is created at the first completed lap
        self.laps = []
        self.radio.rules.reset()
        self.timing.reset()
        self.track = self._load_track(info)
        self.live_lap.reset(info.get("sector_count") or 3)
        self._archive_ref = self._load_archive_reference(info)
        self._update_reference()
        self.session_changed.emit(info)

    @staticmethod
    def _load_track(info: dict) -> TrackWatch:
        """Track AI line (if AC is installed and the track is there), otherwise learned while driving."""
        try:
            lap, pit = find_ai_lines(find_ac_root(), info.get("track_id", ""), info.get("track_config", ""))
        except OSError:
            lap, pit = [], []
        return TrackWatch(lap, pit, info.get("track_length") or 0.0)

    def _on_lap(self, lap: LapData):
        if self._closed:                # a lap queued by the worker after shutdown: the archive is closed
            return
        if self.session_id is None:
            self.session_id = self.db.new_session(self.session_info)
        self.db.save_lap(self.session_id, lap)
        self.laps = self.laps + [lap]    # new list: MCP threads read without a lock
        self._update_reference()
        self.lap_completed.emit(lap)
        self.db_changed.emit()
        if self.radio_active:
            s, b = self.last_sample, self.bridge_state
            others = [c.best_lap_ms for c in (b.cars if b else []) if c.index != 0 and c.best_lap_ms > 0]
            for m in self.radio.rules.on_lap(lap, self.laps, neighbours(self.standings_rows), self.is_race,
                                             self._to_go(s), s.position if s is not None else None,
                                             min(others) if others else None):
                self.radio.say_msg(m)

    def _to_go(self, s) -> int | None:
        if s is None:
            return None
        b = self.bridge_state
        return race_progress_for(s, b.cars if b else [], self.is_race, self.session_info.get("extra_lap", False)).to_go

    def _race_context(self, s) -> RaceContext:
        b = self.bridge_state
        return RaceContext(now=time.monotonic(), race=self.is_race, rows=self.standings_rows,
                           zone_ahead=self.track.zone_ahead(s.lap_position), to_go=self._to_go(s),
                           cars_known=bool(b and len(b.cars) > 1))

    def _on_sample(self, s):
        self.last_sample = s
        self.is_race = s.session_type == ACSessionType.RACE
        if s.status == ACStatus.LIVE:
            self.track.feed_position(s.lap_position, s.car_x, s.car_z)
            self.live_lap.feed(s, self.session_info.get("track_length") or 0.0)
        if self.radio_active and s.status == ACStatus.LIVE:
            for m in self.radio.rules.on_sample(s, self.session_info, self._race_context(s)):
                self.radio.say_msg(m)
        self.sample.emit(s)

    # -------------------------------------------------------- reference lap
    @property
    def delta_vs_archive(self) -> bool:
        """Live delta against the all-time best lap for this car and track instead of the session best."""
        return self.setting("delta/archive", False, bool)

    def set_delta_vs_archive(self, on: bool):
        self.settings.setValue("delta/archive", on)
        self._update_reference()

    def _load_archive_reference(self, info: dict) -> LapData | None:
        car, track = info.get("car"), info.get("track")
        if not car or not track:
            return None
        try:
            best = self.db.best_laps(car, track, limit=1)
            if not best:
                return None
            b = best[0]
            channels = self.db.lap_channels(b["session_id"], b["lap_no"])
        except Exception:
            return None
        if len(channels.get("t", [])) < 10:
            return None
        return LapData(b["lap_no"], b["lap_time_ms"], True, [], 0.0, 0.0, [], [], [], [], 0.0, channels)

    def _update_reference(self):
        """Live delta reference: the session's best valid lap, or the archive best if faster and enabled."""
        candidates = [l for l in self.laps if l.valid]
        if self.delta_vs_archive and self._archive_ref is not None:
            candidates.append(self._archive_ref)
        if candidates:
            self.live_lap.set_reference(min(candidates, key=lambda l: l.lap_time_ms))

    # ------------------------------------------------------------ CSP app
    def _on_bridge(self, b: BridgeState | None):
        was_editable = self.bridge_state is not None and self.bridge_state.setup_editable
        self.bridge_state = b
        if b is not None:
            self._handle_buttons(b)
            self.proposal_ctl.on_bridge(b, was_editable)
            now = time.monotonic()
            s = self.last_sample
            self.track.update_cars(b.cars, now, s.session_laps if s is not None and self.is_race else 0,
                                   live=s is not None and s.status == ACStatus.LIVE)
            self.timing.update(now, b.cars)
            self.standings_rows = self.timing.standings(now, b.cars, self.is_race, 0)
            self.standings_changed.emit(self.standings_rows)
        self.bridge_changed.emit(b)

    def _handle_buttons(self, b: BridgeState):
        """Wheel buttons bound in the CSP app: confirm / discard the latest proposal, push-to-talk."""
        counts = (b.confirm_count, b.cancel_count)
        pressed = b.ptt_down or (self._bridge_counts is not None and counts != self._bridge_counts)
        if pressed and not self.setting("checklist/wheel_used", False, bool):
            self.settings.setValue("checklist/wheel_used", True)     # a wheel button works: bound
        if self._bridge_counts is not None:
            if counts[0] != self._bridge_counts[0]:
                self.proposal_ctl.confirm_latest()
            if counts[1] != self._bridge_counts[1]:
                self.proposal_ctl.discard_latest()
        self._bridge_counts = counts
        if b.ptt_down != self.radio.ptt_down:
            self.radio.set_ptt(b.ptt_down)

    def send_command(self, cmd: int, value: float = 0.0, name: str = "", text: str = "") -> int | None:
        if self.worker is None or self.worker.bridge is None:
            return None
        return self.worker.bridge.send(cmd, value, name, text)

    def set_setup_value(self, name: str, value: int) -> int | None:
        return self.send_command(CMD_SETUP, value, name)

    # ------------------------------------------------------------- shutdown
    def shutdown(self):
        self._closed = True
        self.stop()
        self.onboard_feed.disconnect()
        self.engineer.shutdown()
        self.radio.shutdown()
        self.mcp.stop()
        self.db.close()
