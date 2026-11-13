"""Small line of values (lap times of a session), the best one marked."""

from __future__ import annotations

from PyQt6.QtCore import QPointF, Qt
from PyQt6.QtGui import QColor, QPainter, QPen, QPolygonF
from PyQt6.QtWidgets import QSizePolicy, QWidget

from ui.theme import C


class Sparkline(QWidget):
    def __init__(self, height: int = 56):
        super().__init__()
        self.values: list[float] = []
        self.setMinimumHeight(height)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

    def set_values(self, values: list[float]):
        self.values = list(values)
        self.update()

    def paintEvent(self, _):
        if len(self.values) < 2:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        lo, hi = min(self.values), max(self.values)
        span = (hi - lo) or 1.0
        w, h, pad = self.width(), self.height(), 6
        n = len(self.values)
        pts = [QPointF(pad + i * (w - 2 * pad) / (n - 1), pad + (v - lo) / span * (h - 2 * pad))   # faster = higher
               for i, v in enumerate(self.values)]
        p.setPen(QPen(QColor(C["blue"]), 2))
        p.drawPolyline(QPolygonF(pts))
        best = min(range(n), key=lambda i: self.values[i])
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(C["purple"]))
        p.drawEllipse(pts[best], 4, 4)
        p.end()
