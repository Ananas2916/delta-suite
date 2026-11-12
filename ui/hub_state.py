"""Shared hub state: acquisition, archive, CSP app, radio, AI engineer and MCP server."""

from __future__ import annotations

import os
import threading
import time

from PyQt6.QtCore import QObject, QSettings, pyqtSignal

from ai_engine.agent_cli import APIAgent, CLIAgent
from ai_engine.mcp_server import MCPServer
from ai_engine.lang import DEFAULT_VOICE, Language, language_of
from ai_engine.race_calls import RaceContext
from ai_engine.race_chatter import AI_COMMENT_PROMPT
from ai_engine.radio import Msg, RadioConfig, RadioRules
from ai_engine.stt import DEFAULT_MODEL, make_stt
from ai_engine.voice import PRIO_HIGH, PRIO_NORMAL, PRIO_URGENT, RadioVoice, make_backend
from hub_core.ac.csp_bridge import CMD_SETUP, BridgeState, find_ac_root
from hub_core.ac.onboard_feed import OnboardFeed
from hub_core.ac.track_map import find_ai_lines
from hub_core.analysis.lap_recorder import LapData
from hub_core.analysis.live_lap import LiveLap
from hub_core.analysis.race_strategy import race_progress_for
from hub_core.analysis.timing import TimingTower, neighbours
from hub_core.analysis.track_status import TrackWatch
from hub_core.database import TelemetryDB
from hub_core.model import ACSessionType, ACStatus
from ui.hub_data import KIND_CMD, HubDataProvider, Proposal
from ui.mic import MicRecorder
from ui.workers import SOURCE_AC, Job, TelemetryWorker

MODES = {"driver": "Driver", "engineer": "Engineer", "analysis": "Analysis"}
_OLD_MODES = {"pilota": "driver", "ingegnere": "engineer", "analisi": "analysis"}   # settings saved before 0.5.9


