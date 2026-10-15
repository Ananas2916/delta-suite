"""Modulo 4: Bridge CAD/FEA/CFD (viewer mesh e mappe aerodinamiche)."""

from __future__ import annotations

import numpy as np
import pyqtgraph as pg
from PyQt6.QtWidgets import (
    QCheckBox, QComboBox, QFileDialog, QFormLayout, QGroupBox, QHBoxLayout, QMessageBox, QPushButton,
    QTabWidget, QVBoxLayout, QWidget,
)

from hub_core import cad_bridge as cb
from ui.theme import C, LAP_COLORS
from ui.widgets import dspin, label, make_plot, readonly_table, table_item

try:
    import pyqtgraph.opengl as gl
    _GL_ERROR = None
except Exception as exc:   # PyOpenGL mancante o driver senza OpenGL
    gl = None
    _GL_ERROR = str(exc)


class MeshTab(QWidget):
    def __init__(self):
        super().__init__()
        self.mesh: cb.Mesh | None = None
        lay = QHBoxLayout(self)
        left = QVBoxLayout()
        open_btn = QPushButton("Apri STL / OBJ…")
        open_btn.setObjectName("primary")
        open_btn.clicked.connect(self._open)
        demo_btn = QPushButton("Carica vettura demo")
        demo_btn.clicked.connect(lambda: self._show(cb.demo_car_mesh(), "vettura demo"))
        left.addWidget(open_btn)
        left.addWidget(demo_btn)
        opts = QGroupBox("Interpretazione")
        f = QFormLayout(opts)
        self.units = QComboBox()
        self.units.addItem("metri", 1.0)
        self.units.addItem("millimetri", 0.001)
        self.axis = QComboBox()
        self.axis.addItems(["X", "Y", "Z"])
        f.addRow("Unità file", self.units)
        f.addRow("Asse longitudinale", self.axis)
        self.units.currentIndexChanged.connect(self._update_info)
        self.axis.currentIndexChanged.connect(self._update_info)
        left.addWidget(opts)
        self.info = label("Nessuna geometria caricata.", "dim")
        self.info.setWordWrap(True)
        left.addWidget(self.info)
        left.addStretch()
        lw = QWidget()
        lw.setLayout(left)
        lw.setFixedWidth(320)
        lay.addWidget(lw)

        if gl is not None:
            self.view = gl.GLViewWidget()
            self.view.setBackgroundColor(C["panel"])
            self.view.setCameraPosition(distance=8, elevation=18, azimuth=-60)
            grid = gl.GLGridItem()
            grid.setSize(20, 20)
            grid.setSpacing(1, 1)
            grid.setColor((60, 66, 80, 255))
            self.view.addItem(grid)
            self.item = None
            lay.addWidget(self.view, 1)
        else:
            self.view = None
            lay.addWidget(label(f"Vista 3D non disponibile (OpenGL): {_GL_ERROR}", "dim"), 1)

    def _open(self):
        path, _ = QFileDialog.getOpenFileName(self, "Apri geometria", "", "Mesh (*.stl *.obj)")
        if not path:
            return
        try:
            self._show(cb.load_mesh(path), path.replace("\\", "/").split("/")[-1])
        except Exception as exc:
            QMessageBox.warning(self, "Errore", f"Impossibile leggere il file:\n{exc}")

    def _show(self, mesh: cb.Mesh, name: str):
        self.mesh, self.name = mesh, name
        if self.view is not None:
            if self.item is not None:
                self.view.removeItem(self.item)
            lo, hi = mesh.bbox()
            center = (lo + hi) / 2
            size = float(np.max(hi - lo)) or 1.0
            verts = (mesh.vertices - center) / size * 6.0
            verts[:, 2] -= verts[:, 2].min()
            # illuminazione lambertiana calcolata qui: indipendente dal verso delle normali nel file
            tri = verts[mesh.faces]
            n = np.cross(tri[:, 1] - tri[:, 0], tri[:, 2] - tri[:, 0])
            n /= np.maximum(np.linalg.norm(n, axis=1, keepdims=True), 1e-12)
            light = np.array([0.35, -0.55, 0.76])
            k = 0.35 + 0.65 * np.abs(n @ (light / np.linalg.norm(light)))
            colors = np.column_stack([0.95 * k, 0.16 * k, 0.12 * k, np.ones_like(k)])
            self.item = gl.GLMeshItem(vertexes=verts, faces=mesh.faces, faceColors=colors, smooth=False,
                                      shader=None, drawEdges=True, edgeColor=(0, 0, 0, 0.6))
            self.view.addItem(self.item)
        self._update_info()

    def _update_info(self):
        m = self.mesh
        if m is None:
            return
        k = self.units.currentData()
        lo, hi = m.bbox()
        dims = (hi - lo) * k
        areas = m.projected_areas() * k * k
        ax = self.axis.currentIndex()
        lateral_axis = [i for i in range(3) if i != ax]
        self.info.setText(
            f"<b>{self.name}</b><br>{len(m.faces):,} triangoli · {len(m.vertices):,} vertici<br>"
            f"Ingombro: {dims[0]:.3f} × {dims[1]:.3f} × {dims[2]:.3f} m<br>"
            f"Superficie: {m.surface_area() * k * k:.3f} m²<br><br>"
            f"<b>Area frontale: {areas[ax]:.3f} m²</b><br>"
            f"Proiezioni sugli altri piani: {areas[lateral_axis[0]]:.3f} / {areas[lateral_axis[1]]:.3f} m²<br><br>"
            "L'area frontale è il riferimento A per convertire CL e CD in CL·A e CD·A.".replace(",", "."))


