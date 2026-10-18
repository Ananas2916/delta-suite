"""Widget riutilizzati dalle pagine dell'hub."""

from __future__ import annotations

import pyqtgraph as pg
from PyQt6.QtCore import QRectF, Qt
from PyQt6.QtGui import QColor, QFont, QPainter
from PyQt6.QtWidgets import (
    QComboBox, QDoubleSpinBox, QFrame, QGridLayout, QLabel, QSizePolicy, QTableWidget,
    QTableWidgetItem, QAbstractItemView, QHeaderView, QVBoxLayout, QWidget,
)

from ui.theme import C


def label(text: str = "", obj: str | None = None, align=None) -> QLabel:
    lb = QLabel(text)
    if obj:
        lb.setObjectName(obj)
    if align is not None:
        lb.setAlignment(align)
    return lb


def dspin(lo: float, hi: float, val: float, step: float = 1.0, decimals: int = 2, suffix: str = "") -> QDoubleSpinBox:
    sb = QDoubleSpinBox()
    sb.setRange(lo, hi)
    sb.setDecimals(decimals)
    sb.setSingleStep(step)
    sb.setValue(val)
    if suffix:
        sb.setSuffix(" " + suffix)
    sb.setKeyboardTracking(False)
    return sb


def make_plot(title: str = "", y_label: str = "", x_label: str = "") -> pg.PlotWidget:
    pw = pg.PlotWidget()
    pi = pw.getPlotItem()
    if title:
        pi.setTitle(f"<span style='color:{C['dim']}'>{title}</span>")
    if y_label:
        pi.setLabel("left", y_label)
    if x_label:
        pi.setLabel("bottom", x_label)
    pi.showGrid(x=True, y=True, alpha=0.15)
    return pw


def readonly_table(headers: list[str]) -> QTableWidget:
    t = QTableWidget(0, len(headers))
    t.setHorizontalHeaderLabels(headers)
    t.verticalHeader().setVisible(False)
    t.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
    t.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
    t.setAlternatingRowColors(True)
    t.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
    return t


def table_item(text: str, color: str | None = None, bold: bool = False) -> QTableWidgetItem:
    it = QTableWidgetItem(text)
    it.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
    if color:
        it.setForeground(QColor(color))
    if bold:
        f = it.font()
        f.setBold(True)
        it.setFont(f)
    return it


class Card(QFrame):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("card")


class ValueTile(Card):
    """Riquadro con titolo piccolo e valore grande."""

    def __init__(self, title: str, value: str = "--", big: int = 20):
        super().__init__()
        lay = QVBoxLayout(self)
        lay.setContentsMargins(12, 8, 12, 8)
        lay.setSpacing(0)
        self.title = label(title.upper(), "dim")
        self.title.setStyleSheet("font-size: 8pt; letter-spacing: 1px;")
        self.value = QLabel(value)
        # via stylesheet: lo stylesheet globale ha la precedenza su setFont
        self._base_style = f"font-size: {big}pt; font-weight: 700;"
        self.value.setStyleSheet(self._base_style)
        lay.addWidget(self.title)
        lay.addWidget(self.value)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

    def set(self, text: str, color: str | None = None):
        self.value.setText(text)
        self.value.setStyleSheet(self._base_style + (f" color: {color};" if color else ""))


class Bar(QWidget):
    """Barra verticale (pedali) o orizzontale centrata (sterzo)."""

    def __init__(self, name: str, color: str, centered: bool = False):
        super().__init__()
        self.name, self.color, self.centered = name, QColor(color), centered
        self.value = 0.0
        if centered:
            self.setMinimumSize(160, 34)
        else:
            self.setMinimumSize(34, 150)

    def set_value(self, v: float):
        v = max(-1.0, min(1.0, v)) if self.centered else max(0.0, min(1.0, v))
        if abs(v - self.value) > 0.002:
            self.value = v
            self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(self.rect()).adjusted(1, 1, -1, -16)
        p.setPen(QColor(C["border"]))
        p.setBrush(QColor(C["panel2"]))
        p.drawRoundedRect(r, 4, 4)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(self.color)
        if self.centered:
            mid = r.center().x()
            w = r.width() / 2 * self.value
            p.drawRoundedRect(QRectF(min(mid, mid + w), r.top() + 2, abs(w), r.height() - 4), 3, 3)
            p.setPen(QColor(C["dim"]))
            p.drawLine(int(mid), int(r.top()), int(mid), int(r.bottom()))
        else:
            h = (r.height() - 4) * self.value
            p.drawRoundedRect(QRectF(r.left() + 2, r.bottom() - 2 - h, r.width() - 4, h), 3, 3)
        p.setPen(QColor(C["dim"]))
        p.drawText(QRectF(0, self.height() - 15, self.width(), 15), Qt.AlignmentFlag.AlignCenter, self.name)
        p.end()


