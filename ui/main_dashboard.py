"""Main hub window: top bar with the views, the live strip, the views stacked below."""

from __future__ import annotations

import os
import sys

from PyQt6.QtCore import QSettings, QTimer
from PyQt6.QtWidgets import (
    QApplication, QFrame, QMainWindow, QMessageBox, QScrollArea, QStackedWidget, QTabWidget, QVBoxLayout, QWidget,
)

from hub_core.ac import csp_bridge
from hub_core.i18n import set_language, tr
from ui import race_view as rv
from ui import theme
from ui.hub_state import HubState
from ui.navigation import LIVE_VIEWS, VIEWS
from ui.pages.analysis_page import AnalysisPage
from ui.pages.box_page import BoxPage
from ui.pages.dynamics_page import DynamicsPage
from ui.pages.engineer_page import EngineerPage
from ui.pages.general_page import GeneralPage
from ui.pages.home_page import HomePage
from ui.pages.onboard import OnboardPage
from ui.pages.settings_page import SettingsPage
from ui.pages.strategy_page import StrategyPage
from ui.pages.telemetry_page import TelemetryPage
from ui.workers import SOURCE_AC, SOURCE_REPLAY
from ui.widgets.live_strip import LiveStrip
from ui.widgets.topbar import TopBar

APP_NAME = "Delta Suite"
VERSION = "0.6.1"

