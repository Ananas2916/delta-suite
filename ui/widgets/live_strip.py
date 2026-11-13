"""Live strip on the live views: position, lap and delta, gaps ahead and behind with the trend, fuel, battery."""

from __future__ import annotations

from PyQt6.QtWidgets import QHBoxLayout, QLabel, QSizePolicy, QVBoxLayout, QWidget

from ui.theme import C
from ui.widgets import Card

KIND_COLORS = {"good": "green", "bad": "red", "warn": "yellow"}


class StripTile(Card):
    def __init__(self, big: bool = False):
        super().__init__()
        lay = QVBoxLayout(self)
        lay.setContentsMargins(12, 8, 12, 8)
        lay.setSpacing(1)
        self.title = QLabel()
        self.title.setStyleSheet(f"color: {C['dim']}; font-size: 7.5pt; letter-spacing: 1px;")
        self.value = QLabel("–")
        size = 30 if big else 17
        family = C["title_font"] if big else "Consolas"
        self._style = f"font-family: '{family}'; font-size: {size}pt; font-weight: {800 if big else 600};"
        self.value.setStyleSheet(self._style)
        self.sub = QLabel()
        self.sub.setStyleSheet(f"color: {C['dim']}; font-size: 8pt;")
        lay.addWidget(self.title)
        lay.addWidget(self.value)
        if not big:
            lay.addWidget(self.sub)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

    def set(self, title: str, value: str, sub: str = "", sub_kind: str = ""):
        if self.title.text() != title.upper():
            self.title.setText(title.upper())
        if self.value.text() != value:
            self.value.setText(value)
        if self.sub.text() != sub:
            self.sub.setText(sub)
        col = C[KIND_COLORS[sub_kind]] if sub_kind in KIND_COLORS else C["dim"]
        style = f"color: {col}; font-size: 8pt;"
        if self.sub.styleSheet() != style:
            self.sub.setStyleSheet(style)


class LiveStrip(QWidget):
    def __init__(self):
        super().__init__()
        lay = QHBoxLayout(self)
        lay.setContentsMargins(14, 10, 14, 0)
        lay.setSpacing(8)
        self.pos = StripTile(big=True)
        self.pos.setFixedWidth(110)
        self.lap, self.ahead, self.behind, self.fuel, self.battery = (StripTile() for _ in range(5))
        for t in (self.pos, self.lap, self.ahead, self.behind, self.fuel, self.battery):
            lay.addWidget(t)

    def update_from(self, v: dict, titles: dict[str, str]):
        self.pos.set(titles["pos"], v["pos"])
        self.lap.set(v["lap_title"], v["lap_time"], v["delta"], v["delta_kind"])
        self.ahead.set(v["ahead_title"], v["ahead"], v["ahead_sub"])
        self.behind.set(v["behind_title"], v["behind"], v["behind_sub"])
        self.fuel.set(titles["fuel"], v["fuel"], v["fuel_sub"], v["fuel_kind"])
        self.battery.setVisible(v["battery"] is not None)
        if v["battery"] is not None:
            self.battery.set(titles["battery"], v["battery"], v["battery_sub"])
