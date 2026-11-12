"""Strategy & Timing (fuel, pit window, tyre degradation, sectors)."""

from __future__ import annotations

import numpy as np
import pyqtgraph as pg
from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtWidgets import (
    QCheckBox, QComboBox, QFormLayout, QGridLayout, QGroupBox, QHBoxLayout, QSpinBox, QVBoxLayout, QWidget,
)

from hub_core.analysis import race_strategy as rs
from ui.theme import C
from ui.widgets import SessionPicker, ValueTile, dspin, label, make_plot, readonly_table, table_item


class StrategyPage(QWidget):
    def __init__(self, hub):
        super().__init__()
        self.hub = hub
        root = QHBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 16)

        # --- input
        left = QVBoxLayout()
        left.addWidget(label("Strategy & Timing", "h1"))
        self.picker = SessionPicker(hub)
        left.addWidget(self.picker)

        race = QGroupBox("Race")
        f = QFormLayout(race)
        self.race_type = QComboBox()
        self.race_type.addItems(["Lap count", "Timed"])
        self.race_laps = QSpinBox()
        self.race_laps.setRange(1, 999)
        self.race_laps.setValue(30)
        self.time_left = dspin(0, 1440, 60, 1, 0, "min")
        self.laps_done = QSpinBox()
        self.laps_done.setRange(0, 999)
        f.addRow("Type", self.race_type)
        f.addRow("Total laps", self.race_laps)
        f.addRow("Time left", self.time_left)
        f.addRow("Laps completed", self.laps_done)
        left.addWidget(race)

        car = QGroupBox("Car and pits")
        f2 = QFormLayout(car)
        self.fuel_now = dspin(0, 200, 40, 0.5, 1, "L")
        self.tank = dspin(1, 200, 70, 1, 0, "L")
        self.per_lap = dspin(0.1, 20, 2.5, 0.05, 2, "L/lap")
        self.auto_fuel = QCheckBox("Fuel use computed from laps")
        self.auto_fuel.setChecked(True)
        self.margin = dspin(0, 5, 1, 0.25, 2, "laps")
        self.pit_loss = dspin(5, 120, 25, 0.5, 1, "s")
        self.fuel_corr = dspin(0, 0.2, 0.025, 0.005, 3, "s/L")
        self.live = QCheckBox("Take race, laps and fuel from the session")
        self.live.setToolTip("Race type, total laps, time left, laps completed and fuel come from AC; "
                             "untick to try your own numbers (what if)")
        self.live.setChecked(True)
        f2.addRow("Fuel on board", self.fuel_now)
        f2.addRow("Tank", self.tank)
        f2.addRow("Fuel use", self.per_lap)
        f2.addRow("", self.auto_fuel)
        f2.addRow("Margin", self.margin)
        f2.addRow("Pit-lane loss", self.pit_loss)
        f2.addRow("Fuel weight effect", self.fuel_corr)
        f2.addRow(self.live)
        left.addWidget(car)
        left.addStretch()
        lw = QWidget()
        lw.setLayout(left)
        lw.setFixedWidth(370)
        root.addWidget(lw)

        # --- results
        right = QVBoxLayout()
        tiles = QGridLayout()
        self.t_needed = ValueTile("Fuel to finish", "--")
        self.t_add = ValueTile("To add", "--")
        self.t_range = ValueTile("Current range", "--")
        self.t_window = ValueTile("Pit window (lap)", "--")
        self.t_deg = ValueTile("Tyre degradation", "--")
        self.t_pit = ValueTile("Optimal tyre stop", "--")
        self.t_theo = ValueTile("Ideal lap", "--")
        self.t_cliff = ValueTile("Expected drop-off", "--")
        for i, t in enumerate((self.t_needed, self.t_add, self.t_range, self.t_window,
                               self.t_deg, self.t_pit, self.t_theo, self.t_cliff)):
            tiles.addWidget(t, i // 4, i % 4)
        right.addLayout(tiles)

        self.plot = make_plot("Stint lap times and forecast (fuel corrected)", "s", "stint lap")
        self.plot.addLegend(offset=(-10, 10))
        right.addWidget(self.plot, 1)

        self.table = readonly_table(["Lap", "Time", "S1", "S2", "S3", "Fuel used", "Valid"])
        self.table.setMaximumHeight(220)
        right.addWidget(self.table)
        note = label("Gaps and intervals to rivals are on the Pit & Setup page and the Overview: AC's shared memory "
                     "only exposes your car, the rivals come from the CSP app.", "dim")
        note.setWordWrap(True)
        right.addWidget(note)
        root.addLayout(right, 1)

        for w in (self.race_type, self.picker):
            w.currentIndexChanged.connect(self.recompute)
        for w in (self.race_laps, self.laps_done):
            w.valueChanged.connect(self.recompute)
        for w in (self.time_left, self.fuel_now, self.tank, self.per_lap, self.margin, self.pit_loss, self.fuel_corr):
            w.valueChanged.connect(self.recompute)
        self.auto_fuel.toggled.connect(self.recompute)
        self.live.toggled.connect(self._on_live_toggled)
        self.picker.currentIndexChanged.connect(lambda _: self._live_update())
        hub.lap_completed.connect(lambda _: self.recompute())
        hub.session_changed.connect(self._on_session)

        self.timer = QTimer(self)
        self.timer.timeout.connect(self._live_update)
        self.timer.start(1000)
        self.recompute()

    def _on_session(self, info):
        if info.get("max_fuel"):
            self.tank.setValue(float(info["max_fuel"]))

    def _following_session(self) -> bool:
        return self.live.isChecked() and self.picker.currentData() is None

    def _on_live_toggled(self, _on: bool):
        self._live_update()
        self.recompute()

    def _live_update(self):
        """With "from the session" ticked, the race inputs mirror AC: the fields become read-only."""
        following = self._following_session()
        self.race_type.setEnabled(not following)
        for w in (self.race_laps, self.time_left, self.laps_done, self.fuel_now):
            w.setReadOnly(following)
        s = self.hub.last_sample
        if not following or s is None:
            return
        b = self.hub.bridge_state
        prog = rs.race_progress_for(s, b.cars if b else [], self.hub.is_race,
                                    self.hub.session_info.get("extra_lap", False))
        timed = s.session_laps <= 0 and s.session_time_left > 0
        widgets = (self.race_type, self.race_laps, self.time_left, self.laps_done, self.fuel_now)
        for w in widgets:
            w.blockSignals(True)
        self.race_type.setCurrentIndex(1 if timed else 0)
        if s.session_laps > 0:
            self.race_laps.setValue(s.session_laps)
        if s.session_time_left > 0:
            self.time_left.setValue(s.session_time_left / 60000)
        self.laps_done.setValue(max(0, prog.lap - 1) if prog is not None else s.completed_laps)
        self.fuel_now.setValue(s.fuel)
        for w in widgets:
            w.blockSignals(False)
        self.recompute()

    def recompute(self):
        info, laps, _ = self.picker.selected()
        timed = self.race_type.currentIndex() == 1
        self.race_laps.setEnabled(not timed)
        self.time_left.setEnabled(timed)

        if self.auto_fuel.isChecked():
            fpl = rs.fuel_per_lap(laps)
            self.per_lap.setEnabled(False)
            if fpl:
                self.per_lap.blockSignals(True)
                self.per_lap.setValue(fpl)
                self.per_lap.blockSignals(False)
        else:
            self.per_lap.setEnabled(True)
        per_lap = self.per_lap.value()

        valid = [l for l in laps if l.valid]
        avg = sum(l.lap_time_ms for l in valid[-5:]) / len(valid[-5:]) / 1000 if valid else None
        remaining = rs.race_laps_remaining(None if timed else self.race_laps.value(), self.laps_done.value(),
                                           self.time_left.value() * 60 if timed else None, avg)
        plan = rs.fuel_plan(self.fuel_now.value(), per_lap, remaining, self.tank.value(), self.laps_done.value(),
                            self.margin.value())
        self.t_needed.set(f"{plan.fuel_needed:.1f} L", None)
        self.t_needed.title.setText(f"FUEL TO FINISH ({remaining} LAPS)")
        self.t_add.set(f"{plan.fuel_to_add:.1f} L" + (f" · {plan.stops_needed} stops" if plan.stops_needed > 1 else ""),
                       C["yellow"] if plan.fuel_to_add > 0 else C["green"])
        self.t_range.set(f"{plan.laps_on_current_fuel:.1f} laps")
        self.t_window.set(f"{plan.pit_window[0]} – {plan.pit_window[1]}" if plan.pit_window else "no stop",
                          C["accent"] if plan.pit_window and plan.pit_window[1] - self.laps_done.value() <= 2 else None)

        theo = rs.theoretical_best(laps)
        self.t_theo.set(rs.fmt_ms(theo), C["purple"])

        self.plot.clear()
        stint = rs.current_stint(laps)
        fc = rs.forecast_degradation(stint, fuel_s_per_l=self.fuel_corr.value())
        if fc:
            self.t_deg.set(f"{fc.deg_per_lap:+.3f} s/lap", C["red"] if fc.deg_per_lap > 0.15 else None)
            self.t_cliff.set(f"stint lap {fc.cliff_lap}" if fc.cliff_lap else "beyond horizon")
            opt = rs.optimal_pit_lap(fc, remaining, self.pit_loss.value())
            self.t_pit.set(f"stint lap {opt}" if opt else "not worth it")
            self.plot.plot(fc.stint_laps, fc.lap_times, pen=None, symbol="o", symbolBrush=C["blue"], name="measured")
            xs = np.linspace(1, fc.forecast_laps[-1], 200)
            self.plot.plot(xs, np.poly1d(fc.coeffs)(xs), pen=pg.mkPen(C["dim"], style=Qt.PenStyle.DashLine),
                           name="model")
            self.plot.plot(fc.forecast_laps, fc.forecast_times, pen=pg.mkPen(C["accent"], width=2), symbol="t",
                           symbolBrush=C["accent"], name="forecast")
        else:
            self.t_deg.set("needs ≥3 laps")
            self.t_cliff.set("--")
            self.t_pit.set("--")

        bs = rs.best_sectors(laps)
        best = min((l.lap_time_ms for l in valid), default=None)
        self.table.setRowCount(len(laps))
        for row, lap in enumerate(reversed(laps)):
            self.table.setItem(row, 0, table_item(str(lap.lap_no)))
            self.table.setItem(row, 1, table_item(rs.fmt_ms(lap.lap_time_ms),
                                                  C["purple"] if lap.valid and lap.lap_time_ms == best else None))
            for i in range(3):
                v = lap.sectors_ms[i] if i < len(lap.sectors_ms) else None
                self.table.setItem(row, 2 + i, table_item(rs.fmt_ms(v), C["purple"] if v and v == bs[i] else None))
            self.table.setItem(row, 5, table_item(f"{lap.fuel_used:.2f} L"))
            self.table.setItem(row, 6, table_item("yes" if lap.valid else "no", None if lap.valid else C["red"]))
