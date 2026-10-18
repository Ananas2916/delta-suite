"""Schema dell'auto vista dall'alto: danni per zona, gomme, freni, sospensioni (pagina Onboard)."""

from __future__ import annotations

from PyQt6.QtCore import QRectF, Qt
from PyQt6.QtGui import QColor, QFont, QPainter, QPainterPath, QPen
from PyQt6.QtWidgets import QWidget

from hub_core.analysis import car_status as cs
from ui.theme import C
from ui.widgets import paint_font, temp_color

LEVEL_COLORS = {cs.OK: C["green"], cs.WARN: C["yellow"], cs.CRIT: C["red"]}
DAMAGE_COLORS = ("#3a414f", "#f1c40f", "#ff9f43", "#ff4d4d")


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
        p.setFont(paint_font(7.5, QFont.Weight.DemiBold))
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
        p.setFont(paint_font(7.5, QFont.Weight.Normal))
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
            lines = [(f"{s.tyre_core_temp[i]:.0f}°", paint_font(13), col.name()),
                     (f"{s.tyre_pressure[i]:.1f} psi", paint_font(8.5, QFont.Weight.Normal), C["red"] if flat else C["text"]),
                     (f"usura {s.tyre_wear[i]:.1f}%", paint_font(8.5, QFont.Weight.Normal),
                      C["red"] if s.tyre_wear[i] < cs.WEAR_CRIT else C["yellow"] if s.tyre_wear[i] < cs.WEAR_WARN
                      else C["text"]),
                     (f"freno {s.brake_temp[i]:.0f}°", paint_font(8.5, QFont.Weight.Normal),
                      C["red"] if s.brake_temp[i] >= cs.BRAKE_WARN else C["dim"]),
                     (f"sosp. {f * 100:.0f}%", paint_font(8, QFont.Weight.Normal), C["dim"])]
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
