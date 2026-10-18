"""Modulo 1b: Onboard live — fino a 4 onboard insieme con grafica TV, GPS della pista e stato della vettura."""

from __future__ import annotations

import time

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtWidgets import (
    QComboBox, QGridLayout, QHBoxLayout, QPushButton, QSlider, QSplitter, QTabWidget, QVBoxLayout, QWidget,
)

from hub_core.ac.csp_bridge import find_ac_root
from hub_core.ac.onboard_feed import (
    DEFAULT_EXPOSURE, DEFAULT_TONEMAP, QUALITIES, SECONDARY_QUALITY, VIEWS, OnboardFeed, ViewRequest, camera_menu,
)
from hub_core.ac.track_map import find_track_map
from hub_core.analysis import car_status as cs
from hub_core.analysis.race_strategy import fmt_ms, fuel_per_lap
from hub_core.analysis.timing import fmt_gap
from hub_core.model import ACStatus, gear_label
from ui.pages.onboard.hud import frame_image
from ui.pages.onboard.panel import VIEW_COLORS, ViewPanel
from ui.theme import C
from ui.widgets import Card, label
from ui.widgets.car_status import LEVEL_COLORS, CarStatusView
from ui.widgets.gps import GPSView
from ui.widgets.timing_table import TimingTable
from ui.workers import SOURCE_AC

STALE_S = 2.0          # senza fotogrammi nuovi da tanto: il video non è più in diretta


