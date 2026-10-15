"""Radio & voce: ingegnere AI (agente), voce, regole della radio, push-to-talk, collegamento MCP."""

from __future__ import annotations

import html
import json
from datetime import datetime

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QGuiApplication
from PyQt6.QtWidgets import (
    QCheckBox, QComboBox, QFileDialog, QFormLayout, QGroupBox, QHBoxLayout, QLineEdit, QPlainTextEdit,
    QPushButton, QScrollArea, QVBoxLayout, QWidget,
)

from ai_engine.agent_cli import BACKENDS, find_executable
from ai_engine.radio import RadioConfig
from ai_engine.lang import DEFAULT_VOICE, KOKORO_VOICES, language_of, voice_label
from ai_engine.stt import DEFAULT_MODEL, WHISPER_MODELS, model_cached
from ai_engine.voice import PRIO_URGENT, make_backend
from ui.mic import input_devices
from ui.theme import C
from ui.widgets import dspin, label

ENGINES = {"kokoro": "Kokoro integrato (locale)", "tsukumo": "Tsukumo (parla la sua finestra)", "none": "Nessuna voce"}
WHO_COLORS = {"radio": C["blue"], "pilota": C["yellow"], "ingegnere": C["green"], "sistema": C["dim"]}


class RadioPage(QWidget):
    def __init__(self, hub):
        super().__init__()
        self.hub = hub
        st = hub.settings
        root = QHBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 16)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFixedWidth(560)
        inner = QWidget()
        col = QVBoxLayout(inner)
        col.addWidget(label("Radio & voce", "h1"))

        # --- ingegnere
        g = QGroupBox("Ingegnere AI")
        f = QFormLayout(g)
        self.backend = QComboBox()
        for k, v in BACKENDS.items():
            self.backend.addItem(v, k)
        self.backend.setCurrentIndex(max(0, self.backend.findData(hub.setting("engineer/backend", "claude"))))
        self.model = QLineEdit(hub.setting("engineer/model", ""))
        self.model.setPlaceholderText("vuoto = modello predefinito dell'agente")
        self.custom = QLineEdit(hub.setting("engineer/custom_cmd", ""))
        self.custom.setPlaceholderText("es. mio_agente.exe --prompt {prompt}  (senza {prompt}: arriva da stdin)")
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
        col.addWidget(g)

        # --- voce
        g = QGroupBox("Voce dell'ingegnere")
        f = QFormLayout(g)
        self.engine = QComboBox()
        for k, v in ENGINES.items():
            self.engine.addItem(v, k)
        self.engine.setCurrentIndex(max(0, self.engine.findData(hub.setting("voice/engine", "kokoro"))))
        self.voice = QComboBox()
        for v in KOKORO_VOICES:
            self.voice.addItem(voice_label(v), v)
        self.voice.setCurrentIndex(max(0, self.voice.findData(hub.setting("voice/voice", DEFAULT_VOICE))))
        self.voice_lang = label("", "dim")
        self.speed = dspin(0.6, 1.8, hub.setting("voice/speed", 1.1, float), 0.05, 2)
        self.model_dir = QLineEdit(hub.setting("voice/model_dir", ""))
        self.model_dir.setPlaceholderText("vuoto = modelli di Tsukumo")
        browse = QPushButton("…")
        browse.setFixedWidth(34)
        browse.clicked.connect(self._browse_model)
        md = QHBoxLayout()
        md.addWidget(self.model_dir, 1)
        md.addWidget(browse)
        self.voice_status = label("", "dim")
        self.voice_status.setWordWrap(True)
        f.addRow("Motore", self.engine)
        f.addRow("Voce", self.voice)
        f.addRow("", self.voice_lang)
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
        col.addWidget(g)

        # --- regole radio
        g = QGroupBox("Radio automatica (senza AI, immediata)")
        f = QFormLayout(g)
        cfg = hub.radio_rules.cfg
        self.rule_boxes = {}
        for key, text in (("lap_times", "Tempo sul giro e delta"), ("fuel", "Carburante (5, 3, 2, 1 giri)"),
                          ("tyres", "Gomme fuori finestra (una volta per stint)"), ("gaps", "Distacchi in gara"),
                          ("flags", "Bandiere")):
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
        f.addRow("Finestra temperatura", row_t)
        f.addRow("Finestra pressione a caldo", row_p)
        self.always = QCheckBox("Radio attiva anche in modalità Ingegnere")
        self.always.setChecked(hub.setting("radio/always", False, bool))
        self.always.toggled.connect(lambda v: hub.settings.setValue("radio/always", v))
        f.addRow(self.always)
        col.addWidget(g)

        # --- push to talk
        g = QGroupBox("Parla con l'ingegnere (push-to-talk)")
        f = QFormLayout(g)
        self.mic = QComboBox()
        self.mic.addItem("Microfono predefinito", b"")
        for d in input_devices():
            self.mic.addItem(d.description(), bytes(d.id()))
        saved = hub.settings.value("voice/mic", b"")
        self.mic.setCurrentIndex(max(0, self.mic.findData(bytes(saved) if saved else b"")))
        self.mic.currentIndexChanged.connect(self._save_mic)
        self.stt_engine = QComboBox()
        self.stt_engine.addItem("Whisper locale (integrato)", "whisper")
        self.stt_engine.addItem("Tsukumo (motore Ascolto)", "tsukumo")
        self.stt_engine.addItem("Disattivata", "none")
        self.stt_engine.setCurrentIndex(max(0, self.stt_engine.findData(hub.setting("stt/engine", "whisper"))))
        self.stt_model = QComboBox()
        for name, note in WHISPER_MODELS.items():
            self.stt_model.addItem(f"{name} — {note}" + ("  ✓ già scaricato" if model_cached(name) else ""), name)
        self.stt_model.setCurrentIndex(max(0, self.stt_model.findData(hub.setting("stt/model", DEFAULT_MODEL))))
        self.stt_status = label("", "dim")
        self.stt_status.setWordWrap(True)
        self.tsukumo_url = QLineEdit(hub.setting("voice/tsukumo_url", "http://127.0.0.1:8770"))
        for w in (self.stt_engine, self.stt_model):
            w.currentIndexChanged.connect(self._save_stt)
        self.tsukumo_url.editingFinished.connect(self._save_stt)
        self.ptt_btn = QPushButton("Tieni premuto e parla")
        self.ptt_btn.setObjectName("primary")
        self.ptt_btn.pressed.connect(lambda: hub.set_ptt(True))
        self.ptt_btn.released.connect(lambda: hub.set_ptt(False))
        note = label("Al volante: assegna il tasto 'Radio ingegnere' nella finestra dell'app Delta Suite Bridge "
                     "in gioco. Tieni premuto, parla nella lingua della voce scelta, rilascia: la trascrizione è "
                     "locale e l'ingegnere ti risponde in cuffia.", "dim")
        note.setWordWrap(True)
        f.addRow("Microfono", self.mic)
        f.addRow("Trascrizione", self.stt_engine)
        f.addRow("Modello Whisper", self.stt_model)
        f.addRow("Tsukumo", self.tsukumo_url)
        f.addRow(self.stt_status)
        f.addRow(self.ptt_btn)
        f.addRow(note)
        col.addWidget(g)

        # --- MCP
        g = QGroupBox("Collegamento per agenti esterni (MCP)")
        f = QVBoxLayout(g)
        self.mcp_info = label("", "dim")
        self.mcp_info.setWordWrap(True)
        self.mcp_info.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        copy = QPushButton("Copia configurazione MCP")
        copy.clicked.connect(self._copy_mcp)
        f.addWidget(self.mcp_info)
        f.addWidget(copy)
        col.addWidget(g)
        col.addStretch()
        scroll.setWidget(inner)
        root.addWidget(scroll)

        # --- registro radio
        right = QVBoxLayout()
        right.addWidget(label("Registro radio", "h2"))
        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        right.addWidget(self.log, 1)
        root.addLayout(right, 1)

        hub.radio_log.connect(self._log)
        hub.voice_error.connect(lambda e: self._log("sistema", f"Voce: {e}"))
        hub.ptt_changed.connect(self._on_ptt)
        hub.engineer_failed.connect(lambda e: self._log("sistema", f"Ingegnere: {e}"))
        self._update_status()

    # ---------------------------------------------------------------- salvataggi
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

    def _browse_model(self):
        d = QFileDialog.getExistingDirectory(self, "Cartella con kokoro-v1.0.onnx e voices-v1.0.bin",
                                             self.model_dir.text())
        if d:
            self.model_dir.setText(d)
            self._save_voice()

    def _copy_mcp(self):
        QGuiApplication.clipboard().setText(json.dumps(self.hub.mcp.client_config(), indent=2))
        self._log("sistema", "Configurazione MCP copiata negli appunti (vale finché l'hub resta aperto)")

    # ---------------------------------------------------------------- stato
    def _update_status(self):
        b = self.backend.currentData()
        exe = {"claude": "claude", "codex": "codex", "antigravity": "agy"}.get(b)
        if exe:
            found = find_executable(exe) or (find_executable("antigravity") if b == "antigravity" else None)
            self.agent_status.setText(f"<span style='color:{C['green']}'>●</span> {found}" if found else
                                      f"<span style='color:{C['red']}'>●</span> '{exe}' non trovato nel PATH")
        elif b == "api":
            self.agent_status.setText("Usa il riepilogo dello stint (senza strumenti MCP). Costi a consumo.")
        else:
            self.agent_status.setText("Il comando riceve URL e token MCP nelle variabili DELTASUITE_MCP_URL e "
                                      "DELTASUITE_MCP_TOKEN.")
        for w, on in ((self.model, b != "custom"), (self.custom, b == "custom"), (self.api_key, b == "api")):
            w.setEnabled(on)

        eng = self.engine.currentData()
        voice = self.voice.currentData()
        lang = language_of(voice)
        self.voice_lang.setText(f"Lingua parlata: {lang.name} — radio, risposte dell'ingegnere e trascrizione "
                                "seguono la voce")
        ok, why = make_backend(eng, voice, self.speed.value(),
                               self.model_dir.text() or None).available()
        self.voice_status.setText(f"<span style='color:{C['green'] if ok else C['red']}'>●</span> "
                                  + ("pronta" if ok else why))
        stt_ok, stt_why = self.hub.stt.available()
        self.stt_status.setText(f"<span style='color:{C['green'] if stt_ok else C['red']}'>●</span> {stt_why}"
                                f" · lingua {lang.code}")
        self.stt_model.setEnabled(self.stt_engine.currentData() == "whisper")
        self.tsukumo_url.setEnabled(self.stt_engine.currentData() == "tsukumo")
        m = self.hub.mcp
        self.mcp_info.setText(
            f"Server MCP attivo su {m.url} (porta solo locale, token nuovo a ogni avvio). L'agente scelto sopra "
            "lo usa da solo; puoi collegare anche una sessione interattiva di Claude Code, Codex o Antigravity "
            "incollando la configurazione." if m.error is None else f"Server MCP non avviato: {m.error}")

    def _on_ptt(self, down: bool):
        self.ptt_btn.setText("Sto ascoltando… rilascia per inviare" if down else "Tieni premuto e parla")

    def _log(self, who: str, text: str):
        ts = datetime.now().strftime("%H:%M:%S")
        col = WHO_COLORS.get(who, C["text"])
        self.log.appendHtml(f"<span style='color:{C['dim']}'>{ts}</span> "
                            f"<b style='color:{col}'>{who.upper()}</b> {html.escape(text)}")
