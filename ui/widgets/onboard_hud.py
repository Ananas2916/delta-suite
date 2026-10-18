"""Grafica TV sopra il video onboard e conversione dei fotogrammi in immagini Qt."""

from __future__ import annotations

from PyQt6.QtCore import QPointF, QRectF, Qt
from PyQt6.QtGui import QColor, QFont, QImage, QLinearGradient, QPainter, QPen
from PyQt6.QtWidgets import QSizePolicy, QWidget

from hub_core.ac.onboard_feed import Frame
from ui.theme import C
from ui.widgets import paint_font
from ui.widgets.car_status import LEVEL_COLORS
from ui.widgets.hybrid import battery_color


def frame_image(f: Frame) -> QImage:
    if f.kind == "jpg":
        return QImage.fromData(f.data, "JPG")
    fmt = QImage.Format.Format_RGBX8888 if f.kind == "rgba" else QImage.Format.Format_RGB32
    return QImage(f.data, f.width, f.height, f.stride, fmt).copy()   # copia: i byte non restano vivi


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
            p.setFont(paint_font(11, QFont.Weight.Normal))
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
        p.setFont(paint_font(9 * k))
        p.drawText(QRectF(tl.left() + 26 * k, tl.top() + 6 * k, tl.width(), 22 * k), Qt.AlignmentFlag.AlignVCenter,
                   ("ONBOARD LIVE" if self.live else "ONBOARD") + (f"  ·  {h['camera']}" if h.get("camera") else ""))
        p.setFont(paint_font(11 * k))
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
                p.setFont(paint_font(8.5 * k, QFont.Weight.DemiBold))
                p.drawText(QRectF(tr.left() + 12 * k, y, 90 * k, 21 * k), Qt.AlignmentFlag.AlignVCenter, name)
                p.setPen(QColor(color or "white"))
                p.setFont(paint_font(11 * k))
                p.drawText(QRectF(tr.left(), y, tr.width() - 12 * k, 21 * k),
                           Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight, value)
            sectors = h.get("sectors") or []
            if sectors:                     # parziali sotto i tempi: striscia del colore e tempo
                n, gap = len(sectors), 4 * k
                sw = (tr.width() - gap * (n - 1)) / n
                for i, (name, text, color) in enumerate(sectors):
                    r = QRectF(tr.left() + i * (sw + gap), tr.bottom() + 4 * k, sw, 26 * k)
                    self._box(p, r)
                    p.setPen(Qt.PenStyle.NoPen)
                    p.setBrush(QColor(color))
                    p.drawRect(QRectF(r.left(), r.bottom() - 3 * k, r.width(), 3 * k))
                    p.setPen(QColor(C["dim"]))
                    p.setFont(paint_font(7 * k, QFont.Weight.DemiBold))
                    p.drawText(r.adjusted(6 * k, 0, 0, -3 * k), Qt.AlignmentFlag.AlignVCenter, name)
                    p.setPen(QColor("white"))
                    p.setFont(paint_font(8.5 * k))
                    p.drawText(r.adjusted(0, 0, -6 * k, -3 * k),
                               Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight, text)

        # in basso a sinistra: velocità, marcia, giri motore
        if "speed" in h:
            bl = QRectF(vr.left() + m, vr.bottom() - m - 92 * k, 250 * k, 92 * k)
            self._box(p, bl)
            p.setPen(QColor("white"))
            p.setFont(paint_font(30 * k, QFont.Weight.Black))
            p.drawText(QRectF(bl.left() + 12 * k, bl.top() + 4 * k, 130 * k, 56 * k),
                       Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight, f"{h['speed']:.0f}")
            p.setPen(QColor(C["dim"]))
            p.setFont(paint_font(8 * k))
            p.drawText(QRectF(bl.left() + 146 * k, bl.top() + 30 * k, 40 * k, 20 * k), Qt.AlignmentFlag.AlignLeft,
                       "KM/H")
            if "gear" in h:
                p.setPen(QColor(C["accent"] if h.get("shift") else "white"))
                p.setFont(paint_font(30 * k, QFont.Weight.Black))
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
                p.setFont(paint_font(7.5 * k, QFont.Weight.DemiBold))
                p.drawText(QRectF(bar.left(), bar.bottom() + 1 * k, bar.width(), 14 * k), Qt.AlignmentFlag.AlignRight,
                           f"{h.get('rpm', 0)} RPM")

        # in basso a destra: pedali, batteria delle ibride e sterzo
        if "gas" in h:
            bars = [("brake", C["red"]), ("gas", C["green"])]
            if "battery" in h:
                bars.append(("battery", battery_color(h["battery"])))
            bw = (150 + 24 * (len(bars) - 2)) * k
            br = QRectF(vr.right() - m - bw, vr.bottom() - m - 92 * k, bw, 92 * k)
            self._box(p, br)
            for i, (key, color) in enumerate(bars):
                bar = QRectF(br.left() + (14 + 24 * i) * k, br.top() + 12 * k, 14 * k, br.height() - 24 * k)
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(QColor(255, 255, 255, 40))
                p.drawRoundedRect(bar, 3, 3)
                v = max(0.0, min(1.0, h[key]))
                p.setBrush(QColor(color))
                p.drawRoundedRect(QRectF(bar.left(), bar.bottom() - bar.height() * v, bar.width(), bar.height() * v),
                                  3, 3)
                if key == "battery":    # fulmine sopra la barra: verde mentre spinge
                    p.setPen(QColor(C["green"] if h.get("battery_deploy") else C["dim"]))
                    p.setFont(paint_font(7 * k))
                    p.drawText(QRectF(bar.left() - 4 * k, br.top(), bar.width() + 8 * k, 12 * k),
                               Qt.AlignmentFlag.AlignCenter, "⚡")
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
            p.setFont(paint_font(10 * k))
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
