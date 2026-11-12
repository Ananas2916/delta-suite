"""Get-started card: one row per checklist item (dot, text, optional button) and a Hide button."""

from __future__ import annotations

from PyQt6.QtCore import pyqtSignal
from PyQt6.QtWidgets import QHBoxLayout, QPushButton, QVBoxLayout, QWidget

from ui.theme import C
from ui.widgets import Card, label
from hub_core.i18n import tr

STATE_COLORS = {"done": C["green"], "todo": C["red"], "wait": C["yellow"]}


class ChecklistCard(Card):
    action = pyqtSignal(str)
    hide_requested = pyqtSignal()

    def __init__(self, title: str = ""):
        super().__init__()
        self._lay = QVBoxLayout(self)
        self._lay.setContentsMargins(12, 10, 12, 10)
        self._lay.setSpacing(4)
        head = QHBoxLayout()
        head.addWidget(label(title or tr("GET STARTED"), "dim"))
        head.addStretch()
        hide = QPushButton(tr("Hide"))
        hide.setToolTip(tr("Hide this list (it comes back from the Race engineer settings)"))
        hide.clicked.connect(self.hide_requested)
        head.addWidget(hide)
        self._lay.addLayout(head)
        self._rows: list[QWidget] = []
        self._key = None

    def set_items(self, items) -> None:
        key = tuple((i.key, i.text, i.state, i.action) for i in items)
        if key == self._key:
            return
        self._key = key
        for w in self._rows:
            w.deleteLater()
        self._rows = []
        for item in items:
            row = QWidget()
            lay = QHBoxLayout(row)
            lay.setContentsMargins(0, 0, 0, 0)
            text = label(f"<span style='color:{STATE_COLORS.get(item.state, C['dim'])}'>●</span>  {item.text}")
            lay.addWidget(text, 1)
            if item.action:
                b = QPushButton(item.action)
                b.clicked.connect(lambda _=False, k=item.action_key: self.action.emit(k))
                lay.addWidget(b)
            self._lay.addWidget(row)
            self._rows.append(row)
