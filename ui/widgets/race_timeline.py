"""Race timeline: lanes for position, tyres (stints and stops), fuel and events, a cursor and the forecast area."""

from __future__ import annotations

from PyQt6.QtCore import QPointF, QRectF, Qt
from PyQt6.QtGui import QBrush, QColor, QFont, QLinearGradient, QPainter, QPen
from PyQt6.QtWidgets import QSizePolicy, QWidget

from hub_core.analysis.race_timeline import Timeline
from hub_core.i18n import tr
from ui.theme import C
from ui.widgets import paint_font

LANES = ("Position", "Tyres", "Fuel", "Events")       # translated when painted
LABEL_W, LANE_H, GAP = 84, 20, 5
EVENT_COLORS = {"best": "purple", "invalid": "red", "pit": "accent"}


class TimelineView(QWidget):
    def __init__(self):
        super().__init__()
        self.tl: Timeline | None = None
        self.cursor = 0
        self.setMinimumHeight(len(LANES) * (LANE_H + GAP) + 6)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

    def set_timeline(self, tl: Timeline | None):
        self.tl = tl
        self.update()

    def set_cursor(self, lap: int):
        self.cursor = lap
        self.update()

    def _x(self, lap: float) -> float:
        span = max(1, self.tl.total - 1)
        return LABEL_W + (lap - 1) / span * (self.width() - LABEL_W - 8)

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setFont(paint_font(7.5, QFont.Weight.DemiBold))
        for i, name in enumerate(LANES):
            p.setPen(QColor(C["dim"]))
            p.drawText(QRectF(0, i * (LANE_H + GAP), LABEL_W, LANE_H), Qt.AlignmentFlag.AlignVCenter, tr(name).upper())
        tl = self.tl
        if tl is None or tl.total < 1:
            p.end()
            return
        top, bottom = 0, len(LANES) * (LANE_H + GAP) - GAP
        # forecast area: hatched right of the current lap
        fx = self._x(tl.done + 0.5) if tl.done else LABEL_W
        p.fillRect(QRectF(fx, top, self.width() - fx, bottom), QBrush(QColor(255, 255, 255, 10),
                                                                       Qt.BrushStyle.BDiagPattern))
        p.setPen(QPen(QColor(C["border"]), 1, Qt.PenStyle.DashLine))
        p.drawLine(QPointF(fx, top), QPointF(fx, bottom))

        def lane_y(i):
            return i * (LANE_H + GAP)

        def tag(x, y, text, color, filled=False):
            w = p.fontMetrics().horizontalAdvance(text) + 10
            r = QRectF(x - w / 2, y + 2, w, LANE_H - 4)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(color) if filled else QColor(C["panel2"]))
            p.drawRoundedRect(r, 4, 4)
            p.setPen(QColor(C["on_accent"]) if filled else QColor(color))
            p.drawText(r, Qt.AlignmentFlag.AlignCenter, text)

        # position changes
        for lap, text, kind in tl.positions:
            tag(self._x(lap), lane_y(0), text, C["green"] if kind == "gain" else C["red"] if kind == "lose" else C["text"])
        # tyre stints and stops
        y = lane_y(1) + 5
        for first, last, future in tl.stints:
            if last < first:
                continue
            x0, x1 = self._x(first - 0.4), self._x(last + 0.4)
            g = QLinearGradient(x0, 0, x1, 0)
            g.setColorAt(0, QColor(C["yellow"]))
            g.setColorAt(1, QColor(C["red"] if not future else C["yellow"]))
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QBrush(g))
            p.setOpacity(0.5 if future else 1.0)
            p.drawRoundedRect(QRectF(x0, y, x1 - x0, LANE_H - 10), 3, 3)
            p.setOpacity(1.0)
        for lap, planned in tl.boxes:
            tag(self._x(lap), lane_y(1), tr("BOX {n}", n=lap), C["accent"], filled=True)
        # fuel: line of litres at the end of each lap, red below zero
        pts = [(lap, f) for lap, f, _fc in tl.fuel]
        if len(pts) > 1:
            hi = max(f for _l, f in pts) or 1.0
            yb, yt = lane_y(2) + LANE_H - 2, lane_y(2) + 2
            for (l0, f0), (l1, f1) in zip(pts, pts[1:]):
                col = C["red"] if min(f0, f1) < 0 else C["green"]
                p.setPen(QPen(QColor(col), 2))
                p.drawLine(QPointF(self._x(l0), yb - max(0, f0) / hi * (yb - yt)),
                           QPointF(self._x(l1), yb - max(0, f1) / hi * (yb - yt)))
        # events
        for lap, kind, _k in tl.events:
            text = {"best": tr("best"), "invalid": tr("invalid"), "pit": tr("pit")}.get(kind, kind)
            tag(self._x(lap), lane_y(3), text, C[EVENT_COLORS.get(kind, "dim")])
        # cursor
        if self.cursor:
            cx = self._x(self.cursor)
            p.setPen(QPen(QColor(C["text"]), 2))
            p.drawLine(QPointF(cx, top), QPointF(cx, bottom))
        p.end()
