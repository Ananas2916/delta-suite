"""Race engineer: conversation with the AI agent, headset radio and agent, voice and radio settings.

Written chat and push-to-talk are the same conversation: questions asked over the radio show up in the chat
with 📻, while the "Headset radio" panel shows what goes over the radio (automatic messages,
spoken answers, transcriptions and errors).
"""

from __future__ import annotations

import html
import json
from datetime import datetime

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QGuiApplication
from PyQt6.QtWidgets import (
    QCheckBox, QComboBox, QFileDialog, QFormLayout, QFrame, QGroupBox, QHBoxLayout, QLineEdit, QPlainTextEdit,
    QPushButton, QScrollArea, QSpinBox, QSplitter, QTabWidget, QTextBrowser, QVBoxLayout, QWidget,
)

from ai_engine.agent_cli import BACKENDS, find_executable
from ai_engine.lang import DEFAULT_VOICE, KOKORO_VOICES, language_of, voice_label
from ai_engine.race_engineer_agent import build_stint_summary
from ai_engine.radio import RadioConfig
from ai_engine.stt import DEFAULT_MODEL, WHISPER_MODELS, model_cached
from ai_engine.voice import PRIO_URGENT, make_backend
from ai_engine.voice_models import DOWNLOAD_MB, download_kokoro
from ui.hub_state import MODES
from ui.mic import input_devices
from ui.theme import C
from ui.widgets import Card, SessionPicker, dspin, label
from ui.workers import Job
from hub_core.i18n import tr

QUICK_QUESTIONS = {
    "Where am I losing time": "Compare my last valid lap with the best one, corner by corner, and tell me where and "
                              "why I am losing time.",
    "Tyre pressures": "Analyse tyre temperatures and pressures. Are the hot pressures in the right window? "
                      "Which cold pressures should I set for the next run, wheel by wheel?",
    "Race strategy": "Give me the strategy for the rest of the race: stint length, pit lap, "
                     "fuel to add and whether a tyre change is worth it.",
    "Balance": "From the tyre, brake and corner data, is the car understeering or oversteering? "
               "Propose the setup changes with propose_change.",
}
ENGINES = {"kokoro": "Built-in Kokoro (local)", "tsukumo": "Tsukumo (its own window speaks)", "none": "No voice"}
WHO_COLORS = {"radio": C["blue"], "driver": C["yellow"], "engineer": C["green"], "system": C["dim"]}
WHO_NAMES = {"radio": "Radio", "driver": "Driver", "engineer": "Engineer", "system": "System"}


def dot(color: str, text: str) -> str:
    return f"<span style='color:{color}'>●</span> {text}"


def compact(combo: QComboBox, chars: int = 18) -> QComboBox:
    """Long entries do not widen the settings column."""
    combo.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
    combo.setMinimumContentsLength(chars)
    return combo


