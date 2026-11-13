"""
Home: the first view. "Ready to drive?" with what AC is running, the buttons to start, the status of everything
Delta Suite needs (replaces the get-started checklist), the last session, the personal bests and the track.
"""

from __future__ import annotations

import time

from PyQt6.QtCore import Qt, QTimer, pyqtSignal
from PyQt6.QtWidgets import (
    QGridLayout, QHBoxLayout, QLabel, QPushButton, QSizePolicy, QVBoxLayout, QWidget,
)

from hub_core.ac import csp_bridge
from hub_core.analysis import race_strategy as rs
from hub_core.i18n import tr
from hub_core.model import ACStatus
from ui import first_run
from ui.theme import C, rgba
from ui.widgets import Card, label
from ui.widgets.gps import GPSView
from ui.widgets.sparkline import Sparkline
from ui.widgets.topbar import pill_style

STATUS_LABELS = {"ac": "Assetto Corsa", "csp": "CSP app", "wheel": "Radio buttons", "agent": "AI engineer",
                 "voice": "Engineer voice", "stt": "Push-to-talk"}
STATE_PILLS = {first_run.DONE: ("ready", "green"), first_run.WAIT: ("waiting", "yellow"),
               first_run.TODO: ("to fix", "red")}


# ------------------------------------------------------------------ data (pure: tested without Qt)

def last_session(sessions: list[dict], current_id: int | None) -> dict | None:
    """Most recent archived session with laps, not the one running now (unless it is the only one)."""
    done = [s for s in sessions if s.get("laps")]
    others = [s for s in done if s["id"] != current_id]
    return (others or done or [None])[0]


def personal_bests(sessions: list[dict], limit: int = 5) -> list[dict]:
    """Best lap per car and track, the most recently driven combinations first."""
    best: dict[tuple, dict] = {}
    for s in sessions:
        if not s.get("best_ms"):
            continue
        key = (s["car"], s["track"])
        b = best.setdefault(key, {"car": s["car"], "track": s["track"], "best_ms": s["best_ms"],
                                  "last": s["started"], "set": s["started"]})
        if s["best_ms"] < b["best_ms"]:
            b["best_ms"], b["set"] = s["best_ms"], s["started"]
        b["last"] = max(b["last"], s["started"])
    return sorted(best.values(), key=lambda b: b["last"], reverse=True)[:limit]


def greeting(hour: int) -> str:
    return tr("Good morning") if 5 <= hour < 12 else tr("Good afternoon") if 12 <= hour < 18 else tr("Good evening")


# ------------------------------------------------------------------ widgets

def _title(text: str) -> QLabel:
    lb = QLabel(text.upper())
    lb.setStyleSheet(f"color: {C['dim']}; font-size: 8pt; font-weight: 600; letter-spacing: 1.3px;")
    return lb


class StatusRow(QWidget):
    action = pyqtSignal(str)

    def __init__(self):
        super().__init__()
        self.setObjectName("strow")
        self.setStyleSheet(f"QWidget#strow {{ background: {C['panel2']}; border-radius: {C['radius']}px; }}")
        lay = QHBoxLayout(self)
        lay.setContentsMargins(10, 6, 8, 6)
        self.name = QLabel()
        self.pill = QLabel()
        self.btn = QPushButton()
        self.btn.clicked.connect(lambda: self.action.emit(self._key))
        self._key = ""
        lay.addWidget(self.name, 1)
        lay.addWidget(self.pill)
        lay.addWidget(self.btn)

    def set(self, name: str, state_text: str, color: str, tip: str, button: str = "", key: str = ""):
        self.name.setText(name)
        self.pill.setText(state_text)
        self.pill.setStyleSheet(pill_style(color))
        self.setToolTip(tip)
        self.btn.setText(button)
        self.btn.setVisible(bool(button))
        self._key = key


