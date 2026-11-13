"""
Race: the track coloured by where you gain or lose against your best lap (corner chips explain why), the cars on
it, a side panel (standings, radio with the engineer, car) and the race timeline: past laps on the left of the
cursor, the forecast (planned stop, fuel to the finish, lap times) on the right.
"""

from __future__ import annotations

import time

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtWidgets import (
    QHBoxLayout, QLabel, QLineEdit, QPushButton, QSlider, QTabWidget, QTextBrowser, QVBoxLayout, QWidget,
)

from hub_core.analysis import race_strategy as rs
from hub_core.analysis.lap_analysis import compare_laps, delta_profile
from hub_core.analysis.race_timeline import RaceLog, build_timeline, describe
from hub_core.i18n import tr
from ui import race_view as rv
from ui.theme import C
from ui.widgets import Card, label
from ui.widgets.car_status import CarStatusView
from ui.widgets.race_timeline import TimelineView
from ui.widgets.timing_table import TimingTable
from ui.widgets.track_delta import TrackDeltaMap

WHO = {"radio": ("Radio", "blue"), "driver": ("Driver", "green"), "engineer": ("AI engineer", "purple"),
       "question": ("You", "text"), "remote": ("Remote", "yellow"), "system": ("System", "dim")}
SUGGESTED = ("Where am I losing time?", "When should I pit?", "Can I catch the car ahead?")


def _h(text: str) -> QLabel:
    lb = QLabel(text.upper())
    lb.setStyleSheet(f"color: {C['dim']}; font-size: 8pt; font-weight: 600; letter-spacing: 1.3px;")
    return lb


