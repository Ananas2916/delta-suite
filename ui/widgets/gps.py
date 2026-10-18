"""GPS della pista: mappa di AC (o percorso fatto) con le auto; clic su un'auto → segnale car_clicked."""

from __future__ import annotations

from collections import deque

from PyQt6.QtCore import QPointF, QRectF, Qt, pyqtSignal
from PyQt6.QtGui import QColor, QFont, QImage, QPainter, QPainterPath, QPen
from PyQt6.QtWidgets import QWidget

from hub_core.ac.track_map import TrackMap
from ui.theme import C
from ui.widgets import paint_font


class GPSView(QWidget):
    """Mappa della pista con le auto: la mappa di AC se c'è, altrimenti il percorso fatto dalla tua auto."""

    car_clicked = pyqtSignal(int)

    def __init__(self):
        super().__init__()
        self.setMinimumSize(200, 150)
        self.track_map: TrackMap | None = None
        self.map_img: QImage | None = None
        self.trail: deque[tuple[float, float]] = deque(maxlen=8000)
        self.cars: list[dict] = []       # {idx, x, z, label, me, ring}
        self._screen: list[tuple[int, QPointF]] = []

    def set_map(self, tmap: TrackMap | None):
        self.track_map, self.map_img = tmap, None
        if tmap is not None:
            img = QImage(str(tmap.image))
            self.map_img = None if img.isNull() else img
        self.update()

    def clear_trail(self):
        self.trail.clear()
        self.update()

    def add_trail(self, x: float, z: float):
        if not self.trail or (x - self.trail[-1][0]) ** 2 + (z - self.trail[-1][1]) ** 2 > 9.0:   # un punto ogni 3 m
            self.trail.append((x, z))

    def set_cars(self, cars: list[dict]):
        self.cars = cars
        self.update()

    def _mapper(self, area: QRectF):
        """Funzione mondo (x, z) → punto nel widget, con l'immagine della mappa se c'è."""
        if self.map_img is not None and self.track_map is not None:
            iw, ih = self.map_img.width(), self.map_img.height()
            k = min(area.width() / iw, area.height() / ih)
            ox, oy = area.center().x() - iw * k / 2, area.center().y() - ih * k / 2
            target = QRectF(ox, oy, iw * k, ih * k)

            def to_px(x, z):
                px, py = self.track_map.to_map(x, z)
                return QPointF(ox + px * k, oy + py * k)
            return to_px, target
        pts = list(self.trail) + [(c["x"], c["z"]) for c in self.cars]
        if not pts:
            return None, None
        xs, zs = [p[0] for p in pts], [p[1] for p in pts]
        w, h = max(max(xs) - min(xs), 50.0), max(max(zs) - min(zs), 50.0)
        k = min(area.width() / w, area.height() / h)
        cx, cz = (max(xs) + min(xs)) / 2, (max(zs) + min(zs)) / 2

        def to_px(x, z):
            return QPointF(area.center().x() + (x - cx) * k, area.center().y() + (z - cz) * k)
        return to_px, None

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.fillRect(self.rect(), QColor(C["panel2"]))
        area = QRectF(self.rect()).adjusted(12, 12, -12, -12)
        to_px, target = self._mapper(area)
        self._screen = []
        if to_px is None:
            p.setPen(QColor(C["dim"]))
            p.setFont(paint_font(9, QFont.Weight.Normal))
            p.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter | Qt.TextFlag.TextWordWrap,
                       "La pista compare qui\nappena l'auto si muove")
            p.end()
            return
        if target is not None:
            p.setOpacity(0.85)
            p.drawImage(target, self.map_img)
            p.setOpacity(1.0)
        elif len(self.trail) > 1:
            path = QPainterPath(to_px(*self.trail[0]))
            for x, z in list(self.trail)[1:]:
                path.lineTo(to_px(x, z))
            p.setPen(QPen(QColor(C["border"]), 7, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap,
                          Qt.PenJoinStyle.RoundJoin))
            p.drawPath(path)
            p.setPen(QPen(QColor(C["dim"]), 2))
            p.drawPath(path)
        # avversari prima, la tua auto sopra
        for c in sorted(self.cars, key=lambda c: c["me"]):
            pt = to_px(c["x"], c["z"])
            self._screen.append((c["idx"], pt))
            r = 7.0 if c["me"] else 5.5
            if c.get("ring"):
                p.setPen(QPen(QColor(c["ring"]), 2.5))
                p.setBrush(Qt.BrushStyle.NoBrush)
                p.drawEllipse(pt, r + 4, r + 4)
            p.setPen(QPen(QColor("#0b0d10"), 1.5))
            p.setBrush(QColor(C["accent"] if c["me"] else "#d7dbe3"))
            p.drawEllipse(pt, r, r)
            if c.get("label"):
                p.setPen(QColor(C["text"]))
                p.setFont(paint_font(7.5))
                p.drawText(QRectF(pt.x() + r + 2, pt.y() - 8, 40, 16), Qt.AlignmentFlag.AlignVCenter, c["label"])
        p.end()

    def mousePressEvent(self, e):
        pos = e.position()
        near = min(self._screen, key=lambda it: (it[1].x() - pos.x()) ** 2 + (it[1].y() - pos.y()) ** 2,
                   default=None)
        if near is not None and (near[1].x() - pos.x()) ** 2 + (near[1].y() - pos.y()) ** 2 < 15 ** 2:
            self.car_clicked.emit(near[0])
