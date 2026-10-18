"""Modulo 1b: Onboard live — fino a 4 onboard insieme con grafica TV, GPS della pista e stato della vettura."""

from __future__ import annotations

import time
from collections import deque

from PyQt6.QtCore import QPointF, QRectF, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QColor, QFont, QImage, QLinearGradient, QPainter, QPainterPath, QPen
from PyQt6.QtWidgets import (
    QAbstractItemView, QComboBox, QGridLayout, QHBoxLayout, QHeaderView, QPushButton, QSizePolicy, QSlider,
    QSplitter, QTableWidget, QTabWidget, QVBoxLayout, QWidget,
)

from hub_core import car_status as cs
from hub_core.model import ACStatus, gear_label
from hub_core.csp_bridge import find_ac_root
from hub_core.onboard_feed import (
    DEFAULT_EXPOSURE, DEFAULT_TONEMAP, QUALITIES, SECONDARY_QUALITY, VIEWS, Frame, OnboardFeed, ViewRequest,
    camera_menu,
)
from hub_core.race_strategy import fmt_ms, fuel_per_lap
from hub_core.timing import fmt_gap
from hub_core.track_map import TrackMap, find_track_map
from ui.hub_state import SOURCE_AC
from ui.theme import C
from ui.widgets import Card, label, table_item, temp_color

STALE_S = 2.0          # senza fotogrammi nuovi da tanto: il video non è più in diretta
LEVEL_COLORS = {cs.OK: C["green"], cs.WARN: C["yellow"], cs.CRIT: C["red"]}
DAMAGE_COLORS = ("#3a414f", "#f1c40f", "#ff9f43", "#ff4d4d")
VIEW_COLORS = ("#ffffff", C["blue"], C["yellow"], C["purple"])   # riquadro principale, poi secondari


def frame_image(f: Frame) -> QImage:
    if f.kind == "jpg":
        return QImage.fromData(f.data, "JPG")
    fmt = QImage.Format.Format_RGBX8888 if f.kind == "rgba" else QImage.Format.Format_RGB32
    return QImage(f.data, f.width, f.height, f.stride, fmt).copy()   # copia: i byte non restano vivi


def _font(size: float, weight=QFont.Weight.Bold) -> QFont:
    f = QFont("Segoe UI")
    f.setPointSizeF(size)
    f.setWeight(weight)
    return f


