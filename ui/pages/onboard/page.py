"""Live onboard — up to 4 onboards at once with TV graphics, track GPS and car status."""

from __future__ import annotations

import time

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtWidgets import (
    QComboBox, QGridLayout, QHBoxLayout, QPushButton, QSlider, QSplitter, QTabWidget, QVBoxLayout, QWidget,
)

from hub_core.ac.onboard_feed import (
    DEFAULT_EXPOSURE, DEFAULT_TONEMAP, QUALITIES, SECONDARY_QUALITY, VIEWS, ViewRequest, camera_menu,
)
from ui import race_view as rv
from ui.race_view import STALE_S
from ui.theme import C
from ui.widgets import Card, label
from ui.widgets.car_status import CarStatusView
from ui.widgets.gps import GPSView
from ui.widgets.onboard_hud import frame_image
from ui.widgets.timing_table import TimingTable
from ui.widgets.view_panel import ViewPanel
from hub_core.i18n import tr


class OnboardPage(QWidget):
    LAYOUTS = ["1 onboard", "1 + 1", "1 + 2", "1 + 3"]
    DEFAULT_CAMERAS = [0, 7, 3, 2]      # T-cam, chase, front left wheel, rear

    def __init__(self, hub):
        super().__init__()
        self.hub = hub
        self._beat_t = 0.0
        self._ui_t = 0.0
        self._f6: list[str] = [n for n in hub.setting("onboard/f6_names", "", str).split("|") if n]
        self._cars_key = None

        root = QVBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 16)
        root.setSpacing(10)

        head = QHBoxLayout()
        head.addWidget(label(tr("Live onboard"), "h1"))
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
        self.layout_box.addItems([tr(x) for x in self.LAYOUTS])
        self.layout_box.setCurrentIndex(max(0, min(3, hub.setting("onboard/layout", 0, int))))
        self.layout_box.setToolTip(tr("How many onboards at once: each one is an extra view rendered by AC (costs FPS)"))
        self.quality = QComboBox()
        for name, *_ in QUALITIES:
            self.quality.addItem(tr(name))
        self.quality.setCurrentIndex(max(0, min(len(QUALITIES) - 1, hub.setting("onboard/quality", 1, int))))
        self.quality.setToolTip(tr("Main view quality; the others run at 640×360 or 480×270"))
        self.quality.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.quality.setMinimumContentsLength(22)
        self.exposure = QSlider(Qt.Orientation.Horizontal)
        self.exposure.setRange(30, 400)
        self.exposure.setFixedWidth(110)
        self.exposure.setValue(round(100 * hub.setting("onboard/exposure", DEFAULT_EXPOSURE, float)))
        self.exposure.setToolTip(tr("Video exposure: the extra view has none of the game's post-processing"))
        for w in (label(tr("Views"), "dim"), self.layout_box, label(tr("Quality"), "dim"), self.quality,
                  label(tr("Brightness"), "dim"), self.exposure):
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
        # top: standings and car status in tabs; bottom: the map, large
        self.side_tabs = QTabWidget()
        self.timing = TimingTable()
        self.timing.setToolTip(tr("Click a car to watch it in the main view"))
        self.timing.car_clicked.connect(self._on_gps_click)
        self.side_tabs.addTab(self.timing, tr("Standings"))
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
        self.side_tabs.addTab(status_page, tr("Car status"))
        self.side_tabs.setCurrentIndex(max(0, min(1, hub.setting("onboard/side_tab", 0, int))))
        self.side_tabs.currentChanged.connect(lambda i: hub.settings.setValue("onboard/side_tab", i))
        side.addWidget(self.side_tabs)
        gps_card = Card()
        gl = QVBoxLayout(gps_card)
        gl.setContentsMargins(12, 10, 12, 12)
        gl.addWidget(label(tr("GPS · TRACK POSITION"), "dim"))
        self.gps = GPSView()
        self.gps.setToolTip(tr("Click a car to watch it in the main view"))
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

    # ------------------------------------------------------------- controls
    @property
    def _n_views(self) -> int:
        return self.layout_box.currentIndex() + 1

    def _video_label(self):
        self.video_btn.setText(tr("Video on") if self.video_btn.isChecked() else tr("Video off"))

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
        """Swap onboard k with the main one."""
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
        others = [(r.index, f"P{r.pos}  {r.driver or tr('car {n}', n=r.index)}") for r in rows if not r.is_player]
        if others == self._cars_key:
            return
        self._cars_key = others
        for k, panel in enumerate(self.panels):
            panel.fill_cars(others, self.hub.setting(f"onboard/view{k}/car", -1, int))

    def _on_session(self, info: dict):
        self._fill_cars([])
        self.gps.clear_trail()

    def _sync_cameras(self):
        """Refresh the lists when the app finds (or changes) the car's F6 cameras."""
        f6 = self.feed.f6_cameras()
        if not f6 or f6 == self._f6:
            return
        self._f6 = f6
        self.hub.settings.setValue("onboard/f6_names", "|".join(f6))
        menu = camera_menu(f6)
        for panel in self.panels:
            panel.fill_cameras(menu, panel.camera_index())

    @property
    def feed(self):
        return self.hub.onboard_feed

    def _push_request(self) -> bool:
        if not self.hub.ac_live or not self.isVisible():    # the link is shared with the Overview page
            return False
        n = self._n_views
        on = self.video_btn.isChecked()
        _name, w, h, fps = QUALITIES[self.quality.currentIndex()]
        _sname, sw, sh, sfps = SECONDARY_QUALITY if n == 2 else QUALITIES[0]
        views = []
        for k, panel in enumerate(self.panels):
            size = (w, h, fps) if k == 0 else (sw, sh, sfps)
            views.append(ViewRequest(on and k < n, panel.camera_index(), panel.car_index(), *size))
        self._beat_t = time.monotonic()
        return self.feed.request(views, self.exposure.value() / 100, DEFAULT_TONEMAP)

    def hideEvent(self, e):
        self.feed.disconnect()          # no rendering in AC while the page is hidden
        super().hideEvent(e)

    # ------------------------------------------------------------- refresh
    def _tick(self):
        if not self.isVisible():
            return
        now = time.monotonic()
        if self.hub.ac_live and self.video_btn.isChecked():
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
        if now - self._ui_t >= 0.066:       # graphics, GPS and status at 15 Hz, video every frame
            self._ui_t = now
            self._refresh()

    def _placeholder(self, k: int) -> str:
        return rv.video_placeholder(self.hub, k == 0, self.panels[k].img is not None,
                                    self.video_btn.isChecked(), k)

    def _refresh(self):
        self._sync_cameras()
        now = time.monotonic()
        s, info, fpl, alerts = rv.live_state(self.hub)
        live_any = False
        for k in range(self._n_views):
            panel = self.panels[k]
            if not self.hub.ac_live:
                panel.img = None
            live = panel.img is not None and now - panel.frame_t < STALE_S
            live_any |= live
            panel.view.set_frame(panel.img, live)
            panel.view.set_hud(self._hud(k, s, alerts), self._placeholder(k) if not live else "")
        self.car_view.set_sample(s, info)
        self.info.setText(rv.car_info_html(self.hub, s, fpl))
        self.alerts.setText(rv.alerts_html(s, alerts))
        rings = self._view_rings()
        rv.update_gps(self.hub, self.gps, s, rings)
        self.timing.fill(rv.timing_rows(self.hub, s, rings))
        self._fill_status(live_any)

    def _hud(self, k: int, s, alerts) -> dict:
        panel = self.panels[k]
        args = (panel.car_index(), panel.camera.currentText(), panel.car.currentText())
        return rv.main_hud(self.hub, s, alerts, *args) if k == 0 else rv.small_hud(self.hub, s, *args)

    def _view_rings(self) -> dict[int, str]:
        return rv.view_rings([self.panels[k].car_index() for k in range(self._n_views)])

    def _fill_status(self, live_video: bool):
        parts = []
        if live_video:
            inf = self.feed.info()
            if inf is not None:
                views = tr("1 view") if self._n_views == 1 else tr("{n} views", n=self._n_views)
                parts.append(f"<span style='color:{C['green']}'>●</span>  "
                             + tr("Live video · {views} · AC at {fps} FPS", views=views, fps=f"{inf.game_fps:.0f}"))
        elif self.hub.ac_live and self.video_btn.isChecked() and self.feed.connected:
            parts.append(f"<span style='color:{C['yellow']}'>●</span>  " + tr("Video not live"))
        if self.feed.shared_error:
            parts.append(tr("shared texture not available, using the slower path"))
        if any(self.panels[k].car_index() >= 0 for k in range(self._n_views)):
            parts.append(tr("car status is always your own car's"))
        self.status.setText("  ·  ".join(parts) if parts else
                            tr("Extra views rendered by AC through the CSP app; GPS from the car positions; damage, "
                               "tyres, brakes and suspension from the shared memory."))
