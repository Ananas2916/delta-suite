"""Settings: what used to crowd the sidebar (mode, language, theme, remote access) plus the CSP app."""

from __future__ import annotations

from PyQt6.QtCore import pyqtSignal
from PyQt6.QtWidgets import QComboBox, QFormLayout, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from hub_core.i18n import LANGUAGES, language, tr
from ui import theme
from ui.hub_state import MODES
from ui.theme import C
from ui.widgets import Card, label


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

        root.addWidget(label(f"Delta Suite {version} · MIT · github.com/Ananas2916/delta-suite", "dim"))
        root.addStretch()
        hub.remote.changed.connect(self._remote)
        self._remote()

    def _remote(self):
        r = self.hub.remote
        n = len(r.pairing.device_list())
        self.remote_state.setText(tr("On · {n} devices paired", n=n) if r.enabled else tr("Off"))
        self.remote_state.setStyleSheet(f"color: {C['green'] if r.enabled else C['dim']}; font-weight: 600;")