class OnboardView(QWidget):
    """Fotogramma onboard (o segnaposto) con sopra la grafica stile diretta TV."""

    def __init__(self):
        super().__init__()
        self.image: QImage | None = None
        self.live = False
        self.placeholder = ""
        self.hud: dict = {}
        self.setMinimumSize(360, 203)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

    def set_frame(self, img: QImage | None, live: bool):
        self.image, self.live = img, live
        self.update()

    def set_hud(self, hud: dict, placeholder: str):
        self.hud, self.placeholder = hud, placeholder
        self.update()

    def _video_rect(self) -> QRectF:
        r = QRectF(self.rect())
        ar = 16 / 9
        if self.image is not None and not self.image.isNull() and self.image.height():
            ar = self.image.width() / self.image.height()
        w = min(r.width(), r.height() * ar)
        h = w / ar
        return QRectF(r.center().x() - w / 2, r.center().y() - h / 2, w, h)

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        p.fillRect(self.rect(), QColor("#000000"))
        vr = self._video_rect()
        if self.image is not None and not self.image.isNull():
            p.drawImage(vr, self.image)
            if not self.live:
                p.fillRect(vr, QColor(0, 0, 0, 140))
        else:
            g = QLinearGradient(vr.topLeft(), vr.bottomLeft())
            g.setColorAt(0, QColor("#141922"))
            g.setColorAt(1, QColor("#07090c"))
            p.fillRect(vr, g)
        if self.placeholder:
            p.setPen(QColor(C["dim"]))
            p.setFont(_font(11, QFont.Weight.Normal))
            p.drawText(vr.adjusted(40, 0, -40, -vr.height() * 0.2), Qt.AlignmentFlag.AlignCenter |
                       Qt.TextFlag.TextWordWrap, self.placeholder)
        if self.hud:
            self._paint_hud(p, vr)
        p.end()

    # ------------------------------------------------------------------ grafica
    def _box(self, p: QPainter, r: QRectF, alpha: int = 170):
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(10, 12, 16, alpha))
        p.drawRoundedRect(r, 6, 6)

    def _paint_hud(self, p: QPainter, vr: QRectF):
        h = self.hud
        k = max(0.7, min(1.6, vr.width() / 960))      # la grafica scala con il video
        m = 14 * k

        # in alto a sinistra: diretta, pilota, telecamera
        tl = QRectF(vr.left() + m, vr.top() + m, 300 * k, 54 * k)
        self._box(p, tl)
        p.setBrush(QColor(C["accent"] if self.live else C["dim"]))
        p.drawEllipse(QPointF(tl.left() + 14 * k, tl.top() + 17 * k), 5 * k, 5 * k)
        p.setPen(QColor("white"))
        p.setFont(_font(9 * k))
        p.drawText(QRectF(tl.left() + 26 * k, tl.top() + 6 * k, tl.width(), 22 * k), Qt.AlignmentFlag.AlignVCenter,
                   ("ONBOARD LIVE" if self.live else "ONBOARD") + (f"  ·  {h['camera']}" if h.get("camera") else ""))
        p.setFont(_font(11 * k))
        p.drawText(QRectF(tl.left() + 12 * k, tl.top() + 27 * k, tl.width() - 20 * k, 22 * k),
                   Qt.AlignmentFlag.AlignVCenter, h.get("title", ""))

        # in alto a destra: giro e tempi
        rows = h.get("times", [])
        if rows:
            tr = QRectF(vr.right() - m - 230 * k, vr.top() + m, 230 * k, (12 + 21 * len(rows)) * k)
            self._box(p, tr)
            for i, (name, value, color) in enumerate(rows):
                y = tr.top() + (6 + 21 * i) * k
                p.setPen(QColor(C["dim"]))
                p.setFont(_font(8.5 * k, QFont.Weight.DemiBold))
                p.drawText(QRectF(tr.left() + 12 * k, y, 90 * k, 21 * k), Qt.AlignmentFlag.AlignVCenter, name)
                p.setPen(QColor(color or "white"))
                p.setFont(_font(11 * k))
                p.drawText(QRectF(tr.left(), y, tr.width() - 12 * k, 21 * k),
                           Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight, value)

        # in basso a sinistra: velocità, marcia, giri motore
        if "speed" in h:
            bl = QRectF(vr.left() + m, vr.bottom() - m - 92 * k, 250 * k, 92 * k)
            self._box(p, bl)
            p.setPen(QColor("white"))
            p.setFont(_font(30 * k, QFont.Weight.Black))
            p.drawText(QRectF(bl.left() + 12 * k, bl.top() + 4 * k, 130 * k, 56 * k),
                       Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight, f"{h['speed']:.0f}")
            p.setPen(QColor(C["dim"]))
            p.setFont(_font(8 * k))
            p.drawText(QRectF(bl.left() + 146 * k, bl.top() + 30 * k, 40 * k, 20 * k), Qt.AlignmentFlag.AlignLeft,
                       "KM/H")
            if "gear" in h:
                p.setPen(QColor(C["accent"] if h.get("shift") else "white"))
                p.setFont(_font(30 * k, QFont.Weight.Black))
                p.drawText(QRectF(bl.right() - 62 * k, bl.top() + 4 * k, 50 * k, 56 * k),
                           Qt.AlignmentFlag.AlignCenter, h["gear"])
            if "rpm_frac" in h:
                bar = QRectF(bl.left() + 12 * k, bl.bottom() - 26 * k, bl.width() - 24 * k, 10 * k)
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(QColor(255, 255, 255, 40))
                p.drawRoundedRect(bar, 3, 3)
                f = max(0.0, min(1.0, h["rpm_frac"]))
                p.setBrush(QColor(C["accent"] if f > 0.95 else C["yellow"] if f > 0.85 else C["green"]))
                p.drawRoundedRect(QRectF(bar.left(), bar.top(), bar.width() * f, bar.height()), 3, 3)
                p.setPen(QColor(C["dim"]))
                p.setFont(_font(7.5 * k, QFont.Weight.DemiBold))
                p.drawText(QRectF(bar.left(), bar.bottom() + 1 * k, bar.width(), 14 * k), Qt.AlignmentFlag.AlignRight,
                           f"{h.get('rpm', 0)} RPM")

        # in basso a destra: pedali e sterzo
        if "gas" in h:
            br = QRectF(vr.right() - m - 150 * k, vr.bottom() - m - 92 * k, 150 * k, 92 * k)
            self._box(p, br)
            for i, (key, color) in enumerate((("brake", C["red"]), ("gas", C["green"]))):
                bar = QRectF(br.left() + (14 + 24 * i) * k, br.top() + 12 * k, 14 * k, br.height() - 24 * k)
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(QColor(255, 255, 255, 40))
                p.drawRoundedRect(bar, 3, 3)
                v = max(0.0, min(1.0, h[key]))
                p.setBrush(QColor(color))
                p.drawRoundedRect(QRectF(bar.left(), bar.bottom() - bar.height() * v, bar.width(), bar.height() * v),
                                  3, 3)
            c = QPointF(br.right() - 46 * k, br.center().y())
            rad = 30 * k
            p.setPen(QPen(QColor(255, 255, 255, 60), 4 * k))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawEllipse(c, rad, rad)
            p.save()
            p.translate(c)
            p.rotate(h.get("steer", 0.0) * 180)
            p.setPen(QPen(QColor(C["yellow"]), 4 * k))
            p.drawLine(QPointF(0, -rad), QPointF(0, -rad + 12 * k))
            p.restore()

        # al centro in basso: l'avviso più grave
        alert = h.get("alert")
        if alert is not None:
            lvl, text = alert
            p.setFont(_font(10 * k))
            w = p.fontMetrics().horizontalAdvance(text) + 36 * k
            ar = QRectF(vr.center().x() - w / 2, vr.bottom() - m - 34 * k, w, 30 * k)
            if "speed" in h and ar.left() < vr.left() + m + 260 * k:
                ar.moveTop(ar.top() - 104 * k)          # video stretto: sopra i riquadri in basso
            col = QColor(LEVEL_COLORS[lvl])
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(col.red(), col.green(), col.blue(), 215))
            p.drawRoundedRect(ar, 6, 6)
            p.setPen(QColor("#111111"))
            p.drawText(ar, Qt.AlignmentFlag.AlignCenter, text)


