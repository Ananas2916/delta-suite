"""Modulo 2: Dinamica veicolo e pneumatici (Pacejka, trasferimenti di carico, cinematica)."""

from __future__ import annotations

import math

import numpy as np
import pyqtgraph as pg
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QCheckBox, QFormLayout, QGridLayout, QGroupBox, QHBoxLayout, QSlider, QTabWidget, QVBoxLayout, QWidget,
)

from hub_core.analysis import vehicle_dynamics as vd
from ui.theme import C, LAP_COLORS
from ui.widgets import ValueTile, dspin, label, make_plot


def _form(group_title: str, fields: list[tuple[str, object]]) -> QGroupBox:
    g = QGroupBox(group_title)
    f = QFormLayout(g)
    for name, w in fields:
        f.addRow(name, w)
    return g


class PacejkaTab(QWidget):
    def __init__(self):
        super().__init__()
        lay = QHBoxLayout(self)
        p, pl = vd.PacejkaParams(), vd.PacejkaParams(B=12.0, C=1.65, mu0=1.65, E=0.3)
        self.lat = {
            "B": dspin(1, 30, p.B, 0.5), "C": dspin(0.5, 3, p.C, 0.05), "mu0": dspin(0.3, 3, p.mu0, 0.05),
            "E": dspin(-3, 1, p.E, 0.05), "load_sens": dspin(-0.5, 0.2, p.load_sens, 0.01),
            "Fz0": dspin(500, 15000, p.Fz0, 100, 0, "N"),
        }
        self.lon = {"B": dspin(1, 40, pl.B, 0.5), "C": dspin(0.5, 3, pl.C, 0.05),
                    "mu0": dspin(0.3, 3, pl.mu0, 0.05), "E": dspin(-3, 1, pl.E, 0.05)}
        left = QVBoxLayout()
        left.addWidget(_form("Laterale (Fy vs angolo di deriva)", [
            ("B rigidezza", self.lat["B"]), ("C forma", self.lat["C"]), ("μ picco (D/Fz)", self.lat["mu0"]),
            ("E curvatura", self.lat["E"]), ("Sensibilità al carico", self.lat["load_sens"]),
            ("Fz nominale", self.lat["Fz0"])]))
        left.addWidget(_form("Longitudinale (Fx vs slip ratio)", [
            ("B", self.lon["B"]), ("C", self.lon["C"]), ("μ picco", self.lon["mu0"]), ("E", self.lon["E"])]))
        self.out = label("", "dim")
        self.out.setWordWrap(True)
        left.addWidget(self.out)
        left.addStretch()
        lw = QWidget()
        lw.setLayout(left)
        lw.setFixedWidth(320)
        lay.addWidget(lw)

        grid = QGridLayout()
        self.p_fy = make_plot("Forza laterale per carico verticale", "Fy N", "angolo di deriva °")
        self.p_fx = make_plot("Forza longitudinale", "Fx N", "slip ratio %")
        self.p_ell = make_plot("Ellisse d'attrito (Fz nominale)", "Fx N", "Fy N")
        self.p_ell.setAspectLocked(True)
        self.p_mu = make_plot("μ in funzione del carico", "μ", "Fz N")
        grid.addWidget(self.p_fy, 0, 0)
        grid.addWidget(self.p_fx, 0, 1)
        grid.addWidget(self.p_ell, 1, 0)
        grid.addWidget(self.p_mu, 1, 1)
        lay.addLayout(grid, 1)
        for w in list(self.lat.values()) + list(self.lon.values()):
            w.valueChanged.connect(self.update_plots)
        self.update_plots()

    def params(self):
        lat = vd.PacejkaParams(**{k: w.value() for k, w in self.lat.items()})
        lon = vd.PacejkaParams(load_sens=lat.load_sens, Fz0=lat.Fz0, **{k: w.value() for k, w in self.lon.items()})
        return lat, lon

    def update_plots(self):
        lat, lon = self.params()
        for p in (self.p_fy, self.p_fx, self.p_ell, self.p_mu):
            p.clear()
        alpha = np.linspace(0, 15, 300)
        kappa = np.linspace(0, 0.3, 300)
        loads = [0.5, 0.75, 1.0, 1.25, 1.5]
        self.p_fy.addLegend(offset=(-10, 10))
        for i, k in enumerate(loads):
            fz = lat.Fz0 * k
            col = LAP_COLORS[i]
            self.p_fy.plot(alpha, vd.magic_formula(np.radians(alpha), fz, lat), pen=pg.mkPen(col, width=2),
                           name=f"{fz:.0f} N")
            self.p_fx.plot(kappa * 100, vd.magic_formula(kappa, fz, lon), pen=pg.mkPen(col, width=2))
        # ellisse: inviluppo delle forze combinate al variare della direzione di slip
        a_pk, _ = vd.peak_slip(lat.Fz0, lat)
        k_pk, _ = vd.peak_slip(lat.Fz0, lon)
        th = np.linspace(0, 2 * np.pi, 361)
        fx, fy = vd.combined_forces(a_pk * np.sin(th), k_pk * np.cos(th), lat.Fz0, lat, lon)
        self.p_ell.plot(fx, fy, pen=pg.mkPen(C["accent"], width=2))
        fz_axis = np.linspace(500, lat.Fz0 * 2, 100)
        self.p_mu.plot(fz_axis, lat.mu(fz_axis), pen=pg.mkPen(C["yellow"], width=2))

        a_peak, f_peak = vd.peak_slip(lat.Fz0, lat)
        k_peak, fx_peak = vd.peak_slip(lat.Fz0, lon)
        cs = float(vd.magic_formula(math.radians(0.1), lat.Fz0, lat) / 0.1)
        self.out.setText(
            f"<b>A Fz nominale ({lat.Fz0:.0f} N)</b><br>"
            f"Deriva di picco: {math.degrees(a_peak):.2f}°  ·  Fy max: {f_peak:.0f} N<br>"
            f"Rigidezza di deriva: {cs:.0f} N/°<br>"
            f"Slip ratio di picco: {k_peak * 100:.1f}%  ·  Fx max: {fx_peak:.0f} N")


