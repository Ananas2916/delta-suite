"""Race control panel: state of the CSP app's FCY/VSC, buttons to call them, automatic director mode."""

from __future__ import annotations

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import QComboBox, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from hub_core.ac import race_link as rl
from hub_core.i18n import tr
from ui.theme import C

AUTO_MODES = (("off", "Manual only"), ("fcy", "Automatic FCY"), ("vsc", "Automatic VSC"))


def state_text(rc: rl.RaceControlState | None) -> tuple[str, str]:
    """(text, colour key) of the race control state, for the panel and the live strip."""
    if rc is None:
        return tr("CSP app not connected"), "dim"
    if not rc.available:
        return tr("Race control works offline only"), "dim"
    name = "VSC" if rc.mode == rl.MODE_VSC else "SC" if rc.mode == rl.MODE_SC else "FCY"
    if rc.mode == rl.MODE_SC and rc.state == rl.ACTIVE:
        return tr("SAFETY CAR"), "red" if rc.over_limit else "yellow"
    if rc.mode == rl.MODE_SC and rc.state == rl.ENDING:
        return tr("Safety car in this lap"), "yellow"
    if rc.state == rl.PENDING:
        return tr("FCY in {n} s", n=max(0, int(rc.countdown + 0.99))), "yellow"
    if rc.state == rl.ACTIVE:
        if rc.mode == rl.MODE_VSC:
            return tr("VSC · delta {d} s", d=f"{rc.delta:+.1f}"), "red" if rc.over_limit else "yellow"
        return tr("FCY · limit {kmh} km/h", kmh=int(rc.limit_kmh)), "red" if rc.over_limit else "yellow"
    if rc.state == rl.ENDING:
        return tr("{name} ending · {n} s", name=name, n=max(0, int(rc.countdown + 0.99))), "yellow"
    if rc.state == rl.GREEN_FLASH:
        return tr("GREEN FLAG"), "green"
    return tr("Green"), "green"


class RaceControlPanel(QWidget):
    request = pyqtSignal(str)          # "fcy", "vsc", "end", "cancel"
    auto_changed = pyqtSignal(str)

    def __init__(self, auto_mode: str = "off"):
        super().__init__()
        lay = QVBoxLayout(self)
        lay.setContentsMargins(4, 10, 4, 4)
        lay.setSpacing(10)
        self.state = QLabel()
        self.state.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.state.setMinimumHeight(54)
        lay.addWidget(self.state)
        self.detail = QLabel()
        self.detail.setWordWrap(True)
        self.detail.setStyleSheet(f"color: {C['dim']};")
        lay.addWidget(self.detail)

        row = QHBoxLayout()
        self.btn_fcy = QPushButton(tr("FCY"))
        self.btn_fcy.setToolTip(tr("Full course yellow: countdown, then everyone at the speed limit"))
        self.btn_vsc = QPushButton(tr("VSC"))
        self.btn_vsc.setToolTip(tr("Virtual safety car: a delta time to stay positive on"))
        self.btn_sc = QPushButton(tr("SC"))
        self.btn_sc.setToolTip(tr("Safety car: the session's safety car comes out ahead of the leader and the field "
                                  "queues behind it"))
        self.btn_end = QPushButton(tr("End"))
        self.btn_end.setToolTip(tr("End the neutralisation: a few seconds of warning, then green"))
        self.btn_green = QPushButton(tr("Green now"))
        self.btn_green.setToolTip(tr("Back to green at once, without the ending phase"))
        for b, kind in ((self.btn_fcy, "fcy"), (self.btn_vsc, "vsc"), (self.btn_sc, "sc"), (self.btn_end, "end"),
                        (self.btn_green, "cancel")):
            b.clicked.connect(lambda _=False, k=kind: self.request.emit(k))
            b.setMinimumHeight(34)
            row.addWidget(b)
        lay.addLayout(row)

        auto = QHBoxLayout()
        auto.addWidget(QLabel(tr("Race director")))
        self.auto = QComboBox()
        for key, text in AUTO_MODES:
            self.auto.addItem(tr(text), key)
        self.auto.setCurrentIndex(max(0, self.auto.findData(auto_mode)))
        self.auto.setToolTip(tr("Automatic: a car stopped on track for a few seconds neutralises the race, the "
                                "track clear again ends it. Races only."))
        self.auto.currentIndexChanged.connect(lambda: self.auto_changed.emit(self.auto.currentData()))
        auto.addWidget(self.auto, 1)
        lay.addLayout(auto)
        self.last = QLabel()
        self.last.setWordWrap(True)
        self.last.setStyleSheet(f"color: {C['dim']}; font-size: 8.5pt;")
        lay.addWidget(self.last)
        note = QLabel(tr("Also from the wheel: bind the DeltaSuite/Race control buttons in the CSP controls. "
                         "In game, the DS Race control window shows the countdown, the speed limit and the delta."))
        note.setWordWrap(True)
        note.setStyleSheet(f"color: {C['dim']}; font-size: 8.5pt;")
        lay.addWidget(note)
        lay.addStretch()
        self.set_state(None)

    def set_state(self, rc: rl.RaceControlState | None, decision=None) -> None:
        text, color = state_text(rc)
        self.state.setText(text)
        bg = C.get(color, C["dim"])
        self.state.setStyleSheet(f"background: {C['panel2']}; border-left: 5px solid {bg}; border-radius: "
                                 f"{C['radius']}px; color: {C['text']}; font-size: 15pt; font-weight: 700;")
        ok = rc is not None and rc.available
        green = ok and rc.state in (rl.GREEN, rl.GREEN_FLASH)
        self.btn_fcy.setEnabled(green)
        self.btn_vsc.setEnabled(green)
        self.btn_sc.setEnabled(green and rc.sc_car >= 0 and rc.sc_phase == rl.SC_PARKED)
        self.btn_end.setEnabled(ok and rc.state in (rl.PENDING, rl.ACTIVE))
        self.btn_green.setEnabled(ok and rc.state in (rl.PENDING, rl.ACTIVE, rl.ENDING))
        details = []
        if ok and rc.state in (rl.ACTIVE, rl.ENDING) and rc.infraction_s > 0.5:
            details.append(tr("Driver over the limit for {s} s", s=f"{rc.infraction_s:.0f}"))
        if ok and rc.sc_car < 0:
            details.append(tr("No safety car in this session: add one to the grid (a car whose name says "
                              "\"safety\", or the one chosen in Settings)."))
        if not ok:
            details.append(tr("Needs the CSP app and an offline session: the AI cars are slowed through the "
                              "physics API, which online servers do not allow."))
        self.detail.setText(" · ".join(details))
        if decision is not None:
            self.last.setText(tr("Last automatic call: {what} ({why})", what=decision.action.upper(),
                                 why=tr(decision.reason)))
