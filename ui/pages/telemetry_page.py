"""Live telemetry (real-time dashboard)."""

from __future__ import annotations

from collections import deque

import numpy as np
import pyqtgraph as pg
from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtWidgets import (
    QCheckBox, QComboBox, QFileDialog, QHBoxLayout, QProgressBar, QPushButton, QSizePolicy, QSpinBox,
    QVBoxLayout, QWidget,
)

from hub_core.ac.recording import recordings_dir
from hub_core.analysis.race_strategy import best_sectors, fmt_ms
from hub_core.model import ACStatus, gear_label
from ui.race_view import sector_views
from ui.theme import C
from ui.widgets import Bar, Card, TyreGrid, ValueTile, label, make_plot, readonly_table, table_item
from ui.widgets.hybrid import HybridCard
from ui.widgets.sectors import LapTimeTile
from ui.workers import SOURCE_AC, SOURCE_DEMO, SOURCE_REPLAY

WINDOW_S = 20.0


class TelemetryPage(QWidget):
    def __init__(self, hub):
        super().__init__()
        self.hub = hub
        self._buf = {k: deque(maxlen=4000) for k in ("t", "speed", "gas", "brake", "lat", "lon")}
        self._dirty = False

        root = QVBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 16)
        root.setSpacing(12)

        # --- control bar
        bar = QHBoxLayout()
        # title on its own row: with the screen scaled to 150% title + controls did not fit
        root.addWidget(label("Live telemetry", "h1"))
        self.source = QComboBox()
        self.source.addItem("Assetto Corsa (shared memory)", SOURCE_AC)
        self.source.addItem("Demo (simulator)", SOURCE_DEMO)
        self.source.addItem("Replay a recorded session…", SOURCE_REPLAY)
        self.record = QCheckBox("Record session")
        self.record.setToolTip("Save AC's raw data to a .dsr file, to watch later as a replay")
        self.record.setChecked(hub.setting("record_sessions", True, bool))
        self.record.toggled.connect(lambda v: hub.settings.setValue("record_sessions", v))
        self.delta_ref = QCheckBox("Delta vs all-time best")
        self.delta_ref.setToolTip("Live delta against the fastest lap in the archive for this car and track, "
                                  "instead of this session's best")
        self.delta_ref.setChecked(hub.delta_vs_archive)
        self.delta_ref.toggled.connect(hub.set_delta_vs_archive)
        self.hz = QSpinBox()
        self.hz.setRange(10, 200)
        self.hz.setValue(60)
        self.hz.setSuffix(" Hz")
        self.demo_speed = QComboBox()
        for f in (1, 2, 5, 10, 30):
            self.demo_speed.addItem(f"{f}x", float(f))
        self.start_btn = QPushButton("Start acquisition")
        self.start_btn.setObjectName("primary")
        self.start_btn.clicked.connect(self._toggle)
        for w in (label("Source", "dim"), self.source, self.record, self.delta_ref, self.hz, label("Demo/replay speed", "dim"),
                  self.demo_speed, self.start_btn):
            bar.addWidget(w)
        bar.addStretch()
        root.addLayout(bar)

        self.status = label("Acquisition stopped", "dim")
        root.addWidget(self.status)

        # --- value tiles
        tiles = QHBoxLayout()
        self.t_speed = ValueTile("Speed", "0", 26)
        self.t_gear = ValueTile("Gear", "N", 26)
        self.t_rpm = ValueTile("RPM", "0", 20)
        self.rpm_bar = QProgressBar()
        self.rpm_bar.setRange(0, 9000)
        self.t_rpm.layout().addWidget(self.rpm_bar)
        self.t_lap = ValueTile("Lap", "-", 20)
        self.t_cur = LapTimeTile()
        self.t_last = ValueTile("Last", "--:--.---", 20)
        self.t_best = ValueTile("Best", "--:--.---", 20)
        self.t_fuel = ValueTile("Fuel", "-- L", 20)
        for t in (self.t_speed, self.t_gear, self.t_rpm, self.t_lap, self.t_cur, self.t_last, self.t_best, self.t_fuel):
            if t is not self.t_cur:     # same height as the time tile, which has the splits below
                t.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
            tiles.addWidget(t, 2 if t is self.t_cur else 1)
        root.addLayout(tiles)

        # --- middle row: driver inputs | plots | tyres + G-G
        mid = QHBoxLayout()
        pedals = Card()
        pl = QVBoxLayout(pedals)
        pl.addWidget(label("DRIVER INPUTS", "dim"))
        row = QHBoxLayout()
        self.b_gas = Bar("THR", C["green"])
        self.b_brake = Bar("BRK", C["red"])
        self.b_clutch = Bar("CLU", C["blue"])
        for b in (self.b_gas, self.b_brake, self.b_clutch):
            row.addWidget(b)
        pl.addLayout(row, 1)
        self.b_steer = Bar("STEERING", C["yellow"], centered=True)
        pl.addWidget(self.b_steer)
        self.aids = label("TC 0  ABS 0", "dim")
        pl.addWidget(self.aids)
        left = QVBoxLayout()
        left.addWidget(pedals, 1)
        self.hybrid = HybridCard()           # hybrids only
        left.addWidget(self.hybrid)
        for w in (pedals, self.hybrid):
            w.setFixedWidth(200)
        mid.addLayout(left)

        plots = QVBoxLayout()
        self.p_speed = make_plot("Speed (last 20 s)", "km/h")
        self.c_speed = self.p_speed.plot(pen=pg.mkPen(C["blue"], width=2))
        self.p_ped = make_plot("Throttle / Brake", "%")
        self.p_ped.setYRange(0, 100)
        self.c_gas = self.p_ped.plot(pen=pg.mkPen(C["green"], width=2))
        self.c_brake = self.p_ped.plot(pen=pg.mkPen(C["red"], width=2))
        self.p_ped.setXLink(self.p_speed)
        plots.addWidget(self.p_speed)
        plots.addWidget(self.p_ped)
        mid.addLayout(plots, 1)

        right = QVBoxLayout()
        self.tyres = TyreGrid()
        right.addWidget(self.tyres)
        self.p_gg = make_plot("G-G", "long. g", "lat. g")
        self.p_gg.setXRange(-3, 3)
        self.p_gg.setYRange(-3, 3)
        self.p_gg.setAspectLocked(True)
        for r in (1, 2, 3):
            circle = pg.QtWidgets.QGraphicsEllipseItem(-r, -r, 2 * r, 2 * r)
            circle.setPen(pg.mkPen(C["border"], style=Qt.PenStyle.DashLine))
            self.p_gg.addItem(circle)
        self.gg_trail = self.p_gg.plot(pen=None, symbol="o", symbolSize=4, symbolBrush=(61, 155, 255, 90),
                                       symbolPen=None)
        self.gg_dot = self.p_gg.plot(pen=None, symbol="o", symbolSize=12, symbolBrush=C["accent"])
        self.p_gg.setFixedSize(230, 230)
        right.addWidget(self.p_gg, alignment=Qt.AlignmentFlag.AlignHCenter)
        mid.addLayout(right)
        root.addLayout(mid, 1)

        # --- lap table
        self.table = readonly_table(["Lap", "Time", "S1", "S2", "S3", "Δ best", "Fuel L",
                                     "Tyre T (FL/FR/RL/RR)", "Valid"])
        self.table.setMaximumHeight(210)
        root.addWidget(self.table)

        hub.sample.connect(self._on_sample)
        hub.lap_completed.connect(lambda _: self._fill_table())
        hub.session_changed.connect(self._on_session)
        hub.status.connect(self._on_status)
        hub.running_changed.connect(self._on_running)

        self.timer = QTimer(self)
        self.timer.timeout.connect(self._refresh)
        self.timer.start(33)

    # ------------------------------------------------------------------
    def _toggle(self):
        if self.hub.running:
            self.hub.stop()
            return
        src = self.source.currentData()
        path = None
        if src == SOURCE_REPLAY:
            path, _ = QFileDialog.getOpenFileName(self, "Open recording", str(recordings_dir()),
                                                  "Delta Suite recordings (*.dsr)")
            if not path:
                return
        self.hub.start(src, self.hz.value(), self.demo_speed.currentData(), path,
                       record=src == SOURCE_AC and self.record.isChecked())

    def start_demo(self):
        self.source.setCurrentIndex(self.source.findData(SOURCE_DEMO))
        if not self.hub.running:
            self._toggle()

    def _on_running(self, running: bool):
        self.start_btn.setText("Stop acquisition" if running else "Start acquisition")
        for w in (self.source, self.hz, self.demo_speed, self.record):
            w.setEnabled(not running)

    def _on_status(self, text: str, ok: bool):
        dot = C["green"] if ok else C["yellow"] if self.hub.running else C["dim"]
        self.status.setText(f"<span style='color:{dot}'>●</span>  {text}")

    def _on_session(self, info: dict):
        self.rpm_bar.setRange(0, max(1000, int(info.get("max_rpm") or 9000)))
        for b in self._buf.values():
            b.clear()
        self._fill_table()

    def _on_sample(self, s):
        if s.status != ACStatus.LIVE:
            return
        b = self._buf
        b["t"].append(s.t)
        b["speed"].append(s.speed_kmh)
        b["gas"].append(s.gas * 100)
        b["brake"].append(s.brake * 100)
        b["lat"].append(s.acc_g[0])
        b["lon"].append(s.acc_g[2])
        self._dirty = True

    def _refresh(self):
        s = self.hub.last_sample
        if s is None or not self._dirty:
            return
        self._dirty = False
        self.t_speed.set(f"{s.speed_kmh:.0f}")
        self.t_gear.set(gear_label(s.gear), C["accent"] if s.rpm > 0.95 * self.rpm_bar.maximum() else None)
        self.t_rpm.set(f"{s.rpm}")
        self.rpm_bar.setValue(int(s.rpm))
        total = f"/{s.session_laps}" if self.hub.is_race and s.session_laps > 0 else ""
        self.t_lap.set(f"{s.completed_laps + 1}{total}" + (" PIT" if s.is_in_pit else ""))
        self.t_cur.set(s.lap_time_ms, self.hub.live_lap.delta_s, sector_views(self.hub, s))
        self.t_last.set(fmt_ms(s.last_lap_ms))
        self.t_best.set(fmt_ms(s.best_lap_ms), C["purple"])
        self.t_fuel.set(f"{s.fuel:.1f} L")
        self.b_gas.set_value(s.gas)
        self.b_brake.set_value(s.brake)
        self.b_clutch.set_value(1.0 - s.clutch)
        self.b_steer.set_value(s.steer_angle)
        self.aids.setText(f"TC {s.tc:.1f}   ABS {s.abs:.1f}\nair {s.air_temp:.0f}°   track {s.road_temp:.0f}°")
        self.tyres.update_from(s)
        self.hybrid.update_from(s, self.hub.session_info)

        if len(self._buf["t"]) > 2:
            t = np.fromiter(self._buf["t"], float)
            t = t - t[-1]
            m = t >= -WINDOW_S
            self.c_speed.setData(t[m], np.fromiter(self._buf["speed"], float)[m])
            self.c_gas.setData(t[m], np.fromiter(self._buf["gas"], float)[m])
            self.c_brake.setData(t[m], np.fromiter(self._buf["brake"], float)[m])
            self.p_speed.setXRange(-WINDOW_S, 0, padding=0)
            lat = np.fromiter(self._buf["lat"], float)[m][-180:]
            lon = np.fromiter(self._buf["lon"], float)[m][-180:]
            self.gg_trail.setData(lat, lon)
            self.gg_dot.setData([lat[-1]], [lon[-1]])

    def _fill_table(self):
        laps = self.hub.laps
        self.table.setRowCount(len(laps))
        valid = [l.lap_time_ms for l in laps if l.valid]
        best = min(valid) if valid else None
        bs = best_sectors(laps)
        for row, lap in enumerate(reversed(laps)):
            is_best = lap.valid and lap.lap_time_ms == best
            self.table.setItem(row, 0, table_item(str(lap.lap_no)))
            self.table.setItem(row, 1, table_item(fmt_ms(lap.lap_time_ms), C["purple"] if is_best else None, is_best))
            for i in range(3):
                v = lap.sectors_ms[i] if i < len(lap.sectors_ms) else None
                col = C["purple"] if v is not None and v == bs[i] else None
                self.table.setItem(row, 2 + i, table_item(fmt_ms(v), col))
            delta = (lap.lap_time_ms - best) / 1000 if best and lap.valid else None
            self.table.setItem(row, 5, table_item(f"+{delta:.3f}" if delta else "-" if delta is None else "0.000"))
            self.table.setItem(row, 6, table_item(f"{lap.fuel_used:.2f}"))
            self.table.setItem(row, 7, table_item(" / ".join(f"{t:.0f}" for t in lap.tyre_temp_avg)))
            self.table.setItem(row, 8, table_item("yes" if lap.valid else "no", None if lap.valid else C["red"]))