class OnboardPage(QWidget):
    LAYOUTS = ["1 onboard", "1 + 1", "1 + 2", "1 + 3"]
    DEFAULT_CAMERAS = [0, 7, 3, 2]      # T-cam, inseguimento, ruota ant. sx, posteriore

    def __init__(self, hub):
        super().__init__()
        self.hub = hub
        self.feed = OnboardFeed()
        self._beat_t = 0.0
        self._ui_t = 0.0
        self._f6: list[str] = [n for n in hub.setting("onboard/f6_names", "", str).split("|") if n]
        self._cars_key = None

        root = QVBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 16)
        root.setSpacing(10)

        head = QHBoxLayout()
        head.addWidget(label("Onboard live", "h1"))
        head.addStretch()
        self.video_btn = QPushButton()
        self.video_btn.setCheckable(True)
        self.video_btn.setChecked(hub.setting("onboard/video", True, bool))
        self._video_label()
        self.video_btn.toggled.connect(self._on_video_toggled)
        head.addWidget(self.video_btn)
        root.addLayout(head)

        controls = QHBoxLayout()
        self.layout_box = QComboBox()
        self.layout_box.addItems(self.LAYOUTS)
        self.layout_box.setCurrentIndex(max(0, min(3, hub.setting("onboard/layout", 0, int))))
        self.layout_box.setToolTip("Quanti onboard insieme: ognuno è una vista in più resa da AC (costa FPS)")
        self.quality = QComboBox()
        for name, *_ in QUALITIES:
            self.quality.addItem(name)
        self.quality.setCurrentIndex(max(0, min(len(QUALITIES) - 1, hub.setting("onboard/quality", 1, int))))
        self.quality.setToolTip("Qualità del riquadro principale; gli altri vanno a 640×360 o 480×270")
        self.quality.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.quality.setMinimumContentsLength(22)
        self.exposure = QSlider(Qt.Orientation.Horizontal)
        self.exposure.setRange(30, 400)
        self.exposure.setFixedWidth(110)
        self.exposure.setValue(round(100 * hub.setting("onboard/exposure", DEFAULT_EXPOSURE, float)))
        self.exposure.setToolTip("Esposizione del video: la vista in più non ha il post-processing del gioco")
        for w in (label("Riquadri", "dim"), self.layout_box, label("Qualità", "dim"), self.quality,
                  label("Luminosità", "dim"), self.exposure):
            controls.addWidget(w)
        controls.addStretch()
        root.addLayout(controls)

        self.status = label("", "dim")
        root.addWidget(self.status)

        body = QHBoxLayout()
        body.setSpacing(12)
        self.grid = QGridLayout()
        self.grid.setSpacing(10)
        self.panels = [ViewPanel(k) for k in range(VIEWS)]
        menu = camera_menu(self._f6)
        for k, panel in enumerate(self.panels):
            panel.fill_cameras(menu, hub.setting(f"onboard/view{k}/camera", self.DEFAULT_CAMERAS[k], int))
            panel.changed.connect(lambda k=k: self._on_panel_changed(k))
            panel.make_main.connect(self._make_main)
            if k == 0:
                self.grid.addWidget(panel, 0, 0, 3, 1)
            else:
                self.grid.addWidget(panel, k - 1, 1)
        body.addLayout(self.grid, 1)

        side = QSplitter(Qt.Orientation.Vertical)
        side.setFixedWidth(300)
        side.setChildrenCollapsible(False)
        # sopra: classifica e stato vettura in schede; sotto: la mappa, grande
        self.side_tabs = QTabWidget()
        self.timing = TimingTable()
        self.timing.setToolTip("Clic su un'auto per vederla nel riquadro principale")
        self.timing.car_clicked.connect(self._on_gps_click)
        self.side_tabs.addTab(self.timing, "Classifica")
        status_page = QWidget()
        sl = QVBoxLayout(status_page)
        sl.setContentsMargins(8, 8, 8, 8)
        self.car_view = CarStatusView()
        sl.addWidget(self.car_view, 1)
        self.info = label("", "dim")
        self.info.setWordWrap(True)
        sl.addWidget(self.info)
        self.alerts = label("")
        self.alerts.setWordWrap(True)
        self.alerts.setTextFormat(Qt.TextFormat.RichText)
        self.alerts.setAlignment(Qt.AlignmentFlag.AlignTop)
        sl.addWidget(self.alerts)
        self.side_tabs.addTab(status_page, "Stato vettura")
        self.side_tabs.setCurrentIndex(max(0, min(1, hub.setting("onboard/side_tab", 0, int))))
        self.side_tabs.currentChanged.connect(lambda i: hub.settings.setValue("onboard/side_tab", i))
        side.addWidget(self.side_tabs)
        gps_card = Card()
        gl = QVBoxLayout(gps_card)
        gl.setContentsMargins(12, 10, 12, 12)
        gl.addWidget(label("GPS · POSIZIONE IN PISTA", "dim"))
        self.gps = GPSView()
        self.gps.setToolTip("Clic su un'auto per vederla nel riquadro principale")
        self.gps.car_clicked.connect(self._on_gps_click)
        gl.addWidget(self.gps, 1)
        side.addWidget(gps_card)
        side.setSizes([400, 380])
        body.addWidget(side)
        root.addLayout(body, 1)

        self.layout_box.currentIndexChanged.connect(self._on_layout)
        self.quality.currentIndexChanged.connect(lambda i: (hub.settings.setValue("onboard/quality", i),
                                                            self._push_request()))
        self.exposure.valueChanged.connect(lambda v: (hub.settings.setValue("onboard/exposure", v / 100),
                                                      self._push_request()))
        hub.standings_changed.connect(self._fill_cars)
        hub.session_changed.connect(self._on_session)
        hub.running_changed.connect(lambda _: self._refresh())
        self._restore_cars()
        self._on_layout(self.layout_box.currentIndex(), save=False)

        self.timer = QTimer(self)
        self.timer.timeout.connect(self._tick)
        self.timer.start(33)

    # ------------------------------------------------------------- controlli
    @property
    def _n_views(self) -> int:
        return self.layout_box.currentIndex() + 1

    def _video_label(self):
        self.video_btn.setText("Video acceso" if self.video_btn.isChecked() else "Video spento")

    def _on_video_toggled(self, on: bool):
        self.hub.settings.setValue("onboard/video", on)
        self._video_label()
        self._push_request()

    def _on_layout(self, i: int, save: bool = True):
        if save:
            self.hub.settings.setValue("onboard/layout", i)
        n = i + 1
        for k, panel in enumerate(self.panels):
            panel.setVisible(k < n)
        self.grid.setColumnStretch(0, 2)
        self.grid.setColumnStretch(1, 1 if n > 1 else 0)
        self._push_request()

    def _on_panel_changed(self, k: int):
        panel = self.panels[k]
        self.hub.settings.setValue(f"onboard/view{k}/camera", panel.camera_index())
        self.hub.settings.setValue(f"onboard/view{k}/car", panel.car_index())
        panel.img = None
        self._push_request()

    def _make_main(self, k: int):
        """Scambia l'onboard k con quello principale."""
        a, b = self.panels[0], self.panels[k]
        sel_a, sel_b = (a.car_index(), a.camera_index()), (b.car_index(), b.camera_index())
        a.select(*sel_b)
        b.select(*sel_a)
        a.img = b.img = None
        for i in (0, k):
            self._on_panel_changed(i)

    def _on_gps_click(self, idx: int):
        main = self.panels[0]
        main.select(-1 if idx == 0 else idx, main.camera_index())
        self._on_panel_changed(0)

    def _restore_cars(self):
        for k, panel in enumerate(self.panels):
            panel.select(self.hub.setting(f"onboard/view{k}/car", -1, int), panel.camera_index())

    def _fill_cars(self, rows):
        others = [(r.index, f"P{r.pos}  {r.driver or 'auto ' + str(r.index)}") for r in rows if not r.is_player]
        if others == self._cars_key:
            return
        self._cars_key = others
        for k, panel in enumerate(self.panels):
            panel.fill_cars(others, self.hub.setting(f"onboard/view{k}/car", -1, int))

    def _on_session(self, info: dict):
        self._fill_cars([])
        self.gps.clear_trail()
        tmap = None
        try:
            tmap = find_track_map(find_ac_root(), info.get("track_id", ""), info.get("track_config", ""))
        except OSError:
            pass
        self.gps.set_map(tmap)

    def _sync_cameras(self):
        """Aggiorna gli elenchi quando l'app trova (o cambia) le telecamere F6 dell'auto."""
        f6 = self.feed.f6_cameras()
        if not f6 or f6 == self._f6:
            return
        self._f6 = f6
        self.hub.settings.setValue("onboard/f6_names", "|".join(f6))
        menu = camera_menu(f6)
        for panel in self.panels:
            panel.fill_cameras(menu, panel.camera_index())

    @property
    def _ac_live(self) -> bool:
        w = self.hub.worker
        return self.hub.running and w is not None and w.source == SOURCE_AC

    def _push_request(self) -> bool:
        if not self._ac_live:
            return False
        n = self._n_views
        on = self.video_btn.isChecked() and self.isVisible()
        _name, w, h, fps = QUALITIES[self.quality.currentIndex()]
        _sname, sw, sh, sfps = SECONDARY_QUALITY if n == 2 else QUALITIES[0]
        views = []
        for k, panel in enumerate(self.panels):
            size = (w, h, fps) if k == 0 else (sw, sh, sfps)
            views.append(ViewRequest(on and k < n, panel.camera_index(), panel.car_index(), *size))
        self._beat_t = time.monotonic()
        return self.feed.request(views, self.exposure.value() / 100, DEFAULT_TONEMAP)

    def hideEvent(self, e):
        self.feed.disconnect()          # niente rendering in AC mentre la pagina non si vede
        super().hideEvent(e)

    # ------------------------------------------------------------- aggiornamento
    def _tick(self):
        if not self.isVisible():
            return
        now = time.monotonic()
        if self._ac_live and self.video_btn.isChecked():
            if now - self._beat_t > 0.5:
                self._push_request()
            for k in range(self._n_views):
                frame = self.feed.new_frame(k)
                if frame is not None:
                    img = frame_image(frame)
                    if not img.isNull():
                        self.panels[k].img, self.panels[k].frame_t = img, now
        elif self.feed.connected:
            self.feed.disconnect()
        if now - self._ui_t >= 0.066:       # grafica, GPS e stato a 15 Hz, il video a ogni fotogramma
            self._ui_t = now
            self._refresh()

    def _placeholder(self, k: int) -> str:
        if not self.hub.running:
            return "Acquisizione ferma: avvia la telemetria da Assetto Corsa." if k == 0 else ""
        if not self._ac_live:
            return ("Il video onboard arriva solo da Assetto Corsa. In demo e replay restano grafica, GPS e "
                    "stato vettura." if k == 0 else "Solo con Assetto Corsa")
        if not self.video_btn.isChecked():
            return "Video spento: in AC non si rendono le viste in più (più FPS in gioco)."
        if not self.feed.connected:
            return ("App CSP Delta Suite Bridge non collegata o da aggiornare: aggiornala da Box & Assetto."
                    if k == 0 else "App CSP non collegata")
        inf = self.feed.info(k)
        if inf is not None and inf.status.startswith("errore"):
            return f"L'app CSP non riesce a rendere l'onboard: {inf.status}"
        if self.panels[k].img is None:
            return "In attesa del primo fotogramma…"
        return ""

    def _refresh(self):
        self._sync_cameras()
        now = time.monotonic()
        s = self.hub.last_sample
        info = self.hub.session_info
        laps = self.hub.laps
        fpl = fuel_per_lap(laps) if laps else None
        alerts = cs.car_alerts(s, info, fpl) if s is not None and s.status == ACStatus.LIVE else []
        live_any = False
        for k in range(self._n_views):
            panel = self.panels[k]
            if not self._ac_live:
                panel.img = None
            live = panel.img is not None and now - panel.frame_t < STALE_S
            live_any |= live
            panel.view.set_frame(panel.img, live)
            panel.view.set_hud(self._hud(k, s, alerts), self._placeholder(k) if not live else "")
        self.car_view.set_sample(s, info)
        self._fill_side(s, alerts, fpl)
        self._fill_gps(s)
        self._fill_timing(s)
        self._fill_status(live_any)

    def _entry(self, idx: int):
        b = self.hub.bridge_state
        return next((c for c in (b.cars if b else []) if c.index == idx), None)

    def _hud(self, k: int, s, alerts) -> dict:
        panel = self.panels[k]
        idx, cam = panel.car_index(), panel.camera.currentText()
        if k > 0:       # riquadri piccoli: chi, quale telecamera, distacco e ultimo giro
            if idx < 0:
                who = self.hub.session_info.get("player") or "La mia auto"
                row = next((r for r in self.hub.standings_rows if r.is_player), None)
                if s is not None:
                    who = f"P{s.position}  {who}"
                last = s.last_lap_ms if s is not None else 0
            else:
                entry = self._entry(idx)
                row = next((r for r in self.hub.standings_rows if r.index == idx), None)
                who = f"P{entry.race_pos}  {entry.driver or 'auto ' + str(idx)}" if entry else panel.car.currentText()
                last = entry.last_lap_ms if entry else 0
            times = [("DISTACCO", fmt_gap(row), None)] if row is not None else []
            times.append(("ULTIMO", fmt_ms(last), None))
            return {"title": who, "camera": cam, "times": times}
        if idx >= 0:
            entry = self._entry(idx)
            row = next((r for r in self.hub.standings_rows if r.index == idx), None)
            if entry is None:
                return {"title": panel.car.currentText(), "camera": cam}
            times = [("POSIZIONE", f"P{entry.race_pos}", None), ("GIRO", str(entry.lap_count + 1), None),
                     ("TEMPO", fmt_ms(entry.lap_time_ms), None), ("ULTIMO", fmt_ms(entry.last_lap_ms), None),
                     ("MIGLIORE", fmt_ms(entry.best_lap_ms), C["purple"])]
            if row is not None and row.interval_s is not None:
                times.append(("INTERVAL", f"+{row.interval_s:.1f}", None))
            return {"title": f"{entry.driver or 'Auto ' + str(idx)}  ·  {entry.model}", "camera": cam,
                    "speed": entry.speed_kmh, "times": times}
        if s is None:
            return {}
        info = self.hub.session_info
        max_rpm = max(1000, int(info.get("max_rpm") or 9000))
        player = info.get("player") or "Tu"
        hud = {
            "title": f"{player}  ·  {info.get('car', '')}", "camera": cam,
            "speed": s.speed_kmh, "gear": gear_label(s.gear), "rpm": s.rpm, "rpm_frac": s.rpm / max_rpm,
            "shift": s.rpm > 0.95 * max_rpm, "gas": s.gas, "brake": s.brake, "steer": s.steer_angle,
            "times": [("POSIZIONE", f"P{s.position}", None), ("GIRO", f"{s.completed_laps + 1}"
                                                             + ("  PIT" if s.is_in_pit else ""), None),
                      ("TEMPO", fmt_ms(s.lap_time_ms), None), ("ULTIMO", fmt_ms(s.last_lap_ms), None),
                      ("MIGLIORE", fmt_ms(s.best_lap_ms), C["purple"])],
        }
        if alerts:
            hud["alert"] = (alerts[0].level, alerts[0].text)
        return hud

    def _view_rings(self) -> dict[int, str]:
        """Colore del riquadro per ogni auto inquadrata (0 = la tua)."""
        rings = {}
        for k in range(self._n_views):
            idx = self.panels[k].car_index()
            rings.setdefault(0 if idx < 0 else idx, VIEW_COLORS[k])
        return rings

    def _fill_timing(self, s):
        rings = self._view_rings()
        rows = [(r.index, str(r.pos), r.driver or f"auto {r.index}", fmt_gap(r),
                 "BOX" if r.in_pit else fmt_ms(r.last_ms), r.is_player, rings.get(r.index))
                for r in self.hub.standings_rows]
        if not rows and s is not None and s.status == ACStatus.LIVE:     # senza app CSP o in demo: solo tu
            rows = [(0, str(s.position), self.hub.session_info.get("player") or "Tu", "-",
                     fmt_ms(s.last_lap_ms), True, rings.get(0))]
        self.timing.fill(rows)

    def _fill_gps(self, s):
        if s is not None and s.status == ACStatus.LIVE:
            self.gps.add_trail(s.car_x, s.car_z)
        rings = self._view_rings()
        positions = self.feed.car_positions() if self._ac_live and self.feed.connected else {}
        if not positions and s is not None and s.status == ACStatus.LIVE:
            positions = {0: (s.car_x, s.car_z)}
        b = self.hub.bridge_state
        race_pos = {c.index: c.race_pos for c in b.cars} if b else {}
        connected = {c.index for c in b.cars if c.connected} if b else set()
        cars = []
        for idx, (x, z) in positions.items():
            if idx and connected and idx not in connected:
                continue
            pos = race_pos.get(idx) or (s.position if idx == 0 and s is not None else 0)
            cars.append({"idx": idx, "x": x, "z": z, "me": idx == 0, "ring": rings.get(idx),
                         "label": f"{pos}" if pos else ""})
        self.gps.set_cars(cars)

    def _fill_side(self, s, alerts, fpl):
        if s is None:
            self.info.setText("Nessun dato: avvia l'acquisizione.")
            self.alerts.setText("")
            return
        b = self.hub.bridge_state
        aids = f"ABS {b.abs_mode}/{b.abs_modes}  ·  TC {b.tc_mode}/{b.tc_modes}" if b else \
            f"ABS {s.abs:.1f}  ·  TC {s.tc:.1f}"
        fuel = f"carburante {s.fuel:.1f} L" + (f" (~{s.fuel / fpl:.1f} giri)" if fpl else "")
        self.info.setText(
            f"{fuel}<br>{aids}  ·  bias {s.brake_bias * 100:.1f}%  ·  freno motore {s.engine_brake}<br>"
            f"altezza da terra ant. {s.ride_height[0] * 1000:.0f} mm  ·  post. {s.ride_height[1] * 1000:.0f} mm"
            + ("<br>limitatore pit inserito" if s.pit_limiter else ""))
        if not alerts:
            self.alerts.setText(f"<span style='color:{C['green']}'>●</span>  Tutto in ordine")
            return
        self.alerts.setText("<br>".join(f"<span style='color:{LEVEL_COLORS[a.level]}'>●</span>  {a.text}"
                                        for a in alerts[:6]))

    def _fill_status(self, live_video: bool):
        parts = []
        if live_video:
            inf = self.feed.info()
            if inf is not None:
                parts.append(f"<span style='color:{C['green']}'>●</span>  Video in diretta · "
                             f"{self._n_views} {'riquadro' if self._n_views == 1 else 'riquadri'} · "
                             f"AC a {inf.game_fps:.0f} FPS")
        elif self._ac_live and self.video_btn.isChecked() and self.feed.connected:
            parts.append(f"<span style='color:{C['yellow']}'>●</span>  Video non in diretta")
        if self.feed.shared_error:
            parts.append("texture condivisa non disponibile, si usa la via più lenta")
        if any(self.panels[k].car_index() >= 0 for k in range(self._n_views)):
            parts.append("lo stato vettura è sempre quello della tua auto")
        self.status.setText("  ·  ".join(parts) if parts else
                            "Viste in più rese da AC tramite l'app CSP; GPS dalla posizione delle auto; danni, "
                            "gomme, freni e sospensioni dalla shared memory.")