class EngineerPage(QWidget):
    def __init__(self, hub):
        super().__init__()
        self.hub = hub
        self._transcript = ""

        root = QVBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 16)
        head = QHBoxLayout()
        head.addWidget(label(tr("Race engineer"), "h1"))
        head.addStretch()
        self.overview = label("", "dim")
        head.addWidget(self.overview)
        root.addLayout(head)

        self.tabs = QTabWidget()
        self.tabs.addTab(self._build_chat(), tr("Conversation"))
        self.tabs.addTab(self._build_summary(), tr("Stint summary"))
        self.tabs.addTab(self._build_settings(), tr("Settings"))
        root.addWidget(self.tabs, 1)

        self.render_timer = QTimer(self)
        self.render_timer.timeout.connect(self._render)
        self.picker.currentIndexChanged.connect(self._regen)
        self.laps_left.valueChanged.connect(self._regen)
        hub.lap_completed.connect(lambda _: self._regen() if self.picker.currentData() is None else None)
        hub.engineer_started.connect(self._on_started)
        hub.engineer_text.connect(self._on_text)
        hub.engineer_done.connect(self._on_done)
        hub.engineer_failed.connect(self._on_failed)
        hub.radio_log.connect(self._log)
        hub.voice_error.connect(lambda e: self._log("system", f"Voice: {e}"))
        hub.ptt_changed.connect(self._on_ptt)
        hub.mode_changed.connect(lambda _: self._update_status())
        self._regen()
        self._render()
        self._update_status()

    # ------------------------------------------------------------ layout
    def _build_chat(self) -> QWidget:
        hub = self.hub
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(10, 10, 10, 10)

        row = QHBoxLayout()
        row.addWidget(label(tr("Data"), "dim"))
        self.picker = SessionPicker(hub)
        row.addWidget(self.picker)
        row.addWidget(label(tr("Race laps left"), "dim"))
        self.laps_left = QSpinBox()
        self.laps_left.setRange(0, 999)
        self.laps_left.setSpecialValueText(tr("n/a"))
        row.addWidget(self.laps_left)
        row.addStretch()
        new_btn = QPushButton(tr("New conversation"))
        new_btn.clicked.connect(self._new_chat)
        row.addWidget(new_btn)
        lay.addLayout(row)

        split = QSplitter(Qt.Orientation.Horizontal)
        left = QWidget()
        ll = QVBoxLayout(left)
        ll.setContentsMargins(0, 0, 0, 0)
        self.chat = QTextBrowser()
        self.chat.setOpenExternalLinks(True)
        ll.addWidget(self.chat, 1)
        quick = QHBoxLayout()
        for name, q in QUICK_QUESTIONS.items():
            b = QPushButton(tr(name))
            b.clicked.connect(lambda _=False, q=q: self._send(tr(q)))
            quick.addWidget(b)
        ll.addLayout(quick)
        ask_row = QHBoxLayout()
        self.question = QLineEdit()
        self.question.setPlaceholderText(tr("Ask the engineer…"))
        self.question.returnPressed.connect(lambda: self._send(self.question.text()))
        self.send_btn = QPushButton(tr("Send"))
        self.send_btn.setObjectName("primary")
        self.send_btn.clicked.connect(lambda: self._send(self.question.text()))
        ask_row.addWidget(self.question, 1)
        ask_row.addWidget(self.send_btn)
        ll.addLayout(ask_row)
        self.status = label("", "dim")
        ll.addWidget(self.status)
        split.addWidget(left)

        radio = Card()
        rl = QVBoxLayout(radio)
        rl.setContentsMargins(12, 10, 12, 12)
        rl.addWidget(label(tr("Headset radio"), "h2"))
        self.radio_state = label("", "dim")
        self.radio_state.setWordWrap(True)
        rl.addWidget(self.radio_state)
        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        rl.addWidget(self.log, 1)
        self.ptt_btn = QPushButton(tr("Hold to talk"))
        self.ptt_btn.setObjectName("primary")
        self.ptt_btn.pressed.connect(lambda: hub.set_ptt(True))
        self.ptt_btn.released.connect(lambda: hub.set_ptt(False))
        rl.addWidget(self.ptt_btn)
        hint = label(tr("On the wheel: bind the 'Engineer radio' button in the Delta Suite Bridge app window "
                     "in game. Hold it, speak in the language of the chosen voice, release."), "dim")
        hint.setWordWrap(True)
        rl.addWidget(hint)
        split.addWidget(radio)
        split.setSizes([820, 440])
        lay.addWidget(split, 1)
        return w

    def _build_summary(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(10, 10, 10, 10)
        row = QHBoxLayout()
        self.summary_note = label("", "dim")
        self.summary_note.setWordWrap(True)
        row.addWidget(self.summary_note, 1)
        regen = QPushButton(tr("Regenerate"))
        regen.clicked.connect(self._regen)
        row.addWidget(regen)
        lay.addLayout(row)
        self.summary = QPlainTextEdit()
        self.summary.setReadOnly(True)
        self.summary.setStyleSheet("font-family: Consolas; font-size: 9pt;")
        lay.addWidget(self.summary, 1)
        return w

    def _build_settings(self) -> QWidget:
        hub = self.hub
        inner = QWidget()
        cols = QHBoxLayout(inner)
        cols.setContentsMargins(10, 4, 10, 10)
        cols.setSpacing(14)
        c1, c2, c3 = QVBoxLayout(), QVBoxLayout(), QVBoxLayout()

        # --- agent
        g = QGroupBox(tr("AI agent"))
        f = QFormLayout(g)
        self.backend = compact(QComboBox())
        for k, v in BACKENDS.items():
            self.backend.addItem(tr(v), k)
        self.backend.setCurrentIndex(max(0, self.backend.findData(hub.setting("engineer/backend", "claude"))))
        self.model = QLineEdit(hub.setting("engineer/model", ""))
        self.model.setPlaceholderText(tr("empty = agent default"))
        self.custom = QLineEdit(hub.setting("engineer/custom_cmd", ""))
        self.custom.setPlaceholderText(tr("e.g. my_agent.exe --prompt {prompt}"))
        self.custom.setToolTip(tr("Without {prompt} the question arrives on stdin."))
        self.api_key = QLineEdit(hub.setting("api_key", ""))
        self.api_key.setEchoMode(QLineEdit.EchoMode.Password)
        self.api_key.setPlaceholderText(tr("only for the API backend"))
        self.agent_status = label("", "dim")
        self.agent_status.setWordWrap(True)
        f.addRow(tr("Agent"), self.backend)
        f.addRow(tr("Model"), self.model)
        f.addRow(tr("Command"), self.custom)
        f.addRow(tr("API key"), self.api_key)
        f.addRow(self.agent_status)
        for w in (self.model, self.custom, self.api_key):
            w.editingFinished.connect(self._save_engineer)
        self.backend.currentIndexChanged.connect(self._save_engineer)
        test_eng = QPushButton(tr("Test: ask about fuel over the radio"))
        test_eng.clicked.connect(lambda: hub.ask_engineer(tr("How many laps of fuel do I have? Answer in one sentence."), "RADIO"))
        f.addRow(test_eng)
        c1.addWidget(g)

        g = QGroupBox(tr("External agents (MCP)"))
        v = QVBoxLayout(g)
        self.mcp_info = label("", "dim")
        self.mcp_info.setWordWrap(True)
        self.mcp_info.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        copy = QPushButton(tr("Copy MCP configuration"))
        copy.clicked.connect(self._copy_mcp)
        v.addWidget(self.mcp_info)
        v.addWidget(copy)
        c1.addWidget(g)
        again = QPushButton(tr("Show the get-started list on the Overview"))
        again.clicked.connect(lambda: hub.settings.setValue("checklist/hidden", False))
        c1.addWidget(again)

        # --- voice
        g = QGroupBox(tr("Voice and language"))
        f = QFormLayout(g)
        self.engine = compact(QComboBox())
        for k, v in ENGINES.items():
            self.engine.addItem(tr(v), k)
        self.engine.setCurrentIndex(max(0, self.engine.findData(hub.setting("voice/engine", "kokoro"))))
        self.voice = compact(QComboBox())
        for vc in KOKORO_VOICES:
            self.voice.addItem(voice_label(vc), vc)
        self.voice.setCurrentIndex(max(0, self.voice.findData(hub.setting("voice/voice", DEFAULT_VOICE))))
        self.voice_lang = label("", "dim")
        self.voice_lang.setWordWrap(True)
        self.speed = dspin(0.6, 1.8, hub.setting("voice/speed", 1.1, float), 0.05, 2)
        self.model_dir = QLineEdit(hub.setting("voice/model_dir", ""))
        self.model_dir.setPlaceholderText(tr("empty = downloaded model (or Tsukumo's)"))
        browse = QPushButton("…")
        browse.setFixedWidth(34)
        browse.setStyleSheet("padding: 4px 0;")
        browse.clicked.connect(self._browse_model)
        md = QHBoxLayout()
        md.addWidget(self.model_dir, 1)
        md.addWidget(browse)
        self.voice_status = label("", "dim")
        self.voice_status.setWordWrap(True)
        f.addRow(tr("Engine"), self.engine)
        f.addRow(tr("Voice"), self.voice)
        f.addRow(self.voice_lang)
        f.addRow(tr("Speed"), self.speed)
        f.addRow(tr("Kokoro model"), md)
        f.addRow(self.voice_status)
        self.voice_dl = QPushButton(tr("Download voice ({mb} MB, once)", mb=DOWNLOAD_MB))
        self.voice_dl.setObjectName("primary")
        self.voice_dl.clicked.connect(self.download_voice)
        f.addRow(self.voice_dl)
        self._dl_job = None
        for w in (self.engine, self.voice):
            w.currentIndexChanged.connect(self._save_voice)
        self.speed.valueChanged.connect(self._save_voice)
        self.model_dir.editingFinished.connect(self._save_voice)
        test = QPushButton(tr("Test voice"))
        test.clicked.connect(lambda: hub.say(hub.phrase("radio_check"), PRIO_URGENT, 30))
        f.addRow(test)
        c2.addWidget(g)

        # --- push-to-talk
        g = QGroupBox(tr("Microphone and transcription"))
        f = QFormLayout(g)
        self.mic = compact(QComboBox())
        self.mic.addItem(tr("Default microphone"), b"")
        for d in input_devices():
            self.mic.addItem(d.description(), bytes(d.id()))
        saved = hub.settings.value("voice/mic", b"")
        self.mic.setCurrentIndex(max(0, self.mic.findData(bytes(saved) if saved else b"")))
        self.mic.currentIndexChanged.connect(self._save_mic)
        self.stt_engine = compact(QComboBox())
        self.stt_engine.addItem(tr("Local Whisper (built in)"), "whisper")
        self.stt_engine.addItem(tr("Tsukumo (listening engine)"), "tsukumo")
        self.stt_engine.addItem(tr("Off"), "none")
        self.stt_engine.setCurrentIndex(max(0, self.stt_engine.findData(hub.setting("stt/engine", "whisper"))))
        self.stt_model = compact(QComboBox())
        for name, note in WHISPER_MODELS.items():
            self.stt_model.addItem(f"{name} — {tr(note)}" + ("  ✓ " + tr("downloaded") if model_cached(name) else ""), name)
        self.stt_model.setCurrentIndex(max(0, self.stt_model.findData(hub.setting("stt/model", DEFAULT_MODEL))))
        self.stt_status = label("", "dim")
        self.stt_status.setWordWrap(True)
        self.tsukumo_url = QLineEdit(hub.setting("voice/tsukumo_url", "http://127.0.0.1:8770"))
        for w in (self.stt_engine, self.stt_model):
            w.currentIndexChanged.connect(self._save_stt)
        self.tsukumo_url.editingFinished.connect(self._save_stt)
        f.addRow(tr("Microphone"), self.mic)
        f.addRow(tr("Transcription"), self.stt_engine)
        f.addRow(tr("Whisper model"), self.stt_model)
        f.addRow(tr("Tsukumo"), self.tsukumo_url)
        f.addRow(self.stt_status)
        c2.addWidget(g)

        # --- radio rules
        g = QGroupBox(tr("Automatic radio (no AI, instant)"))
        f = QFormLayout(g)
        cfg = hub.radio_rules.cfg
        self.rule_boxes = {}
        for key, text in (("lap_times", "Lap time, delta, laps to go and session time"), ("fuel", "Fuel (5, 3, 2, 1 laps)"),
                          ("tyres", "Tyres out of the window (once per stint)"), ("gaps", "Race gaps, with the trend"),
                          ("flags", "Flags, yellows ahead with the distance, track clear"),
                          ("positions", "Positions: first lap, overtakes, fastest lap, finish"),
                          ("rivals", "Rivals: close car ahead or behind, pit stops"),
                          ("car", "Car: punctures, damage, worn tyres, limiter"),
                          ("hybrid", "Hybrid battery (20%, empty, lap energy)")):
            cb = QCheckBox(tr(text))
            cb.setChecked(getattr(cfg, key))
            cb.toggled.connect(self._save_rules)
            self.rule_boxes[key] = cb
            f.addRow(cb)
        self.chatter = QComboBox()
        for level, text in ((0, "Essential"), (1, "Normal"), (2, "Chatty, like F1 radio")):
            self.chatter.addItem(tr(text), level)
        self.chatter.setCurrentIndex(max(0, self.chatter.findData(cfg.chatter)))
        self.chatter.setToolTip(tr("How much the engineer talks between the important calls. All local phrases: "
                                "instant and free.\nEssential: only the calls above.\nNormal: + start, "
                                "overtakes by name, rivals' pit stops (undercut/overcut), your stop, purple "
                                "sectors, pace, half distance, timesheet in practice.\nChatty: + every purple "
                                "sector, rivals' lap times, praise, battery to attack or defend, updates when "
                                "the radio is quiet."))
        self.chatter.currentIndexChanged.connect(self._save_rules)
        f.addRow(tr("Engineer"), compact(self.chatter, 24))
        self.ai_laps = QSpinBox()
        self.ai_laps.setRange(0, 20)
        self.ai_laps.setValue(cfg.ai_comment_laps)
        self.ai_laps.setSpecialValueText(tr("never"))
        self.ai_laps.setSuffix(" " + tr("laps"))
        self.ai_laps.setToolTip(tr("In a race, every N laps the AI engineer (Claude Code...) looks at the data and says "
                                "one thing on its own: strategy, pace against the rivals, tyres. Uses the agent: "
                                "a few seconds late and it counts against your subscription."))
        self.ai_laps.valueChanged.connect(self._save_rules)
        f.addRow(tr("AI comment every"), self.ai_laps)
        self.t_lo = dspin(40, 120, cfg.tyre_temp_lo, 1, 0, "°C")
        self.t_hi = dspin(40, 140, cfg.tyre_temp_hi, 1, 0, "°C")
        self.p_lo = dspin(10, 40, cfg.tyre_press_lo, 0.1, 1, "psi")
        self.p_hi = dspin(10, 45, cfg.tyre_press_hi, 0.1, 1, "psi")
        for w in (self.t_lo, self.t_hi, self.p_lo, self.p_hi):
            w.valueChanged.connect(self._save_rules)
        row_t, row_p = QHBoxLayout(), QHBoxLayout()
        row_t.addWidget(self.t_lo)
        row_t.addWidget(self.t_hi)
        row_p.addWidget(self.p_lo)
        row_p.addWidget(self.p_hi)
        f.addRow(tr("Tyre temperature"), row_t)
        f.addRow(tr("Hot pressure"), row_p)
        self.always = QCheckBox(tr("Also on outside Driver mode"))
        self.always.setChecked(hub.setting("radio/always", False, bool))
        self.always.toggled.connect(self._save_always)
        f.addRow(self.always)
        c3.addWidget(g)

        for c in (c1, c2, c3):
            c.addStretch()
            cols.addLayout(c, 1)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setWidget(inner)
        return scroll

    def showEvent(self, e):
        self._update_status()
        super().showEvent(e)

    # ------------------------------------------------------------ conversation
    def _regen(self):
        info, laps, _ = self.picker.selected()
        live = self.picker.currentData() is None and self.hub.last_sample is not None
        fuel = self.hub.last_sample.fuel if live else (laps[-1].fuel_end if laps else None)
        self.summary.setPlainText(build_stint_summary(info or {}, laps, fuel, self.laps_left.value() or None))

    def _new_chat(self):
        self.hub.new_conversation()
        self._transcript = ""
        self._render()

    def _send(self, question: str):
        question = question.strip()
        if not question:
            return
        sid = self.picker.currentData()
        if sid is not None:
            question += " " + tr("(archived session: session_id={sid})", sid=sid)
        if self.laps_left.value():
            question += " " + tr("Race laps left: {n}.", n=self.laps_left.value())
        if not self.hub.ask_engineer(question, "ANALYSIS"):
            self.status.setText(tr("The engineer is already answering."))
            return
        self.question.clear()

    def _on_started(self, question: str, mode: str):
        tag = "📻 " if mode == "RADIO" else ""
        self._transcript += f"\n\n---\n\n**{tag}{tr('You')}:** {question}\n\n**{tr('Engineer')}:** "
        self.send_btn.setEnabled(False)
        self.status.setText(tr("The engineer is analysing the data…"))
        self.render_timer.start(150)

    def _on_text(self, chunk: str):
        self._transcript += chunk

    def _on_done(self, final: str):
        if final and not self._transcript.rstrip().endswith(final.strip()[-40:]):
            self._transcript += final      # backend without streaming
        self._finish(tr("Answer complete."))

    def _on_failed(self, err: str):
        self._transcript += "\n\n*" + tr("Error: {err}", err=err) + "*"
        self._finish(tr("Request failed."))

    def _finish(self, msg: str):
        self.render_timer.stop()
        self.send_btn.setEnabled(True)
        self.status.setText(msg)
        self._render()

    def _render(self):
        intro = "*" + tr("Ask for an analysis: the engineer reads telemetry, laps, setup and standings from Delta "
                         "Suite and can propose changes, which you confirm (Pit & Setup page or wheel button). "
                         "Questions asked over the radio show up here with 📻.") + "*"
        self.chat.setMarkdown(intro + self._transcript)
        sb = self.chat.verticalScrollBar()
        sb.setValue(sb.maximum())

    # ------------------------------------------------------------ radio
    def _on_ptt(self, down: bool):
        self.ptt_btn.setText(tr("Listening… release to send") if down else tr("Hold to talk"))

    def _log(self, who: str, text: str):
        ts = datetime.now().strftime("%H:%M:%S")
        col = WHO_COLORS.get(who, C["text"])
        self.log.appendHtml(f"<span style='color:{C['dim']}'>{ts}</span> "
                            f"<b style='color:{col}'>{tr(WHO_NAMES.get(who, who)).upper()}</b> {html.escape(text)}")

    # ------------------------------------------------------------ saving
    def _save_engineer(self):
        st = self.hub.settings
        st.setValue("engineer/backend", self.backend.currentData())
        st.setValue("engineer/model", self.model.text().strip())
        st.setValue("engineer/custom_cmd", self.custom.text().strip())
        st.setValue("api_key", self.api_key.text().strip())
        self.hub.reset_agent()
        self._update_status()

    def _save_voice(self):
        st = self.hub.settings
        st.setValue("voice/engine", self.engine.currentData())
        st.setValue("voice/voice", self.voice.currentData())
        st.setValue("voice/speed", self.speed.value())
        st.setValue("voice/model_dir", self.model_dir.text().strip())
        self.hub.reload_voice()
        self._update_status()

    def _save_stt(self):
        st = self.hub.settings
        st.setValue("stt/engine", self.stt_engine.currentData())
        st.setValue("stt/model", self.stt_model.currentData())
        st.setValue("voice/tsukumo_url", self.tsukumo_url.text().strip())
        self.hub.reload_stt()
        self._update_status()

    def _save_mic(self):
        self.hub.settings.setValue("voice/mic", self.mic.currentData() or b"")
        self.hub.reload_mic()

    def _save_rules(self):
        c = RadioConfig(**{k: cb.isChecked() for k, cb in self.rule_boxes.items()},
                        tyre_temp_lo=self.t_lo.value(), tyre_temp_hi=self.t_hi.value(),
                        tyre_press_lo=self.p_lo.value(), tyre_press_hi=self.p_hi.value(),
                        chatter=int(self.chatter.currentData()), ai_comment_laps=self.ai_laps.value())
        self.hub.save_radio_config(c)

    def _save_always(self, on: bool):
        self.hub.settings.setValue("radio/always", on)
        self._update_status()

    def _browse_model(self):
        d = QFileDialog.getExistingDirectory(self, tr("Folder with kokoro-v1.0.onnx and voices-v1.0.bin"),
                                             self.model_dir.text())
        if d:
            self.model_dir.setText(d)
            self._save_voice()

    def download_voice(self):
        """Download the Kokoro model in the background, then switch the voice on."""
        if self._dl_job is not None and self._dl_job.isRunning():
            return
        self.voice_dl.setEnabled(False)
        self.voice_dl.setText(tr("Downloading…"))

        def work(emit):
            download_kokoro(progress=lambda done, total: emit(f"{done * 100 // total}"))
            return True

        self._dl_job = Job(work)
        self._dl_job.text.connect(lambda pct: self.voice_dl.setText(tr("Downloading… {pct}%", pct=pct)))
        self._dl_job.done.connect(lambda _: self._download_finished(None))
        self._dl_job.failed.connect(self._download_finished)
        self._dl_job.start()

    def _download_finished(self, error: str | None):
        self.voice_dl.setEnabled(True)
        self.voice_dl.setText(tr("Download voice ({mb} MB, once)", mb=DOWNLOAD_MB))
        if error:
            self._log("system", tr("Voice download failed: {err}", err=error))
        else:
            self.model_dir.clear()          # the default folder now has the model
            self._save_voice()
            self._log("system", tr("Voice downloaded"))
            self.hub.say(self.hub.phrase("radio_check"), PRIO_URGENT, 30)

    def _copy_mcp(self):
        QGuiApplication.clipboard().setText(json.dumps(self.hub.mcp.client_config(), indent=2))
        self._log("system", tr("MCP configuration copied to the clipboard (valid while the hub stays open)"))

    # ------------------------------------------------------------ status
    def _update_status(self):
        b = self.backend.currentData()
        exe = {"claude": "claude"}.get(b)
        agent_ok = True
        if exe:
            found = find_executable(exe)
            agent_ok = found is not None
            self.agent_status.setText(dot(C["green"], found) if found else
                                      dot(C["red"], tr("'{exe}' not found in PATH", exe=exe)))
        elif b == "api":
            agent_ok = bool(self.api_key.text().strip())
            self.agent_status.setText(tr("Uses the stint summary (no MCP tools). Pay-as-you-go costs."))
        else:
            self.agent_status.setText(tr("The command receives the MCP URL and token in the DELTASUITE_MCP_URL and "
                                      "DELTASUITE_MCP_TOKEN variables."))
        for w, on in ((self.model, b != "custom"), (self.custom, b == "custom"), (self.api_key, b == "api")):
            w.setEnabled(on)
        self.summary_note.setText(
            tr("With the API a summary like this is attached to the first question.") if b == "api" else
            tr("The agent reads the data by itself with Delta Suite's tools (MCP): the summary is just for you."))

        voice = self.voice.currentData()
        lang = language_of(voice)
        self.voice_lang.setText(tr("Spoken language: {lang}. Radio, radio answers and transcription follow the "
                                   "voice; the written analysis follows the interface language.", lang=lang.name))
        voice_ok, why = make_backend(self.engine.currentData(), voice, self.speed.value(),
                                     self.model_dir.text() or None).available()
        self.voice_status.setText(dot(C["green"], tr("ready")) if voice_ok else dot(C["red"], tr(why)))
        downloading = self._dl_job is not None and self._dl_job.isRunning()
        missing = self.engine.currentData() == "kokoro" and not voice_ok and not self.model_dir.text().strip()
        self.voice_dl.setVisible(missing or downloading)
        stt_ok, stt_why = self.hub.stt.available()
        self.stt_status.setText(dot(C["green"] if stt_ok else C["red"], tr(stt_why) + " · " + tr("language {code}", code=lang.code)))
        self.stt_model.setEnabled(self.stt_engine.currentData() == "whisper")
        self.tsukumo_url.setEnabled(self.stt_engine.currentData() == "tsukumo")

        m = self.hub.mcp
        self.mcp_info.setText(
            tr("MCP server running on {url} (local-only port, new token at every start). The agent chosen above "
               "uses it by itself; you can also connect an interactive Claude Code session or any MCP client "
               "by pasting the configuration.", url=m.url) if m.error is None else
            tr("MCP server not started: {err}", err=m.error))

        voice_name = voice_label(voice).split(" — ")[0] if self.engine.currentData() != "none" else tr("off")
        self.overview.setText(("&nbsp;" * 5).join((
            dot(C["green"] if agent_ok else C["red"], tr(BACKENDS.get(b, b))),
            dot(C["green"] if voice_ok else C["red"], tr("voice {name} ({lang})", name=voice_name, lang=lang.name)),
            dot(C["green"] if stt_ok else C["red"], "push-to-talk"))))
        mode = tr(MODES.get(self.hub.mode, self.hub.mode))
        self.radio_state.setText(
            dot(C["green"], tr("Automatic radio on · {mode} mode", mode=mode)) if self.hub.radio_active else
            dot(C["yellow"], tr("Automatic radio off in {mode} mode: it turns on in Driver mode or from Settings. "
                                "Push-to-talk answers anyway.", mode=mode)))