class CarStatusView(QWidget):
    """Vettura vista dall'alto: danni per zona, gomme, freni, sospensioni, sporco."""

    def __init__(self):
        super().__init__()
        self.s = None
        self.info: dict = {}
        self.setMinimumSize(270, 300)

    def set_sample(self, s, info: dict):
        self.s, self.info = s, info or {}
        self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        W, H = self.width(), self.height()
        bw, bh = W * 0.34, H * 0.80
        body = QRectF((W - bw) / 2, (H - bh) / 2 + 6, bw, bh)
        s = self.s
        dmg_on = cs.damage_enabled(self.info)

        # carrozzeria: muso in alto, cinque zone di danno
        p.setPen(QColor(C["dim"]))
        p.setFont(_font(7.5, QFont.Weight.DemiBold))
        p.drawText(QRectF(body.left(), 0, bw, (H - bh) / 2 + 4), Qt.AlignmentFlag.AlignCenter, "▲ MUSO")
        zones = {
            "anteriore": QRectF(body.left() + bw * 0.12, body.top(), bw * 0.76, bh * 0.16),
            "posteriore": QRectF(body.left() + bw * 0.08, body.bottom() - bh * 0.14, bw * 0.84, bh * 0.14),
            "sinistra": QRectF(body.left(), body.top() + bh * 0.18, bw * 0.2, bh * 0.64),
            "destra": QRectF(body.right() - bw * 0.2, body.top() + bh * 0.18, bw * 0.2, bh * 0.64),
            "centro": QRectF(body.left() + bw * 0.24, body.top() + bh * 0.2, bw * 0.52, bh * 0.6),
        }
        outline = QPainterPath()
        outline.addRoundedRect(body, bw * 0.3, bw * 0.3)
        p.setPen(QPen(QColor(C["border"]), 2))
        p.setBrush(QColor(C["panel2"]))
        p.drawPath(outline)
        p.save()
        p.setClipPath(outline)
        for i, (zone, r) in enumerate(zones.items()):
            v = s.car_damage[i] if s is not None else 0.0
            lvl = cs.damage_level(v) if dmg_on else 0
            col = QColor(DAMAGE_COLORS[lvl])
            col.setAlpha(230 if lvl else 120)
            p.setPen(QPen(QColor(C["bg"]), 2))
            p.setBrush(col)
            p.drawRoundedRect(r, 5, 5)
        p.restore()
        # abitacolo
        p.setPen(QPen(QColor(C["bg"]), 2))
        p.setBrush(QColor(C["bg"]))
        cock = QRectF(body.center().x() - bw * 0.16, body.top() + bh * 0.4, bw * 0.32, bh * 0.2)
        p.drawRoundedRect(cock, 8, 8)
        p.setPen(QColor(C["dim"]))
        p.setFont(_font(7.5, QFont.Weight.Normal))
        p.drawText(QRectF(body.left(), body.top() + bh * 0.62, bw, 34), Qt.AlignmentFlag.AlignCenter |
                   Qt.TextFlag.TextWordWrap, "danni\ndisattivati" if not dmg_on else "nessun danno"
                   if s is None or not any(cs.damage_level(v) for v in s.car_damage) else "")

        # gomme ai quattro angoli
        tw, th = bw * 0.3, bh * 0.17
        susp = cs.suspension_fraction(s, self.info) if s is not None else (0.0,) * 4
        for i in range(4):
            left, front = i % 2 == 0, i < 2
            cx = body.left() if left else body.right()
            cy = body.top() + bh * (0.2 if front else 0.78)
            tyre = QRectF(cx - tw / 2, cy - th / 2, tw, th)
            col = temp_color(s.tyre_core_temp[i]) if s is not None else QColor(C["panel2"])
            flat = s is not None and i in cs.punctured(s.tyre_pressure)
            p.setPen(QPen(QColor(C["red"] if flat else "#0b0d10"), 3 if flat else 1.5))
            p.setBrush(col)
            p.drawRoundedRect(tyre, 6, 6)
            if s is not None and s.tyre_dirt[i] >= cs.DIRT_WARN:
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(QColor(110, 80, 40, 150))
                p.drawRoundedRect(tyre.adjusted(3, th * 0.55, -3, -3), 4, 4)
            # corsa sospensione: barra sul lato interno della gomma
            sb = QRectF(tyre.right() + 4 if left else tyre.left() - 10, tyre.top(), 6, th)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(C["border"]))
            p.drawRoundedRect(sb, 2, 2)
            f = susp[i]
            p.setBrush(QColor(C["red"] if f >= 0.97 else C["blue"]))
            p.drawRoundedRect(QRectF(sb.left(), sb.bottom() - th * f, sb.width(), th * f), 2, 2)

            if s is None:
                continue
            lines = [(f"{s.tyre_core_temp[i]:.0f}°", _font(13), col.name()),
                     (f"{s.tyre_pressure[i]:.1f} psi", _font(8.5, QFont.Weight.Normal), C["red"] if flat else C["text"]),
                     (f"usura {s.tyre_wear[i]:.1f}%", _font(8.5, QFont.Weight.Normal),
                      C["red"] if s.tyre_wear[i] < cs.WEAR_CRIT else C["yellow"] if s.tyre_wear[i] < cs.WEAR_WARN
                      else C["text"]),
                     (f"freno {s.brake_temp[i]:.0f}°", _font(8.5, QFont.Weight.Normal),
                      C["red"] if s.brake_temp[i] >= cs.BRAKE_WARN else C["dim"]),
                     (f"sosp. {f * 100:.0f}%", _font(8, QFont.Weight.Normal), C["dim"])]
            tx_w = (W - bw) / 2 - tw / 2 - 18
            x = 4 if left else body.right() + tw / 2 + 14
            y = cy - 44
            align = (Qt.AlignmentFlag.AlignRight if left else Qt.AlignmentFlag.AlignLeft) | \
                Qt.AlignmentFlag.AlignVCenter
            for text, font, color in lines:
                p.setFont(font)
                p.setPen(QColor(color))
                hgt = 22 if font.pointSizeF() > 10 else 16
                p.drawText(QRectF(x, y, tx_w, hgt), align, text)
                y += hgt
        p.end()


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
            p.setFont(_font(9, QFont.Weight.Normal))
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
                p.setFont(_font(7.5))
                p.drawText(QRectF(pt.x() + r + 2, pt.y() - 8, 40, 16), Qt.AlignmentFlag.AlignVCenter, c["label"])
        p.end()

    def mousePressEvent(self, e):
        pos = e.position()
        near = min(self._screen, key=lambda it: (it[1].x() - pos.x()) ** 2 + (it[1].y() - pos.y()) ** 2,
                   default=None)
        if near is not None and (near[1].x() - pos.x()) ** 2 + (near[1].y() - pos.y()) ** 2 < 15 ** 2:
            self.car_clicked.emit(near[0])


