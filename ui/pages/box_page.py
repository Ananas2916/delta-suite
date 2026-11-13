"""Pit & Setup: live adjustments, setup, the engineer's proposals and standings (CSP app)."""

from __future__ import annotations

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtWidgets import (
    QHBoxLayout, QMessageBox, QPushButton, QSpinBox, QSplitter, QVBoxLayout, QWidget,
)

from hub_core.ac import csp_bridge
from hub_core.ac.csp_bridge import CMD_ABS, CMD_BRAKE_BIAS, CMD_ENGINE_BRAKE, CMD_TC
from hub_core.analysis.race_strategy import fmt_ms
from hub_core.analysis.timing import fmt_gap
from ui.theme import C
from ui.widgets import Card, label, readonly_table, table_item
from hub_core.i18n import tr

STATUS_COLORS = {"pending": C["yellow"], "in pits": C["blue"], "sent": C["blue"], "applied": C["green"],
                 "error": C["red"], "discarded": C["dim"]}


class ControlTile(Card):
    """Value with − and + (bias, ABS, TC, engine brake)."""

    def __init__(self, title: str, on_change):
        super().__init__()
        lay = QVBoxLayout(self)
        lay.setContentsMargins(12, 8, 12, 8)
        t = label(title.upper(), "dim")
        t.setStyleSheet("font-size: 8pt; letter-spacing: 1px;")
        lay.addWidget(t)
        row = QHBoxLayout()
        self.minus, self.plus = QPushButton("−"), QPushButton("+")
        for b in (self.minus, self.plus):
            b.setFixedWidth(40)
        self.value = label("--")
        self.value.setStyleSheet("font-size: 20pt; font-weight: 700;")
        self.value.setAlignment(Qt.AlignmentFlag.AlignCenter)
        row.addWidget(self.minus)
        row.addWidget(self.value, 1)
        row.addWidget(self.plus)
        lay.addLayout(row)
        self.minus.clicked.connect(lambda: on_change(-1))
        self.plus.clicked.connect(lambda: on_change(+1))

    def set(self, text: str, enabled: bool):
        self.value.setText(text)
        self.minus.setEnabled(enabled)
        self.plus.setEnabled(enabled)


