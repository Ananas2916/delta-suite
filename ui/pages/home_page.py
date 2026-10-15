"""Pagina iniziale: panoramica dei moduli e stato della sessione."""

from __future__ import annotations

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import QGridLayout, QHBoxLayout, QPushButton, QVBoxLayout, QWidget

from hub_core.race_strategy import fmt_ms
from ui.theme import C
from ui.widgets import Card, label

MODULES = [
    (1, "Telemetria live", "Acquisizione 60–100 Hz dalla shared memory di Assetto Corsa: pedali, sterzo, "
     "gomme, freni, G-G, giri e settori.", "MoTeC i2 · ATLAS · WinDARAB"),
    (2, "Analisi giri", "Giri sovrapposti su distanza, Delta-T, traiettoria, cursore sincronizzato, "
     "archivio DuckDB ed esportazione Parquet.", "MoTeC i2 · Pi Toolbox"),
    (3, "Dinamica veicolo", "Pneumatico Pacejka, ellisse d'attrito, trasferimenti di carico con aero, "
     "cinematica del quadrilatero e centro di rollio.", "ChassisSim · OptimumG · Adams"),
    (4, "Strategia & Timing", "Consumo medio, finestra pit, previsione degrado gomme, sosta ottimale, "
     "settori e giro ideale.", "HH Timing · SBG RaceWatch"),
    (5, "CAD / CFD bridge", "Viewer STL/OBJ con area frontale e mappe aerodinamiche CL/CD vs ride height "
     "da OpenFOAM/Ansys.", "Viewer CAD · post-processing CFD"),
    (6, "AI Race Engineer", "Claude analizza lo stint e propone pressioni, setup e strategia.",
     "Ingegnere di pista"),
]


class HomePage(QWidget):
    open_module = pyqtSignal(int)
    start_demo = pyqtSignal()

    def __init__(self, hub):
        super().__init__()
        self.hub = hub
        root = QVBoxLayout(self)
        root.setContentsMargins(28, 24, 28, 24)
        root.setSpacing(14)
        root.addWidget(label("Mio Hub Motorsport", "h1"))
        sub = label("All-in-One Engineering & Strategy Suite per Assetto Corsa", "dim")
        sub.setStyleSheet("font-size: 12pt;")
        root.addWidget(sub)

        status = Card()
        sl = QHBoxLayout(status)
        self.status = label("Acquisizione ferma. Avvia una sessione in AC, oppure prova il simulatore demo.")
        self.status.setWordWrap(True)
        sl.addWidget(self.status, 1)
        demo = QPushButton("Avvia demo")
        demo.clicked.connect(self.start_demo)
        live = QPushButton("Vai alla telemetria")
        live.setObjectName("primary")
        live.clicked.connect(lambda: self.open_module.emit(1))
        sl.addWidget(demo)
        sl.addWidget(live)
        root.addWidget(status)

        grid = QGridLayout()
        grid.setSpacing(14)
        for i, (idx, name, desc, replaces) in enumerate(MODULES):
            card = Card()
            cl = QVBoxLayout(card)
            cl.setContentsMargins(16, 14, 16, 14)
            t = label(name, "h2")
            d = label(desc)
            d.setWordWrap(True)
            r = label(f"Al posto di: {replaces}", "dim")
            btn = QPushButton("Apri")
            btn.clicked.connect(lambda _=False, idx=idx: self.open_module.emit(idx))
            cl.addWidget(t)
            cl.addWidget(d)
            cl.addStretch(1)
            cl.addWidget(r)
            cl.addWidget(btn, alignment=Qt.AlignmentFlag.AlignRight)
            grid.addWidget(card, i // 3, i % 3)
        root.addLayout(grid, 1)

        db_note = f"Archivio telemetria: {hub.db.path}"
        if hub.db_error:
            db_note = f"<span style='color:{C['yellow']}'>Archivio non disponibile ({hub.db_error}): " \
                      f"i dati di questa sessione restano solo in memoria.</span>"
        root.addWidget(label(db_note, "dim"))

        hub.status.connect(self._on_status)
        hub.lap_completed.connect(lambda _: self._on_status(None, True))

    def _on_status(self, text, ok):
        info = self.hub.session_info
        laps = self.hub.laps
        parts = [text] if text else []
        if info and self.hub.running:
            valid = [l.lap_time_ms for l in laps if l.valid]
            parts.append(f"{len(laps)} giri registrati · migliore {fmt_ms(min(valid) if valid else None)}")
        if parts:
            color = C["green"] if ok else C["yellow"]
            self.status.setText(f"<span style='color:{color}'>●</span>  " + "  ·  ".join(parts))
