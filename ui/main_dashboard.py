"""Finestra principale dell'hub: barra laterale con i moduli e pagine impilate."""

from __future__ import annotations

import os
import sys

from PyQt6.QtCore import QSize, QTimer
from PyQt6.QtWidgets import (
    QApplication, QHBoxLayout, QLabel, QListWidget, QListWidgetItem, QMainWindow, QStackedWidget, QVBoxLayout,
    QWidget,
)

from ui import theme
from ui.hub_state import HubState
from ui.pages.analysis_page import AnalysisPage
from ui.pages.cad_page import CadPage
from ui.pages.dynamics_page import DynamicsPage
from ui.pages.engineer_page import EngineerPage
from ui.pages.home_page import HomePage
from ui.pages.strategy_page import StrategyPage
from ui.pages.telemetry_page import TelemetryPage

APP_NAME = "Delta Suite"
VERSION = "0.1.0"


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(f"{APP_NAME} {VERSION}")
        self.setWindowIcon(theme.app_icon())
        self.resize(1500, 920)
        self.hub = HubState()

        central = QWidget()
        lay = QHBoxLayout(central)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)

        side = QWidget()
        side.setFixedWidth(220)
        sl = QVBoxLayout(side)
        sl.setContentsMargins(0, 0, 0, 0)
        brand = QLabel("  DELTA SUITE")
        brand.setStyleSheet(f"background: {theme.C['panel']}; color: {theme.C['accent']}; font-size: 15pt;"
                            "font-weight: 800; padding: 16px 8px 4px 8px; letter-spacing: 2px;")
        sl.addWidget(brand)
        self.nav = QListWidget()
        self.nav.setObjectName("sidebar")
        sl.addWidget(self.nav, 1)
        lay.addWidget(side)

        self.stack = QStackedWidget()
        lay.addWidget(self.stack, 1)
        self.setCentralWidget(central)

        self.home = HomePage(self.hub)
        self.telemetry = TelemetryPage(self.hub)
        pages = [
            ("Home", self.home),
            ("Telemetria live", self.telemetry),
            ("Analisi giri", AnalysisPage(self.hub)),
            ("Dinamica veicolo", DynamicsPage(self.hub)),
            ("Strategia & Timing", StrategyPage(self.hub)),
            ("CAD / CFD bridge", CadPage(self.hub)),
            ("AI Race Engineer", EngineerPage(self.hub)),
        ]
        for name, page in pages:
            it = QListWidgetItem(name)
            it.setSizeHint(QSize(200, 44))
            self.nav.addItem(it)
            self.stack.addWidget(page)
        self.nav.currentRowChanged.connect(self.stack.setCurrentIndex)
        self.nav.setCurrentRow(0)

        self.home.open_module.connect(self.nav.setCurrentRow)
        self.home.start_demo.connect(self._start_demo)

        self.status_label = QLabel("Pronto")
        self.statusBar().addWidget(self.status_label, 1)
        self.hub.status.connect(lambda text, ok: self.status_label.setText(text))
        self.hub.lap_completed.connect(
            lambda lap: self.statusBar().showMessage(f"Giro {lap.lap_no} salvato in archivio", 4000))

    def _start_demo(self):
        self.nav.setCurrentRow(1)
        self.telemetry.start_demo()

    def closeEvent(self, event):
        self.hub.shutdown()
        super().closeEvent(event)


def _self_test(win: MainWindow, out_dir: str):
    """DELTA_SELFTEST=<cartella>: demo veloce, giro di tutte le pagine con screenshot, poi uscita."""
    from pathlib import Path

    from hub_core.cad_bridge import demo_car_mesh
    from ui.pages import cad_page

    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    win.telemetry.demo_speed.setCurrentIndex(win.telemetry.demo_speed.count() - 1)
    win._start_demo()

    def tour(i=0):
        if i < win.stack.count():
            win.nav.setCurrentRow(i)
            if i == 5:
                win.stack.widget(5).findChild(cad_page.MeshTab)._show(demo_car_mesh(), "vettura demo")
            QTimer.singleShot(1200, lambda: (win.grab().save(str(out / f"page_{i}.png")), tour(i + 1)))
        else:
            (out / "selftest.txt").write_text(
                f"ok\ngiri={len(win.hub.laps)}\nopengl={'ok' if cad_page.gl else cad_page._GL_ERROR}\n",
                encoding="utf-8")
            win.close()

    QTimer.singleShot(15000, tour)


def main():
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setOrganizationName("DeltaSuite")
    app.setWindowIcon(theme.app_icon())
    theme.apply(app)
    win = MainWindow()
    win.show()
    if os.environ.get("DELTA_SELFTEST"):
        _self_test(win, os.environ["DELTA_SELFTEST"])
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