# view opened by each mode
MODE_PAGES = {"driver": "race", "engineer": "box", "analysis": "analysis"}


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(f"{APP_NAME} {VERSION}")
        self.setWindowIcon(theme.app_icon())
        self.resize(1500, 920)
        self.hub = HubState()
        self.ambient = None

        central = QWidget()
        lay = QVBoxLayout(central)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        self.topbar = TopBar(VIEWS)
        self.topbar.view_selected.connect(self.open_page)
        self.topbar.settings_clicked.connect(lambda: self.open_page("settings"))
        self.topbar.ptt.connect(self.hub.set_ptt)
        lay.addWidget(self.topbar)
        self.strip = LiveStrip()
        lay.addWidget(self.strip)
        self.stack = QStackedWidget()
        lay.addWidget(self.stack, 1)
        self.setCentralWidget(central)

        self._areas: dict[str, QScrollArea] = {}
        self.trend = rv.GapTrend()
        self._strip_titles = {"pos": tr("Pos"), "fuel": tr("Fuel"), "battery": tr("Battery")}
        self.home = HomePage(self.hub)
        self.general = GeneralPage(self.hub, with_checklist=False)
        self.telemetry = TelemetryPage(self.hub)
        self.engineer = EngineerPage(self.hub)
        self.analysis = QTabWidget()
        self.analysis.setDocumentMode(True)
        self.analysis.addTab(AnalysisPage(self.hub), tr("Lap analysis"))
        self.analysis.addTab(DynamicsPage(self.hub), tr("Vehicle dynamics"))
        self.settings_page = SettingsPage(self.hub, VERSION)
        self.pages = {
            "home": self.home,
            "race": self.general,
            "onboard": OnboardPage(self.hub),
            "telemetry": self.telemetry,
            "box": BoxPage(self.hub),
            "strategy": StrategyPage(self.hub),
            "analysis": self.analysis,
            "engineer": self.engineer,
            "settings": self.settings_page,
        }
        for key, page in self.pages.items():
            self.stack.addWidget(self._scrollable(key, page))
        self.current = ""
        self.open_page("home")

        self.home.start_ac.connect(lambda: self._start(SOURCE_AC))
        self.home.start_demo.connect(self._start_demo)
        self.home.open_recording.connect(lambda: self._start(SOURCE_REPLAY))
        self.home.open_view.connect(self.open_page)
        self.home.action.connect(self._on_checklist)
        self.general.open_module.connect(self.open_page)
        self.general.start_demo.connect(self.telemetry.start_demo)
        self.general.checklist_action.connect(self._on_checklist)
        self.settings_page.mode_changed.connect(self._on_mode)
        self.settings_page.language_changed.connect(self._on_language)
        self.settings_page.theme_changed.connect(self._on_theme)
        self.settings_page.open_remote.connect(self._open_remote)
        self.settings_page.install_csp.connect(lambda: self._on_checklist("install_csp"))

        self.statusBar().showMessage(tr("Ready"))
        self.hub.status.connect(lambda text, ok: self.statusBar().showMessage(text))
        self.hub.lap_completed.connect(
            lambda lap: self.statusBar().showMessage(tr("Lap {n} saved to the archive", n=lap.lap_no), 4000))

        self.hub.session_changed.connect(lambda _info: self.trend.reset())
        self.strip_timer = QTimer(self)
        self.strip_timer.timeout.connect(self._refresh_strip)
        self.strip_timer.start(200)

    # ------------------------------------------------------------- views
    def _scrollable(self, key: str, page: QWidget) -> QScrollArea:
        """Page in a scroll area: on a narrow screen (or scaled to 150%) the window never asks for more
        width than the screen, at most a scroll bar appears."""
        area = QScrollArea()
        area.setWidget(page)
        area.setWidgetResizable(True)
        area.setFrameShape(QFrame.Shape.NoFrame)
        self._areas[key] = area
        return area

    def open_page(self, key: str):
        if key == "general":                 # old name of the Race view
            key = "race"
        if key == "ambient":
            self.open_ambient()
            return
        if key == "dynamics":
            key = "analysis"
            self.analysis.setCurrentIndex(1)
        if key not in self._areas:
            return
        self.current = key
        self.stack.setCurrentWidget(self._areas[key])
        self.topbar.set_view(key)
        self.strip.setVisible(key in LIVE_VIEWS)
        self._refresh_strip()

    def open_ambient(self):
        from ui.ambient import AmbientWindow
        if self.ambient is None or not self.ambient.isVisible():
            self.ambient = AmbientWindow(self.hub)
        screens = QApplication.screens()
        if len(screens) > 1:                     # on the second monitor when there is one
            other = next((sc for sc in screens if sc is not self.screen()), screens[0])
            self.ambient.setGeometry(other.geometry())
        self.ambient.showFullScreen()
        self.ambient.raise_()

    def _refresh_strip(self):
        hub = self.hub
        v = rv.strip_values(hub, self.trend)
        self.topbar.set_flag(v["flag"] if hub.running else None)
        info = hub.session_info
        self.topbar.set_session(" · ".join(x for x in (info.get("session"), info.get("track"), info.get("car")) if x)
                                if hub.running else "")
        if self.strip.isVisible():
            self.strip.update_from(v, self._strip_titles)

    # ------------------------------------------------------------- settings
    def _open_remote(self):
        from ui.remote_dialog import RemoteDialog
        RemoteDialog(self.hub, self).exec()

    def _on_mode(self, mode: str):
        self.hub.set_mode(mode)
        self.open_page(MODE_PAGES[mode])
        tips = {"driver": "Driver mode: radio and engineer voice on",
                "engineer": "Engineer mode: live adjustments and setup from the Pit & Setup page",
                "analysis": "Analysis mode: lap comparison and archive, radio off"}
        self.statusBar().showMessage(tr(tips[mode]), 5000)

    def _on_language(self, code: str):
        if code == self.hub.setting("ui/language", "en"):
            return
        self.hub.settings.setValue("ui/language", code)
        QMessageBox.information(self, "Delta Suite", tr("The new language is applied the next time you start "
                                                        "Delta Suite."))

    def _on_theme(self, key: str):
        if key == self.hub.setting("ui/theme", theme.DEFAULT_THEME):
            return
        self.hub.settings.setValue("ui/theme", key)
        QMessageBox.information(self, "Delta Suite", tr("The new theme is applied the next time you start "
                                                        "Delta Suite."))

    def _on_checklist(self, key: str):
        """Buttons of the status list on Home (and of the old get-started list)."""
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
        elif key == "remote":
            self._open_remote()
        self.home.refresh()

    # ------------------------------------------------------------- acquisition
    def _start(self, source: str):
        """Start (or stop) from Home: AC live or a recording; then the Race view."""
        t = self.telemetry
        if self.hub.running:
            t._toggle()
            return
        t.source.setCurrentIndex(t.source.findData(source))
        t._toggle()
        if self.hub.running:
            self.open_page("race")

    def _start_demo(self):
        self.telemetry.start_demo()
        self.open_page("race")

    def closeEvent(self, event):
        if self.ambient is not None:
            self.ambient.close()
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
    shots.append(("analysis_dynamics", lambda: (win.open_page("analysis"), win.analysis.setCurrentIndex(1))))
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
