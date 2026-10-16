"""Tema scuro stile muretto box."""

from __future__ import annotations

import pyqtgraph as pg
from PyQt6.QtCore import QRectF, Qt
from PyQt6.QtGui import QColor, QFont, QIcon, QPainter, QPixmap

C = {
    "bg": "#0d0f13",
    "panel": "#151920",
    "panel2": "#1c212b",
    "border": "#2a303c",
    "text": "#e7e9ee",
    "dim": "#8b93a3",
    "accent": "#e10600",
    "green": "#2ecc71",
    "yellow": "#f1c40f",
    "purple": "#b05cff",
    "blue": "#3d9bff",
    "red": "#ff4d4d",
}

LAP_COLORS = ["#3d9bff", "#ff4d4d", "#2ecc71", "#f1c40f", "#b05cff", "#ff9f43"]

STYLESHEET = f"""
QWidget {{ background: {C['bg']}; color: {C['text']}; font-family: 'Segoe UI'; font-size: 10pt; }}
QMainWindow::separator {{ background: {C['border']}; }}
QFrame#card, QGroupBox {{ background: {C['panel']}; border: 1px solid {C['border']}; border-radius: 8px; }}
QGroupBox {{ margin-top: 14px; padding: 10px 8px 8px 8px; font-weight: 600; }}
QGroupBox::title {{ subcontrol-origin: margin; left: 10px; padding: 0 4px; color: {C['dim']}; }}
QLabel {{ background: transparent; }}
QLabel#dim {{ color: {C['dim']}; }}
QLabel#h1 {{ font-size: 20pt; font-weight: 700; }}
QLabel#h2 {{ font-size: 13pt; font-weight: 600; }}
QListWidget#sidebar {{ background: {C['panel']}; border: none; border-right: 1px solid {C['border']};
    font-size: 11pt; padding-top: 8px; outline: 0; }}
QListWidget#sidebar::item {{ padding: 11px 14px; border-left: 3px solid transparent; }}
QListWidget#sidebar::item:selected {{ background: {C['panel2']}; border-left: 3px solid {C['accent']}; color: white; }}
QListWidget#sidebar::item:hover {{ background: {C['panel2']}; }}
QListWidget#sidebar::item:disabled {{ background: transparent; color: {C['dim']}; padding: 14px 14px 2px 17px; }}
QPushButton {{ background: {C['panel2']}; border: 1px solid {C['border']}; border-radius: 6px; padding: 6px 14px; }}
QPushButton:hover {{ border-color: {C['accent']}; }}
QPushButton:disabled {{ color: {C['dim']}; }}
QPushButton#primary {{ background: {C['accent']}; border-color: {C['accent']}; color: white; font-weight: 600; }}
QPushButton#primary:hover {{ background: #ff1a14; }}
QComboBox, QSpinBox, QDoubleSpinBox, QLineEdit, QPlainTextEdit, QTextEdit, QTextBrowser {{
    background: {C['panel2']}; border: 1px solid {C['border']}; border-radius: 5px; padding: 4px 6px; }}
QComboBox QAbstractItemView {{ background: {C['panel2']}; selection-background-color: {C['accent']}; }}
QTableWidget {{ background: {C['panel']}; gridline-color: {C['border']}; border: 1px solid {C['border']};
    border-radius: 6px; alternate-background-color: {C['panel2']}; }}
QHeaderView::section {{ background: {C['panel2']}; color: {C['dim']}; border: none; padding: 5px;
    border-bottom: 1px solid {C['border']}; }}
QTabWidget::pane {{ border: 1px solid {C['border']}; border-radius: 6px; top: -1px; }}
QTabBar::tab {{ background: {C['panel']}; padding: 7px 16px; border: 1px solid {C['border']};
    border-bottom: none; border-top-left-radius: 6px; border-top-right-radius: 6px; margin-right: 2px; }}
QTabBar::tab:selected {{ background: {C['panel2']}; border-top: 2px solid {C['accent']}; }}
QProgressBar {{ background: {C['panel2']}; border: 1px solid {C['border']}; border-radius: 4px; height: 10px;
    text-align: center; color: transparent; }}
QProgressBar::chunk {{ background: {C['accent']}; border-radius: 3px; }}
QSlider::groove:horizontal {{ height: 4px; background: {C['border']}; border-radius: 2px; }}
QSlider::handle:horizontal {{ background: {C['accent']}; width: 14px; margin: -6px 0; border-radius: 7px; }}
QScrollBar:vertical {{ background: {C['bg']}; width: 10px; }}
QScrollBar::handle:vertical {{ background: {C['border']}; border-radius: 4px; min-height: 30px; }}
QStatusBar {{ background: {C['panel']}; color: {C['dim']}; border-top: 1px solid {C['border']}; }}
QCheckBox::indicator {{ width: 15px; height: 15px; }}
"""


def apply(app) -> None:
    app.setStyleSheet(STYLESHEET)
    pg.setConfigOptions(antialias=True, background=C["panel"], foreground=C["dim"])


def app_icon_pixmap(size: int = 256) -> QPixmap:
    """Logo disegnato a runtime: quadrato rosso con bandiera a scacchi e 'Δ'."""
    pm = QPixmap(size, size)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QColor(C["accent"]))
    p.drawRoundedRect(QRectF(0, 0, size, size), size * 0.18, size * 0.18)
    cell = size / 8
    for r in range(2):
        for c in range(8):
            p.setBrush(QColor("white" if (r + c) % 2 == 0 else "#111111"))
            p.drawRect(QRectF(c * cell, size - (2 - r) * cell * 0.9 - size * 0.06, cell, cell * 0.9))
    p.setPen(QColor("white"))
    f = QFont("Segoe UI", int(size * 0.44))
    f.setWeight(QFont.Weight.Black)
    p.setFont(f)
    p.drawText(QRectF(0, 0, size, size * 0.72), Qt.AlignmentFlag.AlignCenter, "Δ")
    p.end()
    return pm


def app_icon() -> QIcon:
    icon = QIcon()
    for s in (16, 32, 48, 64, 128, 256):
        icon.addPixmap(app_icon_pixmap(s))
    return icon
