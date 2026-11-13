"""
Interface themes. Seven looks the user picks from the sidebar (setting "ui/theme", applied at the next start):
the palette `C` is filled at import time, before any page reads it, so every widget built from `C` follows it.

    pitwall    dark graphite with the red accent (default, the original look)
    broadcast  F1 TV graphics: deep navy, condensed bold type, white selection bars
    instrument MoTeC/ATLAS style: black, amber and cyan data, monospace everywhere
    paddock    light theme with rounded cards (daylight, the remote pit-wall tablet)
    glass      Apple-like: dark violet glass, large radius, system blue and green
    fluent     Windows 11: soft greys, light-blue accent
    swiss      industrial design: warm paper, black borders, a single orange
"""

from __future__ import annotations

import os

import pyqtgraph as pg
from PyQt6.QtCore import QRectF, QSettings, Qt
from PyQt6.QtGui import QColor, QFont, QIcon, QPainter, QPixmap

# semantic colours (good / warning / purple sector / info / critical), darker on the light themes
_DARK_SEM = {"green": "#2ecc71", "yellow": "#f1c40f", "purple": "#b05cff", "blue": "#3d9bff", "red": "#ff4d4d"}
_LIGHT_SEM = {"green": "#16a34a", "yellow": "#c98a00", "purple": "#8b3dff", "blue": "#1d6fe0", "red": "#d92d2d"}

THEMES: dict[str, dict] = {
    "pitwall": {"name": "Pit Wall", **_DARK_SEM,
                "bg": "#0d0f13", "panel": "#151920", "panel2": "#1c212b", "border": "#2a303c", "text": "#e7e9ee",
                "dim": "#8b93a3", "accent": "#e10600", "accent_hover": "#ff1a14", "on_accent": "#ffffff",
                "nav_sel_bg": "#1c212b", "nav_sel_fg": "#ffffff", "font": "Segoe UI", "title_font": "Segoe UI",
                "radius": 8},
    "broadcast": {"name": "Broadcast F1", **_DARK_SEM,
                  "bg": "#0a0f2c", "panel": "#121838", "panel2": "#1b2250", "border": "#2a3266", "text": "#ffffff",
                  "dim": "#9aa3c7", "accent": "#e10600", "accent_hover": "#ff2a20", "on_accent": "#ffffff",
                  "nav_sel_bg": "#ffffff", "nav_sel_fg": "#0a0f2c",
                  "font": "Bahnschrift", "title_font": "Bahnschrift SemiBold SemiConden", "radius": 2},
    "instrument": {"name": "Carbon Instrument", **_DARK_SEM, "yellow": "#ffb000", "blue": "#00e0ff",
                   "bg": "#050607", "panel": "#0a0c0e", "panel2": "#11161b", "border": "#1d242b", "text": "#cfd6dd",
                   "dim": "#6b7782", "accent": "#ffb000", "accent_hover": "#ffc533", "on_accent": "#050607",
                   "nav_sel_bg": "#11161b", "nav_sel_fg": "#00e0ff", "font": "Consolas", "title_font": "Consolas",
                   "radius": 0},
    "paddock": {"name": "Paddock Light", **_LIGHT_SEM,
                "bg": "#eef0f3", "panel": "#ffffff", "panel2": "#f4f5f7", "border": "#dfe3e8", "text": "#14171c",
                "dim": "#5d6470", "accent": "#d10a0a", "accent_hover": "#e82b2b", "on_accent": "#ffffff",
                "nav_sel_bg": "#14171c", "nav_sel_fg": "#ffffff", "font": "Segoe UI", "title_font": "Bahnschrift",
                "radius": 12},
    "glass": {"name": "Glass (Apple style)", **_DARK_SEM, "green": "#30d158", "blue": "#0a84ff",
              "bg": "#14121f", "panel": "#1f1c2e", "panel2": "#2a2640", "border": "#36314f", "text": "#f5f5f7",
              "dim": "#a19cb8", "accent": "#0a84ff", "accent_hover": "#3d9dff", "on_accent": "#ffffff",
              "nav_sel_bg": "#2f2a48", "nav_sel_fg": "#ffffff", "font": "Segoe UI Variable Text",
              "title_font": "Segoe UI Variable Display", "radius": 16},
    "fluent": {"name": "Fluent (Windows 11)", **_DARK_SEM, "blue": "#60cdff",
               "bg": "#202020", "panel": "#272727", "panel2": "#2d2d2d", "border": "#383838", "text": "#ffffff",
               "dim": "#c5c5c5", "accent": "#60cdff", "accent_hover": "#8ad9ff", "on_accent": "#000000",
               "nav_sel_bg": "#2d2d2d", "nav_sel_fg": "#ffffff", "font": "Segoe UI Variable Text",
               "title_font": "Segoe UI Variable Display", "radius": 6},
    "swiss": {"name": "Swiss", **_LIGHT_SEM,
              "bg": "#e9e6df", "panel": "#f1eee8", "panel2": "#e2ded5", "border": "#111111", "text": "#111111",
              "dim": "#5c5850", "accent": "#ff5a00", "accent_hover": "#ff7a30", "on_accent": "#111111",
              "nav_sel_bg": "#ff5a00", "nav_sel_fg": "#111111", "font": "Consolas", "title_font": "Bahnschrift",
              "radius": 0},
}
DEFAULT_THEME = "pitwall"


