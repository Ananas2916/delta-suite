"""
Track GPS: the track line drawn like a circuit (dark band with a light edge), finish line,
pit lane, coloured stretches for yellow (slow car), red (stopped car) and blue, and the cars as circles with
their position. Click on a car → car_clicked signal.
"""

from __future__ import annotations

import math
from collections import deque

from PyQt6.QtCore import QPointF, QRectF, Qt, pyqtSignal
from PyQt6.QtGui import QColor, QFont, QPainter, QPainterPath, QPen
from PyQt6.QtWidgets import QWidget

from hub_core.analysis.track_status import TrackLine, Zone
from ui.theme import C
from ui.widgets import paint_font
from hub_core.i18n import tr

TRACK_EDGE, TRACK_FILL, PIT_LANE = "#e6e9ef", "#2f3540", "#6b7280"
ZONE_FILL = {"yellow": "#f5c518", "red": "#ff3b3b", "blue": "#3d9bff"}
ME_FILL, LEADER_FILL, CAR_FILL = "#f5c518", "#c43cff", "#e7e9ee"


def _pen(color: str, width: float, alpha: int = 255, style=Qt.PenStyle.SolidLine) -> QPen:
    col = QColor(color)
    col.setAlpha(alpha)
    return QPen(col, width, style, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin)


