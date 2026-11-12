"""Top-down car diagram: damage per zone, tyres, brakes, suspension (Onboard page)."""

from __future__ import annotations

from PyQt6.QtCore import QRectF, Qt
from PyQt6.QtGui import QColor, QFont, QFontMetricsF, QPainter, QPainterPath, QPen
from PyQt6.QtWidgets import QWidget

from hub_core.analysis import car_status as cs
from ui.theme import C
from ui.widgets import paint_font, temp_color
from hub_core.i18n import tr

LEVEL_COLORS = {cs.OK: C["green"], cs.WARN: C["yellow"], cs.CRIT: C["red"]}
DAMAGE_COLORS = ("#3a414f", "#f1c40f", "#ff9f43", "#ff4d4d")

MIN_FONT_PT = 6.5


def fit_font(p: QPainter, font: QFont, text: str, width: float) -> None:
    """Set the font on the painter, smaller if needed for the text to fit the width (narrow column
    of the Onboard page). Measure on the painter's device, not on the screen."""
    p.setFont(font)
    w = QFontMetricsF(p.font(), p.device()).horizontalAdvance(text)
    if w > width > 0:
        font.setPointSizeF(max(MIN_FONT_PT, font.pointSizeF() * width / w * 0.97))
        p.setFont(font)


class CarStatusView(QWidget):
    """Car seen from above: damage per zone, tyres, brakes, suspension, dirt."""

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

        # bodywork: nose at the top, five damage zones
        p.setPen(QColor(C["dim"]))
        p.setFont(paint_font(7.5, QFont.Weight.DemiBold))
        p.drawText(QRectF(body.left(), 0, bw, (H - bh) / 2 + 4), Qt.AlignmentFlag.AlignCenter, tr("▲ NOSE"))
        zones = {
            "front": QRectF(body.left() + bw * 0.12, body.top(), bw * 0.76, bh * 0.16),
            "rear": QRectF(body.left() + bw * 0.08, body.bottom() - bh * 0.14, bw * 0.84, bh * 0.14),
            "left": QRectF(body.left(), body.top() + bh * 0.18, bw * 0.2, bh * 0.64),
            "right": QRectF(body.right() - bw * 0.2, body.top() + bh * 0.18, bw * 0.2, bh * 0.64),
            "centre": QRectF(body.left() + bw * 0.24, body.top() + bh * 0.2, bw * 0.52, bh * 0.6),
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
        # cockpit
        p.setPen(QPen(QColor(C["bg"]), 2))
        p.setBrush(QColor(C["bg"]))
        cock = QRectF(body.center().x() - bw * 0.16, body.top() + bh * 0.4, bw * 0.32, bh * 0.2)
        p.drawRoundedRect(cock, 8, 8)
        note = tr("damage disabled") if not dmg_on else tr("no damage") \
            if s is None or not any(cs.damage_level(v) for v in s.car_damage) else ""
        if note:
            p.setPen(QColor(C["dim"]))
            inner = bw - bw * 0.3 - 6       # between the tyres, which overlap the bodywork by half
            fit_font(p, paint_font(7.5, QFont.Weight.Normal), note, inner)
            p.drawText(QRectF(body.left(), body.top() + bh * 0.29, bw, bh * 0.1), Qt.AlignmentFlag.AlignCenter, note)

        # tyres at the four corners
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
            # suspension travel: bar on the inner side of the tyre
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
                     (tr("wear {w}%", w=f"{s.tyre_wear[i]:.1f}"), paint_font(8.5, QFont.Weight.Normal),
                      C["red"] if s.tyre_wear[i] < cs.WEAR_CRIT else C["yellow"] if s.tyre_wear[i] < cs.WEAR_WARN
                      else C["text"]),
                     (tr("brake {t}°", t=f"{s.brake_temp[i]:.0f}"), paint_font(8.5, QFont.Weight.Normal),
                      C["red"] if s.brake_temp[i] >= cs.BRAKE_WARN else C["dim"]),
                     (tr("susp. {pct}%", pct=f"{f * 100:.0f}"), paint_font(8, QFont.Weight.Normal), C["dim"])]
            tx_w = (W - bw) / 2 - tw / 2 - 14
            x = 2 if left else body.right() + tw / 2 + 12
            y = cy - 44
            align = (Qt.AlignmentFlag.AlignRight if left else Qt.AlignmentFlag.AlignLeft) | \
                Qt.AlignmentFlag.AlignVCenter
            for text, font, color in lines:
                fit_font(p, font, text, tx_w)
                p.setPen(QColor(color))
                hgt = 22 if font.pointSizeF() > 10 else 16
                p.drawText(QRectF(x, y, tx_w, hgt), align, text)
                y += hgt
        p.end()
