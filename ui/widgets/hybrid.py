"""Hybrid card: battery, deploy or charge, lap energy, ERS map. Hidden if the car is not a hybrid."""

from __future__ import annotations

from PyQt6.QtCore import QRectF, Qt
from PyQt6.QtGui import QColor, QPainter
from PyQt6.QtWidgets import QHBoxLayout, QVBoxLayout, QWidget

from hub_core.analysis import car_status as cs
from ui.theme import C
from ui.widgets import Card, label


def battery_color(charge: float) -> str:
    return C["red"] if charge < cs.BATTERY_WARN else C["yellow"] if charge < 0.4 else C["green"]


def state_color(h: cs.HybridState) -> str:
    return C["green"] if h.deploying else C["blue"] if h.charging else C["dim"]


class MeterBar(QWidget):
    """Horizontal bar filled from the left (0..1)."""

    def __init__(self, height: int = 12):
        super().__init__()
        self.value, self.color = 0.0, QColor(C["green"])
        self.setFixedHeight(height)
        self.setMinimumWidth(60)

    def set(self, value: float, color: str) -> None:
        value = max(0.0, min(1.0, value))
        if abs(value - self.value) > 0.002 or QColor(color) != self.color:
            self.value, self.color = value, QColor(color)
            self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        p.setPen(QColor(C["border"]))
        p.setBrush(QColor(C["panel2"]))
        p.drawRoundedRect(r, 3, 3)
        if self.value > 0:
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(self.color)
            p.drawRoundedRect(QRectF(r.left() + 1.5, r.top() + 1.5, (r.width() - 3) * self.value, r.height() - 3), 2, 2)
        p.end()


class HybridCard(Card):
    def __init__(self, title: str = "HYBRID"):
        super().__init__()
        lay = QVBoxLayout(self)
        lay.setContentsMargins(12, 8, 12, 10)
        lay.setSpacing(4)
        head = QHBoxLayout()
        head.addWidget(label(title, "dim"))
        head.addStretch()
        self.state = label("")
        head.addWidget(self.state)
        lay.addLayout(head)
        self.charge = label("--%")
        lay.addWidget(self.charge)
        self.battery = MeterBar(14)
        lay.addWidget(self.battery)
        self.lap = label("", "dim")
        lay.addWidget(self.lap)
        self.lap_bar = MeterBar(8)
        lay.addWidget(self.lap_bar)
        self.modes = label("", "dim")      # no word wrap: inside QScrollArea it makes the page taller
        lay.addWidget(self.modes)
        self.hide()

    def update_from(self, s, info: dict | None) -> None:
        h = cs.hybrid_state(s, info) if s is not None else None
        self.setVisible(h is not None)
        if h is None:
            return
        col = battery_color(h.charge)
        self.charge.setText(f"Battery {h.charge * 100:.0f}%")
        self.charge.setStyleSheet(f"font-size: 16pt; font-weight: 700; color: {col};")
        self.battery.set(h.charge, col)
        self.state.setText(h.mode_text)
        self.state.setStyleSheet(f"font-weight: 700; color: {state_color(h)};")
        if h.lap_limit_kj > 0:
            left = h.lap_left_kj
            self.lap.setText(f"Lap {h.lap_used_kj:.0f} / {h.lap_limit_kj:.0f} kJ")
            self.lap_bar.set(h.lap_used_fraction or 0.0, C["red"] if left is not None and left <= 0.5 else C["blue"])
            self.lap_bar.show()
        else:
            self.lap.setText(f"Lap {h.lap_used_kj:.0f} kJ")
            self.lap_bar.hide()
        mode = f"{h.power_mode}/{h.power_modes}" if h.power_modes else f"{h.power_mode}"
        self.modes.setText(f"Map {mode} · recovery {h.recovery}\n"
                           f"MGU-H → {'battery' if h.heat_to_battery else 'engine'}")
