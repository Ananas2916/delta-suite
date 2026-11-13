"""Top bar: logo, the views as a segmented control, flag pill, session, push-to-talk and settings."""

from __future__ import annotations

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import QButtonGroup, QHBoxLayout, QLabel, QPushButton, QWidget

from hub_core.i18n import tr
from ui.theme import C, rgba

FLAG_COLORS = {"green": "green", "yellow": "yellow", "red": "red", "blue": "blue", "black": "red", "penalty": "red",
               "white": "dim", "checkered": "text"}


def pill_style(color_key: str) -> str:
    """Coloured pill (states are pills, not sentences)."""
    col = C.get(color_key, C["dim"])
    return (f"QLabel {{ background: {rgba(col, 0.16)}; color: {col}; border-radius: 10px; padding: 3px 10px; "
            f"font-weight: 700; font-size: 8.5pt; letter-spacing: 0.5px; }}")


class TopBar(QWidget):
    view_selected = pyqtSignal(str)
    ptt = pyqtSignal(bool)                  # push-to-talk pressed / released
    settings_clicked = pyqtSignal()

    def __init__(self, views: list[tuple[str, str, str]]):
        super().__init__()
        self.setObjectName("topbar")
        self.setStyleSheet(f"QWidget#topbar {{ background: {C['panel']}; border-bottom: 1px solid {C['border']}; }}")
        lay = QHBoxLayout(self)
        lay.setContentsMargins(14, 8, 14, 8)
        lay.setSpacing(12)
        logo = QLabel(f"<b style='color:{C['accent']}'>Δ</b> DELTA SUITE")
        logo.setStyleSheet(f"font-family: '{C['title_font']}'; font-size: 14pt; font-weight: 800; letter-spacing: 1px;")
        lay.addWidget(logo)

        seg = QWidget()
        seg.setObjectName("views")
        r = max(4, C["radius"] + 6)
        seg.setStyleSheet(
            f"QWidget#views {{ background: {C['panel2']}; border-radius: {r}px; }}"
            f"QPushButton {{ background: transparent; border: 0; border-radius: {r - 2}px; padding: 6px 13px; "
            f"color: {C['dim']}; font-weight: 600; }}"
            f"QPushButton:hover {{ color: {C['text']}; }}"
            f"QPushButton:checked {{ background: {C['accent']}; color: {C['on_accent']}; }}")
        sl = QHBoxLayout(seg)
        sl.setContentsMargins(3, 3, 3, 3)
        sl.setSpacing(2)
        self.group = QButtonGroup(self)
        self.group.setExclusive(True)
        self.buttons: dict[str, QPushButton] = {}
        for key, name, desc in views:
            b = QPushButton(tr(name).replace("&", "&&"))
            b.setCheckable(key != "ambient")
            b.setToolTip(tr(desc))
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.clicked.connect(lambda _=False, k=key: self.view_selected.emit(k))
            if key != "ambient":
                self.group.addButton(b)
            self.buttons[key] = b
            sl.addWidget(b)
        lay.addWidget(seg)

        self.flag = QLabel()
        self.flag.hide()
        lay.addWidget(self.flag)
        self.session = QLabel()
        self.session.setStyleSheet(f"color: {C['dim']};")
        lay.addWidget(self.session, 1)

        self.ptt_btn = QPushButton("●  " + tr("Hold: radio"))
        self.ptt_btn.setToolTip(tr("Hold to talk to the engineer (same as the wheel button)"))
        self.ptt_btn.pressed.connect(lambda: self._ptt(True))
        self.ptt_btn.released.connect(lambda: self._ptt(False))
        self._ptt(False, emit=False)
        lay.addWidget(self.ptt_btn)
        self.settings_btn = QPushButton("⚙")
        self.settings_btn.setCheckable(True)
        self.settings_btn.setToolTip(tr("Settings: mode, language, theme, remote access, CSP app"))
        self.settings_btn.clicked.connect(self.settings_clicked)
        self.group.addButton(self.settings_btn)
        lay.addWidget(self.settings_btn)

    def _ptt(self, down: bool, emit: bool = True):
        col = C["accent"] if down else C["border"]
        self.ptt_btn.setStyleSheet(f"QPushButton {{ border: 1px solid {col}; color: {C['text'] if down else C['dim']};"
                                   f" background: {rgba(C['accent'], 0.25) if down else C['panel2']}; }}")
        if emit:
            self.ptt.emit(down)

    def set_view(self, key: str):
        b = self.settings_btn if key == "settings" else self.buttons.get(key)
        if b is not None and b.isCheckable():
            b.setChecked(True)

    def set_flag(self, flag: tuple[str, str] | None):
        if flag is None:
            self.flag.hide()
            return
        kind, text = flag
        self.flag.setText(text.upper())
        self.flag.setStyleSheet(pill_style(FLAG_COLORS.get(kind, "dim")))
        self.flag.show()

    def set_session(self, text: str):
        if self.session.text() != text:
            self.session.setText(text)
