"""Lap analysis (overlaid channels, Delta-T, racing line), MoTeC i2 style."""

from __future__ import annotations

import numpy as np
import pyqtgraph as pg
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QComboBox, QFileDialog, QHBoxLayout, QListWidget, QListWidgetItem, QMessageBox, QPushButton, QSplitter,
    QVBoxLayout, QWidget,
)

from hub_core.analysis.lap_analysis import clean_lap
from hub_core.analysis.race_strategy import fmt_ms
from ui.theme import C, LAP_COLORS
from ui.widgets import Card, SessionPicker, label, make_plot

MAX_LAPS = 4
GRID_POINTS = 2000


class AnalysisPage(QWidget):
    def __init__(self, hub):
        super().__init__()
        self.hub = hub
        self._loaded: list[tuple[str, dict, str]] = []

        root = QHBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 16)

        # --- left panel
        left = Card()
        left.setFixedWidth(330)
        ll = QVBoxLayout(left)
        ll.addWidget(label("Lap analysis", "h2"))
        ll.addWidget(label("Session", "dim"))
        self.picker = SessionPicker(hub)
        self.picker.currentIndexChanged.connect(self._load_laps)
        ll.addWidget(self.picker)
        ll.addWidget(label("Reference from the archive (same car and track)", "dim"))
        self.ref = QComboBox()
        self.ref.setToolTip("A lap from another session, e.g. your all-time best: it becomes the reference "
                            "for Delta-T and is drawn first")
        self.ref.currentIndexChanged.connect(lambda _: self._redraw())
        ll.addWidget(self.ref)
        ll.addWidget(label(f"Laps (tick up to {MAX_LAPS}; the first is the reference)", "dim"))
        self.lap_list = QListWidget()
        self.lap_list.itemChanged.connect(self._on_check)
        ll.addWidget(self.lap_list, 1)
        best_btn = QPushButton("Compare best lap with the last")
        best_btn.clicked.connect(self._best_vs_last)
        ll.addWidget(best_btn)
        exp = QPushButton("Export session to Parquet…")
        exp.clicked.connect(self._export)
        ll.addWidget(exp)
        dele = QPushButton("Delete session from the archive")
        dele.clicked.connect(self._delete)
        ll.addWidget(dele)
        self.legend = label("", "dim")
        self.legend.setWordWrap(True)
        ll.addWidget(self.legend)
        root.addWidget(left)

        # --- plots
        split = QSplitter(Qt.Orientation.Horizontal)
        glw = pg.GraphicsLayoutWidget()
        self.plots = {}
        specs = [("speed", "Speed km/h"), ("delta", "Delta-T s"), ("pedals", "Throttle / Brake %"),
                 ("rpm", "RPM"), ("steer", "Steering")]
        for i, (key, title) in enumerate(specs):
            p = glw.addPlot(row=i, col=0)
            p.setLabel("left", title)
            p.showGrid(x=True, y=True, alpha=0.15)
            if i:
                p.setXLink(self.plots["speed"])
            self.plots[key] = p
        self.plots["steer"].setLabel("bottom", "Distance m")
        glw.ci.layout.setRowStretchFactor(0, 3)
        glw.ci.layout.setRowStretchFactor(1, 2)
        self.cursor = pg.InfiniteLine(angle=90, movable=True, pen=pg.mkPen(C["yellow"], width=1))
        self.plots["speed"].addItem(self.cursor)
        self.cursor.sigPositionChanged.connect(self._on_cursor)
        self.cursor_lines = []
        for key in ("delta", "pedals", "rpm", "steer"):
            ln = pg.InfiniteLine(angle=90, movable=False, pen=pg.mkPen(C["yellow"], width=1))
            self.plots[key].addItem(ln)
            self.cursor_lines.append(ln)
        split.addWidget(glw)

        self.map = make_plot("Racing line")
        self.map.setAspectLocked(True)
        self.map.hideAxis("left")
        self.map.hideAxis("bottom")
        self.map_marker = self.map.plot(pen=None, symbol="o", symbolSize=12, symbolBrush=C["yellow"])
        self.cursor_info = label("", "dim")
        mapbox = QWidget()
        mb = QVBoxLayout(mapbox)
        mb.setContentsMargins(0, 0, 0, 0)
        mb.addWidget(self.map, 1)
        mb.addWidget(self.cursor_info)
        split.addWidget(mapbox)
        split.setSizes([900, 380])
        root.addWidget(split, 1)

        hub.lap_completed.connect(self._on_live_lap)
        self._load_laps()

    # ------------------------------------------------------------------
    def _track_len(self, info) -> float:
        return float(info.get("track_length") or 0) or 5000.0

    def _load_laps(self):
        info, laps, _ = self.picker.selected()
        self._laps = laps
        self.lap_list.blockSignals(True)
        self.lap_list.clear()
        valid = [l.lap_time_ms for l in laps if l.valid]
        best = min(valid) if valid else None
        for lap in laps:
            tag = "  ★" if lap.lap_time_ms == best and lap.valid else ("" if lap.valid else "  (invalid)")
            it = QListWidgetItem(f"Lap {lap.lap_no:>3}   {fmt_ms(lap.lap_time_ms)}{tag}")
            it.setFlags(it.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            it.setCheckState(Qt.CheckState.Unchecked)
            it.setData(Qt.ItemDataRole.UserRole, lap.lap_no)
            self.lap_list.addItem(it)
        self.lap_list.blockSignals(False)
        self._fill_reference(info)
        self._redraw()

    def _fill_reference(self, info):
        """Best laps of the same car and track from other sessions."""
        current = self.ref.currentData()
        self.ref.blockSignals(True)
        self.ref.clear()
        self.ref.addItem("None", None)
        car, track = (info or {}).get("car"), (info or {}).get("track")
        if car and track:
            sid = self.picker.selected()[2]
            for b in self.hub.db.best_laps(car, track, limit=10, exclude_session=sid):
                when = f"{b['started']:%d/%m %H:%M}" if b.get("started") else ""
                self.ref.addItem(f"{fmt_ms(b['lap_time_ms'])}  ·  session #{b['session_id']} lap {b['lap_no']}  {when}",
                                 (b["session_id"], b["lap_no"], b["lap_time_ms"]))
        self.ref.setCurrentIndex(max(0, self.ref.findData(current)))
        self.ref.blockSignals(False)

    def _on_live_lap(self, _lap):
        if self.picker.currentData() is None:
            checked = self._checked()
            self._load_laps()
            self._set_checked(checked)

    def _checked(self) -> list[int]:
        return [self.lap_list.item(i).data(Qt.ItemDataRole.UserRole) for i in range(self.lap_list.count())
                if self.lap_list.item(i).checkState() == Qt.CheckState.Checked]

    def _set_checked(self, lap_nos: list[int]):
        self.lap_list.blockSignals(True)
        for i in range(self.lap_list.count()):
            it = self.lap_list.item(i)
            it.setCheckState(Qt.CheckState.Checked if it.data(Qt.ItemDataRole.UserRole) in lap_nos
                             else Qt.CheckState.Unchecked)
        self.lap_list.blockSignals(False)
        self._redraw()

    def _on_check(self, item):
        if len(self._checked()) > MAX_LAPS:
            self.lap_list.blockSignals(True)
            item.setCheckState(Qt.CheckState.Unchecked)
            self.lap_list.blockSignals(False)
        self._redraw()

    def _best_vs_last(self):
        valid = [l for l in self._laps if l.valid]
        if not valid:
            return
        best = min(valid, key=lambda l: l.lap_time_ms)
        last = self._laps[-1]
        self._set_checked([best.lap_no] if best is last else [best.lap_no, last.lap_no])

    def _channels(self, lap_no: int) -> dict | None:
        info, _, sid = self.picker.selected()
        if self.picker.currentData() is None:
            lap = next((l for l in self.hub.laps if l.lap_no == lap_no), None)
            ch = lap.channels if lap else None
        else:
            ch = self.hub.db.lap_channels(sid, lap_no)
        if not ch or len(ch["t"]) < 10:
            return None
        return clean_lap(ch, self._track_len(info))

    def _redraw(self):
        for key, p in self.plots.items():
            for item in list(p.listDataItems()):
                p.removeItem(item)
        for item in list(self.map.listDataItems()):
            if item is not self.map_marker:
                self.map.removeItem(item)

        info, _, _ = self.picker.selected()
        order = self._checked()
        self._loaded = []
        ref = self.ref.currentData()
        if ref is not None:
            sid, lap_no, lap_ms = ref
            ch = self.hub.db.lap_channels(sid, lap_no)
            if len(ch["t"]) >= 10:
                self._loaded.append((f"Ref #{sid} lap {lap_no} {fmt_ms(lap_ms)}", clean_lap(ch, self._track_len(info)),
                                     C["text"]))
        for i, lap_no in enumerate(order):
            ch = self._channels(lap_no)
            if ch is not None:
                lap = next(l for l in self._laps if l.lap_no == lap_no)
                self._loaded.append((f"Lap {lap_no} {fmt_ms(lap.lap_time_ms)}", ch, LAP_COLORS[i % len(LAP_COLORS)]))
        if not self._loaded:
            self.legend.setText("Tick one or more laps to overlay them.")
            return

        ref = self._loaded[0][1]
        end = min(c["dist"][-1] for _, c, _ in self._loaded)
        grid = np.linspace(0.0, end, GRID_POINTS)
        t_ref = np.interp(grid, ref["dist"], ref["t"])
        legend = []
        for name, ch, color in self._loaded:
            pen = pg.mkPen(color, width=2)
            d = ch["dist"]
            self.plots["speed"].plot(d, ch["speed"], pen=pen)
            self.plots["pedals"].plot(d, ch["gas"] * 100, pen=pen)
            self.plots["pedals"].plot(d, ch["brake"] * 100, pen=pg.mkPen(color, width=2, style=Qt.PenStyle.DashLine))
            self.plots["rpm"].plot(d, ch["rpm"], pen=pen)
            self.plots["steer"].plot(d, ch["steer"], pen=pen)
            self.map.plot(ch["x"], ch["z"], pen=pg.mkPen(color, width=2))
            delta = np.interp(grid, d, ch["t"]) - t_ref
            self.plots["delta"].plot(grid, delta, pen=pen)
            legend.append(f"<span style='color:{color}'>■</span> {name}  (Δ at end {delta[-1]:+.3f} s)")
        self.legend.setText("<br>".join(legend) + "<br><br>Throttle solid, brake dashed. "
                            "Drag the yellow line to move the cursor.")
        self.plots["speed"].setXRange(0, end, padding=0.01)
        self._on_cursor()

    def _on_cursor(self):
        x = self.cursor.value()
        for ln in self.cursor_lines:
            ln.setValue(x)
        if not self._loaded:
            return
        rows = []
        for i, (name, ch, color) in enumerate(self._loaded):
            idx = int(np.clip(np.searchsorted(ch["dist"], x), 0, len(ch["dist"]) - 1))
            if i == 0:
                self.map_marker.setData([ch["x"][idx]], [ch["z"][idx]])
            rows.append(f"<span style='color:{color}'>■</span> {ch['speed'][idx]:.0f} km/h · "
                        f"gear {ch['gear'][idx]:.0f} · throttle {ch['gas'][idx] * 100:.0f}% · "
                        f"brake {ch['brake'][idx] * 100:.0f}%")
        self.cursor_info.setText(f"Distance {x:.0f} m<br>" + "<br>".join(rows))

    def _export(self):
        sid = self.picker.selected()[2]
        if sid is None:
            QMessageBox.information(self, "Export", "The current session has no saved laps yet.")
            return
        path, _ = QFileDialog.getSaveFileName(self, "Export Parquet", f"session_{sid}.parquet", "Parquet (*.parquet)")
        if path:
            self.hub.db.export_parquet(sid, path)
            QMessageBox.information(self, "Export", f"Saved to {path}")

    def _delete(self):
        sid = self.picker.currentData()
        if sid is None:
            QMessageBox.information(self, "Delete", "Select a session from the archive (not the live one).")
            return
        if QMessageBox.question(self, "Delete", f"Permanently delete session #{sid}?") \
                == QMessageBox.StandardButton.Yes:
            self.hub.db.delete_session(sid)
            self.hub.db_changed.emit()
            self.picker.setCurrentIndex(0)