class GPSView(QWidget):
    """Track map with the cars. The line comes from the track AI line (or is learned while driving); until
    it exists, the path driven by your car is drawn."""

    car_clicked = pyqtSignal(int)

    def __init__(self):
        super().__init__()
        self.setMinimumSize(200, 150)
        self.line: TrackLine | None = None
        self.pit: list[tuple[float, float]] = []
        self._pit_src = None
        self.trail: deque[tuple[float, float]] = deque(maxlen=8000)
        self.zones: list[Zone] = []
        self.cars: list[dict] = []       # {idx, pos, x, z, num, me, leader, ring, pit, label}
        self.overlay = None              # f(painter, to_px, edge, fill): drawn on the track, under the cars
        self._screen: list[tuple[int, QPointF]] = []

    # ------------------------------------------------------------- data
    def set_track(self, line: TrackLine | None, pit: list[tuple[float, float]] | None = None):
        if line is not self.line or pit is not self._pit_src:
            self.line, self._pit_src, self.pit = line, pit, list(pit or [])
            self.update()

    def clear_trail(self):
        self.trail.clear()
        self.update()

    def add_trail(self, x: float, z: float):
        if not self.trail or (x - self.trail[-1][0]) ** 2 + (z - self.trail[-1][1]) ** 2 > 9.0:   # one point every 3 m
            self.trail.append((x, z))

    def set_zones(self, zones: list[Zone]):
        self.zones = zones

    def set_cars(self, cars: list[dict]):
        self.cars = cars
        self.update()

    # ------------------------------------------------------------- painting
    def _car_xy(self, c: dict) -> tuple[float, float] | None:
        if self.line is not None and c.get("pos") is not None:
            return self.line.point(c["pos"])
        if c.get("x") is not None:
            return c["x"], c["z"]
        return None

    def _mapper(self, area: QRectF):
        """World (x, z) → widget point function: the whole track (or the driven path) centred."""
        if self.line is not None:
            pts = list(zip(self.line.xs, self.line.zs)) + self.pit
        else:
            pts = list(self.trail) + [xy for xy in (self._car_xy(c) for c in self.cars) if xy is not None]
        if not pts:
            return None
        xs, zs = [p[0] for p in pts], [p[1] for p in pts]
        w, h = max(max(xs) - min(xs), 50.0), max(max(zs) - min(zs), 50.0)
        k = min(area.width() / w, area.height() / h)
        cx, cz = (max(xs) + min(xs)) / 2, (max(zs) + min(zs)) / 2
        ox, oy = area.center().x(), area.center().y()
        return lambda x, z: QPointF(ox + (x - cx) * k, oy + (z - cz) * k)

    @staticmethod
    def _path(to_px, pts, closed: bool = False) -> QPainterPath:
        path = QPainterPath(to_px(*pts[0]))
        for x, z in pts[1:]:
            path.lineTo(to_px(x, z))
        if closed:
            path.closeSubpath()
        return path

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.fillRect(self.rect(), QColor(C["panel2"]))
        size = min(self.width(), self.height())
        r = max(7.0, min(11.0, size / 34))            # car radius
        edge, fill = r * 1.6, r * 1.1                 # track thickness: edge and band
        area = QRectF(self.rect()).adjusted(r * 2.2, r * 2.2, -r * 2.2, -r * 2.2)
        to_px = self._mapper(area)
        self._screen = []
        if to_px is None:
            p.setPen(QColor(C["dim"]))
            p.setFont(paint_font(9, QFont.Weight.Normal))
            p.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, tr("The track appears here\nas soon as the car moves"))
            p.end()
            return

        if self.line is not None:
            if len(self.pit) > 1:
                p.setPen(_pen(PIT_LANE, max(2.0, fill * 0.35), 220, Qt.PenStyle.DashLine))
                p.drawPath(self._path(to_px, self.pit))
            track = self._path(to_px, list(zip(self.line.xs, self.line.zs)), closed=True)
            p.setPen(_pen(TRACK_EDGE, edge))
            p.drawPath(track)
            p.setPen(_pen(TRACK_FILL, fill))
            p.drawPath(track)
            for z in self.zones:
                seg = self._path(to_px, self.line.points(z.start, z.end))
                p.setPen(_pen(ZONE_FILL[z.kind], edge * 1.9, 70))     # halo
                p.drawPath(seg)
                p.setPen(_pen(ZONE_FILL[z.kind], fill))
                p.drawPath(seg)
            self._finish_line(p, to_px, edge)
            if self.overlay is not None:
                self.overlay(p, to_px, edge, fill)
        elif len(self.trail) > 1:
            trail = self._path(to_px, list(self.trail))
            p.setPen(_pen(TRACK_EDGE, edge, 160))
            p.drawPath(trail)
            p.setPen(_pen(TRACK_FILL, fill))
            p.drawPath(trail)

        # in order: rivals, leader, cars on screen, yours on top
        order = sorted(self.cars, key=lambda c: (c.get("me", False), bool(c.get("ring")), c.get("leader", False)))
        for c in order:
            xy = self._car_xy(c)
            if xy is None:
                continue
            pt = to_px(*xy)
            self._screen.append((c["idx"], pt))
            self._car(p, pt, c, r)
            if c.get("label"):                      # short driver name next to the car
                p.setPen(QColor(C["text"]))
                p.setFont(paint_font(max(7.0, r * 0.75)))
                p.drawText(QPointF(pt.x() + r * 1.3, pt.y() - r * 0.9), c["label"])
        p.end()

    def _finish_line(self, p: QPainter, to_px, edge: float):
        a, b = to_px(*self.line.point(0.0)), to_px(*self.line.point(0.004))
        dx, dy = b.x() - a.x(), b.y() - a.y()
        n = math.hypot(dx, dy) or 1.0
        nx, ny = -dy / n, dx / n                       # perpendicular to the track
        half = edge * 0.9
        p.setPen(QPen(QColor("#ff3b3b"), max(3.0, edge * 0.28), Qt.PenStyle.SolidLine, Qt.PenCapStyle.FlatCap))
        p.drawLine(QPointF(a.x() - nx * half, a.y() - ny * half), QPointF(a.x() + nx * half, a.y() + ny * half))
        # small chequered flag outside the track
        sq = max(3.5, edge * 0.3)
        ox, oy = a.x() + nx * (half + sq * 1.6), a.y() + ny * (half + sq * 1.6)
        p.setPen(Qt.PenStyle.NoPen)
        for i in range(2):
            for j in range(3):
                p.setBrush(QColor("#ffffff" if (i + j) % 2 == 0 else "#111111"))
                p.drawRect(QRectF(ox + i * sq - sq, oy + j * sq - sq * 1.5, sq, sq))

    @staticmethod
    def _car(p: QPainter, pt: QPointF, c: dict, r: float):
        me, leader, pit = c.get("me", False), c.get("leader", False), c.get("pit", False)
        rad = r * (1.12 if me else 1.0)
        if c.get("ring"):
            p.setPen(QPen(QColor(c["ring"]), 2.5))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawEllipse(pt, rad + 3.5, rad + 3.5)
        if pit:
            p.setPen(QPen(QColor(C["dim"]), 1.5))
            p.setBrush(QColor(C["panel2"]))
            text_col = C["dim"]
        else:
            fill = ME_FILL if me else LEADER_FILL if leader else CAR_FILL
            p.setPen(QPen(QColor("#0b0d10"), 1.5))
            p.setBrush(QColor(fill))
            text_col = "#ffffff" if leader and not me else "#111111"
        p.drawEllipse(pt, rad, rad)
        num = c.get("num", "")
        if num:
            p.setPen(QColor(text_col))
            p.setFont(paint_font(max(6.0, rad * (0.62 if len(num) > 1 else 0.75)), QFont.Weight.Black))
            p.drawText(QRectF(pt.x() - rad, pt.y() - rad, rad * 2, rad * 2), Qt.AlignmentFlag.AlignCenter, num)

    def mousePressEvent(self, e):
        pos = e.position()
        near = min(self._screen, key=lambda it: (it[1].x() - pos.x()) ** 2 + (it[1].y() - pos.y()) ** 2,
                   default=None)
        if near is not None and (near[1].x() - pos.x()) ** 2 + (near[1].y() - pos.y()) ** 2 < 15 ** 2:
            self.car_clicked.emit(near[0])
