"""Track map coloured by where the last lap gained (green) or lost (red) against the best one, with a clickable
chip on each corner ("T4 +0.14") and the cars with their short names."""

from __future__ import annotations

from PyQt6.QtCore import QPointF, QRectF, Qt, pyqtSignal
from PyQt6.QtGui import QColor, QFont, QPainter, QPen

from ui.theme import C
from ui.widgets import paint_font
from ui.widgets.gps import GPSView

GAIN_FULL_S = 0.03          # per stretch: at this gain or loss the colour is full


class TrackDeltaMap(GPSView):
    corner_clicked = pyqtSignal(int)        # index in self.corners

    def __init__(self):
        super().__init__()
        self.setMinimumSize(420, 320)
        self.profile: list[float] = []      # time lost per equal stretch from the start line
        self.corners: list[dict] = []       # {frac, label, lost}
        self.selected = -1
        self._chips: list[QRectF] = []
        self.overlay = self._paint_delta

    def set_delta(self, profile: list[float], corners: list[dict]):
        self.profile, self.corners = profile, corners
        if self.selected >= len(corners):
            self.selected = -1
        self.update()

    def _paint_delta(self, p: QPainter, to_px, edge: float, fill: float):
        self._chips = []
        if self.line is None or not self.profile:
            return
        n = len(self.profile)
        green, red = QColor(C["green"]), QColor(C["red"])
        for i, v in enumerate(self.profile):
            k = max(-1.0, min(1.0, v / GAIN_FULL_S))
            if abs(k) < 0.05:
                continue
            col = QColor(red if k > 0 else green)
            col.setAlpha(int(70 + 185 * abs(k)))
            pts = self.line.points(i / n, (i + 1) / n)
            p.setPen(QPen(col, fill * 0.8, Qt.PenStyle.SolidLine, Qt.PenCapStyle.FlatCap, Qt.PenJoinStyle.RoundJoin))
            p.drawPath(self._path(to_px, pts))
        p.setFont(paint_font(8, QFont.Weight.DemiBold))
        fm = p.fontMetrics()
        for i, c in enumerate(self.corners):
            pt = to_px(*self.line.point(c["frac"]))
            text = c["label"]
            w, h = fm.horizontalAdvance(text) + 10, fm.height() + 4
            r = QRectF(pt.x() - w / 2, pt.y() - edge * 1.4 - h, w, h)
            lost = c["lost"] > 0
            base = QColor(C["red"] if lost else C["green"])
            bg = QColor(base)
            bg.setAlpha(230 if i == self.selected else 60)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(bg)
            p.drawRoundedRect(r, 5, 5)
            p.setPen(QColor(C["on_accent"]) if i == self.selected else base)
            p.drawText(r, Qt.AlignmentFlag.AlignCenter, text)
            self._chips.append(r)

    def mousePressEvent(self, e):
        pos = QPointF(e.position())
        for i, r in enumerate(self._chips):
            if r.contains(pos):
                self.selected = i
                self.update()
                self.corner_clicked.emit(i)
                return
        super().mousePressEvent(e)
