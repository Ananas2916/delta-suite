"""Parziali: riquadri S1..Sn colorati come in TV e il tempo del giro in corso con il delta live sul migliore."""

from __future__ import annotations

from PyQt6.QtCore import QRectF, Qt
from PyQt6.QtGui import QColor, QFont, QPainter
from PyQt6.QtWidgets import QHBoxLayout, QLabel, QSizePolicy, QVBoxLayout, QWidget

from hub_core.analysis.live_lap import SectorView
from hub_core.analysis.race_strategy import fmt_ms
from ui.theme import C
from ui.widgets import Card, label, paint_font

SECTOR_COLORS = {"best": C["purple"], "slower": C["yellow"], "current": "#ffffff", "empty": C["border"]}


def fmt_sector(ms: int | None) -> str:
    if ms is None:
        return ""
    return f"{ms / 1000:.3f}" if ms < 60_000 else fmt_ms(ms)


def fmt_delta(delta_s: float | None) -> tuple[str, str]:
    """Testo e colore del delta live: rosso se più lento del migliore, verde se più veloce."""
    if delta_s is None:
        return "", C["dim"]
    color = C["red"] if delta_s > 0.05 else C["green"] if delta_s < -0.05 else C["text"]
    return f"{delta_s:+.2f}", color


class SectorBar(QWidget):
    """Un riquadro per settore: etichetta, tempo, striscia del colore (viola migliore, giallo più lento)."""

    def __init__(self, height: int = 30):
        super().__init__()
        self.views: list[SectorView] = []
        self.setFixedHeight(height)
        self.setMinimumWidth(150)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

    def set_views(self, views: list[SectorView]) -> None:
        if views != self.views:
            self.views = views
            self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        n = max(1, len(self.views))
        gap = 4.0
        w = (self.width() - gap * (n - 1)) / n
        h = float(self.height())
        for i, v in enumerate(self.views):
            r = QRectF(i * (w + gap), 0, w, h)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(C["panel2"]))
            p.drawRoundedRect(r, 4, 4)
            p.setBrush(QColor(SECTOR_COLORS.get(v.state, C["border"])))
            p.drawRoundedRect(QRectF(r.left(), r.bottom() - 4, r.width(), 4), 2, 2)
            body = r.adjusted(6, 0, -6, -4)
            p.setPen(QColor(C["dim"]))
            p.setFont(paint_font(7.5, QFont.Weight.DemiBold))
            p.drawText(body, Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, v.label)
            if v.ms is not None:
                col = "#ffffff" if v.state == "current" else SECTOR_COLORS.get(v.state, C["text"])
                p.setPen(QColor(col))
                p.setFont(paint_font(9, QFont.Weight.Bold))
                p.drawText(body, Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight, fmt_sector(v.ms))
        p.end()


class LapTimeTile(Card):
    """Tempo del giro in corso, delta live sul migliore e parziali sotto."""

    def __init__(self, title: str = "TEMPO GIRO"):
        super().__init__()
        lay = QVBoxLayout(self)
        lay.setContentsMargins(12, 8, 12, 8)
        lay.setSpacing(4)
        head = QHBoxLayout()
        t = label(title, "dim")
        t.setStyleSheet("font-size: 8pt; letter-spacing: 1px;")
        head.addWidget(t)
        head.addStretch()
        self.delta = QLabel("")
        head.addWidget(self.delta)
        lay.addLayout(head)
        self.time = QLabel("--:--.---")
        self.time.setStyleSheet("font-size: 20pt; font-weight: 700;")
        lay.addWidget(self.time)
        self.sectors = SectorBar(26)
        lay.addWidget(self.sectors)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

    def set(self, lap_ms: int | None, delta_s: float | None, views: list[SectorView]) -> None:
        self.time.setText(fmt_ms(lap_ms))
        text, color = fmt_delta(delta_s)
        self.delta.setText(text)
        self.delta.setStyleSheet(f"font-size: 13pt; font-weight: 800; color: {color};")
        self.sectors.set_views(views)