class TimingTable(QTableWidget):
    """Classifica compatta come le torri dei tempi in TV: posizione, pilota, distacco, ultimo giro.
    Un segno colorato a sinistra indica le auto nei riquadri; clic su una riga → riquadro principale."""

    car_clicked = pyqtSignal(int)

    def __init__(self):
        super().__init__(0, 4)
        self.setHorizontalHeaderLabels(["P", "Pilota", "Distacco", "Ultimo"])
        self.verticalHeader().setVisible(False)
        self.verticalHeader().setDefaultSectionSize(22)
        self.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self.setShowGrid(False)
        self.setStyleSheet("QTableWidget { font-size: 9pt; }")
        hh = self.horizontalHeader()
        for col, mode in enumerate((QHeaderView.ResizeMode.ResizeToContents, QHeaderView.ResizeMode.Stretch,
                                    QHeaderView.ResizeMode.ResizeToContents,
                                    QHeaderView.ResizeMode.ResizeToContents)):
            hh.setSectionResizeMode(col, mode)
        self._indices: list[int] = []
        self.cellClicked.connect(lambda row, _col: self.car_clicked.emit(self._indices[row])
                                 if row < len(self._indices) else None)

    def fill(self, rows: list[tuple[int, str, str, str, str, bool, str | None]]):
        """rows: (indice auto, posizione, pilota, distacco, ultimo, sei tu, colore del riquadro o None)."""
        self._indices = [r[0] for r in rows]
        self.setRowCount(len(rows))
        for i, (_idx, pos, driver, gap, last, me, ring) in enumerate(rows):
            cells = [table_item(pos, bold=True), table_item(driver, C["accent"] if me else None, me),
                     table_item(gap), table_item(last)]
            cells[1].setTextAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
            if ring:
                cells[0].setBackground(QColor(ring))
                cells[0].setForeground(QColor("#111111"))
            for col, cell in enumerate(cells):
                self.setItem(i, col, cell)


class ViewPanel(QWidget):
    """Un riquadro onboard: scelta di auto e telecamera sopra, video con grafica sotto."""

    changed = pyqtSignal()
    make_main = pyqtSignal(int)

    def __init__(self, index: int):
        super().__init__()
        self.index = index
        self.img: QImage | None = None
        self.frame_t = 0.0
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(4)
        bar = QHBoxLayout()
        bar.setSpacing(6)
        dot = label("●")
        dot.setStyleSheet(f"color: {VIEW_COLORS[index]}; font-size: 12pt;")
        dot.setToolTip("Colore del riquadro, uguale al cerchio dell'auto sul GPS")
        self.car = QComboBox()
        self.car.addItem("La mia auto", -1)
        self.camera = QComboBox()
        for combo in (self.car, self.camera):     # stringibili: nomi lunghi non allargano la pagina
            combo.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
            combo.setMinimumContentsLength(8 if index else 11)
            combo.currentIndexChanged.connect(lambda _: self.changed.emit())
        bar.addWidget(dot)
        bar.addWidget(self.car, 1)
        bar.addWidget(self.camera, 1)
        if index:
            up = QPushButton("▲")
            up.setToolTip("Metti questo onboard nel riquadro principale")
            up.setFixedWidth(34)
            up.clicked.connect(lambda: self.make_main.emit(self.index))
            bar.addWidget(up)
        lay.addLayout(bar)
        self.view = OnboardView()
        if index:
            self.view.setMinimumSize(180, 101)
        lay.addWidget(self.view, 1)

    def car_index(self) -> int:
        d = self.car.currentData()
        return -1 if d is None else d

    def camera_index(self) -> int:
        d = self.camera.currentData()
        return 0 if d is None else d

    def fill_cameras(self, menu: list[tuple[str, int | None]], selected: int):
        self.camera.blockSignals(True)
        self.camera.clear()
        for text, idx in menu:
            self.camera.addItem(text if idx is not None else f"— {text} —", idx)
            if idx is None:     # intestazione di gruppo: non selezionabile
                self.camera.model().item(self.camera.count() - 1).setEnabled(False)
        row = self.camera.findData(selected)
        self.camera.setCurrentIndex(row if row >= 0 else 1)
        self.camera.blockSignals(False)

    def fill_cars(self, others: list[tuple[int, str]], selected: int):
        self.car.blockSignals(True)
        self.car.clear()
        self.car.addItem("La mia auto", -1)
        for idx, text in others:
            self.car.addItem(text, idx)
        self.car.setCurrentIndex(max(0, self.car.findData(selected)))
        self.car.blockSignals(False)

    def select(self, car: int, camera: int):
        self.car.blockSignals(True)
        self.camera.blockSignals(True)
        self.car.setCurrentIndex(max(0, self.car.findData(car)))
        row = self.camera.findData(camera)
        self.camera.setCurrentIndex(row if row >= 0 else 1)
        self.car.blockSignals(False)
        self.camera.blockSignals(False)