class RacePage(QWidget):
    def __init__(self, hub):
        super().__init__()
        self.hub = hub
        self.log = RaceLog()
        self.timeline = None
        self._corners: list[dict] = []
        self._chip_src: list[dict] = []
        self._unread = 0
        self._follow = True

        root = QVBoxLayout(self)
        root.setContentsMargins(14, 10, 14, 14)
        root.setSpacing(10)
        top = QHBoxLayout()
        top.setSpacing(10)

        # --- track map
        mapcard = Card()
        ml = QVBoxLayout(mapcard)
        ml.setContentsMargins(12, 10, 12, 12)
        head = QHBoxLayout()
        head.addWidget(_h(tr("Against your best lap")))
        legend = QLabel(f"<span style='color:{C['green']}'>" + tr("green") + "</span> " + tr("you gain") + "  ·  "
                        f"<span style='color:{C['red']}'>" + tr("red") + "</span> " + tr("you lose"))
        legend.setStyleSheet(f"color: {C['dim']};")
        head.addStretch()
        head.addWidget(legend)
        ml.addLayout(head)
        self.map = TrackDeltaMap()
        self.map.corner_clicked.connect(self._on_corner)
        ml.addWidget(self.map, 1)
        self.corner = QLabel(tr("Corners appear after two timed laps: tap one on the map to see why."))
        self.corner.setWordWrap(True)
        self.corner.setStyleSheet(f"background: {C['panel2']}; border-radius: {C['radius']}px; padding: 8px 10px;")
        ml.addWidget(self.corner)
        top.addWidget(mapcard, 3)

        # --- side panel
        self.tabs = QTabWidget()
        self.tabs.setDocumentMode(True)
        self.timing = TimingTable()
        self.tabs.addTab(self.timing, tr("Standings"))
        radio = QWidget()
        rl = QVBoxLayout(radio)
        rl.setContentsMargins(4, 8, 4, 4)
        self.feed = QTextBrowser()
        self.feed.setOpenLinks(False)
        rl.addWidget(self.feed, 1)
        self.props_box = QVBoxLayout()
        rl.addLayout(self.props_box)
        ask = QHBoxLayout()
        self.ask = QLineEdit()
        self.ask.setPlaceholderText(tr("Ask the engineer…"))
        self.ask.returnPressed.connect(lambda: self._ask(self.ask.text()))
        send = QPushButton(tr("Ask"))
        send.setObjectName("primary")
        send.clicked.connect(lambda: self._ask(self.ask.text()))
        ask.addWidget(self.ask, 1)
        ask.addWidget(send)
        rl.addLayout(ask)
        chips = QHBoxLayout()
        for q in SUGGESTED:
            b = QPushButton(tr(q))
            b.setStyleSheet(f"QPushButton {{ border-radius: 11px; padding: 3px 10px; font-size: 8.5pt; }}")
            b.clicked.connect(lambda _=False, q=q: self._ask(tr(q)))
            chips.addWidget(b)
        chips.addStretch()
        rl.addLayout(chips)
        self.tabs.addTab(radio, tr("Radio"))
        car = QWidget()
        cl = QVBoxLayout(car)
        self.car_view = CarStatusView()
        cl.addWidget(self.car_view, 1)
        self.car_info = label("", "dim")
        self.car_info.setTextFormat(Qt.TextFormat.RichText)
        self.alerts = QLabel()
        cl.addWidget(self.car_info)
        cl.addWidget(self.alerts)
        self.tabs.addTab(car, tr("Car"))
        self.tabs.currentChanged.connect(self._on_tab)
        self.tabs.setMinimumWidth(380)
        top.addWidget(self.tabs, 2)
        root.addLayout(top, 1)

        # --- race timeline
        tlcard = Card()
        tl = QVBoxLayout(tlcard)
        tl.setContentsMargins(14, 10, 14, 12)
        th = QHBoxLayout()
        th.addWidget(_h(tr("Race timeline")))
        self.tl_note = label(tr("drag to review the past or see the forecast"), "dim")
        th.addWidget(self.tl_note, 1)
        live = QPushButton(tr("Back to live"))
        live.clicked.connect(self._back_to_live)
        th.addWidget(live)
        tl.addLayout(th)
        self.tl_view = TimelineView()
        tl.addWidget(self.tl_view)
        self.scrub = QSlider(Qt.Orientation.Horizontal)
        self.scrub.setRange(1, 1)
        self.scrub.valueChanged.connect(self._on_scrub)
        tl.addWidget(self.scrub)
        root.addWidget(tlcard)

        hub.lap_completed.connect(self._on_lap)
        hub.session_changed.connect(self._on_session)
        hub.radio_log.connect(self._on_radio)
        hub.engineer_started.connect(lambda q, mode: self._add("question", q) if mode != "RADIO" else None)
        hub.engineer_done.connect(lambda a: self._add("engineer", a) if a else None)
        hub.proposals_changed.connect(self._fill_proposals)
        self._prop_rows: list[QWidget] = []
        self._fill_proposals()
        self.timer = QTimer(self)
        self.timer.timeout.connect(self._tick)
        self.timer.start(100)
        self._rebuild()

    # ------------------------------------------------------------- laps: comparison and timeline
    def _on_session(self, _info):
        self.log.reset()
        self.map.clear_trail()
        self.map.set_delta([], [])
        self._corners = []
        self._rebuild()

    def _on_lap(self, lap):
        laps = list(self.hub.laps)
        prev = laps[-2] if len(laps) >= 2 else None
        s = self.hub.last_sample
        self.log.add(lap, s.position if s is not None else None, prev)
        self._compare(laps)
        self._rebuild()

    def _compare(self, laps):
        """Last lap against the best one (against the previous best when the last one is the best)."""
        timed = [l for l in laps if l.valid and l.channels and l.lap_time_ms > 0]
        if len(timed) < 2 or not laps[-1].channels:
            return
        last = laps[-1]
        ranked = sorted(timed, key=lambda l: l.lap_time_ms)
        ref = ranked[0] if ranked[0] is not last else ranked[1]
        length = float(self.hub.session_info.get("track_length") or 0) or 5000.0
        try:
            res = compare_laps(ref.channels, last.channels, length)
            prof = delta_profile(ref.channels, last.channels, length)
        except (KeyError, ValueError, IndexError):
            return
        self._corners = res["corners"]
        chips = [{"frac": c["apex_m"] / length, "label": rv.corner_label(c), "lost": c["time_lost_s"]}
                 for c in self._corners if abs(c["time_lost_s"]) >= 0.02]
        self._chip_src = [c for c in self._corners if abs(c["time_lost_s"]) >= 0.02]
        self.map.set_delta(prof, chips)
        worst = max(self._chip_src, key=lambda c: c["time_lost_s"], default=None)
        self.corner.setText(tr("Lap {a} against lap {b}: {d}. Tap a corner on the map.", a=last.lap_no,
                               b=ref.lap_no, d=f"{res['final_delta_s']:+.2f} s")
                            + ("  " + tr("Most time lost in corner {n}.", n=worst["corner"])
                               if worst is not None and worst["time_lost_s"] > 0.02 else ""))

    def _on_corner(self, i: int):
        c = self._chip_src[i]
        self.corner.setText(f"<b>{tr('Corner {n}', n=c['corner'])}</b> · {rv.corner_text(c)}")

    def _rebuild(self):
        hub, s = self.hub, self.hub.last_sample
        prog = rv.progress(hub, s)
        to_go = prog.to_go if prog is not None and hub.is_race else None
        tank = float(hub.session_info.get("max_fuel") or 0) or None
        self.timeline = build_timeline(self.log, list(hub.laps), to_go, s.fuel if s is not None else None, tank,
                                       hub.setting("strategy/pit_loss", 25.0, float))
        self.tl_view.set_timeline(self.timeline)
        self.scrub.blockSignals(True)
        self.scrub.setRange(1, max(1, self.timeline.total))
        if self._follow:
            self.scrub.setValue(max(1, self.timeline.done))
        self.scrub.blockSignals(False)
        self._on_scrub(self.scrub.value(), user=False)

    def _on_scrub(self, lap: int, user: bool = True):
        if user:
            self._follow = self.timeline is not None and lap == self.timeline.done
        self.tl_view.set_cursor(lap)
        if self.timeline is None or self.timeline.done == 0:
            self.tl_note.setText(tr("drag to review the past or see the forecast"))
            return
        future, d = describe(self.timeline, lap)
        bits = []
        if d.get("time"):
            bits.append(d["time"])
        if d.get("position"):
            bits.append(f"P{d['position']}")
        if d.get("fuel") is not None:
            bits.append(f"{d['fuel']:.1f} L")
        if d.get("pit"):
            bits.append(tr("box"))
        if future:
            self.tl_note.setText(tr("forecast · lap {n}", n=lap) + ("  ·  " + "  ·  ".join(bits) if bits else ""))
        elif lap == self.timeline.done:
            self.tl_note.setText(tr("now · lap {n}", n=lap) + ("  ·  " + "  ·  ".join(bits) if bits else ""))
        else:
            self.tl_note.setText(tr("review · lap {n}", n=lap) + ("  ·  " + "  ·  ".join(bits) if bits else ""))

    def _back_to_live(self):
        self._follow = True
        if self.timeline is not None:
            self.scrub.setValue(max(1, self.timeline.done))

    # ------------------------------------------------------------- radio and engineer
    def _add(self, who: str, text: str):
        name, col = WHO.get(who, (who, "dim"))
        when = time.strftime("%H:%M")
        self.feed.append(f"<div style='margin:4px 0'><span style='color:{C['dim']}; font-size:8pt'>"
                         f"{tr(name).upper()} · {when}</span><br><span style='color:{C[col]}'>"
                         f"{text.replace('<', '&lt;')}</span></div>")
        if self.tabs.currentIndex() != 1:
            self._unread += 1
            self.tabs.setTabText(1, tr("Radio") + f" ({self._unread})")

    def _on_radio(self, who: str, text: str):
        self._add(who, text)

    def _on_tab(self, i: int):
        if i == 1:
            self._unread = 0
            self.tabs.setTabText(1, tr("Radio"))

    def _ask(self, q: str):
        q = q.strip()
        if not q:
            return
        if self.hub.ask_engineer(q, "ANALYSIS"):
            self.ask.clear()
        else:
            self._add("system", tr("The engineer is busy or not available"))

    def _fill_proposals(self):
        for w in self._prop_rows:
            w.deleteLater()
        self._prop_rows = []
        for p in self.hub.pending()[-3:]:
            row = QWidget()
            row.setStyleSheet(f"background: {C['panel2']}; border-left: 3px solid {C['accent']};")
            lay = QHBoxLayout(row)
            lay.setContentsMargins(8, 4, 4, 4)
            text = QLabel(p.describe())
            text.setToolTip(p.reason)
            ok = QPushButton(tr("Confirm"))
            ok.setObjectName("primary")
            ok.clicked.connect(lambda _=False, pid=p.id: self.hub.apply_proposal(pid))
            no = QPushButton(tr("Discard"))
            no.clicked.connect(lambda _=False, pid=p.id: self.hub.discard_proposal(pid))
            lay.addWidget(text, 1)
            lay.addWidget(ok)
            lay.addWidget(no)
            self.props_box.addWidget(row)
            self._prop_rows.append(row)

    # ------------------------------------------------------------- live refresh
    def _tick(self):
        if not self.isVisible():
            return
        hub = self.hub
        s, info, fpl, alerts = rv.live_state(hub)
        rv.update_gps(hub, self.map, s, {})
        names = {r.index: r.driver for r in hub.standings_rows}
        cars = self.map.cars
        for c in cars:
            if not c.get("me"):
                c["label"] = rv.short_name(names.get(c["idx"], ""))
        self.map.update()
        self.timing.fill(rv.timing_rows(hub, s, {}))
        if self.tabs.currentIndex() == 2:
            self.car_view.set_sample(s, info)
            self.car_info.setText(rv.car_info_html(hub, s, fpl))
            self.alerts.setText(rv.alerts_html(s, alerts, 6))

    def showEvent(self, e):
        super().showEvent(e)
        self._rebuild()