class LoadTransferTab(QWidget):
    def __init__(self, hub):
        super().__init__()
        self.hub = hub
        v = vd.VehicleParams()
        self.f = {
            "mass": dspin(300, 3000, v.mass, 10, 0, "kg"), "cg_height": dspin(0.15, 1.0, v.cg_height, 0.01, 3, "m"),
            "wheelbase": dspin(1.5, 4, v.wheelbase, 0.01, 3, "m"), "track_f": dspin(1, 2.2, v.track_f, 0.01, 3, "m"),
            "track_r": dspin(1, 2.2, v.track_r, 0.01, 3, "m"),
            "weight_dist_f": dspin(0.3, 0.7, v.weight_dist_f, 0.005, 3),
            "roll_stiff_dist_f": dspin(0.2, 0.8, v.roll_stiff_dist_f, 0.01, 3),
            "rc_height_f": dspin(-0.1, 0.3, v.rc_height_f, 0.005, 3, "m"),
            "rc_height_r": dspin(-0.1, 0.3, v.rc_height_r, 0.005, 3, "m"),
            "cl_a": dspin(0, 6, v.cl_a, 0.05, 2, "m²"), "cd_a": dspin(0, 3, v.cd_a, 0.05, 2, "m²"),
            "aero_balance_f": dspin(0.2, 0.7, v.aero_balance_f, 0.01, 3),
        }
        names = {"mass": "Massa", "cg_height": "Altezza baricentro", "wheelbase": "Passo",
                 "track_f": "Carreggiata ant.", "track_r": "Carreggiata post.", "weight_dist_f": "Ripartizione pesi ant.",
                 "roll_stiff_dist_f": "Ripartizione rigidezza rollio ant.", "rc_height_f": "Centro rollio ant.",
                 "rc_height_r": "Centro rollio post.", "cl_a": "CL·A", "cd_a": "CD·A",
                 "aero_balance_f": "Bilanciamento aero ant."}
        lay = QHBoxLayout(self)
        form = _form("Vettura", [(names[k], w) for k, w in self.f.items()])
        form.setFixedWidth(340)
        lay.addWidget(form)

        right = QVBoxLayout()
        cond = QGroupBox("Condizione")
        cg = QGridLayout(cond)
        self.s_ay, self.l_ay = self._slider(-300, 300, 150), label()
        self.s_ax, self.l_ax = self._slider(-300, 150, 0), label()
        self.s_v, self.l_v = self._slider(0, 330, 180), label()
        for r, (n, s, l) in enumerate((("Acc. laterale", self.s_ay, self.l_ay), ("Acc. longitudinale", self.s_ax, self.l_ax),
                                        ("Velocità", self.s_v, self.l_v))):
            cg.addWidget(label(n), r, 0)
            cg.addWidget(s, r, 1)
            cg.addWidget(l, r, 2)
        self.live = QCheckBox("Usa i dati live della telemetria")
        cg.addWidget(self.live, 3, 0, 1, 3)
        right.addWidget(cond)

        car = QGridLayout()
        self.tiles = [ValueTile(n, "--", 18) for n in ("Anteriore sinistra", "Anteriore destra",
                                                       "Posteriore sinistra", "Posteriore destra")]
        for i, t in enumerate(self.tiles):
            car.addWidget(t, i // 2, i % 2)
        right.addLayout(car)
        self.summary = label("", "dim")
        self.summary.setWordWrap(True)
        right.addWidget(self.summary)
        right.addStretch()
        lay.addLayout(right, 1)

        for w in self.f.values():
            w.valueChanged.connect(self.recompute)
        for s in (self.s_ay, self.s_ax, self.s_v):
            s.valueChanged.connect(self.recompute)
        hub.sample.connect(self._on_sample)
        self.recompute()

    def _slider(self, lo, hi, val):
        s = QSlider(Qt.Orientation.Horizontal)
        s.setRange(lo, hi)
        s.setValue(val)
        return s

    def _on_sample(self, s):
        if self.live.isChecked() and self.isVisible():
            self.s_ay.setValue(int(s.acc_g[0] * 100))
            self.s_ax.setValue(int(s.acc_g[2] * 100))
            self.s_v.setValue(int(s.speed_kmh))

    def recompute(self):
        v = vd.VehicleParams(**{k: w.value() for k, w in self.f.items()})
        ay, ax, spd = self.s_ay.value() / 100, self.s_ax.value() / 100, self.s_v.value()
        self.l_ay.setText(f"{ay:+.2f} g")
        self.l_ax.setText(f"{ax:+.2f} g")
        self.l_v.setText(f"{spd} km/h")
        wl = vd.wheel_loads(v, ay, ax, spd)
        loads = wl.as_list()
        total = sum(loads) or 1.0
        for t, f in zip(self.tiles, loads):
            t.set(f"{f:.0f} N  ·  {f / vd.G:.0f} kg  ·  {f / total * 100:.1f}%",
                  C["red"] if f < 0.05 * total else None)
        self.summary.setText(
            f"Deportanza {wl.downforce:.0f} N ({wl.downforce / vd.G:.0f} kg) · Resistenza {wl.drag:.0f} N · "
            f"Ripartizione ant. {(loads[0] + loads[1]) / total * 100:.1f}% · "
            f"LLTD anteriore {wl.lltd_f * 100:.1f}% (più alto = tendenza al sottosterzo in appoggio)."
            + ("  ⚠ ruota interna quasi scarica: rischio sollevamento." if min(loads) < 0.05 * total else ""))


class KinematicsTab(QWidget):
    def __init__(self):
        super().__init__()
        g = vd.WishboneGeometry()
        self.pts = {}
        fields = []
        for key, name in (("lower_in", "Braccio inf. interno"), ("lower_out", "Braccio inf. esterno"),
                          ("upper_in", "Braccio sup. interno"), ("upper_out", "Braccio sup. esterno")):
            y, z = getattr(g, key)
            sy, sz = dspin(-2000, 2000, y, 5, 0, "mm"), dspin(-500, 1500, z, 5, 0, "mm")
            row = QHBoxLayout()
            row.addWidget(label("y"))
            row.addWidget(sy)
            row.addWidget(label("z"))
            row.addWidget(sz)
            w = QWidget()
            w.setLayout(row)
            fields.append((name, w))
            self.pts[key] = (sy, sz)
        self.half_track = dspin(400, 1200, g.half_track, 5, 0, "mm")
        fields.append(("Semi-carreggiata", self.half_track))
        lay = QHBoxLayout(self)
        left = QVBoxLayout()
        left.addWidget(_form("Quadrilatero, vista frontale (lato destro)", fields))
        self.out = label("", "dim")
        self.out.setWordWrap(True)
        left.addWidget(self.out)
        left.addStretch()
        lw = QWidget()
        lw.setLayout(left)
        lw.setFixedWidth(420)
        lay.addWidget(lw)
        self.plot = make_plot("Geometria, centro istantaneo e centro di rollio", "z mm", "y mm")
        self.plot.setAspectLocked(True)
        lay.addWidget(self.plot, 1)
        for sy, sz in self.pts.values():
            sy.valueChanged.connect(self.recompute)
            sz.valueChanged.connect(self.recompute)
        self.half_track.valueChanged.connect(self.recompute)
        self.recompute()

    def recompute(self):
        g = vd.WishboneGeometry(**{k: (sy.value(), sz.value()) for k, (sy, sz) in self.pts.items()},
                                half_track=self.half_track.value())
        r = vd.wishbone_kinematics(g)
        p = self.plot
        p.clear()
        p.plot([-g.half_track - 300, g.half_track + 300], [0, 0], pen=pg.mkPen(C["dim"]))
        p.plot([0, 0], [-100, 600], pen=pg.mkPen(C["border"], style=Qt.PenStyle.DashLine))
        for a, b in (("lower_in", "lower_out"), ("upper_in", "upper_out")):
            for side in (1, -1):
                pa, pb = getattr(g, a), getattr(g, b)
                p.plot([side * pa[0], side * pb[0]], [pa[1], pb[1]], pen=pg.mkPen(C["blue"], width=3),
                       symbol="o", symbolSize=7, symbolBrush=C["blue"])
        for side in (1, -1):
            lo, up = g.lower_out, g.upper_out
            p.plot([side * lo[0], side * up[0]], [lo[1], up[1]], pen=pg.mkPen(C["text"], width=3))
            p.plot([side * g.half_track], [0], pen=None, symbol="s", symbolSize=9, symbolBrush=C["dim"])
        if r.instant_center:
            ic = r.instant_center
            p.plot([g.lower_out[0], ic[0]], [g.lower_out[1], ic[1]], pen=pg.mkPen(C["dim"], style=Qt.PenStyle.DotLine))
            p.plot([g.upper_out[0], ic[0]], [g.upper_out[1], ic[1]], pen=pg.mkPen(C["dim"], style=Qt.PenStyle.DotLine))
            p.plot([g.half_track, ic[0]], [0, ic[1]], pen=pg.mkPen(C["yellow"], style=Qt.PenStyle.DashLine))
            p.plot([ic[0]], [ic[1]], pen=None, symbol="+", symbolSize=16, symbolBrush=C["yellow"], symbolPen=C["yellow"])
        if r.roll_center_height is not None:
            p.plot([0], [r.roll_center_height], pen=None, symbol="o", symbolSize=13, symbolBrush=C["accent"])
        txt = []
        if r.instant_center:
            txt.append(f"Centro istantaneo: y = {r.instant_center[0]:.0f} mm, z = {r.instant_center[1]:.0f} mm")
            txt.append(f"Braccio oscillante virtuale (FVSA): {r.fvsa_length:.0f} mm")
            txt.append(f"Recupero di camber: {r.camber_gain * 25.4:.3f} °/pollice  ({r.camber_gain:.4f} °/mm)")
        else:
            txt.append("Bracci paralleli: centro istantaneo all'infinito, nessun recupero di camber.")
        if r.roll_center_height is not None:
            txt.append(f"<b>Altezza centro di rollio: {r.roll_center_height:.1f} mm</b>")
        self.out.setText("<br>".join(txt) + "<br><br>Punto rosso = centro di rollio, croce gialla = centro "
                         "istantaneo. Usa l'altezza del centro di rollio nella scheda Trasferimenti di carico.")


class DynamicsPage(QWidget):
    def __init__(self, hub):
        super().__init__()
        lay = QVBoxLayout(self)
        lay.setContentsMargins(16, 16, 16, 16)
        lay.addWidget(label("Dinamica veicolo & pneumatici", "h1"))
        tabs = QTabWidget()
        tabs.addTab(PacejkaTab(), "Pneumatico (Pacejka)")
        tabs.addTab(LoadTransferTab(hub), "Trasferimenti di carico")
        tabs.addTab(KinematicsTab(), "Cinematica sospensione")
        lay.addWidget(tabs, 1)