def temp_color(t: float, cold: float = 70.0, ideal: float = 88.0, hot: float = 105.0) -> QColor:
    """Blu (freddo) -> verde (finestra) -> rosso (caldo)."""
    blue, green, red = QColor(C["blue"]), QColor(C["green"]), QColor(C["red"])

    def mix(a: QColor, b: QColor, k: float) -> QColor:
        k = max(0.0, min(1.0, k))
        return QColor(int(a.red() + (b.red() - a.red()) * k), int(a.green() + (b.green() - a.green()) * k),
                      int(a.blue() + (b.blue() - a.blue()) * k))

    if t <= ideal:
        return mix(blue, green, (t - cold) / (ideal - cold))
    return mix(green, red, (t - ideal) / (hot - ideal))


class TyreBox(QFrame):
    def __init__(self, name: str):
        super().__init__()
        self.setMinimumSize(96, 92)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(6, 4, 6, 4)
        lay.setSpacing(0)
        self.name = label(name, align=Qt.AlignmentFlag.AlignCenter)
        self.name.setStyleSheet("font-size: 8pt; color: #111; font-weight: 600;")
        self.temp = label("--°", align=Qt.AlignmentFlag.AlignCenter)
        self.temp.setStyleSheet("font-size: 17pt; font-weight: 700; color: #111;")
        self.info = label("", align=Qt.AlignmentFlag.AlignCenter)
        self.info.setStyleSheet("font-size: 8pt; color: #111;")
        for w in (self.name, self.temp, self.info):
            lay.addWidget(w)
        self.set(None, None, None)

    def set(self, temp, press, wear, brake=None):
        col = temp_color(temp) if temp is not None else QColor(C["panel2"])
        self.setStyleSheet(f"QFrame {{ background: {col.name()}; border-radius: 10px; }}")
        if temp is None:
            self.temp.setText("--°")
            self.info.setText("")
            return
        self.temp.setText(f"{temp:.0f}°")
        extra = f"\nfreno {brake:.0f}°" if brake is not None else ""
        self.info.setText(f"{press:.1f} psi · {wear:.1f}%{extra}")


class TyreGrid(Card):
    NAMES = ("ANT SX", "ANT DX", "POST SX", "POST DX")

    def __init__(self):
        super().__init__()
        g = QGridLayout(self)
        g.setContentsMargins(10, 10, 10, 10)
        g.setSpacing(8)
        self.boxes = [TyreBox(n) for n in self.NAMES]
        for i, b in enumerate(self.boxes):
            g.addWidget(b, i // 2, i % 2)

    def update_from(self, s):
        for i, b in enumerate(self.boxes):
            b.set(s.tyre_core_temp[i], s.tyre_pressure[i], s.tyre_wear[i], s.brake_temp[i])


class SessionPicker(QComboBox):
    """Scelta della sorgente dati: sessione live corrente o una sessione dell'archivio."""

    def __init__(self, hub):
        super().__init__()
        self.hub = hub
        self.setMinimumWidth(260)
        self.refresh()
        hub.db_changed.connect(self.refresh)

    def refresh(self):
        current = self.currentData()
        self.blockSignals(True)
        self.clear()
        self.addItem("Sessione corrente (live)", None)
        for s in self.hub.db.sessions():
            self.addItem(f"#{s['id']}  {s['started']:%d/%m %H:%M}  {s['car']} @ {s['track']}  ({s['laps']} giri)",
                         s["id"])
        idx = self.findData(current)
        self.setCurrentIndex(max(0, idx))
        self.blockSignals(False)

    def selected(self):
        """Ritorna (info, laps, session_id)."""
        sid = self.currentData()
        if sid is None:
            return self.hub.session_info, list(self.hub.laps), self.hub.session_id
        info = next((s for s in self.hub.db.sessions() if s["id"] == sid), {})
        return info, self.hub.db.laps(sid), sid


def paint_font(size: float, weight=QFont.Weight.Bold) -> QFont:
    """Font per i widget disegnati a mano (grafica TV, GPS, schema dell'auto)."""
    f = QFont("Segoe UI")
    f.setPointSizeF(size)
    f.setWeight(weight)
    return f