class BoxPage(QWidget):
    def __init__(self, hub):
        super().__init__()
        self.hub = hub
        self._setup_names: list[str] = []
        self._dirty = False

        root = QVBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 16)
        root.setSpacing(10)

        head = QHBoxLayout()
        head.addWidget(label(tr("Pit & Setup"), "h1"))
        head.addStretch()
        self.bridge_status = label("", "dim")
        head.addWidget(self.bridge_status)
        self.install_btn = QPushButton(tr("Install CSP app in AC"))
        self.install_btn.clicked.connect(self._install)
        head.addWidget(self.install_btn)
        root.addLayout(head)

        tiles = QHBoxLayout()
        self.t_bias = ControlTile(tr("Brake bias"), self._bias)
        self.t_abs = ControlTile("ABS", lambda d: self._mode(CMD_ABS, "abs_mode", "abs_modes", d))
        self.t_tc = ControlTile("TC", lambda d: self._mode(CMD_TC, "tc_mode", "tc_modes", d))
        self.t_eb = ControlTile(tr("Engine brake"), self._engine_brake)
        for t in (self.t_bias, self.t_abs, self.t_tc, self.t_eb):
            tiles.addWidget(t)
        root.addLayout(tiles)
        self.ack = label("", "dim")
        root.addWidget(self.ack)

        split = QSplitter(Qt.Orientation.Vertical)
        top = QSplitter(Qt.Orientation.Horizontal)

        prop = Card()
        pl = QVBoxLayout(prop)
        pl.addWidget(label(tr("Engineer proposals"), "h2"))
        pl.addWidget(label(tr("They can also be confirmed with the wheel buttons bound in the CSP app."), "dim"))
        self.prop_table = readonly_table([tr(h) for h in ("Change", "Reason", "Status", "Outcome")])
        pl.addWidget(self.prop_table, 1)
        row = QHBoxLayout()
        apply_btn = QPushButton(tr("Apply"))
        apply_btn.setObjectName("primary")
        apply_btn.clicked.connect(lambda: self._on_selected(self.hub.apply_proposal))
        drop_btn = QPushButton(tr("Discard"))
        drop_btn.clicked.connect(lambda: self._on_selected(self.hub.discard_proposal))
        row.addStretch()
        row.addWidget(drop_btn)
        row.addWidget(apply_btn)
        pl.addLayout(row)
        top.addWidget(prop)

        st = Card()
        sl = QVBoxLayout(st)
        sl.addWidget(label(tr("Standings"), "h2"))
        self.standings = readonly_table([tr(h) for h in ("Pos", "Driver", "Car", "Laps", "Last", "Best", "Gap", "Int.", "Pit")])
        sl.addWidget(self.standings, 1)
        top.addWidget(st)
        top.setSizes([620, 680])
        split.addWidget(top)

        su = Card()
        ul = QVBoxLayout(su)
        hl = QHBoxLayout()
        hl.addWidget(label(tr("Setup"), "h2"))
        self.setup_note = label("", "dim")
        hl.addWidget(self.setup_note, 1)
        ul.addLayout(hl)
        self.setup_table = readonly_table([tr(h) for h in ("Item", "Value", "Clicks", "Min", "Max", "Change (clicks)")])
        ul.addWidget(self.setup_table, 1)
        split.addWidget(su)
        split.setSizes([330, 420])
        root.addWidget(split, 1)

        hub.bridge_changed.connect(lambda _: self._mark())
        hub.proposals_changed.connect(self._fill_proposals)
        hub.standings_changed.connect(lambda _: self._mark())
        self.timer = QTimer(self)
        self.timer.timeout.connect(self._refresh)
        self.timer.start(250)
        self._refresh(force=True)
        self._fill_proposals()

    # ------------------------------------------------------------ commands
    def _b(self):
        return self.hub.bridge_state

    def _bias(self, d: int):
        b = self._b()
        if b is None:
            return
        step = b.brake_bias_step or 0.005
        v = min(max(b.brake_bias + d * step, b.brake_bias_min or 0.0), b.brake_bias_max or 1.0)
        self.hub.send_command(CMD_BRAKE_BIAS, v)

    def _mode(self, cmd: int, cur: str, count: str, d: int):
        b = self._b()
        if b is None:
            return
        v = min(max(getattr(b, cur) + d, 0), getattr(b, count))
        self.hub.send_command(cmd, v)

    def _engine_brake(self, d: int):
        b, s = self._b(), self.hub.last_sample
        if b is None or s is None:
            return
        hi = max(1, b.engine_brake_count)
        self.hub.send_command(CMD_ENGINE_BRAKE, min(max(s.engine_brake + d, 0), hi))

    def _on_selected(self, fn):
        row = self.prop_table.currentRow()
        if row < 0:
            return
        props = list(reversed(self.hub.proposals))
        if row < len(props):
            fn(props[row].id)

    def _install(self):
        try:
            path = csp_bridge.install_app()
        except Exception as exc:
            QMessageBox.warning(self, tr("Installation"), tr("Installation failed:\n{err}", err=exc))
            return
        QMessageBox.information(
            self, tr("CSP app installed"),
            tr("App copied to:\n{path}\n\nRestart the AC session to load it. In game, open 'Delta Suite Bridge' from "
               "the app bar to bind the wheel buttons (radio, confirm, discard).", path=path))
        self._refresh(force=True)

    # ------------------------------------------------------------ view
    def _mark(self):
        self._dirty = True

    def _refresh(self, force: bool = False):
        if not (self._dirty or force) or not (self.isVisible() or force):
            return
        self._dirty = False
        b = self._b()
        if b is None:
            err = self.hub.worker.bridge.layout_error if self.hub.worker and self.hub.worker.bridge else None
            needs = csp_bridge.app_needs_update()
            self.bridge_status.setText(
                f"<span style='color:{C['yellow']}'>●</span> " + (err or (
                    tr("CSP app not connected: start the acquisition from AC and install the app") if needs else
                    tr("CSP app not connected: start the acquisition from AC"))))
            self.install_btn.setText(tr("Update CSP app") if not needs else tr("Install CSP app in AC"))
            for t in (self.t_bias, self.t_abs, self.t_tc, self.t_eb):
                t.set("--", False)
            self.setup_note.setText("")
            return
        self.bridge_status.setText(f"<span style='color:{C['green']}'>●</span> " + tr("CSP app connected"))
        self.install_btn.setText(tr("Update CSP app"))
        self.t_bias.set(f"{b.brake_bias * 100:.1f}%", b.brake_bias > 0)
        self.t_abs.set(f"{b.abs_mode}/{b.abs_modes}" if b.abs_modes else tr("n/a"), b.abs_modes > 0)
        self.t_tc.set(f"{b.tc_mode}/{b.tc_modes}" if b.tc_modes else tr("n/a"), b.tc_modes > 0)
        s = self.hub.last_sample
        eb = s.engine_brake if s else 0
        self.t_eb.set(f"{eb}/{b.engine_brake_count}" if b.engine_brake_count else tr("n/a"), b.engine_brake_count > 0)
        if b.ack_msg:
            col = C["green"] if b.ack_ok else C["red"]
            self.ack.setText(f"<span style='color:{col}'>" + tr("Last command:") + f"</span> {b.ack_msg}")
        self._fill_setup(b)
        self._fill_standings()

    def _fill_setup(self, b):
        editable = b.setup_editable
        self.setup_note.setText(tr("editable now: changes go straight to the car") if editable else
                                tr("not editable right now: confirmed proposals are applied in the pits"))
        names = [it.name for it in b.setup]
        if names != self._setup_names:
            self._setup_names = names
            self.setup_table.setRowCount(len(b.setup))
            for r, it in enumerate(b.setup):
                sb = QSpinBox()
                sb.setRange(it.min, it.max)
                sb.setSingleStep(it.step)
                sb.setKeyboardTracking(False)
                sb.editingFinished.connect(lambda sb=sb, n=it.name: self.hub.set_setup_value(n, sb.value()))
                self.setup_table.setCellWidget(r, 5, sb)
        for r, it in enumerate(b.setup):
            self.setup_table.setItem(r, 0, table_item(it.label or it.name))
            disp = f"{it.display:g} {it.units}".strip()
            self.setup_table.setItem(r, 1, table_item(disp))
            self.setup_table.setItem(r, 2, table_item(str(it.value)))
            self.setup_table.setItem(r, 3, table_item(str(it.min)))
            self.setup_table.setItem(r, 4, table_item(str(it.max)))
            sb = self.setup_table.cellWidget(r, 5)
            if sb is not None and not sb.hasFocus():
                sb.blockSignals(True)
                sb.setValue(it.value)
                sb.blockSignals(False)
                sb.setEnabled(editable and not it.read_only)

    def _fill_standings(self):
        rows = self.hub.standings_rows
        self.standings.setRowCount(len(rows))
        for i, r in enumerate(rows):
            col = C["accent"] if r.is_player else None
            gap = fmt_gap(r)
            vals = [str(r.pos), r.driver, r.model, str(r.laps), fmt_ms(r.last_ms), fmt_ms(r.best_ms), gap,
                    "-" if r.interval_s is None else f"+{r.interval_s:.1f}", tr("PIT") if r.in_pit else ""]
            for c, v in enumerate(vals):
                self.standings.setItem(i, c, table_item(v, col, r.is_player))

    def _fill_proposals(self):
        props = list(reversed(self.hub.proposals))
        self.prop_table.setRowCount(len(props))
        for i, p in enumerate(props):
            self.prop_table.setItem(i, 0, table_item(p.describe(), None, p.status == "pending"))
            self.prop_table.setItem(i, 1, table_item(p.reason))
            self.prop_table.setItem(i, 2, table_item(tr(p.status), STATUS_COLORS.get(p.status)))
            self.prop_table.setItem(i, 3, table_item(p.result))