def saved_theme() -> str:
    key = os.environ.get("DELTA_THEME") or QSettings("DeltaSuite", "DeltaSuite").value("ui/theme", DEFAULT_THEME)
    return key if key in THEMES else DEFAULT_THEME


THEME = saved_theme()
C: dict = dict(THEMES[THEME])

LAP_COLORS = ["#3d9bff", "#ff4d4d", "#2ecc71", "#f1c40f", "#b05cff", "#ff9f43"]


def stylesheet(c: dict) -> str:
    r = c["radius"]
    r2 = max(0, r - 2)
    return f"""
QWidget {{ background: {c['bg']}; color: {c['text']}; font-family: '{c['font']}'; font-size: 10pt; }}
QMainWindow::separator {{ background: {c['border']}; }}
QFrame#card, QGroupBox {{ background: {c['panel']}; border: 1px solid {c['border']}; border-radius: {r}px; }}
QGroupBox {{ margin-top: 14px; padding: 10px 8px 8px 8px; font-weight: 600; }}
QGroupBox::title {{ subcontrol-origin: margin; left: 10px; padding: 0 4px; color: {c['dim']}; }}
QLabel {{ background: transparent; }}
QLabel#dim {{ color: {c['dim']}; }}
QLabel#h1 {{ font-family: '{c['title_font']}'; font-size: 20pt; font-weight: 700; }}
QLabel#h2 {{ font-family: '{c['title_font']}'; font-size: 13pt; font-weight: 600; }}
QListWidget#sidebar {{ background: {c['panel']}; border: none; border-right: 1px solid {c['border']};
    font-size: 11pt; padding-top: 8px; outline: 0; }}
QListWidget#sidebar::item {{ padding: 11px 14px; border-left: 3px solid transparent; }}
QListWidget#sidebar::item:selected {{ background: {c['nav_sel_bg']}; border-left: 3px solid {c['accent']};
    color: {c['nav_sel_fg']}; }}
QListWidget#sidebar::item:hover:!selected {{ background: {c['panel2']}; }}
QListWidget#sidebar::item:disabled {{ background: transparent; color: {c['dim']}; padding: 14px 14px 2px 17px; }}
QPushButton {{ background: {c['panel2']}; border: 1px solid {c['border']}; border-radius: {r2}px; padding: 6px 14px; }}
QPushButton:hover {{ border-color: {c['accent']}; }}
QPushButton:disabled {{ color: {c['dim']}; }}
QPushButton#primary {{ background: {c['accent']}; border-color: {c['accent']}; color: {c['on_accent']};
    font-weight: 600; }}
QPushButton#primary:hover {{ background: {c['accent_hover']}; }}
QComboBox, QSpinBox, QDoubleSpinBox, QLineEdit, QPlainTextEdit, QTextEdit, QTextBrowser {{
    background: {c['panel2']}; border: 1px solid {c['border']}; border-radius: {r2}px; padding: 4px 6px; }}
QComboBox QAbstractItemView {{ background: {c['panel2']}; selection-background-color: {c['accent']};
    selection-color: {c['on_accent']}; }}
QTableWidget {{ background: {c['panel']}; gridline-color: {c['border']}; border: 1px solid {c['border']};
    border-radius: {r2}px; alternate-background-color: {c['panel2']}; }}
QHeaderView::section {{ background: {c['panel2']}; color: {c['dim']}; border: none; padding: 5px;
    border-bottom: 1px solid {c['border']}; }}
QTabWidget::pane {{ border: 1px solid {c['border']}; border-radius: {r2}px; top: -1px; }}
QTabBar::tab {{ background: {c['panel']}; padding: 7px 16px; border: 1px solid {c['border']};
    border-bottom: none; border-top-left-radius: {r2}px; border-top-right-radius: {r2}px; margin-right: 2px; }}
QTabBar::tab:selected {{ background: {c['panel2']}; border-top: 2px solid {c['accent']}; }}
QProgressBar {{ background: {c['panel2']}; border: 1px solid {c['border']}; border-radius: 4px; height: 10px;
    text-align: center; color: transparent; }}
QProgressBar::chunk {{ background: {c['accent']}; border-radius: 3px; }}
QSlider::groove:horizontal {{ height: 4px; background: {c['border']}; border-radius: 2px; }}
QSlider::handle:horizontal {{ background: {c['accent']}; width: 14px; margin: -6px 0; border-radius: 7px; }}
QScrollBar:vertical {{ background: {c['bg']}; width: 10px; }}
QScrollBar::handle:vertical {{ background: {c['border']}; border-radius: 4px; min-height: 30px; }}
QStatusBar {{ background: {c['panel']}; color: {c['dim']}; border-top: 1px solid {c['border']}; }}
QCheckBox::indicator {{ width: 15px; height: 15px; }}
QToolTip {{ background: {c['panel2']}; color: {c['text']}; border: 1px solid {c['border']}; }}
"""


STYLESHEET = stylesheet(C)


def apply(app) -> None:
    app.setStyleSheet(STYLESHEET)
    pg.setConfigOptions(antialias=True, background=C["panel"], foreground=C["dim"])


def app_icon_pixmap(size: int = 256) -> QPixmap:
    """Logo drawn at runtime: red square with a chequered flag and 'Δ'."""
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
