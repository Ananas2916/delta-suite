"""
Ambient: a full-screen window for a second monitor (or a glance during a race). Left the delta on the best lap in
huge numbers on green (gaining) or red (losing); right the gap to the car ahead, blue when it is within a second.
A yellow edge on a yellow flag. Esc or the button closes it.
"""

from __future__ import annotations

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from hub_core.i18n import tr
from ui import race_view as rv

GOOD_BG, BAD_BG, IDLE_BG, CLOSE_BG = "#0e5a31", "#6a1414", "#111419", "#123e7a"


def ambient_colors(delta: float | None, gap_ahead: float | None) -> tuple[str, str]:
    """Background of the delta half and of the gap half."""
    left = IDLE_BG if delta is None else GOOD_BG if delta <= 0 else BAD_BG
    right = CLOSE_BG if gap_ahead is not None and gap_ahead < 1.0 else IDLE_BG
    return left, right


class _Half(QWidget):
    def __init__(self, title: str):
        super().__init__()
        self.setAutoFillBackground(True)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        self.edge = QLabel()
        self.edge.setFixedHeight(18)
        lay.addWidget(self.edge)
        lay.addStretch()
        self.title = QLabel(title.upper())
        self.big = QLabel("–")
        self.sub = QLabel()
        for w, css in ((self.title, "font-size: 14pt; letter-spacing: 2px; color: #dfe6ee;"),
                       (self.big, "font-family: 'Bahnschrift', 'Segoe UI'; font-size: 150pt; font-weight: 800; "
                                  "color: white;"),
                       (self.sub, "font-family: Consolas; font-size: 18pt; color: #dfe6ee;")):
            w.setStyleSheet("background: transparent; " + css)
            w.setAlignment(Qt.AlignmentFlag.AlignCenter)
            lay.addWidget(w)
        lay.addStretch()

    def paint(self, bg: str, edge: str | None = None):
        self.setStyleSheet(f"background: {bg};")
        self.edge.setStyleSheet(f"background: {edge or 'transparent'};")


class AmbientWindow(QWidget):
    def __init__(self, hub):
        super().__init__(None, Qt.WindowType.Window)
        self.hub = hub
        self.trend = rv.GapTrend()
        self.setWindowTitle("Delta Suite · Ambient")
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        self.left = _Half(tr("Delta on best"))
        self.right = _Half(tr("Ahead"))
        lay.addWidget(self.left)
        lay.addWidget(self.right)
        close = QPushButton(tr("Exit Ambient"), self)
        close.setStyleSheet("background: rgba(0,0,0,0.45); color: white; border: 1px solid rgba(255,255,255,0.3); "
                            "border-radius: 8px; padding: 6px 12px;")
        close.clicked.connect(self.close)
        close.move(16, 30)
        self.timer = QTimer(self)
        self.timer.timeout.connect(self._tick)
        self.timer.start(100)
        self._tick()

    def keyPressEvent(self, e):
        if e.key() == Qt.Key.Key_Escape:
            self.close()
        else:
            super().keyPressEvent(e)

    def _tick(self):
        hub = self.hub
        v = rv.strip_values(hub, self.trend)
        d = hub.live_lap.delta_s if hub.last_sample is not None else None
        self.left.big.setText("–" if d is None else f"{d:+.2f}".replace("-", "−"))
        self.left.sub.setText(v["lap_title"])
        gap = None
        if v["ahead"] not in ("–", ""):
            try:
                gap = float(v["ahead"].lstrip("+"))
            except ValueError:
                gap = None
        self.right.title.setText(v["ahead_title"].upper())
        self.right.big.setText("–" if gap is None else f"{gap:.1f}")
        self.right.sub.setText(v["ahead_sub"])
        left, right = ambient_colors(d, gap)
        flag = v["flag"]
        edge = "#f1c40f" if flag and flag[0] == "yellow" else "#ff3b3b" if flag and flag[0] == "red" else None
        self.left.paint(left, edge)
        self.right.paint(right, edge)

    def closeEvent(self, e):
        self.timer.stop()
        super().closeEvent(e)
