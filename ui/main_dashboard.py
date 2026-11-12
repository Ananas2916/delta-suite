"""Main hub window: sidebar with the modules and stacked pages."""

from __future__ import annotations

import os
import sys

from PyQt6.QtCore import QSettings, QSize, Qt, QTimer
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import (
    QApplication, QComboBox, QFrame, QHBoxLayout, QLabel, QListWidget, QListWidgetItem, QMainWindow, QMessageBox,
    QPushButton, QScrollArea, QStackedWidget, QVBoxLayout, QWidget,
)

from hub_core.ac import csp_bridge
from hub_core.i18n import LANGUAGES, language, set_language, tr
from ui import theme
from ui.hub_state import MODES, HubState
from ui.navigation import GENERAL, SECTIONS
from ui.pages.analysis_page import AnalysisPage
from ui.pages.box_page import BoxPage
from ui.pages.dynamics_page import DynamicsPage
from ui.pages.engineer_page import EngineerPage
from ui.pages.general_page import GeneralPage
from ui.pages.onboard import OnboardPage
from ui.pages.strategy_page import StrategyPage
from ui.pages.telemetry_page import TelemetryPage

APP_NAME = "Delta Suite"
VERSION = "0.5.9"

# page opened by each mode
MODE_PAGES = {"driver": "telemetry", "engineer": "box", "analysis": "analysis"}


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
        mode_box = QWidget()
        mode_box.setStyleSheet(f"background: {theme.C['panel']};")
        ml = QVBoxLayout(mode_box)
        ml.setContentsMargins(12, 6, 12, 8)
        ml.addWidget(QLabel(tr("MODE")))
        self.mode = QComboBox()
        for k, v in MODES.items():
            self.mode.addItem(tr(v), k)
        self.mode.setToolTip(tr("Driver: radio and voice on · Engineer: adjustments and setup · Analysis: archive"))
        ml.addWidget(self.mode)
        ml.addWidget(QLabel(tr("LANGUAGE")))
        self.language = QComboBox()
        for code, name in LANGUAGES.items():
            self.language.addItem(name, code)
        self.language.setCurrentIndex(max(0, self.language.findData(language())))
        self.language.setToolTip(tr("Interface language (applied at the next start). The radio speaks the "
                                    "language of the chosen voice."))
        self.language.currentIndexChanged.connect(self._on_language)
        ml.addWidget(self.language)
        sl.addWidget(mode_box)
        self.nav = QListWidget()
        self.nav.setObjectName("sidebar")
        sl.addWidget(self.nav, 1)
        self.remote_btn = QPushButton()
        self.remote_btn.setToolTip("Follow the session and act as the engineer from another PC, tablet or phone")
        self.remote_btn.clicked.connect(self._open_remote)
        sl.addWidget(self.remote_btn)
        lay.addWidget(side)

        self.stack = QStackedWidget()
        lay.addWidget(self.stack, 1)
        self.setCentralWidget(central)

        self._areas: dict[str, QScrollArea] = {}
        self.general = GeneralPage(self.hub)
        self.telemetry = TelemetryPage(self.hub)
        self.engineer = EngineerPage(self.hub)
        self.pages = {
            "general": self.general,
            "telemetry": self.telemetry,
            "onboard": OnboardPage(self.hub),
            "engineer": self.engineer,
            "box": BoxPage(self.hub),
            "analysis": AnalysisPage(self.hub),
            "strategy": StrategyPage(self.hub),
            "dynamics": DynamicsPage(self.hub),
        }
        self._add_nav(GENERAL[0], tr(GENERAL[1]), tr(GENERAL[2]))
        for section, modules in SECTIONS:
            head = QListWidgetItem(tr(section).upper())
            head.setFlags(Qt.ItemFlag.NoItemFlags)
            head.setSizeHint(QSize(200, 34))
            f = head.font()
            f.setPointSize(8)
            f.setBold(True)
            head.setFont(f)
            head.setForeground(QColor(theme.C["dim"]))
            self.nav.addItem(head)
            for key, name, desc, replaces in modules:
                self._add_nav(key, tr(name), tr(desc) + "\n" + tr("Replaces: {what}", what=tr(replaces)))
        for key, page in self.pages.items():
            self.stack.addWidget(self._scrollable(key, page))
        self.nav.currentItemChanged.connect(self._on_nav)
        self.open_page("general")

        self.mode.setCurrentIndex(max(0, self.mode.findData(self.hub.mode)))
        self.mode.currentIndexChanged.connect(self._on_mode)

        self.general.open_module.connect(self.open_page)
        self.general.start_demo.connect(self.telemetry.start_demo)     # the demo starts while staying on the Overview
        self.general.checklist_action.connect(self._on_checklist)

        self.hub.remote.changed.connect(self._remote_label)
        self._remote_label()

        self.status_label = QLabel(tr("Ready"))
        self.statusBar().addWidget(self.status_label, 1)
        self.hub.status.connect(lambda text, ok: self.status_label.setText(text))
        self.hub.lap_completed.connect(
            lambda lap: self.statusBar().showMessage(tr("Lap {n} saved to the archive", n=lap.lap_no), 4000))

    def _remote_label(self):
        r = self.hub.remote
        n = len(r.pairing.device_list())
        self.remote_btn.setText(f"  Remote access: {'on' if r.enabled else 'off'}" + (f" · {n}" if r.enabled and n else ""))
        color = theme.C["green"] if r.enabled else theme.C["dim"]
        self.remote_btn.setStyleSheet(f"text-align: left; padding: 10px 12px; border: 0; border-radius: 0; "
                                      f"background: {theme.C['panel']}; color: {color}; font-weight: 600;")

    def _open_remote(self):
        from ui.remote_dialog import RemoteDialog
        RemoteDialog(self.hub, self).exec()

    def _scrollable(self, key: str, page: QWidget) -> QScrollArea:
        """Page in a scroll area: on a narrow screen (or scaled to 150%) the window never asks for more
        width than the screen, at most a scroll bar appears."""
        area = QScrollArea()
        area.setWidget(page)
        area.setWidgetResizable(True)
        area.setFrameShape(QFrame.Shape.NoFrame)
        self._areas[key] = area
        return area

    def _add_nav(self, key: str, name: str, tip: str = ""):
        it = QListWidgetItem(name)
        it.setData(Qt.ItemDataRole.UserRole, key)
        it.setToolTip(tip)
        it.setSizeHint(QSize(200, 44))
        self.nav.addItem(it)

    def _on_nav(self, item, _previous):
        if item is not None:
            self.stack.setCurrentWidget(self._areas[item.data(Qt.ItemDataRole.UserRole)])

    def open_page(self, key: str):
        for row in range(self.nav.count()):
            if self.nav.item(row).data(Qt.ItemDataRole.UserRole) == key:
                self.nav.setCurrentRow(row)
                return

    def _on_mode(self):
        mode = self.mode.currentData()
        self.hub.set_mode(mode)
        self.open_page(MODE_PAGES[mode])
        tips = {"driver": "Driver mode: radio and engineer voice on",
                "engineer": "Engineer mode: live adjustments and setup from the Pit & Setup page",
                "analysis": "Analysis mode: lap comparison and archive, radio off"}
        self.statusBar().showMessage(tr(tips[mode]), 5000)

    def _on_language(self):
        code = self.language.currentData()
        if code == self.hub.setting("ui/language", "en"):
            return
        self.hub.settings.setValue("ui/language", code)
        QMessageBox.information(self, "Delta Suite", tr("The new language is applied the next time you start "
                                                        "Delta Suite."))

    def _on_checklist(self, key: str):
        """Buttons of the get-started list on the Overview."""
        if key == "install_csp":
            try:
                path = csp_bridge.install_app()
            except Exception as exc:
                QMessageBox.warning(self, tr("Installation"), tr("Installation failed:\n{err}", err=exc))
            else:
                QMessageBox.information(
                    self, tr("CSP app installed"),
                    tr("App copied to:\n{path}\n\nRestart the AC session to load it. In game, open 'Delta Suite "
                       "Bridge' from the app bar to bind the wheel buttons (radio, confirm, discard).", path=path))
        elif key == "open_telemetry":
            self.open_page("telemetry")
        elif key in ("open_engineer", "download_voice"):
            self.open_page("engineer")
            self.engineer.tabs.setCurrentIndex(2)
            if key == "download_voice":
                self.engineer.download_voice()
        self.general.refresh_checklist()

    def _start_demo(self):
        self.open_page("telemetry")
        self.telemetry.start_demo()

    def closeEvent(self, event):
        self.hub.shutdown()
        super().closeEvent(event)