class HomePage(QWidget):
    start_ac = pyqtSignal()
    start_demo = pyqtSignal()
    open_recording = pyqtSignal()
    open_view = pyqtSignal(str)
    action = pyqtSignal(str)          # status list buttons (MainWindow._on_checklist) and "remote"

    def __init__(self, hub):
        super().__init__()
        self.hub = hub
        self._ac_root = None
        self._ac_root_t = -1e9
        root = QVBoxLayout(self)
        root.setContentsMargins(14, 14, 14, 14)
        root.setSpacing(10)

        # --- hero: ready to drive? + status list
        hero = Card()
        hero.setStyleSheet(f"QFrame#card {{ background: qlineargradient(x1:0, y1:0, x2:1, y2:1, "
                           f"stop:0 {rgba(C['accent'], 0.22)}, stop:0.45 {C['panel']}, stop:1 {C['panel']}); }}")
        hl = QHBoxLayout(hero)
        hl.setContentsMargins(26, 22, 26, 22)
        hl.setSpacing(24)
        left = QVBoxLayout()
        self.hello = _title("")
        self.h1 = QLabel(tr("Ready to drive?").upper())
        self.h1.setStyleSheet(f"font-family: '{C['title_font']}'; font-size: 30pt; font-weight: 800;")
        self.intro = QLabel()
        self.intro.setStyleSheet(f"color: {C['text']}; font-size: 10.5pt;")
        self.intro.setWordWrap(True)
        self.intro.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Minimum)
        btns = QHBoxLayout()
        self.go = QPushButton("▶  " + tr("Start acquisition"))
        self.go.setObjectName("primary")
        self.go.clicked.connect(self.start_ac)
        self.demo = QPushButton(tr("Try the demo"))
        self.demo.clicked.connect(self.start_demo)
        self.rec = QPushButton(tr("Open a recording"))
        self.rec.clicked.connect(self.open_recording)
        for b in (self.go, self.demo, self.rec):
            b.setMinimumHeight(36)
            btns.addWidget(b)
        btns.addStretch()
        left.addWidget(self.hello)
        left.addWidget(self.h1)
        left.addWidget(self.intro)
        left.addSpacing(8)
        left.addLayout(btns)
        left.addStretch()
        hl.addLayout(left, 3)
        self.status_box = QVBoxLayout()
        self.status_box.setSpacing(6)
        self.rows: list[StatusRow] = []
        hl.addLayout(self.status_box, 2)
        root.addWidget(hero)
        if hub.db_error:
            root.addWidget(label(f"<span style='color:{C['yellow']}'>"
                                 + tr("Archive not available ({err}): this session's data stays in memory only.",
                                      err=hub.db_error) + "</span>"))

        # --- last session · personal bests · this track
        grid = QGridLayout()
        grid.setSpacing(10)
        last = Card()
        ll = QVBoxLayout(last)
        ll.setContentsMargins(14, 12, 14, 12)
        head = QHBoxLayout()
        head.addWidget(_title(tr("Last session")))
        head.addStretch()
        self.last_when = label("", "dim")
        head.addWidget(self.last_when)
        ll.addLayout(head)
        nums = QHBoxLayout()
        self.last_where = QLabel()
        self.last_where.setStyleSheet(f"color: {C['dim']}; font-size: 8pt;")
        self.last_laps = QLabel("–")
        self.last_laps.setStyleSheet(f"font-family: '{C['title_font']}'; font-size: 24pt; font-weight: 800;")
        self.last_best = QLabel("–")
        self.last_best.setStyleSheet(f"font-family: Consolas; font-size: 16pt; font-weight: 600; color: {C['purple']};")
        self.last_ideal = label("", "dim")
        col1, col2 = QVBoxLayout(), QVBoxLayout()
        col1.addWidget(self.last_where)
        col1.addWidget(self.last_laps)
        col2.addWidget(_title(tr("Best lap")))
        col2.addWidget(self.last_best)
        col2.addWidget(self.last_ideal)
        nums.addLayout(col1, 1)
        nums.addLayout(col2, 1)
        ll.addLayout(nums)
        self.spark = Sparkline()
        ll.addWidget(self.spark)
        ab = QHBoxLayout()
        analyse = QPushButton(tr("Analyse the laps"))
        analyse.clicked.connect(lambda: self.open_view.emit("analysis"))
        ab.addWidget(analyse)
        ab.addStretch()
        ll.addLayout(ab)
        ll.addStretch()

        recs = Card()
        rl = QVBoxLayout(recs)
        rl.setContentsMargins(14, 12, 14, 12)
        rl.addWidget(_title(tr("Personal bests")))
        self.recs_box = QVBoxLayout()
        self.recs_box.setSpacing(6)
        rl.addLayout(self.recs_box)
        rl.addStretch()

        here = Card()
        tl = QVBoxLayout(here)
        tl.setContentsMargins(14, 12, 14, 12)
        tl.addWidget(_title(tr("On this track")))
        row = QHBoxLayout()
        self.map = GPSView()
        self.map.setFixedSize(170, 120)
        row.addWidget(self.map)
        info = QVBoxLayout()
        self.track_name = QLabel("–")
        self.track_name.setStyleSheet("font-weight: 700; font-size: 11pt;")
        self.track_info = label("", "dim")
        info.addWidget(self.track_name)
        info.addWidget(self.track_info)
        info.addStretch()
        row.addLayout(info, 1)
        tl.addLayout(row)
        self.tip = QLabel()
        self.tip.setWordWrap(True)
        self.tip.setStyleSheet(f"background: {C['panel2']}; border-left: 3px solid {C['purple']}; "
                               f"border-radius: {C['radius']}px; padding: 8px 10px;")
        tl.addWidget(self.tip)
        tl.addStretch()

        for i, w in enumerate((last, recs, here)):
            grid.addWidget(w, 0, i)
            grid.setColumnStretch(i, 1)
        root.addLayout(grid)
        root.addStretch()

        for sig in (hub.db_changed, hub.running_changed, hub.session_changed):
            sig.connect(lambda *_: self.refresh() if self.isVisible() else None)
        self.timer = QTimer(self)
        self.timer.timeout.connect(lambda: self.refresh() if self.isVisible() else None)
        self.timer.start(3000)

    def showEvent(self, e):
        super().showEvent(e)
        self.refresh()

    # ------------------------------------------------------------- refresh
    def refresh(self):
        self._hero()
        self._status()
        self._sessions()

    def _hero(self):
        hub, s, info = self.hub, self.hub.last_sample, self.hub.session_info
        self.hello.setText(greeting(time.localtime().tm_hour).upper())
        live = s is not None and s.status == ACStatus.LIVE
        if hub.running and live and info.get("track"):
            text = tr("On track: {track} with the {car}. Everything is live in the other views.",
                      track=info.get("track"), car=info.get("car") or "?")
        elif hub.running:
            text = tr("Acquisition on: waiting for you to go on track in Assetto Corsa.")
        else:
            text = tr("Start Assetto Corsa and press Start: Delta Suite follows you as soon as you leave the pits. "
                      "No AC at hand? Try the demo.")
        self.intro.setText(text)
        self.go.setText(("■  " + tr("Stop acquisition")) if hub.running else ("▶  " + tr("Start acquisition")))

    def _status(self):
        now = time.monotonic()
        if now - self._ac_root_t > 30:
            self._ac_root, self._ac_root_t = csp_bridge.find_ac_root(), now
        items = first_run.checklist(self.hub, self._ac_root)
        remote = self.hub.remote
        n = len(remote.pairing.device_list())
        rows = [(tr(STATUS_LABELS.get(it.key, it.key)), *(tr(STATE_PILLS[it.state][0]), STATE_PILLS[it.state][1]),
                 it.text, it.action, it.action_key) for it in items]
        rows.append((tr("Remote pit wall"), tr("on · {n}", n=n) if remote.enabled and n else
                     tr("on") if remote.enabled else tr("off"), "green" if remote.enabled else "dim",
                     tr("Follow the session from another PC, a tablet or a phone"), tr("Open"), "remote"))
        while len(self.rows) < len(rows):
            r = StatusRow()
            r.action.connect(self.action)
            self.rows.append(r)
            self.status_box.addWidget(r)
        for r, data in zip(self.rows, rows):
            r.set(*data)
            r.show()
        for r in self.rows[len(rows):]:
            r.hide()

    def _sessions(self):
        db = self.hub.db
        try:
            sessions = db.sessions()
        except Exception:
            sessions = []
        last = last_session(sessions, self.hub.session_id)
        if last is None:
            self.last_where.setText(tr("No session in the archive yet"))
            self.last_laps.setText("–")
            self.last_best.setText("–")
            self.last_ideal.setText("")
            self.last_when.setText("")
            self.spark.set_values([])
        else:
            laps = db.laps(last["id"])
            self.last_where.setText(f"{last['track']} · {last['car']}".upper())
            self.last_when.setText(f"{last['started']:%d/%m %H:%M}")
            self.last_laps.setText(tr("{n} laps", n=last["laps"]))
            self.last_best.setText(rs.fmt_ms(last["best_ms"]) if last["best_ms"] else "–")
            ideal = rs.theoretical_best(laps) if laps else None
            self.last_ideal.setText(tr("ideal lap {t}", t=rs.fmt_ms(ideal)) if ideal else "")
            valid = [l.lap_time_ms / 1000 for l in laps if l.valid and l.lap_time_ms > 0]
            if valid:                              # outliers (yellow flags, pit laps) would flatten the line
                cap = min(valid) * 1.07
                valid = [min(v, cap) for v in valid]
            self.spark.set_values(valid)

        while self.recs_box.count():
            w = self.recs_box.takeAt(0).widget()
            if w is not None:
                w.deleteLater()
        bests = personal_bests(sessions)
        if not bests:
            self.recs_box.addWidget(label(tr("Your best lap for each car and track appears here."), "dim"))
        for b in bests:
            row = QLabel(f"<table width='100%'><tr><td>{b['track']} · {b['car']}</td>"
                         f"<td align='right'><b style='font-family:Consolas'>{rs.fmt_ms(b['best_ms'])}</b></td></tr>"
                         f"<tr><td colspan=2 style='color:{C['dim']}; font-size:8pt'>"
                         f"{tr('set on {when}', when=b['set'].strftime('%d/%m'))}</td></tr></table>")
            row.setStyleSheet(f"background: {C['panel2']}; border-radius: {C['radius']}px; padding: 6px 10px;")
            self.recs_box.addWidget(row)

        self._track(last)

    def _track(self, last: dict | None):
        info, s = self.hub.session_info, self.hub.last_sample
        car, track = info.get("car") or (last or {}).get("car"), info.get("track") or (last or {}).get("track")
        self.track_name.setText(track or "–")
        bits = []
        length = info.get("track_length") or (last or {}).get("track_length")
        if length:
            bits.append(f"{float(length) / 1000:.3f} km")
        if s is not None and s.status == ACStatus.LIVE:
            bits.append(tr("air {a}° · track {t}°", a=f"{s.air_temp:.0f}", t=f"{s.road_temp:.0f}"))
        self.track_info.setText("\n".join(bits))
        self.map.set_track(self.hub.track.line if info.get("track") else None)
        self.map.setVisible(self.hub.track.line is not None and bool(info.get("track")))
        tip = ""
        if car and track:
            best = self.hub.db.best_laps(car, track, 1)
            if best:
                tip = tr("Your best here with the {car}: {t}. Beat it and the live delta turns green.",
                         car=car, t=rs.fmt_ms(best[0]["lap_time_ms"]))
            else:
                tip = tr("First time here with the {car}: the archive starts from today's laps.", car=car)
        self.tip.setText(tip)
        self.tip.setVisible(bool(tip))
