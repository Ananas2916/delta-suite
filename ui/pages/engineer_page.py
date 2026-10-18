"""Ingegnere di pista: conversazione con l'agente AI, radio in cuffia e impostazioni di agente, voce e radio.

Chat scritta e push-to-talk sono la stessa conversazione: le domande fatte via radio compaiono nella chat
con 📻, mentre il pannello "Radio in cuffia" riporta quello che passa in radio (messaggi automatici,
risposte lette, trascrizioni ed errori).
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
from ui.hub_state import MODES
from ui.mic import input_devices
from ui.theme import C
from ui.widgets import Card, SessionPicker, dspin, label

QUICK_QUESTIONS = {
    "Dove perdo tempo": "Confronta il mio ultimo giro valido con il migliore, curva per curva, e dimmi dove e "
                        "perché perdo tempo.",
    "Pressioni gomme": "Analizza temperature e pressioni gomme. Le pressioni a caldo sono nella finestra giusta? "
                       "Che pressioni a freddo imposto per il prossimo run, ruota per ruota?",
    "Strategia gara": "Dammi la strategia per il resto della gara: lunghezza stint, giro di sosta, "
                      "carburante da imbarcare e se conviene cambiare gomme.",
    "Bilanciamento": "Dai dati di gomme, freni e curve, la macchina è sottosterzante o sovrasterzante? "
                     "Proponi le modifiche di setup con proponi_modifica.",
}
ENGINES = {"kokoro": "Kokoro integrato (locale)", "tsukumo": "Tsukumo (parla la sua finestra)", "none": "Nessuna voce"}
WHO_COLORS = {"radio": C["blue"], "pilota": C["yellow"], "ingegnere": C["green"], "sistema": C["dim"]}


def dot(color: str, text: str) -> str:
    return f"<span style='color:{color}'>●</span> {text}"


def compact(combo: QComboBox, chars: int = 18) -> QComboBox:
    """Le voci lunghe non allargano la colonna delle impostazioni."""
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
        head.addWidget(label("Ingegnere di pista", "h1"))
        head.addStretch()
        self.overview = label("", "dim")
        head.addWidget(self.overview)
        root.addLayout(head)

        self.tabs = QTabWidget()
        self.tabs.addTab(self._build_chat(), "Conversazione")
        self.tabs.addTab(self._build_summary(), "Riepilogo stint")
        self.tabs.addTab(self._build_settings(), "Impostazioni")
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
        hub.voice_error.connect(lambda e: self._log("sistema", f"Voce: {e}"))
        hub.ptt_changed.connect(self._on_ptt)
        hub.mode_changed.connect(lambda _: self._update_status())
        self._regen()
        self._render()
        self._update_status()

    # ------------------------------------------------------------ costruzione
    def _build_chat(self) -> QWidget:
        hub = self.hub
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(10, 10, 10, 10)

        row = QHBoxLayout()
        row.addWidget(label("Dati", "dim"))
        self.picker = SessionPicker(hub)
        row.addWidget(self.picker)
        row.addWidget(label("Giri gara rimanenti", "dim"))
        self.laps_left = QSpinBox()
        self.laps_left.setRange(0, 999)
        self.laps_left.setSpecialValueText("n/d")
        row.addWidget(self.laps_left)
        row.addStretch()
        new_btn = QPushButton("Nuova conversazione")
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
            b = QPushButton(name)
            b.clicked.connect(lambda _=False, q=q: self._send(q))
            quick.addWidget(b)
        ll.addLayout(quick)
        ask_row = QHBoxLayout()
        self.question = QLineEdit()
        self.question.setPlaceholderText("Chiedi all'ingegnere…")
        self.question.returnPressed.connect(lambda: self._send(self.question.text()))
        self.send_btn = QPushButton("Invia")
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
        rl.addWidget(label("Radio in cuffia", "h2"))
        self.radio_state = label("", "dim")
        self.radio_state.setWordWrap(True)
        rl.addWidget(self.radio_state)
        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        rl.addWidget(self.log, 1)
        self.ptt_btn = QPushButton("Tieni premuto e parla")
        self.ptt_btn.setObjectName("primary")
        self.ptt_btn.pressed.connect(lambda: hub.set_ptt(True))
        self.ptt_btn.released.connect(lambda: hub.set_ptt(False))
        rl.addWidget(self.ptt_btn)
        hint = label("Al volante: assegna il tasto 'Radio ingegnere' nella finestra dell'app Delta Suite Bridge "
                     "in gioco. Tieni premuto, parla nella lingua della voce scelta, rilascia.", "dim")
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
        regen = QPushButton("Rigenera")
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

        # --- agente
        g = QGroupBox("Agente AI")
        f = QFormLayout(g)
        self.backend = compact(QComboBox())
        for k, v in BACKENDS.items():
            self.backend.addItem(v, k)
        self.backend.setCurrentIndex(max(0, self.backend.findData(hub.setting("engineer/backend", "claude"))))
        self.model = QLineEdit(hub.setting("engineer/model", ""))
        self.model.setPlaceholderText("vuoto = predefinito dell'agente")
        self.custom = QLineEdit(hub.setting("engineer/custom_cmd", ""))
        self.custom.setPlaceholderText("es. mio_agente.exe --prompt {prompt}")
        self.custom.setToolTip("Senza {prompt} la domanda arriva da stdin.")
        self.api_key = QLineEdit(hub.setting("api_key", ""))
        self.api_key.setEchoMode(QLineEdit.EchoMode.Password)
        self.api_key.setPlaceholderText("solo per il backend API")
        self.agent_status = label("", "dim")
        self.agent_status.setWordWrap(True)
        f.addRow("Agente", self.backend)
        f.addRow("Modello", self.model)
        f.addRow("Comando", self.custom)
        f.addRow("Chiave API", self.api_key)
        f.addRow(self.agent_status)
        for w in (self.model, self.custom, self.api_key):
            w.editingFinished.connect(self._save_engineer)
        self.backend.currentIndexChanged.connect(self._save_engineer)
        test_eng = QPushButton("Prova: chiedi il carburante via radio")
        test_eng.clicked.connect(lambda: hub.ask_engineer("Quanti giri di carburante ho? Rispondi in una frase.", "RADIO"))
        f.addRow(test_eng)
        c1.addWidget(g)

        g = QGroupBox("Agenti esterni (MCP)")
        v = QVBoxLayout(g)
        self.mcp_info = label("", "dim")
        self.mcp_info.setWordWrap(True)
        self.mcp_info.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        copy = QPushButton("Copia configurazione MCP")
        copy.clicked.connect(self._copy_mcp)
        v.addWidget(self.mcp_info)
        v.addWidget(copy)
        c1.addWidget(g)

        # --- voce
        g = QGroupBox("Voce e lingua")
        f = QFormLayout(g)
        self.engine = compact(QComboBox())
        for k, v in ENGINES.items():
            self.engine.addItem(v, k)
        self.engine.setCurrentIndex(max(0, self.engine.findData(hub.setting("voice/engine", "kokoro"))))
        self.voice = compact(QComboBox())
        for vc in KOKORO_VOICES:
            self.voice.addItem(voice_label(vc), vc)
        self.voice.setCurrentIndex(max(0, self.voice.findData(hub.setting("voice/voice", DEFAULT_VOICE))))
        self.voice_lang = label("", "dim")
        self.voice_lang.setWordWrap(True)
        self.speed = dspin(0.6, 1.8, hub.setting("voice/speed", 1.1, float), 0.05, 2)
        self.model_dir = QLineEdit(hub.setting("voice/model_dir", ""))
        self.model_dir.setPlaceholderText("vuoto = modelli di Tsukumo")
        browse = QPushButton("…")
        browse.setFixedWidth(34)
        browse.setStyleSheet("padding: 4px 0;")
        browse.clicked.connect(self._browse_model)
        md = QHBoxLayout()
        md.addWidget(self.model_dir, 1)
        md.addWidget(browse)
        self.voice_status = label("", "dim")
        self.voice_status.setWordWrap(True)
        f.addRow("Motore", self.engine)
        f.addRow("Voce", self.voice)
        f.addRow(self.voice_lang)
        f.addRow("Velocità", self.speed)
        f.addRow("Modello Kokoro", md)
        f.addRow(self.voice_status)
        for w in (self.engine, self.voice):
            w.currentIndexChanged.connect(self._save_voice)
        self.speed.valueChanged.connect(self._save_voice)
        self.model_dir.editingFinished.connect(self._save_voice)
        test = QPushButton("Prova voce")
        test.clicked.connect(lambda: hub.say(hub.phrase("radio_check"), PRIO_URGENT, 30))
        f.addRow(test)
        c2.addWidget(g)

        # --- push-to-talk
        g = QGroupBox("Microfono e trascrizione")
        f = QFormLayout(g)
        self.mic = compact(QComboBox())
        self.mic.addItem("Microfono predefinito", b"")
        for d in input_devices():
            self.mic.addItem(d.description(), bytes(d.id()))
        saved = hub.settings.value("voice/mic", b"")
        self.mic.setCurrentIndex(max(0, self.mic.findData(bytes(saved) if saved else b"")))
        self.mic.currentIndexChanged.connect(self._save_mic)
        self.stt_engine = compact(QComboBox())
        self.stt_engine.addItem("Whisper locale (integrato)", "whisper")
        self.stt_engine.addItem("Tsukumo (motore Ascolto)", "tsukumo")
        self.stt_engine.addItem("Disattivata", "none")
        self.stt_engine.setCurrentIndex(max(0, self.stt_engine.findData(hub.setting("stt/engine", "whisper"))))
        self.stt_model = compact(QComboBox())
        for name, note in WHISPER_MODELS.items():
            self.stt_model.addItem(f"{name} — {note}" + ("  ✓ già scaricato" if model_cached(name) else ""), name)
        self.stt_model.setCurrentIndex(max(0, self.stt_model.findData(hub.setting("stt/model", DEFAULT_MODEL))))
        self.stt_status = label("", "dim")
        self.stt_status.setWordWrap(True)
        self.tsukumo_url = QLineEdit(hub.setting("voice/tsukumo_url", "http://127.0.0.1:8770"))
        for w in (self.stt_engine, self.stt_model):
            w.currentIndexChanged.connect(self._save_stt)
        self.tsukumo_url.editingFinished.connect(self._save_stt)
        f.addRow("Microfono", self.mic)
        f.addRow("Trascrizione", self.stt_engine)
        f.addRow("Modello Whisper", self.stt_model)
        f.addRow("Tsukumo", self.tsukumo_url)
        f.addRow(self.stt_status)
        c2.addWidget(g)

        # --- regole radio
        g = QGroupBox("Radio automatica (senza AI, immediata)")
        f = QFormLayout(g)
        cfg = hub.radio_rules.cfg
        self.rule_boxes = {}
        for key, text in (("lap_times", "Tempo sul giro e delta"), ("fuel", "Carburante (5, 3, 2, 1 giri)"),
                          ("tyres", "Gomme fuori finestra (una volta per stint)"), ("gaps", "Distacchi in gara"),
                          ("flags", "Bandiere"), ("hybrid", "Batteria delle ibride (20%, scarica, energia del giro)")):
            cb = QCheckBox(text)
            cb.setChecked(getattr(cfg, key))
            cb.toggled.connect(self._save_rules)
            self.rule_boxes[key] = cb
            f.addRow(cb)
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
        f.addRow("Temperatura gomme", row_t)
        f.addRow("Pressione a caldo", row_p)
        self.always = QCheckBox("Attiva anche fuori dalla modalità Pilota")
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

    # ------------------------------------------------------------ conversazione
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
            question += f" (sessione in archivio: session_id={sid})"
        if self.laps_left.value():
            question += f" Giri di gara rimanenti: {self.laps_left.value()}."
        if not self.hub.ask_engineer(question, "ANALISI"):
            self.status.setText("L'ingegnere sta già rispondendo.")
            return
        self.question.clear()

    def _on_started(self, question: str, mode: str):
        tag = "📻 " if mode == "RADIO" else ""
        self._transcript += f"\n\n---\n\n**{tag}Tu:** {question}\n\n**Ingegnere:** "
        self.send_btn.setEnabled(False)
        self.status.setText("L'ingegnere sta analizzando i dati…")
        self.render_timer.start(150)

    def _on_text(self, chunk: str):
        self._transcript += chunk

    def _on_done(self, final: str):
        if final and not self._transcript.rstrip().endswith(final.strip()[-40:]):
            self._transcript += final      # backend senza streaming
        self._finish("Risposta completata.")

    def _on_failed(self, err: str):
        self._transcript += f"\n\n*Errore: {err}*"
        self._finish("Errore nella richiesta.")

    def _finish(self, msg: str):
        self.render_timer.stop()
        self.send_btn.setEnabled(True)
        self.status.setText(msg)
        self._render()

    def _render(self):
        intro = ("*Chiedi un'analisi: l'ingegnere legge telemetria, giri, setup e classifica da Delta Suite e può "
                 "proporre modifiche, che confermi tu (pagina Box & Assetto o tasto al volante). Le domande fatte "
                 "via radio compaiono qui con 📻.*")
        self.chat.setMarkdown(intro + self._transcript)
        sb = self.chat.verticalScrollBar()
        sb.setValue(sb.maximum())

    # ------------------------------------------------------------ radio
    def _on_ptt(self, down: bool):
        self.ptt_btn.setText("Sto ascoltando… rilascia per inviare" if down else "Tieni premuto e parla")

    def _log(self, who: str, text: str):
        ts = datetime.now().strftime("%H:%M:%S")
        col = WHO_COLORS.get(who, C["text"])
        self.log.appendHtml(f"<span style='color:{C['dim']}'>{ts}</span> "
                            f"<b style='color:{col}'>{who.upper()}</b> {html.escape(text)}")

    # ------------------------------------------------------------ salvataggi
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
                        tyre_press_lo=self.p_lo.value(), tyre_press_hi=self.p_hi.value())
        self.hub.save_radio_config(c)

    def _save_always(self, on: bool):
        self.hub.settings.setValue("radio/always", on)
        self._update_status()

    def _browse_model(self):
        d = QFileDialog.getExistingDirectory(self, "Cartella con kokoro-v1.0.onnx e voices-v1.0.bin",
                                             self.model_dir.text())
        if d:
            self.model_dir.setText(d)
            self._save_voice()

    def _copy_mcp(self):
        QGuiApplication.clipboard().setText(json.dumps(self.hub.mcp.client_config(), indent=2))
        self._log("sistema", "Configurazione MCP copiata negli appunti (vale finché l'hub resta aperto)")

    # ------------------------------------------------------------ stato
    def _update_status(self):
        b = self.backend.currentData()
        exe = {"claude": "claude", "codex": "codex", "antigravity": "agy"}.get(b)
        agent_ok = True
        if exe:
            found = find_executable(exe) or (find_executable("antigravity") if b == "antigravity" else None)
            agent_ok = found is not None
            self.agent_status.setText(dot(C["green"], found) if found else
                                      dot(C["red"], f"'{exe}' non trovato nel PATH"))
        elif b == "api":
            agent_ok = bool(self.api_key.text().strip())
            self.agent_status.setText("Usa il riepilogo dello stint (senza strumenti MCP). Costi a consumo.")
        else:
            self.agent_status.setText("Il comando riceve URL e token MCP nelle variabili DELTASUITE_MCP_URL e "
                                      "DELTASUITE_MCP_TOKEN.")
        for w, on in ((self.model, b != "custom"), (self.custom, b == "custom"), (self.api_key, b == "api")):
            w.setEnabled(on)
        self.summary_note.setText(
            "Con l'API un riepilogo come questo viene allegato alla prima domanda." if b == "api" else
            "L'agente legge i dati da solo con gli strumenti di Delta Suite (MCP): il riepilogo è solo per te.")

        voice = self.voice.currentData()
        lang = language_of(voice)
        self.voice_lang.setText(f"Lingua parlata: {lang.name}. Radio, risposte via radio e trascrizione "
                                "seguono la voce; l'analisi scritta resta in italiano.")
        voice_ok, why = make_backend(self.engine.currentData(), voice, self.speed.value(),
                                     self.model_dir.text() or None).available()
        self.voice_status.setText(dot(C["green"], "pronta") if voice_ok else dot(C["red"], why))
        stt_ok, stt_why = self.hub.stt.available()
        self.stt_status.setText(dot(C["green"] if stt_ok else C["red"], f"{stt_why} · lingua {lang.code}"))
        self.stt_model.setEnabled(self.stt_engine.currentData() == "whisper")
        self.tsukumo_url.setEnabled(self.stt_engine.currentData() == "tsukumo")

        m = self.hub.mcp
        self.mcp_info.setText(
            f"Server MCP attivo su {m.url} (porta solo locale, token nuovo a ogni avvio). L'agente scelto sopra "
            "lo usa da solo; puoi collegare anche una sessione interattiva di Claude Code, Codex o Antigravity "
            "incollando la configurazione." if m.error is None else f"Server MCP non avviato: {m.error}")

        voice_name = voice_label(voice).split(" — ")[0] if self.engine.currentData() != "none" else "spenta"
        self.overview.setText(("&nbsp;" * 5).join((
            dot(C["green"] if agent_ok else C["red"], BACKENDS.get(b, b)),
            dot(C["green"] if voice_ok else C["red"], f"voce {voice_name} ({lang.name})"),
            dot(C["green"] if stt_ok else C["red"], "push-to-talk"))))
        mode = MODES.get(self.hub.mode, self.hub.mode)
        self.radio_state.setText(
            dot(C["green"], f"Radio automatica attiva · modalità {mode}") if self.hub.radio_active else
            dot(C["yellow"], f"Radio automatica spenta in modalità {mode}: si accende in modalità Pilota o da "
                             "Impostazioni. Il push-to-talk risponde comunque."))
