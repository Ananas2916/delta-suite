"""Remote access window: turn it on, the code that changes every 10 seconds, the address to open, paired devices."""

from __future__ import annotations

import time

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QGuiApplication
from PyQt6.QtWidgets import (
    QCheckBox, QDialog, QHBoxLayout, QLabel, QListWidget, QListWidgetItem, QProgressBar, QPushButton, QVBoxLayout,
)

from ui import theme
from hub_core.i18n import tr


def _ago(t: float) -> str:
    if not t:
        return tr("not seen since the restart")
    s = time.time() - t
    if s < 10:
        return tr("online now")
    if s < 3600:
        return tr("seen {n} min ago", n=int(s // 60))
    return tr("seen {when}", when=time.strftime("%d/%m %H:%M", time.localtime(t)))


class RemoteDialog(QDialog):
    def __init__(self, hub, parent=None):
        super().__init__(parent)
        self.hub = hub
        self.remote = hub.remote
        self.setWindowTitle(tr("Remote access"))
        self.setMinimumWidth(460)
        lay = QVBoxLayout(self)
        lay.setSpacing(10)

        intro = QLabel(tr("Follow the session from another PC, a tablet or a phone: pit wall, onboard video, setup, "
                       "strategy, laps and radio, and act as the engineer (confirm proposals, adjust the car, talk to "
                       "the driver, ask the AI engineer). Nothing to install there: just a browser. The video is "
                       "rendered in AC only while someone is watching it."))
        intro.setWordWrap(True)
        intro.setStyleSheet(f"color: {theme.C['dim']};")
        lay.addWidget(intro)

        self.enable = QCheckBox(tr("Enable remote access"))
        self.enable.setChecked(self.remote.enabled)
        self.enable.toggled.connect(self._toggle)
        lay.addWidget(self.enable)

        self.url = QLabel()
        self.url.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.url.setWordWrap(True)
        lay.addWidget(self.url)
        self.copy = QPushButton(tr("Copy address"))
        self.copy.clicked.connect(self._copy)
        lay.addWidget(self.copy, 0, Qt.AlignmentFlag.AlignLeft)

        self.code = QLabel("––– –––")
        self.code.setAlignment(Qt.AlignmentFlag.AlignCenter)
        # size in the style sheet: the global one (font-size 10pt) would win over setFont
        self.code.setStyleSheet(f"background: {theme.C['panel']}; border-radius: 10px; padding: 14px; "
                                f"font-family: Consolas, monospace; font-size: 34pt; font-weight: 800; "
                                f"letter-spacing: 6px; color: {theme.C['text']};")
        lay.addWidget(self.code)
        self.countdown = QProgressBar()
        self.countdown.setRange(0, 1000)
        self.countdown.setTextVisible(False)
        self.countdown.setFixedHeight(6)
        lay.addWidget(self.countdown)
        self.code_hint = QLabel(tr("Type this code on the other device: it changes every 10 seconds and works once."))
        self.code_hint.setWordWrap(True)
        self.code_hint.setStyleSheet(f"color: {theme.C['dim']};")
        lay.addWidget(self.code_hint)

        lay.addWidget(QLabel(tr("Paired devices")))
        self.devices = QListWidget()
        self.devices.setMinimumHeight(110)
        lay.addWidget(self.devices)
        row = QHBoxLayout()
        self.revoke = QPushButton(tr("Revoke selected"))
        self.revoke.clicked.connect(self._revoke)
        self.revoke_all = QPushButton(tr("Revoke all"))
        self.revoke_all.clicked.connect(self._revoke_all)
        row.addWidget(self.revoke)
        row.addWidget(self.revoke_all)
        row.addStretch()
        close = QPushButton(tr("Close"))
        close.clicked.connect(self.accept)
        row.addWidget(close)
        lay.addLayout(row)

        note = QLabel(tr("Home network only (plain HTTP). From outside, use a VPN such as Tailscale: do not open the "
                      "port on the router. Windows may ask to allow Delta Suite through the firewall: allow it on "
                      "private networks."))
        note.setWordWrap(True)
        note.setStyleSheet(f"color: {theme.C['dim']}; font-size: 8pt;")
        lay.addWidget(note)

        self.remote.changed.connect(self._refresh)
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._timer.start(100)
        self._refresh()

    def _toggle(self, on: bool):
        if not self.remote.set_enabled(on):
            self.enable.blockSignals(True)
            self.enable.setChecked(False)
            self.enable.blockSignals(False)
            self.url.setText(tr("Could not start the server: {err}", err=self.remote.server.error))
        self._refresh()

    def _refresh(self):
        on = self.remote.enabled
        for w in (self.code, self.countdown, self.code_hint, self.copy):
            w.setVisible(on)
        if on:
            self.url.setText(self._address_text(self.remote.server.labelled_urls()))
        elif not self.remote.server.error:
            self.url.setText(tr("Off: nobody can connect."))
        self.devices.clear()
        for d in self.remote.pairing.device_list():
            item = QListWidgetItem(f"{d.name}   ·   {d.address or '—'}   ·   {_ago(d.last_seen)}")
            item.setData(Qt.ItemDataRole.UserRole, d.id)
            self.devices.addItem(item)
        if not self.devices.count():
            self.devices.addItem(tr("No device paired yet"))
        self.revoke.setEnabled(bool(self.remote.pairing.device_list()))
        self.revoke_all.setEnabled(self.revoke.isEnabled())
        self._tick()

    @staticmethod
    def _address_text(urls: list[tuple[str, str]]) -> str:
        """The addresses to open, LAN and Tailscale on separate lines."""
        lan = [u for kind, u in urls if kind == "lan"]
        ts = [u for kind, u in urls if kind == "tailscale"]
        lines = [tr("On the other device open:")]
        if lan:
            lines.append(tr("Same network (LAN, lowest latency):") + "  " + "   ·   ".join(f"<b>{u}</b>" for u in lan))
        if ts:
            lines.append(tr("Through Tailscale (from anywhere):") + "  " + "   ·   ".join(f"<b>{u}</b>" for u in ts))
        else:
            lines.append(f"<span style='color:{theme.C['dim']}'>"
                         + tr("Tailscale not detected on this PC: install it to connect from outside the home network.")
                         + "</span>")
        return "<br>".join(lines)

    def _tick(self):
        if not self.remote.enabled:
            return
        code, left = self.remote.pairing.current_code()
        text = f"{code[:3]} {code[3:]}"
        if self.code.text() != text:
            self.code.setText(text)
        step = self.remote.pairing.step_s
        self.countdown.setValue(int(1000 * left / step))

    def _copy(self):
        urls = self.remote.server.labelled_urls()
        if urls:
            QGuiApplication.clipboard().setText(urls[0][1])

    def _revoke(self):
        item = self.devices.currentItem()
        did = item.data(Qt.ItemDataRole.UserRole) if item is not None else None
        if did:
            self.remote.pairing.revoke(did)

    def _revoke_all(self):
        self.remote.pairing.revoke_all()

    def done(self, r):
        self._timer.stop()
        try:
            self.remote.changed.disconnect(self._refresh)
        except TypeError:
            pass
        super().done(r)
