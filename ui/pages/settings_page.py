"""Settings: what used to crowd the sidebar (mode, language, theme, remote access) plus the CSP app."""

from __future__ import annotations

from PyQt6.QtCore import pyqtSignal
from PyQt6.QtWidgets import (QComboBox, QFormLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton, QVBoxLayout,
                             QWidget)

from hub_core.i18n import LANGUAGES, language, tr
from ui import theme
from ui.hub_state import MODES
from ui.theme import C
from hub_core.ac.race_link import RaceSettings
from ui.widgets import Card, dspin, label


def _section(title: str, text: str = "") -> tuple[Card, QVBoxLayout]:
    card = Card()
    lay = QVBoxLayout(card)
    lay.setContentsMargins(16, 14, 16, 14)
    h = QLabel(title.upper())
    h.setStyleSheet(f"color: {C['dim']}; font-size: 8pt; font-weight: 600; letter-spacing: 1.3px;")
    lay.addWidget(h)
    if text:
        t = QLabel(text)
        t.setWordWrap(True)
        t.setStyleSheet(f"color: {C['dim']};")
        lay.addWidget(t)
    return card, lay


class SettingsPage(QWidget):
    mode_changed = pyqtSignal(str)
    language_changed = pyqtSignal(str)
    theme_changed = pyqtSignal(str)
    open_remote = pyqtSignal()
    install_csp = pyqtSignal()

    def __init__(self, hub, version: str):
        super().__init__()
        self.hub = hub
        root = QVBoxLayout(self)
        root.setContentsMargins(14, 14, 14, 14)
        root.setSpacing(10)
        root.addWidget(label(tr("Settings"), "h1"))

        card, lay = _section(tr("Interface"))
        form = QFormLayout()
        self.mode = QComboBox()
        for k, v in MODES.items():
            self.mode.addItem(tr(v), k)
        self.mode.setCurrentIndex(max(0, self.mode.findData(hub.mode)))
        self.mode.setToolTip(tr("Driver: radio and voice on · Engineer: adjustments and setup · Analysis: archive"))
        self.mode.currentIndexChanged.connect(lambda: self.mode_changed.emit(self.mode.currentData()))
        self.language = QComboBox()
        for code, name in LANGUAGES.items():
            self.language.addItem(name, code)
        self.language.setCurrentIndex(max(0, self.language.findData(language())))
        self.language.currentIndexChanged.connect(lambda: self.language_changed.emit(self.language.currentData()))
        self.theme = QComboBox()
        for key, t in theme.THEMES.items():
            self.theme.addItem(tr(t["name"]), key)
        self.theme.setCurrentIndex(max(0, self.theme.findData(theme.THEME)))
        self.theme.currentIndexChanged.connect(lambda: self.theme_changed.emit(self.theme.currentData()))
        for w in (self.mode, self.language, self.theme):
            w.setMinimumWidth(260)
        form.addRow(tr("Mode"), self.mode)
        form.addRow(tr("Language"), self.language)
        form.addRow(tr("Theme"), self.theme)
        lay.addLayout(form)
        note = QLabel(tr("Language and theme are applied the next time you start Delta Suite. The radio speaks "
                         "the language of the chosen voice (Engineer → Settings)."))
        note.setStyleSheet(f"color: {C['dim']};")
        note.setWordWrap(True)
        lay.addWidget(note)
        root.addWidget(card)

        card, lay = _section(tr("Remote pit wall"), tr("Follow the session and act as the engineer from another "
                                                       "PC, a tablet or a phone, on your network or through "
                                                       "Tailscale."))
        row = QHBoxLayout()
        self.remote_state = QLabel()
        self.remote_btn = QPushButton(tr("Remote access…"))
        self.remote_btn.clicked.connect(self.open_remote)
        row.addWidget(self.remote_state)
        row.addStretch()
        row.addWidget(self.remote_btn)
        lay.addLayout(row)
        root.addWidget(card)

        card, lay = _section(tr("CSP app"), tr("The Delta Suite Bridge app inside Assetto Corsa: rivals, setup, "
                                               "onboard video and the wheel buttons need it."))
        row = QHBoxLayout()
        install = QPushButton(tr("Install or update the CSP app"))
        install.clicked.connect(self.install_csp)
        row.addStretch()
        row.addWidget(install)
        lay.addLayout(row)
        root.addWidget(card)

        card, lay = _section(tr("Race control"), tr("FCY and VSC run by the CSP app in offline races: the AI cars "
                                                    "slow down, the radio calls it and the DS Race control window "
                                                    "shows the limit or the delta. Call them from the Race view or "
                                                    "from the wheel."))
        rs = hub.race_ctl.settings
        form = QFormLayout()
        self.rc_factor = dspin(1.1, 2.5, rs.vsc_factor, 0.05, 2, "×")
        self.rc_factor.setToolTip(tr("VSC reference: your best lap times this factor (1.40 = 40% slower)"))
        self.rc_ai = dspin(0, 250, rs.vsc_ai_kmh, 5, 0, "km/h")
        self.rc_ai.setSpecialValueText(tr("automatic"))
        self.rc_ai.setToolTip(tr("Speed cap of the AI cars under VSC; automatic follows the VSC reference pace"))
        self.rc_fcy = dspin(40, 150, rs.fcy_kmh, 5, 0, "km/h")
        self.rc_countdown = dspin(3, 30, rs.countdown_s, 1, 0, "s")
        self.rc_ending = dspin(3, 30, rs.ending_s, 1, 0, "s")
        self.rc_sc = dspin(60, 250, rs.sc_kmh, 5, 0, "km/h")
        self.rc_sc.setToolTip(tr("Safety car speed cap: it takes corners slower anyway"))
        self.rc_sc_car = QLineEdit(rs.sc_car_id)
        self.rc_sc_car.setPlaceholderText(tr("automatic: the car whose name says \"safety\""))
        self.rc_sc_car.setToolTip(tr("Folder name of the safety car (content/cars/...), to use a car whose name does "
                                     "not say \"safety\""))
        self.rc_sc_car.editingFinished.connect(self._save_race)
        self.rc_wave = dspin(0, 5, rs.sc_wave_laps, 1, 0, tr("laps"))
        self.rc_wave.setSpecialValueText(tr("never"))
        self.rc_wave.setToolTip(tr("Laps behind the safety car before the lapped cars may overtake it and rejoin at "
                                   "the back of the queue"))
        form.addRow(tr("VSC reference"), self.rc_factor)
        form.addRow(tr("AI speed under VSC"), self.rc_ai)
        form.addRow(tr("FCY speed limit"), self.rc_fcy)
        form.addRow(tr("FCY countdown"), self.rc_countdown)
        form.addRow(tr("Ending warning"), self.rc_ending)
        form.addRow(tr("Safety car speed"), self.rc_sc)
        form.addRow(tr("Safety car"), self.rc_sc_car)
        form.addRow(tr("Lapped cars unlap after"), self.rc_wave)
        for w in (self.rc_factor, self.rc_ai, self.rc_fcy, self.rc_countdown, self.rc_ending, self.rc_sc,
                  self.rc_wave):
            w.setMinimumWidth(160)
            w.valueChanged.connect(self._save_race)
        lay.addLayout(form)
        root.addWidget(card)

        root.addWidget(label(f"Delta Suite {version} · MIT · github.com/Ananas2916/delta-suite", "dim"))
        root.addStretch()
        hub.remote.changed.connect(self._remote)
        self._remote()

    def _save_race(self):
        self.hub.race_ctl.save_settings(RaceSettings(
            vsc_factor=self.rc_factor.value(), vsc_ai_kmh=self.rc_ai.value(), fcy_kmh=self.rc_fcy.value(),
            countdown_s=self.rc_countdown.value(), ending_s=self.rc_ending.value(), sc_kmh=self.rc_sc.value(),
            sc_car_id=self.rc_sc_car.text().strip(), sc_wave_laps=int(self.rc_wave.value())))

    def _remote(self):
        r = self.hub.remote
        n = len(r.pairing.device_list())
        self.remote_state.setText(tr("On · {n} devices paired", n=n) if r.enabled else tr("Off"))
        self.remote_state.setStyleSheet(f"color: {C['green'] if r.enabled else C['dim']}; font-weight: 600;")
