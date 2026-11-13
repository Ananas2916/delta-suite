"""Strategy plans side by side: a coloured bar per stint and the time against the best plan."""

from __future__ import annotations

from PyQt6.QtCore import QRectF
from PyQt6.QtGui import QColor, QPainter
from PyQt6.QtWidgets import QGridLayout, QLabel, QSizePolicy, QWidget

from hub_core.analysis.race_strategy import StrategyPlan
from hub_core.i18n import tr
from ui.theme import C

STINT_COLORS = ("yellow", "text", "red", "blue")


def plan_name(p: StrategyPlan, laps_done: int) -> str:
    stops = len(p.stints) - 1
    if stops == 0:
        return tr("No stop")
    laps = [laps_done + sum(p.stints[:i + 1]) for i in range(stops)]
    if stops == 1:
        return tr("1 stop · lap {n}", n=laps[0])
    return tr("{k} stops · laps {laps}", k=stops, laps=", ".join(str(n) for n in laps))


class StintBar(QWidget):
    def __init__(self, stints: list[int], dim: bool):
        super().__init__()
        self.stints, self.dim = stints, dim
        self.setMinimumHeight(18)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        total = sum(self.stints) or 1
        x, gap = 0.0, 2.0
        w = self.width() - gap * (len(self.stints) - 1)
        p.setOpacity(0.4 if self.dim else 1.0)
        for i, n in enumerate(self.stints):
            sw = w * n / total
            p.setBrush(QColor(C[STINT_COLORS[i % len(STINT_COLORS)]]))
            p.setPen(QColor(0, 0, 0, 0))
            p.drawRoundedRect(QRectF(x, 2, sw, self.height() - 4), 3, 3)
            x += sw + gap
        p.end()


class PlansView(QWidget):
    def __init__(self):
        super().__init__()
        self.grid = QGridLayout(self)
        self.grid.setContentsMargins(0, 0, 0, 0)
        self.grid.setHorizontalSpacing(10)
        self.grid.setColumnStretch(1, 1)
        self._key = None

    def set_plans(self, plans: list[StrategyPlan], laps_done: int):
        key = [(p.stints, round(p.delta_s, 1), p.feasible) for p in plans], laps_done
        if key == self._key:
            return
        self._key = key
        while self.grid.count():
            w = self.grid.takeAt(0).widget()
            if w is not None:
                w.deleteLater()
        if not plans:
            self.grid.addWidget(QLabel(tr("Plans appear after 3 laps in the stint, with the race length known.")), 0, 0)
            return
        for row, p in enumerate(plans):
            best = row == 0 and p.feasible
            name = QLabel(plan_name(p, laps_done))
            name.setStyleSheet("font-weight: 700;" if best else "")
            delta = QLabel(tr("chosen") if best else (f"+{p.delta_s:.1f} s" if p.feasible else tr("not enough fuel")))
            delta.setStyleSheet(f"font-family: Consolas; color: {C['green'] if best else C['red'] if not p.feasible else C['dim']};")
            self.grid.addWidget(name, row, 0)
            self.grid.addWidget(StintBar(p.stints, not p.feasible), row, 1)
            self.grid.addWidget(delta, row, 2)
