"""Modulo 5: AI Race Engineer (chat di analisi; stessa conversazione della radio)."""

from __future__ import annotations

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtWidgets import (
    QHBoxLayout, QLineEdit, QPlainTextEdit, QPushButton, QSpinBox, QSplitter, QTextBrowser, QVBoxLayout, QWidget,
)

from ai_engine.agent_cli import BACKENDS
from ai_engine.race_engineer_agent import build_stint_summary
from ui.widgets import SessionPicker, label

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


class EngineerPage(QWidget):
    def __init__(self, hub):
        super().__init__()
        self.hub = hub
        self._transcript = ""

        root = QVBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 16)
        head = QHBoxLayout()
        head.addWidget(label("AI Race Engineer", "h1"))
        head.addStretch()
        self.backend_lbl = label("", "dim")
        head.addWidget(self.backend_lbl)
        root.addLayout(head)

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
        self.summary_note = label("", "dim")
        self.summary_note.setWordWrap(True)
        ll.addWidget(self.summary_note)
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
        split.setSizes([460, 840])
        root.addWidget(split, 1)

        self.render_timer = QTimer(self)
        self.render_timer.timeout.connect(self._render)
        self.picker.currentIndexChanged.connect(self._regen)
        self.laps_left.valueChanged.connect(self._regen)
        hub.lap_completed.connect(lambda _: self._regen() if self.picker.currentData() is None else None)
        hub.engineer_started.connect(self._on_started)
        hub.engineer_text.connect(self._on_text)
        hub.engineer_done.connect(self._on_done)
        hub.engineer_failed.connect(self._on_failed)
        self._regen()
        self._render()

    def showEvent(self, e):
        backend = self.hub.setting("engineer/backend", "claude")
        self.backend_lbl.setText(f"Agente: {BACKENDS.get(backend, backend)} · si cambia in Radio & voce")
        self.summary_note.setText(
            "Con l'API il riepilogo qui sotto viene allegato alla prima domanda." if backend == "api" else
            "L'agente legge i dati da solo con gli strumenti di Delta Suite (MCP): il riepilogo è solo per te.")
        super().showEvent(e)

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
