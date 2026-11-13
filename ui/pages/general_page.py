"""
Overview: everything at once, like on the pit wall (or in race control, but for the team).

Main onboard with TV graphics, standings, GPS, car status and alerts, fuel and strategy,
hybrid battery, radio and the engineer's proposals to confirm. The video uses the same link
as the Onboard page (`hub.onboard_feed`), only while this page is visible.
"""

from __future__ import annotations

import time
from collections import deque

from PyQt6.QtCore import Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import (
    QHBoxLayout, QListWidget, QListWidgetItem, QPushButton, QSizePolicy, QVBoxLayout, QWidget,
)

from hub_core.ac.onboard_feed import (
    DEFAULT_EXPOSURE, DEFAULT_TONEMAP, QUALITIES, VIEWS, ViewRequest, camera_menu,
)
from hub_core.analysis import race_strategy as rs
from hub_core.model import ACSessionType
from hub_core.ac.csp_bridge import find_ac_root
from ui import first_run
from ui import race_view as rv
from ui.race_view import STALE_S
from ui.theme import C
from ui.widgets import Card, ValueTile, label
from ui.widgets.car_status import CarStatusView
from ui.widgets.checklist import ChecklistCard
from ui.widgets.gps import GPSView
from ui.widgets.hybrid import HybridCard
from ui.widgets.onboard_hud import frame_image
from ui.widgets.sectors import LapTimeTile
from ui.widgets.timing_table import TimingTable
from ui.widgets.view_panel import ViewPanel
from hub_core.i18n import tr

SESSION_NAMES = {
    ACSessionType.PRACTICE: "Practice", ACSessionType.QUALIFY: "Qualifying", ACSessionType.RACE: "Race",
    ACSessionType.HOTLAP: "Hotlap", ACSessionType.TIME_ATTACK: "Time attack", ACSessionType.DRIFT: "Drift",
    ACSessionType.DRAG: "Drag",
}
FLAG_STYLES = {   # flag kind: (background, dark text)
    "yellow": (C["yellow"], True), "red": (C["red"], False), "blue": (C["blue"], False), "green": (C["green"], True),
    "black": ("#000000", False), "white": ("#ffffff", True), "checkered": ("#ffffff", True),
    "penalty": (C["red"], False),
}
WHO_COLORS = {"radio": C["blue"], "driver": C["green"], "engineer": C["purple"], "system": C["dim"]}
WHO_NAMES = {"radio": "Radio", "driver": "Driver", "engineer": "Engineer", "system": "System"}
RADIO_LINES = 60