class OnboardPage(QWidget):
    LAYOUTS = ["1 onboard", "1 + 1", "1 + 2", "1 + 3"]
    DEFAULT_CAMERAS = [0, 7, 3, 2]      # T-cam, inseguimento, ruota ant. sx, posteriore

    def __init__(self, hub):
        super().__init__()
        self.hub = hub
        self.feed = OnboardFeed()
        self._beat_t = 0.0
        self._ui_t = 0.0
        self._f6: list[str] = [n for n in hub.setting("onboard/f6_names", "", str).split("|") if n]
        self._cars_key = None

        root = QVBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 16)
        root.setSpacing(10)

        head = QHBoxLayout()
        head.addWidget(label("Onboard live", "h1"))
        head.addStretch()
        self.video_btn = QPushButton()
        self.video_btn.setCheckable(True)
        self.video_btn.setChecked(hub.setting("onboard/video", True, bool))
        self._video_label()
        self.video_btn.toggled.connect(self._on_video_toggled)
        head.addWidget(self.video_btn)
        root.addLayout(head)

        controls = QHBoxLayout()
        self.layout_box = QComboBox()
        self.layout_box.addItems(self.LAYOUTS)
        self.layout_box.setCurrentIndex(max(0, min(3, hub.setting("onboard/layout", 0, int))))
        self.layout_box.setToolTip("Quanti onboard insieme: ognuno è una vista in più resa da AC (costa FPS)")
        self.quality = QComboBox()
        for name, *_ in QUALITIES:
            self.quality.addItem(name)
        self.quality.setCurrentIndex(max(0, min(len(QUALITIES) - 1, hub.setting("onboard/quality", 1, int))))
        self.quality.setToolTip("Qualità del riquadro principale; gli altri vanno a 640×360 o 480×270")
        self.quality.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.quality.setMinimumContentsLength(22)
        self.exposure = QSlider(Qt.Orientation.Horizontal)
        self.exposure.setRange(30, 400)
        self.exposure.setFixedWidth(110)
        self.exposure.setValue(round(100 * hub.setting("onboard/exposure", DEFAULT_EXPOSURE, float)))
        self.exposure.setToolTip("Esposizione del video: la vista in più non ha il post-processing del gioco")
        for w in (label("Riquadri", "dim"), self.layout_box, label("Qualità", "dim"), self.quality,
                  label("Luminosità", "dim"), self.exposure):
            controls.addWidget(w)
        controls.addStretch()
        root.addLayout(controls)

        self.status = label("", "dim")
        root.addWidget(self.status)

        body = QHBoxLayout()
        body.setSpacing(12)
        self.grid = QGridLayout()
        self.grid.setSpacing(10)
        self.panels = [ViewPanel(k) for k in range(VIEWS)]
        menu = camera_menu(self._f6)
        for k, panel in enumerate(self.panels):
            panel.fill_cameras(menu, hub.setting(f"onboard/view{k}/camera", self.DEFAULT_CAMERAS[k], int))
            panel.changed.connect(lambda k=k: self._on_panel_changed(k))
            panel.make_main.connect(self._make_main)
            if k == 0:
                self.grid.addWidget(panel, 0, 0, 3, 1)
            else:
                self.grid.addWidget(panel, k - 1, 1)
        body.addLayout(self.grid, 1)

        side = QSplitter(Qt.Orientation.Vertical)
        side.setFixedWidth(300)
        side.setChildrenCollapsible(False)
        # sopra: classifica e stato vettura in schede; sotto: la mappa, grande
        self.side_tabs = QTabWidget()
        self.timing = TimingTable()
        self.timing.setToolTip("Clic su un'auto per vederla nel riquadro principale")
        self.timing.car_clicked.connect(self._on_gps_click)
        self.side_tabs.addTab(self.timing, "Classifica")
        status_page = QWidget()
        sl = QVBoxLayout(status_page)
        sl.setContentsMargins(8, 8, 8, 8)
        self.car_view = CarStatusView()
        sl.addWidget(self.car_view, 1)
        self.info = label("", "dim")
        self.info.setWordWrap(True)
        sl.addWidget(self.info)
        self.alerts = label("")
        self.alerts.setWordWrap(True)
        self.alerts.setTextFormat(Qt.TextFormat.RichText)
        self.alerts.setAlignment(Qt.AlignmentFlag.AlignTop)
        sl.addWidget(self.alerts)
        self.side_tabs.addTab(status_page, "Stato vettura")
        self.side_tabs.setCurrentIndex(max(0, min(1, hub.setting("onboard/side_tab", 0, int))))
        self.side_tabs.currentChanged.connect(lambda i: hub.settings.setValue("onboard/side_tab", i))
        side.addWidget(self.side_tabs)
        gps_card = Card()
        gl = QVBoxLayout(gps_card)
        gl.setContentsMargins(12, 10, 12, 12)
        gl.addWidget(label("GPS · POSIZIONE IN PISTA", "dim"))
        self.gps = GPSView()
        self.gps.setToolTip("Clic su un'auto per vederla nel riquadro principale")
        self.gps.car_clicked.connect(self._on_gps_click)
        gl.addWidget(self.gps, 1)
        side.addWidget(gps_card)
        side.setSizes([400, 380])
        body.addWidget(side)
        root.addLayout(body, 1)

        self.layout_box.currentIndexChanged.connect(self._on_layout)
        self.quality.currentIndexChanged.connect(lambda i: (hub.settings.setValue("onboard/quality", i),
                                                            self._push_request()))
        self.exposure.valueChanged.connect(lambda v: (hub.settings.setValue("onboard/exposure", v / 100),
                                                      self._push_request()))
        hub.standings_changed.connect(self._fill_cars)
        hub.session_changed.connect(self._on_session)
        hub.running_changed.connect(lambda _: self._refresh())
        self._restore_cars()
        self._on_layout(self.layout_box.currentIndex(), save=False)

        self.timer = QTimer(self)
        self.timer.timeout.connect(self._tick)
        self.timer.start(33)

    # ------------------------------------------------------------- controlli
    @property
    def _n_views(self) -> int:
        return self.layout_box.currentIndex() + 1

    def _video_label(self):
        self.video_btn.setText("Video acceso" if self.video_btn.isChecked() else "Video spento")

    def _on_video_toggled(self, on: bool):
        self.hub.settings.setValue("onboard/video", on)
        self._video_label()
        self._push_request()

    def _on_layout(self, i: int, save: bool = True):
        if save:
            self.hub.settings.setValue("onboard/layout", i)
        n = i + 1
        for k, panel in enumerate(self.panels):
            panel.setVisible(k < n)
        self.grid.setColumnStretch(0, 2)
        self.grid.setColumnStretch(1, 1 if n > 1 else 0)
        self._push_request()

    def _on_panel_changed(self, k: int):
        panel = self.panels[k]
        self.hub.settings.setValue(f"onboard/view{k}/camera", panel.camera_index())
        self.hub.settings.setValue(f"onboard/view{k}/car", panel.car_index())
        panel.img = None
        self._push_request()

    def _make_main(self, k: int):
        """Scambia l'onboard k con quello principale."""
        a, b = self.panels[0], self.panels[k]
        sel_a, sel_b = (a.car_index(), a.camera_index()), (b.car_index(), b.camera_index())
        a.select(*sel_b)
        b.select(*sel_a)
        a.img = b.img = None
        for i in (0, k):
            self._on_panel_changed(i)

    def _on_gps_click(self, idx: int):
        main = self.panels[0]
        main.select(-1 if idx == 0 else idx, main.camera_index())
        self._on_panel_changed(0)

    def _restore_cars(self):
        for k, panel in enumerate(self.panels):
            panel.select(self.hub.setting(f"onboard/view{k}/car", -1, int), panel.camera_index())

    def _fill_cars(self, rows):
        others = [(r.index, f"P{r.pos}  {r.driver or 'auto ' + str(r.index)}") for r in rows if not r.is_player]
        if others == self._cars_key:
            return
        self._cars_key = others
        for k, panel in enumerate(self.panels):
            panel.fill_cars(others, self.hub.setting(f"onboard/view{k}/car", -1, int))

    def _on_session(self, info: dict):
        self._fill_cars([])
        self.gps.clear_trail()
        tmap = None
        try:
            tmap = find_track_map(find_ac_root(), info.get("track_id", ""), info.get("track_config", ""))
        except OSError:
            pass
        self.gps.set_map(tmap)

    def _sync_cameras(self):
        """Aggiorna gli elenchi quando l'app trova (o cambia) le telecamere F6 dell'auto."""
        f6 = self.feed.f6_cameras()
        if not f6 or f6 == self._f6:
            return
        self._f6 = f6
        self.hub.settings.setValue("onboard/f6_names", "|".join(f6))
        menu = camera_menu(f6)
        for panel in self.panels:
            panel.fill_cameras(menu, panel.camera_index())

    @property
    def _ac_live(self) -> bool:
        w = self.hub.worker
        return self.hub.running and w is not None and w.source == SOURCE_AC

    def _push_request(self) -> bool:
        if not self._ac_live:
            return False
        n = self._n_views
        on = self.video_btn.isChecked() and self.isVisible()
        _name, w, h, fps = QUALITIES[self.quality.currentIndex()]
        _sname, sw, sh, sfps = SECONDARY_QUALITY if n == 2 else QUALITIES[0]
        views = []
        for k, panel in enumerate(self.panels):
            size = (w, h, fps) if k == 0 else (sw, sh, sfps)
            views.append(ViewRequest(on and k < n, panel.camera_index(), panel.car_index(), *size))
        self._beat_t = time.monotonic()
        return self.feed.request(views, self.exposure.value() / 100, DEFAULT_TONEMAP)

    def hideEvent(self, e):
        self.feed.disconnect()          # niente rendering in AC mentre la pagina non si vede
        super().hideEvent(e)

    # ------------------------------------------------------------- aggiornamento
    def _tick(self):
        if not self.isVisible():
            return
        now = time.monotonic()
        if self._ac_live and self.video_btn.isChecked():
            if now - self._beat_t > 0.5:
                self._push_request()
            for k in range(self._n_views):
                frame = self.feed.new_frame(k)
                if frame is not None:
                    img = frame_image(frame)
                    if not img.isNull():
                        self.panels[k].img, self.panels[k].frame_t = img, now
        elif self.feed.connected:
            self.feed.disconnect()
        if now - self._ui_t >= 0.066:       # grafica, GPS e stato a 15 Hz, il video a ogni fotogramma
            self._ui_t = now
            self._refresh()

    def _placeholder(self, k: int) -> str:
        if not self.hub.running:
            return "Acquisizione ferma: avvia la telemetria da Assetto Corsa." if k == 0 else ""
        if not self._ac_live:
            return ("Il video onboard arriva solo da Assetto Corsa. In demo e replay restano grafica, GPS e "
                    "stato vettura." if k == 0 else "Solo con Assetto Corsa")
        if not self.video_btn.isChecked():
            return "Video spento: in AC non si rendono le viste in più (più FPS in gioco)."
        if not self.feed.connected:
            return ("App CSP Delta Suite Bridge non collegata o da aggiornare: aggiornala da Box & Assetto."
                    if k == 0 else "App CSP non collegata")
        inf = self.feed.info(k)
        if inf is not None and inf.status.startswith("errore"):
            return f"L'app CSP non riesce a rendere l'onboard: {inf.status}"
        if self.panels[k].img is None:
            return "In attesa del primo fotogramma…"
        return ""

    def _refresh(self):
        self._sync_cameras()
        now = time.monotonic()
        s = self.hub.last_sample
        info = self.hub.session_info
        laps = self.hub.laps
        fpl = fuel_per_lap(laps) if laps else None
        alerts = cs.car_alerts(s, info, fpl) if s is not None and s.status == ACStatus.LIVE else []
        live_any = False
        for k in range(self._n_views):
            panel = self.panels[k]
            if not self._ac_live:
                panel.img = None
            live = panel.img is not None and now - panel.frame_t < STALE_S
            live_any |= live
            panel.view.set_frame(panel.img, live)
            panel.view.set_hud(self._hud(k, s, alerts), self._placeholder(k) if not live else "")
        self.car_view.set_sample(s, info)
        self._fill_side(s, alerts, fpl)
        self._fill_gps(s)
        self._fill_timing(s)
        self._fill_status(live_any)

    def _entry(self, idx: int):
        b = self.hub.bridge_state
        return next((c for c in (b.cars if b else []) if c.index == idx), None)

    def _hud(self, k: int, s, alerts) -> dict:
        panel = self.panels[k]
        idx, cam = panel.car_index(), panel.camera.currentText()
        if k > 0:       # riquadri piccoli: chi, quale telecamera, distacco e ultimo giro
            if idx < 0:
                who = self.hub.session_info.get("player") or "La mia auto"
                row = next((r for r in self.hub.standings_rows if r.is_player), None)
                if s is not None:
                    who = f"P{s.position}  {who}"
                last = s.last_lap_ms if s is not None else 0
            else:
                entry = self._entry(idx)
                row = next((r for r in self.hub.standings_rows if r.index == idx), None)
                who = f"P{entry.race_pos}  {entry.driver or 'auto ' + str(idx)}" if entry else panel.car.currentText()
                last = entry.last_lap_ms if entry else 0
            times = [("DISTACCO", fmt_gap(row), None)] if row is not None else []
            times.append(("ULTIMO", fmt_ms(last), None))
            return {"title": who, "camera": cam, "times": times}
        if idx >= 0:
            entry = self._entry(idx)
            row = next((r for r in self.hub.standings_rows if r.index == idx), None)
            if entry is None:
                return {"title": panel.car.currentText(), "camera": cam}
            times = [("POSIZIONE", f"P{entry.race_pos}", None), ("GIRO", str(entry.lap_count + 1), None),
                     ("TEMPO", fmt_ms(entry.lap_time_ms), None), ("ULTIMO", fmt_ms(entry.last_lap_ms), None),
                     ("MIGLIORE", fmt_ms(entry.best_lap_ms), C["purple"])]
            if row is not None and row.interval_s is not None:
                times.append(("INTERVAL", f"+{row.interval_s:.1f}", None))
            return {"title": f"{entry.driver or 'Auto ' + str(idx)}  ·  {entry.model}", "camera": cam,
                    "speed": entry.speed_kmh, "times": times}
        if s is None:
            return {}
        info = self.hub.session_info
        max_rpm = max(1000, int(info.get("max_rpm") or 9000))
        player = info.get("player") or "Tu"
        hud = {
            "title": f"{player}  ·  {info.get('car', '')}", "camera": cam,
            "speed": s.speed_kmh, "gear": gear_label(s.gear), "rpm": s.rpm, "rpm_frac": s.rpm / max_rpm,
            "shift": s.rpm > 0.95 * max_rpm, "gas": s.gas, "brake": s.brake, "steer": s.steer_angle,
            "times": [("POSIZIONE", f"P{s.position}", None), ("GIRO", f"{s.completed_laps + 1}"
                                                             + ("  PIT" if s.is_in_pit else ""), None),
                      ("TEMPO", fmt_ms(s.lap_time_ms), None), ("ULTIMO", fmt_ms(s.last_lap_ms), None),
                      ("MIGLIORE", fmt_ms(s.best_lap_ms), C["purple"])],
        }
        if alerts:
            hud["alert"] = (alerts[0].level, alerts[0].text)
        return hud

    def _view_rings(self) -> dict[int, str]:
        """Colore del riquadro per ogni auto inquadrata (0 = la tua)."""
        rings = {}
        for k in range(self._n_views):
            idx = self.panels[k].car_index()
            rings.setdefault(0 if idx < 0 else idx, VIEW_COLORS[k])
        return rings

    def _fill_timing(self, s):
        rings = self._view_rings()
        rows = [(r.index, str(r.pos), r.driver or f"auto {r.index}", fmt_gap(r),
                 "BOX" if r.in_pit else fmt_ms(r.last_ms), r.is_player, rings.get(r.index))
                for r in self.hub.standings_rows]
        if not rows and s is not None and s.status == ACStatus.LIVE:     # senza app CSP o in demo: solo tu
            rows = [(0, str(s.position), self.hub.session_info.get("player") or "Tu", "-",
                     fmt_ms(s.last_lap_ms), True, rings.get(0))]
        self.timing.fill(rows)

    def _fill_gps(self, s):
        if s is not None and s.status == ACStatus.LIVE:
            self.gps.add_trail(s.car_x, s.car_z)
        rings = self._view_rings()
        positions = self.feed.car_positions() if self._ac_live and self.feed.connected else {}
        if not positions and s is not None and s.status == ACStatus.LIVE:
            positions = {0: (s.car_x, s.car_z)}
        b = self.hub.bridge_state
        race_pos = {c.index: c.race_pos for c in b.cars} if b else {}
        connected = {c.index for c in b.cars if c.connected} if b else set()
        cars = []
        for idx, (x, z) in positions.items():
            if idx and connected and idx not in connected:
                continue
            pos = race_pos.get(idx) or (s.position if idx == 0 and s is not None else 0)
            cars.append({"idx": idx, "x": x, "z": z, "me": idx == 0, "ring": rings.get(idx),
                         "label": f"{pos}" if pos else ""})
        self.gps.set_cars(cars)

    def _fill_side(self, s, alerts, fpl):
        if s is None:
            self.info.setText("Nessun dato: avvia l'acquisizione.")
            self.alerts.setText("")
            return
        b = self.hub.bridge_state
        aids = f"ABS {b.abs_mode}/{b.abs_modes}  ·  TC {b.tc_mode}/{b.tc_modes}" if b else \
            f"ABS {s.abs:.1f}  ·  TC {s.tc:.1f}"
        fuel = f"carburante {s.fuel:.1f} L" + (f" (~{s.fuel / fpl:.1f} giri)" if fpl else "")
        self.info.setText(
            f"{fuel}<br>{aids}  ·  bias {s.brake_bias * 100:.1f}%  ·  freno motore {s.engine_brake}<br>"
            f"altezza da terra ant. {s.ride_height[0] * 1000:.0f} mm  ·  post. {s.ride_height[1] * 1000:.0f} mm"
            + ("<br>limitatore pit inserito" if s.pit_limiter else ""))
        if not alerts:
            self.alerts.setText(f"<span style='color:{C['green']}'>●</span>  Tutto in ordine")
            return
        self.alerts.setText("<br>".join(f"<span style='color:{LEVEL_COLORS[a.level]}'>●</span>  {a.text}"
                                        for a in alerts[:6]))

    def _fill_status(self, live_video: bool):
        parts = []
        if live_video:
            inf = self.feed.info()
            if inf is not None:
                parts.append(f"<span style='color:{C['green']}'>●</span>  Video in diretta · "
                             f"{self._n_views} {'riquadro' if self._n_views == 1 else 'riquadri'} · "
                             f"AC a {inf.game_fps:.0f} FPS")
        elif self._ac_live and self.video_btn.isChecked() and self.feed.connected:
            parts.append(f"<span style='color:{C['yellow']}'>●</span>  Video non in diretta")
        if self.feed.shared_error:
            parts.append("texture condivisa non disponibile, si usa la via più lenta")
        if any(self.panels[k].car_index() >= 0 for k in range(self._n_views)):
            parts.append("lo stato vettura è sempre quello della tua auto")
        self.status.setText("  ·  ".join(parts) if parts else
                            "Viste in più rese da AC tramite l'app CSP; GPS dalla posizione delle auto; danni, "
                            "gomme, freni e sospensioni dalla shared memory.")
