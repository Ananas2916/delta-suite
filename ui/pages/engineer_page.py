"""Modulo 5: AI Race Engineer (Claude)."""

from __future__ import annotations

import os

from PyQt6.QtCore import QSettings, QThread, QTimer, pyqtSignal
from PyQt6.QtWidgets import (
    QGroupBox, QHBoxLayout, QLineEdit, QPlainTextEdit, QPushButton, QSpinBox, QSplitter, QTextBrowser,
    QVBoxLayout, QWidget,
)
from PyQt6.QtCore import Qt

from ai_engine.race_engineer_agent import MODEL, RaceEngineer, build_stint_summary
from ui.widgets import SessionPicker, label

QUICK_QUESTIONS = {
    "Pressioni gomme": "Analizza temperature e pressioni gomme. Le pressioni a caldo sono nella finestra giusta? "
                       "Che pressioni a freddo imposto per il prossimo run, ruota per ruota?",
    "Strategia gara": "Dammi la strategia per il resto della gara: lunghezza stint, giro di sosta, "
                      "carburante da imbarcare e se conviene cambiare gomme.",
    "Bilanciamento": "Dai dati di temperature gomme, freni e tempi nei settori, la macchina è sottosterzante o "
                     "sovrasterzante? Quali modifiche di setup proponi?",
    "Costanza pilota": "Valuta la costanza dei miei giri e dove perdo tempo rispetto al giro ideale.",
}


class EngineerWorker(QThread):
    text = pyqtSignal(str)
    done = pyqtSignal(str)
    failed = pyqtSignal(str)

    def __init__(self, engineer: RaceEngineer, question: str, summary: str | None):
        super().__init__()
        self.engineer, self.question, self.summary = engineer, question, summary

    def run(self):
        try:
            final = self.engineer.ask(self.question, self.summary, on_text=self.text.emit)
            self.done.emit(final)
        except Exception as exc:
            self.failed.emit(f"{type(exc).__name__}: {exc}")