def _quiet(fn):
    try:
        fn()
    except Exception:
        pass        # the error resurfaces, with its message, at the first transcription


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

    def __init__(self):
        super().__init__()
        self.settings = QSettings("DeltaSuite", "DeltaSuite")
        try:
            self.db = TelemetryDB()
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
        self.proposals: list[Proposal] = []
        self._bridge_counts: tuple[int, int] | None = None
        # onboard video from the CSP app: a single feed, used by the visible page (Onboard or Overview)
        self.onboard_feed = OnboardFeed()
        self.track = TrackWatch()           # track line and yellow/red/blue zones of the session
        self.live_lap = LiveLap()           # splits and live delta of the current lap
        self._ptt = False
        self._closed = False

        self.radio_rules = RadioRules(self.load_radio_config(), self.lang)
        self.voice = RadioVoice(self._make_tts(), is_safe=self._safe_to_talk,
                                on_spoken=lambda t: self.radio_log.emit("radio", t),
                                on_error=self.voice_error.emit)
        self.voice.start()
        self.mic = MicRecorder(self._mic_id(), self)
        self.stt = None
        self.reload_stt()

        self.provider = HubDataProvider(self)
        self.mcp = MCPServer(self.provider, int(self.settings.value("mcp_port", 8787)))
        self.mcp.start()
        self.agent = None
        self._job: Job | None = None
        self._job_mode = "ANALYSIS"
        self._job_auto = False
        self._stt_job: Job | None = None

        self.proposal_requested.connect(self._add_proposal)
        # remote access from another device (web page on the local network, off by default)
        from ui.remote_data import RemoteAccess      # here: it reads HubState's signals and provider
        self.remote = RemoteAccess(self)

    # ----------------------------------------------------------- settings
    def setting(self, key: str, default, typ=str):
        return self.settings.value(key, default, typ)

    def load_radio_config(self) -> RadioConfig:
        c = RadioConfig()
        for f in ("lap_times", "fuel", "tyres", "gaps", "flags", "hybrid", "positions", "rivals", "car"):
            setattr(c, f, self.setting(f"radio/{f}", True, bool))
        for f in ("tyre_temp_lo", "tyre_temp_hi", "tyre_press_lo", "tyre_press_hi"):
            setattr(c, f, self.setting(f"radio/{f}", getattr(c, f), float))
        for f in ("chatter", "ai_comment_laps"):
            setattr(c, f, self.setting(f"radio/{f}", getattr(c, f), int))
        return c

    def save_radio_config(self, c: RadioConfig):
        for k, v in c.__dict__.items():
            self.settings.setValue(f"radio/{k}", v)
        self.radio_rules.cfg = c

    @property
    def lang(self) -> Language:
        return language_of(self.setting("voice/voice", DEFAULT_VOICE))

    def phrase(self, key: str, **kw) -> str:
        return self.lang.phrases[key].format(**kw)

    def reload_stt(self):
        self.stt = make_stt(self.setting("stt/engine", "whisper"), self.setting("stt/model", DEFAULT_MODEL),
                            self.setting("voice/tsukumo_url", "http://127.0.0.1:8770"))
        if self.stt.available()[0] and not os.environ.get("DELTA_SELFTEST") and not os.environ.get("DELTA_MUTE"):
            stt = self.stt
            threading.Thread(target=lambda: _quiet(stt.preload), daemon=True, name="STTPreload").start()

    def _make_tts(self):
        if os.environ.get("DELTA_MUTE") or os.environ.get("DELTA_SELFTEST"):
            return make_backend("none", "", 1.0)      # tests and self-test: no audio
        return make_backend(self.setting("voice/engine", "kokoro"), self.setting("voice/voice", DEFAULT_VOICE),
                            self.setting("voice/speed", 1.1, float), self.setting("voice/model_dir", "") or None)

    def reload_voice(self):
        self.voice.set_backend(self._make_tts())
        self.radio_rules.lang = self.lang

    def _mic_id(self) -> bytes | None:
        v = self.settings.value("voice/mic", b"")
        return bytes(v) if v else None

    def reload_mic(self):
        self.mic.device_id = self._mic_id()

    def reset_agent(self):
        if self.agent is not None:
            self.agent.cancel()
        self.agent = None

    def set_mode(self, mode: str):
        if mode not in MODES or mode == self.mode:
            return
        self.mode = mode
        self.settings.setValue("mode", mode)
        self.mode_changed.emit(mode)

    @property
    def radio_active(self) -> bool:
        return self.mode == "driver" or self.setting("radio/always", False, bool)

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
        self.radio_rules.reset()
        self.timing.reset()
        self.track = self._load_track(info)
        self.live_lap.reset(info.get("sector_count") or 3)
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
        valid = [l for l in self.laps if l.valid]
        if valid:                        # live delta against the best valid lap
            self.live_lap.set_reference(min(valid, key=lambda l: l.lap_time_ms))
        self.lap_completed.emit(lap)
        self.db_changed.emit()
        if self.radio_active:
            s, b = self.last_sample, self.bridge_state
            others = [c.best_lap_ms for c in (b.cars if b else []) if c.index != 0 and c.best_lap_ms > 0]
            for m in self.radio_rules.on_lap(lap, self.laps, neighbours(self.standings_rows), self.is_race,
                                             self._to_go(s), s.position if s is not None else None,
                                             min(others) if others else None, rows=self.standings_rows):
                self._say(m)
            self._maybe_ai_comment(lap)

    def _maybe_ai_comment(self, lap: LapData):
        """Every N race laps the AI engineer says one thing on its own (where the local phrases cannot reach)."""
        n = self.radio_rules.cfg.ai_comment_laps
        if n and self.is_race and lap.lap_no >= 2 and lap.lap_no % n == 0 and not self.engineer_busy:
            self.ask_engineer(AI_COMMENT_PROMPT, "RADIO", auto=True)

    def _to_go(self, s) -> int | None:
        if s is None:
            return None
        b = self.bridge_state
        return race_progress_for(s, b.cars if b else [], self.is_race, self.session_info.get("extra_lap", False)).to_go

    def _race_context(self, s) -> RaceContext:
        b = self.bridge_state
        return RaceContext(now=time.monotonic(), race=self.is_race, rows=self.standings_rows,
                           zone_ahead=self.track.zone_ahead(s.lap_position), to_go=self._to_go(s),
                           cars_known=bool(b and len(b.cars) > 1),
                           slow_cars={z.car for z in self.track.zones if z.kind in ("yellow", "red") and z.car > 0})

    def _on_sample(self, s):
        self.last_sample = s
        self.is_race = s.session_type == ACSessionType.RACE
        if s.status == ACStatus.LIVE:
            self.track.feed_position(s.lap_position, s.car_x, s.car_z)
            self.live_lap.feed(s, self.session_info.get("track_length") or 0.0)
        if self.radio_active and s.status == ACStatus.LIVE:
            for m in self.radio_rules.on_sample(s, self.session_info, self._race_context(s)):
                self._say(m)
        self.sample.emit(s)

    # ------------------------------------------------------------- radio
    def _safe_to_talk(self) -> bool:
        s = self.last_sample
        if s is None or s.status != ACStatus.LIVE:
            return True
        return s.brake < 0.05 and abs(s.steer_angle) < 0.15 and abs(s.acc_g[0]) < 1.2

    def _say(self, m: Msg):
        self.voice.say(m.text, m.priority, m.ttl_s, m.key)

    def say(self, text: str, priority: int = PRIO_NORMAL, ttl_s: float = 30.0):
        self.voice.say(text, priority, ttl_s)

    # ------------------------------------------------------------ app CSP
    def _on_bridge(self, b: BridgeState | None):
        was_editable = self.bridge_state is not None and self.bridge_state.setup_editable
        self.bridge_state = b
        if b is not None:
            self._handle_buttons(b)
            self._handle_acks(b)
            if b.setup_editable and not was_editable:
                for p in self.proposals:
                    if p.status == "in pits":
                        self._send_proposal(p)
            now = time.monotonic()
            s = self.last_sample
            self.track.update_cars(b.cars, now, s.session_laps if s is not None and self.is_race else 0,
                                   live=s is not None and s.status == ACStatus.LIVE)
            self.timing.update(now, b.cars)
            self.standings_rows = self.timing.standings(now, b.cars, self.is_race, 0)
            self.standings_changed.emit(self.standings_rows)
        self.bridge_changed.emit(b)

    def _handle_buttons(self, b: BridgeState):
        counts = (b.confirm_count, b.cancel_count)
        if self._bridge_counts is not None:
            if counts[0] != self._bridge_counts[0]:
                self.confirm_latest()
            if counts[1] != self._bridge_counts[1]:
                self.discard_latest()
        self._bridge_counts = counts
        if b.ptt_down != self._ptt:
            self.set_ptt(b.ptt_down)

    def send_command(self, cmd: int, value: float = 0.0, name: str = "", text: str = "") -> int | None:
        if self.worker is None or self.worker.bridge is None:
            return None
        return self.worker.bridge.send(cmd, value, name, text)

    # ------------------------------------------------------------ proposals
    def _add_proposal(self, p: Proposal):
        self.proposals.append(p)
        self.radio_log.emit("engineer", f"Proposal: {p.describe()} — {p.reason}")
        if self.radio_active:
            self.say(self.phrase("proposal", what=p.spoken(self.lang), reason=p.reason), PRIO_HIGH, 60)
        self.proposals_changed.emit()

    def pending(self) -> list[Proposal]:
        return [p for p in self.proposals if p.status == "pending"]

    def confirm_latest(self):
        pend = self.pending()
        if pend:
            self.apply_proposal(pend[-1].id)

    def discard_latest(self):
        pend = self.pending()
        if pend:
            self.discard_proposal(pend[-1].id)

    def apply_proposal(self, pid: int):
        p = next((x for x in self.proposals if x.id == pid), None)
        if p is None or p.status not in ("pending", "error"):
            return
        if p.kind == "setup" and not (self.bridge_state and self.bridge_state.setup_editable):
            p.status, p.result = "in pits", "confirmed: applied as soon as you enter the pits"
            if self.radio_active:
                self.say(self.phrase("at_box"), PRIO_NORMAL)
        else:
            self._send_proposal(p)
        self.proposals_changed.emit()

    def _send_proposal(self, p: Proposal):
        seq = self.send_command(KIND_CMD[p.kind], p.value, p.name)
        if seq is None:
            p.status, p.result = "error", "CSP app not connected"
        else:
            p.status, p.seq = "sent", seq
        self.proposals_changed.emit()

    def discard_proposal(self, pid: int):
        p = next((x for x in self.proposals if x.id == pid), None)
        if p is not None and p.status in ("pending", "in pits", "error"):
            p.status = "discarded"
            if self.radio_active:
                self.say(self.phrase("discarded"), PRIO_NORMAL, 15)
            self.proposals_changed.emit()

    def _handle_acks(self, b: BridgeState):
        for p in self.proposals:
            if p.status == "sent" and p.seq is not None and b.ack_seq == p.seq:
                p.status = "applied" if b.ack_ok else "error"
                p.result = b.ack_msg
                if self.radio_active:
                    self.say(self.phrase("done", what=p.spoken(self.lang)) if b.ack_ok else
                             self.phrase("failed", msg=b.ack_msg), PRIO_HIGH, 20)
                self.radio_log.emit("system", f"{p.describe()}: {b.ack_msg}")
                self.proposals_changed.emit()

    def set_setup_value(self, name: str, value: int) -> int | None:
        return self.send_command(CMD_SETUP, value, name)

    # ------------------------------------------------------- AI engineer
    def _make_agent(self):
        backend = self.setting("engineer/backend", "claude")
        if backend == "api":
            from ai_engine.race_engineer_agent import RaceEngineer, build_stint_summary
            key = self.setting("api_key", "") or None
            return APIAgent(RaceEngineer(key), lambda: build_stint_summary(
                self.session_info, self.laps, self.last_sample.fuel if self.last_sample else None))
        return CLIAgent(backend, self.mcp.client_config(), self.setting("engineer/custom_cmd", ""),
                        self.setting("engineer/model", ""))

    @property
    def engineer_busy(self) -> bool:
        return self._job is not None and self._job.isRunning()

    def ask_engineer(self, question: str, mode: str = "ANALYSIS", auto: bool = False) -> bool:
        """`auto`: comment the engineer makes on its own (not asked by the driver): fails silently."""
        question = question.strip()
        if not question or self.engineer_busy:
            return False
        if self.agent is None:
            try:
                self.agent = self._make_agent()
            except Exception as exc:
                self.engineer_failed.emit(str(exc))
                return False
        agent = self.agent
        timeout = 120.0 if mode == "RADIO" else 600.0
        # on the radio the voice's language is spoken; the written analysis follows the interface (English)
        lang_name = self.lang.name if mode == "RADIO" else "English"
        self._job = Job(lambda emit: agent.ask(question, mode, emit, timeout, lang_name))
        self._job.text.connect(self.engineer_text)
        self._job.done.connect(lambda ans, m=mode: self._on_engineer_done(ans, m))
        self._job.failed.connect(self._on_engineer_failed)
        self._job_mode = mode
        self._job_auto = auto
        self.engineer_started.emit("(spontaneous radio update)" if auto else question, mode)
        self._job.start()
        return True

    def _on_engineer_done(self, answer: str, mode: str):
        self.engineer_done.emit(answer)
        if mode == "RADIO" and answer:
            self.say(answer, PRIO_HIGH, 60)      # ends up in the radio log once spoken

    def _on_engineer_failed(self, err: str):
        self.engineer_failed.emit(err)
        self.radio_log.emit("system", f"Engineer: {err}")
        if self._job_mode == "RADIO" and not self._job_auto:
            self.say(self.phrase("agent_error"), PRIO_NORMAL, 15)

    def new_conversation(self):
        if self.agent is not None:
            self.agent.reset()

    # ------------------------------------------------------- push-to-talk
    def set_ptt(self, down: bool):
        """Radio pressed: stop the voice and record; released: transcription → engineer."""
        if down == self._ptt:
            return
        self._ptt = down
        self.ptt_changed.emit(down)
        if down:
            self.voice.interrupt()
            if not self.mic.start():
                self.radio_log.emit("system", "Microphone not available")
            return
        pcm = self.mic.stop()
        if len(pcm) < 16000 * 2 * 0.4:          # under 0.4 s: accidental press
            return
        stt, lang = self.stt, self.lang
        self._stt_job = Job(lambda _emit: stt.transcribe(pcm, lang))
        self._stt_job.done.connect(self._on_transcript)
        self._stt_job.failed.connect(lambda e: (self.radio_log.emit("system", f"Transcription: {e}"),
                                                self.say(self.phrase("stt_error"), PRIO_URGENT, 10)))
        self._stt_job.start()

    def _on_transcript(self, text: str):
        if not text:
            self.say(self.phrase("stt_error"), PRIO_URGENT, 10)
            return
        self.radio_log.emit("driver", text)
        if not self.ask_engineer(text, "RADIO"):
            self.say(self.phrase("busy"), PRIO_NORMAL, 10)

    # ------------------------------------------------------------- shutdown
    def shutdown(self):
        self._closed = True
        self.stop()
        self.onboard_feed.disconnect()
        if self.agent is not None:
            self.agent.cancel()
        self.voice.shutdown()
        self.mcp.stop()
        self.remote.shutdown()
        self.db.close()