class AeroTab(QWidget):
    def __init__(self, hub):
        super().__init__()
        self.hub = hub
        self.map: cb.AeroMap | None = None
        lay = QHBoxLayout(self)
        left = QVBoxLayout()
        open_btn = QPushButton("Apri mappa CSV…")
        open_btn.setObjectName("primary")
        open_btn.clicked.connect(self._open)
        demo_btn = QPushButton("Carica mappa demo")
        demo_btn.clicked.connect(lambda: self._set_map(cb.demo_aero_map(), "mappa demo GT3"))
        left.addWidget(open_btn)
        left.addWidget(demo_btn)
        hint = label("Colonne riconosciute: rh oppure rh_front + rh_rear (mm), CL, CD, opzionale "
                     "CL_front. Separatore , ; o tab.", "dim")
        hint.setWordWrap(True)
        left.addWidget(hint)
        calc = QGroupBox("Calcolatore")
        f = QFormLayout(calc)
        self.speed = dspin(0, 400, 200, 5, 0, "km/h")
        self.rho = dspin(0.9, 1.4, 1.20, 0.01, 3, "kg/m³")
        self.area = dspin(0.01, 10, 1.0, 0.05, 3, "m²")
        self.rhf = dspin(0, 300, 60, 1, 1, "mm")
        self.rhr = dspin(0, 300, 85, 1, 1, "mm")
        self.live = QCheckBox("Ride height e velocità dalla telemetria")
        f.addRow("Velocità", self.speed)
        f.addRow("Densità aria", self.rho)
        f.addRow("Area riferimento", self.area)
        f.addRow("Ride height ant.", self.rhf)
        f.addRow("Ride height post.", self.rhr)
        f.addRow(self.live)
        left.addWidget(calc)
        self.out = label("Carica una mappa.", "dim")
        self.out.setWordWrap(True)
        left.addWidget(self.out)
        left.addStretch()
        lw = QWidget()
        lw.setLayout(left)
        lw.setFixedWidth(340)
        lay.addWidget(lw)

        right = QVBoxLayout()
        self.p_cl = make_plot("CL in funzione del ride height anteriore", "CL", "ride height ant. mm")
        self.p_cl.addLegend(offset=(10, -10))
        self.p_cd = make_plot("CD", "CD", "ride height ant. mm")
        self.p_cd.setXLink(self.p_cl)
        right.addWidget(self.p_cl, 2)
        right.addWidget(self.p_cd, 1)
        self.table = readonly_table([])
        self.table.setMaximumHeight(170)
        right.addWidget(self.table)
        lay.addLayout(right, 1)

        for w in (self.speed, self.rho, self.area, self.rhf, self.rhr):
            w.valueChanged.connect(self._calc)
        hub.sample.connect(self._on_sample)

    def _open(self):
        path, _ = QFileDialog.getOpenFileName(self, "Apri mappa aerodinamica", "", "CSV (*.csv *.txt)")
        if not path:
            return
        try:
            self._set_map(cb.load_aero_map(path), path.replace("\\", "/").split("/")[-1])
        except Exception as exc:
            QMessageBox.warning(self, "Errore", f"Impossibile leggere la mappa:\n{exc}")

    def _set_map(self, m: cb.AeroMap, name: str):
        self.map, self.name = m, name
        self.p_cl.clear()
        self.p_cd.clear()
        cols = m.columns
        if m.is_2d:
            for i, rr in enumerate(np.unique(cols["rh_rear"])):
                sel = cols["rh_rear"] == rr
                order = np.argsort(cols["rh_front"][sel])
                pen = pg.mkPen(LAP_COLORS[i % len(LAP_COLORS)], width=2)
                self.p_cl.plot(cols["rh_front"][sel][order], cols["cl"][sel][order], pen=pen, symbol="o",
                               symbolSize=5, name=f"post. {rr:.0f} mm")
                if "cd" in cols:
                    self.p_cd.plot(cols["rh_front"][sel][order], cols["cd"][sel][order], pen=pen)
        else:
            order = np.argsort(cols["rh"])
            self.p_cl.plot(cols["rh"][order], cols["cl"][order], pen=pg.mkPen(C["blue"], width=2), symbol="o")
            if "cd" in cols:
                self.p_cd.plot(cols["rh"][order], cols["cd"][order], pen=pg.mkPen(C["red"], width=2), symbol="o")
        keys = list(cols.keys())
        n = len(next(iter(cols.values())))
        self.table.setColumnCount(len(keys))
        self.table.setHorizontalHeaderLabels(keys)
        self.table.setRowCount(n)
        for r in range(n):
            for c, k in enumerate(keys):
                self.table.setItem(r, c, table_item(f"{cols[k][r]:.4g}"))
        self._calc()

    def _on_sample(self, s):
        if self.live.isChecked() and self.isVisible():
            for w, v in ((self.speed, s.speed_kmh), (self.rhf, s.ride_height[0] * 1000), (self.rhr, s.ride_height[1] * 1000)):
                w.blockSignals(True)
                w.setValue(v)
                w.blockSignals(False)
            self._calc()

    def _calc(self):
        if self.map is None:
            return
        co = self.map.at(self.rhf.value(), self.rhr.value())
        v = self.speed.value() / 3.6
        q = 0.5 * self.rho.value() * v * v * self.area.value()
        df = q * co.get("cl", 0.0)
        drag = q * co.get("cd", 0.0)
        txt = [f"<b>{self.name}</b>", f"CL = {co.get('cl', 0):.3f}   CD = {co.get('cd', 0):.3f}"]
        if co.get("cd"):
            txt.append(f"Efficienza L/D = {co['cl'] / co['cd']:.2f}")
        txt.append(f"<b>Deportanza: {df:.0f} N ({df / 9.81:.0f} kg)</b>")
        txt.append(f"Resistenza: {drag:.0f} N · potenza assorbita {drag * v / 1000:.1f} kW")
        if "balance_f" in co:
            txt.append(f"Bilanciamento aero anteriore: {co['balance_f'] * 100:.1f}%")
        self.out.setText("<br>".join(txt))


class CadPage(QWidget):
    def __init__(self, hub):
        super().__init__()
        lay = QVBoxLayout(self)
        lay.setContentsMargins(16, 16, 16, 16)
        lay.addWidget(label("CAD / FEA / CFD bridge", "h1"))
        tabs = QTabWidget()
        tabs.addTab(MeshTab(), "Geometria 3D")
        tabs.addTab(AeroTab(hub), "Mappa aerodinamica")
        lay.addWidget(tabs, 1)