class EngineerPage(QWidget):
    def __init__(self, hub):
        super().__init__()
        self.hub = hub
        self.settings = QSettings("MioHub", "MotorsportSuite")
        self.engineer: RaceEngineer | None = None
        self.worker: EngineerWorker | None = None
        self._transcript = ""
        self._summary_sent = False

        root = QVBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 16)
        root.addWidget(label("AI Race Engineer", "h1"))

        key_box = QGroupBox(f"Connessione Claude · modello {MODEL}")
        kl = QHBoxLayout(key_box)
        self.key = QLineEdit(self.settings.value("api_key", "", str))
        self.key.setEchoMode(QLineEdit.EchoMode.Password)
        self.key.setPlaceholderText("Chiave API Anthropic (vuoto = usa ANTHROPIC_API_KEY)")
        save = QPushButton("Salva chiave")
        save.clicked.connect(self._save_key)
        kl.addWidget(self.key, 1)
        kl.addWidget(save)
        root.addWidget(key_box)

        split = QSplitter(Qt.Orientation.Horizontal)
        left = QWidget()
        ll = QVBoxLayout(left)
        ll.setContentsMargins(0, 0, 0, 0)
        row = QHBoxLayout()
        self.picker = SessionPicker(hub)
        row.addWidget(self.picker, 1)
        row.addWidget(label("Giri gara rimanenti", "dim"))
        self.laps_left = QSpinBox()
        self.laps_left.setRange(0, 999)
        self.laps_left.setSpecialValueText("n/d")
        row.addWidget(self.laps_left)
        ll.addLayout(row)
        regen = QPushButton("Rigenera riepilogo stint")
        regen.clicked.connect(self._regen)
        ll.addWidget(regen)
        ll.addWidget(label("Riepilogo inviato all'ingegnere (modificabile):", "dim"))
        self.summary = QPlainTextEdit()
        self.summary.setStyleSheet("font-family: Consolas; font-size: 9pt;")
        ll.addWidget(self.summary, 1)
        split.addWidget(left)

        right = QWidget()
        rl = QVBoxLayout(right)
        rl.setContentsMargins(0, 0, 0, 0)
        self.chat = QTextBrowser()
        self.chat.setOpenExternalLinks(True)
        rl.addWidget(self.chat, 1)
        quick = QHBoxLayout()
        for name, q in QUICK_QUESTIONS.items():
            b = QPushButton(name)
            b.clicked.connect(lambda _=False, q=q: self._send(q))
            quick.addWidget(b)
        rl.addLayout(quick)
        ask_row = QHBoxLayout()
        self.question = QLineEdit()
        self.question.setPlaceholderText("Chiedi all'ingegnere…")
        self.question.returnPressed.connect(lambda: self._send(self.question.text()))
        self.send_btn = QPushButton("Invia")
        self.send_btn.setObjectName("primary")
        self.send_btn.clicked.connect(lambda: self._send(self.question.text()))
        new_btn = QPushButton("Nuova conversazione")
        new_btn.clicked.connect(self._new_chat)
        ask_row.addWidget(self.question, 1)
        ask_row.addWidget(self.send_btn)
        ask_row.addWidget(new_btn)
        rl.addLayout(ask_row)
        self.status = label("", "dim")
        rl.addWidget(self.status)
        split.addWidget(right)
        split.setSizes([480, 820])
        root.addWidget(split, 1)

        self.render_timer = QTimer(self)
        self.render_timer.timeout.connect(self._render)
        self.picker.currentIndexChanged.connect(self._regen)
        self.laps_left.valueChanged.connect(self._regen)
        hub.lap_completed.connect(lambda _: self._regen() if self.picker.currentData() is None else None)
        self._regen()
        self._render()

    # ------------------------------------------------------------------
    def _save_key(self):
        self.settings.setValue("api_key", self.key.text().strip())
        self.engineer = None
        self.status.setText("Chiave salvata.")

    def _regen(self):
        info, laps, _ = self.picker.selected()
        live = self.picker.currentData() is None and self.hub.last_sample is not None
        fuel = self.hub.last_sample.fuel if live else (laps[-1].fuel_end if laps else None)
        self.summary.setPlainText(build_stint_summary(info or {}, laps, fuel, self.laps_left.value() or None))
        self._summary_sent = False

    def _new_chat(self):
        if self.engineer:
            self.engineer.reset()
        self._transcript = ""
        self._summary_sent = False
        self._render()

    def _send(self, question: str):
        question = question.strip()
        if not question or (self.worker and self.worker.isRunning()):
            return
        key = self.key.text().strip() or None
        if key is None and not os.environ.get("ANTHROPIC_API_KEY"):
            self.status.setText("Inserisci una chiave API Anthropic oppure imposta ANTHROPIC_API_KEY.")
            return
        if self.engineer is None:
            self.engineer = RaceEngineer(key)
        summary = None if self._summary_sent else self.summary.toPlainText()
        self._summary_sent = True
        self.question.clear()
        self._transcript += f"\n\n---\n\n**Tu:** {question}\n\n**Ingegnere:** "
        self.worker = EngineerWorker(self.engineer, question, summary)
        self.worker.text.connect(self._on_text)
        self.worker.done.connect(self._on_done)
        self.worker.failed.connect(self._on_failed)
        self.send_btn.setEnabled(False)
        self.status.setText("L'ingegnere sta analizzando i dati…")
        self.worker.start()
        self.render_timer.start(120)

    def _on_text(self, chunk: str):
        self._transcript += chunk

    def _on_done(self, final: str):
        if final.startswith("La richiesta è stata rifiutata"):
            self._transcript += final
        self._finish("Risposta completata.")

    def _on_failed(self, err: str):
        self._transcript += f"\n\n*Errore: {err}*"
        self._summary_sent = False
        self._finish("Errore nella richiesta.")

    def _finish(self, msg: str):
        self.render_timer.stop()
        self.send_btn.setEnabled(True)
        self.status.setText(msg)
        self._render()

    def _render(self):
        intro = ("*Il riepilogo dello stint a sinistra viene allegato alla prima domanda della conversazione. "
                 "Le domande successive proseguono la stessa conversazione.*")
        self.chat.setMarkdown(intro + self._transcript)
        sb = self.chat.verticalScrollBar()
        sb.setValue(sb.maximum())
