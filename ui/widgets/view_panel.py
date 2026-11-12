"""An onboard view: car and camera picker, ▲ to make it the main one, video with graphics (Onboard and
Overview pages)."""

from __future__ import annotations

from PyQt6.QtCore import pyqtSignal
from PyQt6.QtGui import QImage
from PyQt6.QtWidgets import QComboBox, QHBoxLayout, QPushButton, QVBoxLayout, QWidget

from ui.widgets.onboard_hud import OnboardView
from ui.theme import C
from ui.widgets import label

VIEW_COLORS = ("#ffffff", C["blue"], C["yellow"], C["purple"])   # main view, then secondary


class ViewPanel(QWidget):
    """An onboard view: car and camera picker on top, video with graphics below."""

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
        dot.setToolTip("View colour, same as the car's circle on the GPS")
        self.car = QComboBox()
        self.car.addItem("My car", -1)
        self.camera = QComboBox()
        for combo in (self.car, self.camera):     # shrinkable: long names do not widen the page
            combo.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
            combo.setMinimumContentsLength(8 if index else 11)
            combo.currentIndexChanged.connect(lambda _: self.changed.emit())
        bar.addWidget(dot)
        bar.addWidget(self.car, 1)
        bar.addWidget(self.camera, 1)
        if index:
            up = QPushButton("▲")
            up.setToolTip("Put this onboard in the main view")
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
            if idx is None:     # group header: not selectable
                self.camera.model().item(self.camera.count() - 1).setEnabled(False)
        row = self.camera.findData(selected)
        self.camera.setCurrentIndex(row if row >= 0 else 1)
        self.camera.blockSignals(False)

    def fill_cars(self, others: list[tuple[int, str]], selected: int):
        self.car.blockSignals(True)
        self.car.clear()
        self.car.addItem("My car", -1)
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