def fmt_time_left(ms: float) -> str:
    if ms is None or ms < 0:
        return "—"
    s = int(ms // 1000)
    return f"{s // 3600}:{s // 60 % 60:02d}:{s % 60:02d}" if s >= 3600 else f"{s // 60}:{s % 60:02d}"


def _card(title: str) -> tuple[Card, QVBoxLayout]:
    card = Card()
    lay = QVBoxLayout(card)
    lay.setContentsMargins(12, 10, 12, 12)
    lay.setSpacing(6)
    lay.addWidget(label(title, "dim"))
    return card, lay


class GeneralPage(QWidget):
    open_module = pyqtSignal(str)
    start_demo = pyqtSignal()
    checklist_action = pyqtSignal(str)

    def __init__(self, hub, with_checklist: bool = True):
        super().__init__()
        self.hub = hub
        self._with_checklist = with_checklist       # off when the Home view shows the status list
        self._beat_t = 0.0
        self._ui_t = 0.0
        self._f6: list[str] = [n for n in hub.setting("onboard/f6_names", "", str).split("|") if n]
        self._cars_key = None
        self._radio: deque[tuple[str, str, str]] = deque(maxlen=RADIO_LINES)

        root = QVBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 16)
        root.setSpacing(10)

        # --- header: session, flag, controls
        head = QHBoxLayout()
        head.addWidget(label(tr("Overview"), "h1"))
        head.addSpacing(12)
        self.session = label("", "dim")
        head.addWidget(self.session)
        head.addStretch()
        self.flag = label("")
        head.addWidget(self.flag)
        self.video_btn = QPushButton()
        self.video_btn.setCheckable(True)
        self.video_btn.setChecked(hub.setting("onboard/video", True, bool))
        self.video_btn.setToolTip(tr("Onboard video from AC (same setting as the Onboard page)"))
        self.video_btn.toggled.connect(self._on_video_toggled)
        self._video_label()
        self.demo_btn = QPushButton(tr("Start demo"))
        self.demo_btn.clicked.connect(self.start_demo)
        self.tele_btn = QPushButton(tr("Telemetry"))
        self.tele_btn.setObjectName("primary")
        self.tele_btn.setToolTip(tr("Start or stop the acquisition from AC, demo or replay"))
        self.tele_btn.clicked.connect(lambda: self.open_module.emit("telemetry"))
        for w in (self.video_btn, self.demo_btn, self.tele_btn):
            head.addWidget(w)
        root.addLayout(head)
        if hub.db_error:
            root.addWidget(label(f"<span style='color:{C['yellow']}'>"
                                 + tr("Archive not available ({err}): this session's data stays in memory only.",
                                      err=hub.db_error) + "</span>"))

        # --- get started: what is ready and what is missing, until everything is green or hidden
        self.checklist = ChecklistCard()
        self.checklist.action.connect(self.checklist_action)
        self.checklist.hide_requested.connect(self._hide_checklist)
        root.addWidget(self.checklist)
        self._ac_root = None
        self._ac_root_t = -1e9
        self._check_t = -1e9

        # --- numbers
        tiles = QHBoxLayout()
        self.t_pos = ValueTile(tr("Position"), "-", 20)
        self.t_lap = ValueTile(tr("Lap"), "-", 20)
        self.t_cur = LapTimeTile()          # time, live delta to the best and splits
        self.t_last = ValueTile(tr("Last"), "--:--.---", 20)
        self.t_best = ValueTile(tr("Best"), "--:--.---", 20)
        self.t_fuel = ValueTile(tr("Fuel"), "-- L", 20)
        self.t_left = ValueTile(tr("To go"), "—", 20)
        for t in (self.t_pos, self.t_lap, self.t_cur, self.t_last, self.t_best, self.t_fuel, self.t_left):
            if t is not self.t_cur:     # same height as the time tile, which has the splits below
                t.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
            tiles.addWidget(t, 2 if t is self.t_cur else 1)
        root.addLayout(tiles)

        body = QHBoxLayout()
        body.setSpacing(12)

        # --- column 1: main onboard, below it car status and alerts
        col1 = QVBoxLayout()
        col1.setSpacing(10)
        self.panel = ViewPanel(0)
        self.panel.fill_cameras(camera_menu(self._f6), hub.setting("general/camera", 0, int))
        self.panel.select(hub.setting("general/car", -1, int), self.panel.camera_index())
        self.panel.changed.connect(self._on_panel_changed)
        self.panel.view.setMinimumSize(400, 225)
        col1.addWidget(self.panel, 3)
        car_card, cl = _card(tr("CAR STATUS"))
        row = QHBoxLayout()
        self.car_view = CarStatusView()
        self.car_view.setMinimumSize(270, 250)
        row.addWidget(self.car_view, 1)
        texts = QVBoxLayout()
        self.info = label("", "dim")
        self.info.setTextFormat(Qt.TextFormat.RichText)
        self.alerts = label("")
        self.alerts.setTextFormat(Qt.TextFormat.RichText)
        self.alerts.setAlignment(Qt.AlignmentFlag.AlignTop)
        texts.addWidget(self.info)
        texts.addSpacing(6)
        texts.addWidget(self.alerts, 1)
        row.addLayout(texts, 1)
        cl.addLayout(row, 1)
        col1.addWidget(car_card, 2)
        body.addLayout(col1, 5)

        # --- column 2: standings and GPS
        col2 = QVBoxLayout()
        col2.setSpacing(10)
        timing_card, tl = _card(tr("STANDINGS"))
        self.timing = TimingTable()
        self.timing.setToolTip(tr("Click a car to watch it in the onboard"))
        self.timing.car_clicked.connect(self._on_car_click)
        tl.addWidget(self.timing, 1)
        col2.addWidget(timing_card, 1)
        gps_card, gl = _card(tr("GPS · TRACK POSITION"))
        self.gps = GPSView()
        self.gps.setToolTip(tr("Click a car to watch it in the onboard"))
        self.gps.car_clicked.connect(self._on_car_click)
        gl.addWidget(self.gps, 1)
        col2.addWidget(gps_card, 1)
        body.addLayout(col2, 3)

        # --- column 3: strategy and battery, proposals, radio
        col3 = QVBoxLayout()
        col3.setSpacing(10)
        strat_card, sl = _card(tr("STRATEGY"))
        self.strategy = label("", "dim")
        self.strategy.setTextFormat(Qt.TextFormat.RichText)
        sl.addWidget(self.strategy)
        col3.addWidget(strat_card)
        self.hybrid = HybridCard(tr("BATTERY"))
        col3.addWidget(self.hybrid)
        prop_card, self._prop_lay = _card(tr("ENGINEER PROPOSALS"))
        self._prop_rows: list[QWidget] = []
        self.no_props = label(tr("No pending proposals"), "dim")
        self._prop_lay.addWidget(self.no_props)
        col3.addWidget(prop_card)
        radio_card, rl = _card(tr("RADIO"))
        self.radio = QListWidget()
        self.radio.setWordWrap(True)
        self.radio.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.radio.setSelectionMode(QListWidget.SelectionMode.NoSelection)
        rl.addWidget(self.radio, 1)
        col3.addWidget(radio_card, 1)
        side = QWidget()
        side.setLayout(col3)
        side.setFixedWidth(300)
        side.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Expanding)
        body.addWidget(side)
        root.addLayout(body, 1)

        hub.session_changed.connect(self._on_session)
        hub.standings_changed.connect(self._fill_cars)
        hub.proposals_changed.connect(self._fill_proposals)
        hub.radio_log.connect(self._on_radio)
        hub.running_changed.connect(lambda _: self._refresh())
        self._fill_proposals()

        self.timer = QTimer(self)
        self.timer.timeout.connect(self._tick)
        self.timer.start(33)

    # ------------------------------------------------------------- controls
    @property
    def feed(self):
        return self.hub.onboard_feed

    def _video_label(self):
        self.video_btn.setText(tr("Video on") if self.video_btn.isChecked() else tr("Video off"))

    def _on_video_toggled(self, on: bool):
        self.hub.settings.setValue("onboard/video", on)
        self._video_label()
        self._push_request()

    def _on_panel_changed(self):
        self.hub.settings.setValue("general/camera", self.panel.camera_index())
        self.hub.settings.setValue("general/car", self.panel.car_index())
        self.panel.img = None
        self._push_request()

    def _on_car_click(self, idx: int):
        self.panel.select(-1 if idx == 0 else idx, self.panel.camera_index())
        self._on_panel_changed()

    def _fill_cars(self, rows):
        others = [(r.index, f"P{r.pos}  {r.driver or tr('car {n}', n=r.index)}") for r in rows if not r.is_player]
        if others == self._cars_key:
            return
        self._cars_key = others
        self.panel.fill_cars(others, self.hub.setting("general/car", -1, int))

    def _on_session(self, info: dict):
        self._fill_cars([])
        self.gps.clear_trail()

    def _sync_cameras(self):
        f6 = self.feed.f6_cameras()
        if not f6 or f6 == self._f6:
            return
        self._f6 = f6
        self.hub.settings.setValue("onboard/f6_names", "|".join(f6))
        self.panel.fill_cameras(camera_menu(f6), self.panel.camera_index())

    def _push_request(self) -> bool:
        """A single view (the main one), with the Onboard page's quality and brightness."""
        if not self.hub.ac_live or not self.isVisible():
            return False
        q = max(0, min(len(QUALITIES) - 1, self.hub.setting("onboard/quality", 1, int)))
        _name, w, h, fps = QUALITIES[q]
        on = self.video_btn.isChecked()
        views = [ViewRequest(on, self.panel.camera_index(), self.panel.car_index(), w, h, fps)]
        views += [ViewRequest(False, 0, -1, w, h, fps) for _ in range(VIEWS - 1)]
        self._beat_t = time.monotonic()
        exposure = self.hub.setting("onboard/exposure", DEFAULT_EXPOSURE, float)
        return self.feed.request(views, exposure, DEFAULT_TONEMAP)

    def hideEvent(self, e):
        self.feed.disconnect()          # no rendering in AC while the page is hidden
        super().hideEvent(e)

    # ------------------------------------------------------------- proposals and radio
    def _fill_proposals(self):
        for w in self._prop_rows:
            w.deleteLater()
        self._prop_rows = []
        pending = self.hub.pending()
        self.no_props.setVisible(not pending)
        for p in pending[-3:]:
            row = QWidget()
            lay = QHBoxLayout(row)
            lay.setContentsMargins(0, 0, 0, 0)
            text = label(p.describe())
            text.setToolTip(p.reason)
            ok = QPushButton(tr("Confirm"))
            ok.setObjectName("primary")
            ok.clicked.connect(lambda _=False, pid=p.id: self.hub.apply_proposal(pid))
            no = QPushButton(tr("Discard"))
            no.clicked.connect(lambda _=False, pid=p.id: self.hub.discard_proposal(pid))
            lay.addWidget(text, 1)
            lay.addWidget(ok)
            lay.addWidget(no)
            self._prop_lay.addWidget(row)
            self._prop_rows.append(row)

    def _on_radio(self, who: str, text: str):
        item = QListWidgetItem(f"{time.strftime('%H:%M')}  {tr(WHO_NAMES.get(who, who))}: {text}")
        item.setForeground(QColor(WHO_COLORS.get(who, C["text"])))
        self.radio.addItem(item)
        while self.radio.count() > RADIO_LINES:
            self.radio.takeItem(0)
        self.radio.scrollToBottom()

    # ------------------------------------------------------------- refresh
    def _tick(self):
        if not self.isVisible():
            return
        now = time.monotonic()
        if self.hub.ac_live and self.video_btn.isChecked():
            if now - self._beat_t > 0.5:
                self._push_request()
            frame = self.feed.new_frame(0)
            if frame is not None:
                img = frame_image(frame)
                if not img.isNull():
                    self.panel.img, self.panel.frame_t = img, now
        elif self.feed.connected:
            self.feed.disconnect()
        if now - self._ui_t >= 0.066:       # graphics at 15 Hz, video every frame
            self._ui_t = now
            self._refresh()
        if now - self._check_t >= 3.0:
            self._check_t = now
            self.refresh_checklist()

    # ------------------------------------------------------------- get started
    def refresh_checklist(self):
        if not self._with_checklist or self.hub.setting("checklist/hidden", False, bool):
            self.checklist.hide()
            return
        now = time.monotonic()
        if now - self._ac_root_t > 30.0:    # the registry lookup is not free: once every 30 s is plenty
            self._ac_root, self._ac_root_t = find_ac_root(), now
        items = first_run.checklist(self.hub, self._ac_root)
        self.checklist.set_items(items)
        self.checklist.setVisible(not first_run.all_done(items))

    def _hide_checklist(self):
        self.hub.settings.setValue("checklist/hidden", True)
        self.checklist.hide()

    def _refresh(self):
        self._sync_cameras()
        s, info, fpl, alerts = rv.live_state(self.hub)
        self.demo_btn.setVisible(not self.hub.running)

        # onboard
        if not self.hub.ac_live:
            self.panel.img = None
        live = self.panel.img is not None and time.monotonic() - self.panel.frame_t < STALE_S
        self.panel.view.set_frame(self.panel.img, live)
        hud = rv.main_hud(self.hub, s, alerts, self.panel.car_index(), self.panel.camera.currentText(),
                          self.panel.car.currentText())
        placeholder = "" if live else rv.video_placeholder(self.hub, True, self.panel.img is not None,
                                                           self.video_btn.isChecked())
        self.panel.view.set_hud(hud, placeholder)

        # standings, GPS, car status
        rings = rv.view_rings([self.panel.car_index()])
        rv.update_gps(self.hub, self.gps, s, rings)
        self.timing.fill(rv.timing_rows(self.hub, s, rings))
        self.car_view.set_sample(s, info)
        self.info.setText(rv.car_info_html(self.hub, s, fpl))
        self.alerts.setText(rv.alerts_html(s, alerts, 8))
        self.hybrid.update_from(s, info)
        prog = rv.progress(self.hub, s)
        self._fill_head(s, info)
        self._fill_tiles(s, fpl, prog)
        self._fill_strategy(s, fpl, prog)

    def _fill_head(self, s, info):
        if not self.hub.running or not info:
            self.session.setText(tr("Acquisition stopped: start an AC session from Telemetry, or the demo."))
            self.flag.setText("")
            return
        kind = tr(SESSION_NAMES.get(s.session_type, "")) if s is not None and s.session_type in SESSION_NAMES else ""
        self.session.setText("  ·  ".join(x for x in (info.get("source", ""), f"{info.get('car', '')} @ "
                                                      f"{info.get('track', '')}", kind) if x))
        flag = rv.flag_status(self.hub, s)
        if flag is None:
            self.flag.setText("")
            self.flag.setStyleSheet("")
            self.flag.setMinimumWidth(0)
            return
        bg, dark = FLAG_STYLES.get(flag.kind, (C["yellow"], True))
        self.flag.setStyleSheet(f"background: {bg}; color: {'#111111' if dark else '#ffffff'}; font-weight: 800;"
                                "padding: 4px 10px; border-radius: 4px;")
        self.flag.ensurePolished()
        self.flag.setText(flag.text)
        # width from the text: with a full row the QLabel stayed a small coloured box with no text
        self.flag.setMinimumWidth(self.flag.fontMetrics().horizontalAdvance(flag.text) + 28)

    def _fill_tiles(self, s, fpl, prog):
        if s is None:
            return
        self.t_pos.set(f"P{s.position}" if s.position else "-")
        total = f"/{prog.total}" if prog is not None and prog.total else ""
        self.t_lap.set(f"{s.completed_laps + 1}{total}" + (" " + tr("PIT") if s.is_in_pit else ""))
        self.t_cur.set(s.lap_time_ms, self.hub.live_lap.delta_s, rv.sector_views(self.hub, s))
        self.t_last.set(rs.fmt_ms(s.last_lap_ms))
        self.t_best.set(rs.fmt_ms(s.best_lap_ms), C["purple"])
        laps_left = s.fuel / fpl if fpl else None
        self.t_fuel.set(f"{s.fuel:.1f} L", C["red"] if laps_left is not None and laps_left < 2 else None)
        self.t_left.set(*self._to_go(prog))

    @staticmethod
    def _to_go(prog) -> tuple[str, str | None]:
        """Laps to go (from the leader) or time left; yellow on the last lap."""
        if prog is None:
            return "—", None
        if prog.to_go is not None:
            text = prog.to_go_text
            if prog.estimated and prog.time_left_s is not None:
                text += f" · {fmt_time_left(prog.time_left_s * 1000)}"
            return text, C["yellow"] if prog.to_go <= 1 else None
        return (fmt_time_left(prog.time_left_s * 1000), None) if prog.time_left_s is not None else ("—", None)

    def _fill_strategy(self, s, fpl, prog):
        laps = self.hub.laps
        if s is None:
            self.strategy.setText(tr("No data"))
            return
        lines = []
        if fpl:
            lines.append(tr("Fuel use {fpl} L/lap  ·  ~{n} laps", fpl=f"{fpl:.2f}", n=f"{s.fuel / fpl:.1f}"))
            if prog is not None and prog.to_go:
                # at the finish: fuel left after the laps to go (the current lap counts in full)
                margin = s.fuel - prog.to_go * fpl
                col = C["green"] if margin >= fpl else C["yellow"] if margin >= 0 else C["red"]
                verdict = (tr("{l} L spare", l=f"{margin:.1f}") if margin >= 0 else
                           tr("{l} L short: a stop is needed", l=f"{-margin:.1f}"))
                lines.append(tr("At the finish:") + f" <span style='color:{col}'>{verdict}</span>")
        else:
            lines.append(tr("Fuel use: needs a full lap"))
        theo = rs.theoretical_best(laps) if laps else None
        if theo:
            lines.append(tr("Ideal lap") + f" <span style='color:{C['purple']}'>{rs.fmt_ms(theo)}</span>")
        stint = rs.current_stint(laps) if laps else []
        if stint:
            valid = [l.lap_time_ms for l in stint if l.valid]
            avg = sum(valid) / len(valid) if valid else None
            lines.append("Stint: " + (tr("1 lap") if len(stint) == 1 else tr("{n} laps", n=len(stint)))
                         + ("  ·  " + tr("average {t}", t=rs.fmt_ms(avg)) if avg else ""))
        age = "  ·  " + (tr("1 lap") if len(stint) == 1 else tr("{n} laps", n=len(stint))) if stint else ""
        lines.append(tr("Tyres {compound}", compound=s.tyre_compound.strip() or "—") + age)
        lines.append(tr("Wear") + " " + " / ".join(f"{x:.1f}" for x in s.tyre_wear))
        lines.append(tr("Air {a}°  ·  track {t}°", a=f"{s.air_temp:.0f}", t=f"{s.road_temp:.0f}"))
        self.strategy.setText("<br>".join(lines))