def _voice_check() -> str:
    """Test synthesis with Kokoro (not played): checks that the model and espeak are fine."""
    from ai_engine.voice import KokoroBackend
    k = KokoroBackend()
    ok, why = k.available()
    if not ok:
        return f"voice=not available ({why})"
    try:
        samples, sr = k.synth("Radio check.")
        return f"voice=ok ({len(samples) / sr:.1f} s of audio)"
    except Exception as exc:
        return f"voice=error {type(exc).__name__}: {exc}"


def _mcp_check(win: MainWindow) -> str:
    import json
    import urllib.request
    body = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "tools/list"}).encode()
    req = urllib.request.Request(win.hub.mcp.url, body, {"Content-Type": "application/json",
                                                          "Authorization": f"Bearer {win.hub.mcp.token}"})
    try:
        with urllib.request.urlopen(req, timeout=5) as r:
            return f"ok, {len(json.loads(r.read())['result']['tools'])} tools on {win.hub.mcp.url}"
    except Exception as exc:
        return f"error {exc}"


def _self_test(win: MainWindow, out_dir: str):
    """DELTA_SELFTEST=<folder>: fast demo, tour of every page with screenshots, then exit."""
    from pathlib import Path

    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    win.telemetry.demo_speed.setCurrentIndex(win.telemetry.demo_speed.count() - 1)
    win._start_demo()

    shots = [(f"{i}_{key}", lambda key=key: win.open_page(key)) for i, key in enumerate(win.pages)]
    for i, tab in enumerate(("summary", "settings"), 1):
        shots.append((f"engineer_{tab}", lambda i=i: (win.open_page("engineer"), win.engineer.tabs.setCurrentIndex(i))))

    def tour(i=0):
        if i < len(shots):
            name, show = shots[i]
            show()
            QTimer.singleShot(1200, lambda: (win.grab().save(str(out / f"page_{name}.png")), tour(i + 1)))
        else:
            (out / "selftest.txt").write_text(
                f"ok\nlaps={len(win.hub.laps)}\n{_voice_check()}\n"
                f"app_csp={csp_bridge.bundled_app_dir().is_dir()}\nmcp={_mcp_check(win)}\n",
                encoding="utf-8")
            win.close()

    QTimer.singleShot(15000, tour)


def main():
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setOrganizationName("DeltaSuite")
    app.setWindowIcon(theme.app_icon())
    theme.apply(app)
    # interface language: chosen once at startup (the self-test always runs in English)
    if not os.environ.get("DELTA_SELFTEST"):
        set_language(os.environ.get("DELTA_LANG") or QSettings("DeltaSuite", "DeltaSuite").value("ui/language", "en"))
    win = MainWindow()
    win.show()
    if os.environ.get("DELTA_SELFTEST"):
        _self_test(win, os.environ["DELTA_SELFTEST"])
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
