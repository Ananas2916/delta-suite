"""Modulo 1b: Onboard live — video dalla telecamera sull'auto con grafica TV e stato della vettura."""

from __future__ import annotations

import time

from PyQt6.QtCore import QPointF, QRectF, Qt, QTimer
from PyQt6.QtGui import QColor, QFont, QImage, QLinearGradient, QPainter, QPainterPath, QPen
from PyQt6.QtWidgets import QComboBox, QHBoxLayout, QPushButton, QSizePolicy, QVBoxLayout, QWidget

from hub_core import car_status as cs
from hub_core.ac_shared_memory import ACStatus, gear_label
from hub_core.onboard_feed import CAMERAS, QUALITIES, OnboardFeed
from hub_core.race_strategy import fmt_ms, fuel_per_lap
from ui.hub_state import SOURCE_AC
from ui.theme import C
from ui.widgets import Card, label, temp_color

STALE_S = 2.0          # senza fotogrammi nuovi da tanto: il video non è più in diretta
LEVEL_COLORS = {cs.OK: C["green"], cs.WARN: C["yellow"], cs.CRIT: C["red"]}
DAMAGE_COLORS = ("#3a414f", "#f1c40f", "#ff9f43", "#ff4d4d")


def _font(size: float, weight=QFont.Weight.Bold) -> QFont:
    f = QFont("Segoe UI")
    f.setPointSizeF(size)
    f.setWeight(weight)
    return f


class OnboardView(QWidget):
    """Fotogramma onboard (o segnaposto) con sopra la grafica stile diretta TV."""

    def __init__(self):
        super().__init__()
        self.image: QImage | None = None
        self.live = False
        self.placeholder = ""
        self.hud: dict = {}
        self.setMinimumSize(480, 270)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

    def set_frame(self, img: QImage | None, live: bool):
        self.image, self.live = img, live
        self.update()

    def set_hud(self, hud: dict, placeholder: str):
        self.hud, self.placeholder = hud, placeholder
        self.update()

    def _video_rect(self) -> QRectF:
        r = QRectF(self.rect())
        ar = 16 / 9
        if self.image is not None and not self.image.isNull() and self.image.height():
            ar = self.image.width() / self.image.height()
        w = min(r.width(), r.height() * ar)
        h = w / ar
        return QRectF(r.center().x() - w / 2, r.center().y() - h / 2, w, h)

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        p.fillRect(self.rect(), QColor("#000000"))
        vr = self._video_rect()
        if self.image is not None and not self.image.isNull():
            p.drawImage(vr, self.image)
            if not self.live:
                p.fillRect(vr, QColor(0, 0, 0, 140))
        else:
            g = QLinearGradient(vr.topLeft(), vr.bottomLeft())
            g.setColorAt(0, QColor("#141922"))
            g.setColorAt(1, QColor("#07090c"))
            p.fillRect(vr, g)
        if self.placeholder:
            p.setPen(QColor(C["dim"]))
            p.setFont(_font(11, QFont.Weight.Normal))
            p.drawText(vr.adjusted(40, 0, -40, -vr.height() * 0.2), Qt.AlignmentFlag.AlignCenter |
                       Qt.TextFlag.TextWordWrap, self.placeholder)
        if self.hud:
            self._paint_hud(p, vr)
        p.end()

    # ------------------------------------------------------------------ grafica
    def _box(self, p: QPainter, r: QRectF, alpha: int = 170):
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(10, 12, 16, alpha))
        p.drawRoundedRect(r, 6, 6)

    def _paint_hud(self, p: QPainter, vr: QRectF):
        h = self.hud
        k = max(0.7, min(1.6, vr.width() / 960))      # la grafica scala con il video
        m = 14 * k

        # in alto a sinistra: diretta, pilota, telecamera
        tl = QRectF(vr.left() + m, vr.top() + m, 300 * k, 54 * k)
        self._box(p, tl)
        p.setBrush(QColor(C["accent"] if self.live else C["dim"]))
        p.drawEllipse(QPointF(tl.left() + 14 * k, tl.top() + 17 * k), 5 * k, 5 * k)
        p.setPen(QColor("white"))
        p.setFont(_font(9 * k))
        p.drawText(QRectF(tl.left() + 26 * k, tl.top() + 6 * k, tl.width(), 22 * k), Qt.AlignmentFlag.AlignVCenter,
                   ("ONBOARD LIVE" if self.live else "ONBOARD") + (f"  ·  {h['camera']}" if h.get("camera") else ""))
        p.setFont(_font(11 * k))
        p.drawText(QRectF(tl.left() + 12 * k, tl.top() + 27 * k, tl.width() - 20 * k, 22 * k),
                   Qt.AlignmentFlag.AlignVCenter, h.get("title", ""))

        # in alto a destra: giro e tempi
        rows = h.get("times", [])
        if rows:
            tr = QRectF(vr.right() - m - 230 * k, vr.top() + m, 230 * k, (12 + 21 * len(rows)) * k)
            self._box(p, tr)
            for i, (name, value, color) in enumerate(rows):
                y = tr.top() + (6 + 21 * i) * k
                p.setPen(QColor(C["dim"]))
                p.setFont(_font(8.5 * k, QFont.Weight.DemiBold))
                p.drawText(QRectF(tr.left() + 12 * k, y, 90 * k, 21 * k), Qt.AlignmentFlag.AlignVCenter, name)
                p.setPen(QColor(color or "white"))
                p.setFont(_font(11 * k))
                p.drawText(QRectF(tr.left(), y, tr.width() - 12 * k, 21 * k),
                           Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight, value)

        # in basso a sinistra: velocità, marcia, giri motore
        if "speed" in h:
            bl = QRectF(vr.left() + m, vr.bottom() - m - 92 * k, 250 * k, 92 * k)
            self._box(p, bl)
            p.setPen(QColor("white"))
            p.setFont(_font(30 * k, QFont.Weight.Black))
            p.drawText(QRectF(bl.left() + 12 * k, bl.top() + 4 * k, 130 * k, 56 * k),
                       Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight, f"{h['speed']:.0f}")
            p.setPen(QColor(C["dim"]))
            p.setFont(_font(8 * k))
            p.drawText(QRectF(bl.left() + 146 * k, bl.top() + 30 * k, 40 * k, 20 * k), Qt.AlignmentFlag.AlignLeft,
                       "KM/H")
            if "gear" in h:
                p.setPen(QColor(C["accent"] if h.get("shift") else "white"))
                p.setFont(_font(30 * k, QFont.Weight.Black))
                p.drawText(QRectF(bl.right() - 62 * k, bl.top() + 4 * k, 50 * k, 56 * k),
                           Qt.AlignmentFlag.AlignCenter, h["gear"])
            if "rpm_frac" in h:
                bar = QRectF(bl.left() + 12 * k, bl.bottom() - 26 * k, bl.width() - 24 * k, 10 * k)
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(QColor(255, 255, 255, 40))
                p.drawRoundedRect(bar, 3, 3)
                f = max(0.0, min(1.0, h["rpm_frac"]))
                p.setBrush(QColor(C["accent"] if f > 0.95 else C["yellow"] if f > 0.85 else C["green"]))
                p.drawRoundedRect(QRectF(bar.left(), bar.top(), bar.width() * f, bar.height()), 3, 3)
                p.setPen(QColor(C["dim"]))
                p.setFont(_font(7.5 * k, QFont.Weight.DemiBold))
                p.drawText(QRectF(bar.left(), bar.bottom() + 1 * k, bar.width(), 14 * k), Qt.AlignmentFlag.AlignRight,
                           f"{h.get('rpm', 0)} RPM")

        # in basso a destra: pedali e sterzo
        if "gas" in h:
            br = QRectF(vr.right() - m - 150 * k, vr.bottom() - m - 92 * k, 150 * k, 92 * k)
            self._box(p, br)
            for i, (key, color) in enumerate((("brake", C["red"]), ("gas", C["green"]))):
                bar = QRectF(br.left() + (14 + 24 * i) * k, br.top() + 12 * k, 14 * k, br.height() - 24 * k)
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(QColor(255, 255, 255, 40))
                p.drawRoundedRect(bar, 3, 3)
                v = max(0.0, min(1.0, h[key]))
                p.setBrush(QColor(color))
                p.drawRoundedRect(QRectF(bar.left(), bar.bottom() - bar.height() * v, bar.width(), bar.height() * v),
                                  3, 3)
            c = QPointF(br.right() - 46 * k, br.center().y())
            rad = 30 * k
            p.setPen(QPen(QColor(255, 255, 255, 60), 4 * k))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawEllipse(c, rad, rad)
            p.save()
            p.translate(c)
            p.rotate(h.get("steer", 0.0) * 180)
            p.setPen(QPen(QColor(C["yellow"]), 4 * k))
            p.drawLine(QPointF(0, -rad), QPointF(0, -rad + 12 * k))
            p.restore()

        # al centro in basso: l'avviso più grave
        alert = h.get("alert")
        if alert is not None:
            lvl, text = alert
            p.setFont(_font(10 * k))
            w = p.fontMetrics().horizontalAdvance(text) + 36 * k
            ar = QRectF(vr.center().x() - w / 2, vr.bottom() - m - 34 * k, w, 30 * k)
            if "speed" in h and ar.left() < vr.left() + m + 260 * k:
                ar.moveTop(ar.top() - 104 * k)          # video stretto: sopra i riquadri in basso
            col = QColor(LEVEL_COLORS[lvl])
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(col.red(), col.green(), col.blue(), 215))
            p.drawRoundedRect(ar, 6, 6)
            p.setPen(QColor("#111111"))
            p.drawText(ar, Qt.AlignmentFlag.AlignCenter, text)


class CarStatusView(QWidget):
    """Vettura vista dall'alto: danni per zona, gomme, freni, sospensioni, sporco."""

    def __init__(self):
        super().__init__()
        self.s = None
        self.info: dict = {}
        self.setMinimumSize(340, 400)

    def set_sample(self, s, info: dict):
        self.s, self.info = s, info or {}
        self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        W, H = self.width(), self.height()
        bw, bh = W * 0.34, H * 0.80
        body = QRectF((W - bw) / 2, (H - bh) / 2 + 6, bw, bh)
        s = self.s
        dmg_on = cs.damage_enabled(self.info)

        # carrozzeria: muso in alto, cinque zone di danno
        p.setPen(QColor(C["dim"]))
        p.setFont(_font(7.5, QFont.Weight.DemiBold))
        p.drawText(QRectF(body.left(), 0, bw, (H - bh) / 2 + 4), Qt.AlignmentFlag.AlignCenter, "▲ MUSO")
        zones = {
            "anteriore": QRectF(body.left() + bw * 0.12, body.top(), bw * 0.76, bh * 0.16),
            "posteriore": QRectF(body.left() + bw * 0.08, body.bottom() - bh * 0.14, bw * 0.84, bh * 0.14),
            "sinistra": QRectF(body.left(), body.top() + bh * 0.18, bw * 0.2, bh * 0.64),
            "destra": QRectF(body.right() - bw * 0.2, body.top() + bh * 0.18, bw * 0.2, bh * 0.64),
            "centro": QRectF(body.left() + bw * 0.24, body.top() + bh * 0.2, bw * 0.52, bh * 0.6),
        }
        outline = QPainterPath()
        outline.addRoundedRect(body, bw * 0.3, bw * 0.3)
        p.setPen(QPen(QColor(C["border"]), 2))
        p.setBrush(QColor(C["panel2"]))
        p.drawPath(outline)
        p.save()
        p.setClipPath(outline)
        for i, (zone, r) in enumerate(zones.items()):
            v = s.car_damage[i] if s is not None else 0.0
            lvl = cs.damage_level(v) if dmg_on else 0
            col = QColor(DAMAGE_COLORS[lvl])
            col.setAlpha(230 if lvl else 120)
            p.setPen(QPen(QColor(C["bg"]), 2))
            p.setBrush(col)
            p.drawRoundedRect(r, 5, 5)
        p.restore()
        # abitacolo
        p.setPen(QPen(QColor(C["bg"]), 2))
        p.setBrush(QColor(C["bg"]))
        cock = QRectF(body.center().x() - bw * 0.16, body.top() + bh * 0.4, bw * 0.32, bh * 0.2)
        p.drawRoundedRect(cock, 8, 8)
        p.setPen(QColor(C["dim"]))
        p.setFont(_font(7.5, QFont.Weight.Normal))
        p.drawText(QRectF(body.left(), body.top() + bh * 0.62, bw, 34), Qt.AlignmentFlag.AlignCenter |
                   Qt.TextFlag.TextWordWrap, "danni\ndisattivati" if not dmg_on else "nessun danno"
                   if s is None or not any(cs.damage_level(v) for v in s.car_damage) else "")

        # gomme ai quattro angoli
        tw, th = bw * 0.3, bh * 0.17
        susp = cs.suspension_fraction(s, self.info) if s is not None else (0.0,) * 4
        for i in range(4):
            left, front = i % 2 == 0, i < 2
            cx = body.left() if left else body.right()
            cy = body.top() + bh * (0.2 if front else 0.78)
            tyre = QRectF(cx - tw / 2, cy - th / 2, tw, th)
            col = temp_color(s.tyre_core_temp[i]) if s is not None else QColor(C["panel2"])
            flat = s is not None and i in cs.punctured(s.tyre_pressure)
            p.setPen(QPen(QColor(C["red"] if flat else "#0b0d10"), 3 if flat else 1.5))
            p.setBrush(col)
            p.drawRoundedRect(tyre, 6, 6)
            if s is not None and s.tyre_dirt[i] >= cs.DIRT_WARN:
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(QColor(110, 80, 40, 150))
                p.drawRoundedRect(tyre.adjusted(3, th * 0.55, -3, -3), 4, 4)
            # corsa sospensione: barra sul lato interno della gomma
            sb = QRectF(tyre.right() + 4 if left else tyre.left() - 10, tyre.top(), 6, th)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(C["border"]))
            p.drawRoundedRect(sb, 2, 2)
            f = susp[i]
            p.setBrush(QColor(C["red"] if f >= 0.97 else C["blue"]))
            p.drawRoundedRect(QRectF(sb.left(), sb.bottom() - th * f, sb.width(), th * f), 2, 2)

            if s is None:
                continue
            lines = [(f"{s.tyre_core_temp[i]:.0f}°", _font(13), col.name()),
                     (f"{s.tyre_pressure[i]:.1f} psi", _font(8.5, QFont.Weight.Normal), C["red"] if flat else C["text"]),
                     (f"usura {s.tyre_wear[i]:.1f}%", _font(8.5, QFont.Weight.Normal),
                      C["red"] if s.tyre_wear[i] < cs.WEAR_CRIT else C["yellow"] if s.tyre_wear[i] < cs.WEAR_WARN
                      else C["text"]),
                     (f"freno {s.brake_temp[i]:.0f}°", _font(8.5, QFont.Weight.Normal),
                      C["red"] if s.brake_temp[i] >= cs.BRAKE_WARN else C["dim"]),
                     (f"sosp. {f * 100:.0f}%", _font(8, QFont.Weight.Normal), C["dim"])]
            tx_w = (W - bw) / 2 - tw / 2 - 18
            x = 4 if left else body.right() + tw / 2 + 14
            y = cy - 44
            align = (Qt.AlignmentFlag.AlignRight if left else Qt.AlignmentFlag.AlignLeft) | \
                Qt.AlignmentFlag.AlignVCenter
            for text, font, color in lines:
                p.setFont(font)
                p.setPen(QColor(color))
                hgt = 22 if font.pointSizeF() > 10 else 16
                p.drawText(QRectF(x, y, tx_w, hgt), align, text)
                y += hgt
        p.end()


class OnboardPage(QWidget):
    def __init__(self, hub):
        super().__init__()
        self.hub = hub
        self.feed = OnboardFeed()
        self._frame_t = 0.0
        self._beat_t = 0.0
        self._img: QImage | None = None

        root = QVBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 16)
        root.setSpacing(12)

        bar = QHBoxLayout()
        bar.addWidget(label("Onboard live", "h1"))
        bar.addStretch()
        self.car = QComboBox()
        self.car.setMinimumWidth(240)
        self.car.addItem("La mia auto", -1)
        self.camera = QComboBox()
        for _key, name in CAMERAS:
            self.camera.addItem(name)
        self.camera.setCurrentIndex(max(0, min(len(CAMERAS) - 1, hub.setting("onboard/camera", 0, int))))
        self.quality = QComboBox()
        for name, *_ in QUALITIES:
            self.quality.addItem(name)
        self.quality.setCurrentIndex(max(0, min(len(QUALITIES) - 1, hub.setting("onboard/quality", 1, int))))
        self.quality.setToolTip("Il video è una seconda vista resa da AC: più qualità costa più FPS in gioco")
        self.video_btn = QPushButton()
        self.video_btn.setCheckable(True)
        self.video_btn.setChecked(hub.setting("onboard/video", True, bool))
        self._video_label()
        self.camera.currentIndexChanged.connect(lambda i: (hub.settings.setValue("onboard/camera", i),
                                                           self._push_request()))
        self.quality.currentIndexChanged.connect(lambda i: (hub.settings.setValue("onboard/quality", i),
                                                            self._push_request()))
        self.car.currentIndexChanged.connect(lambda _: self._push_request())
        self.video_btn.toggled.connect(self._on_video_toggled)
        for w in (label("Auto", "dim"), self.car, label("Telecamera", "dim"), self.camera, label("Qualità", "dim"),
                  self.quality, self.video_btn):
            bar.addWidget(w)
        root.addLayout(bar)

        self.status = label("", "dim")
        root.addWidget(self.status)

        mid = QHBoxLayout()
        mid.setSpacing(12)
        self.view = OnboardView()
        mid.addWidget(self.view, 1)
        side = Card()
        side.setFixedWidth(380)
        sl = QVBoxLayout(side)
        sl.setContentsMargins(12, 10, 12, 12)
        sl.addWidget(label("STATO VETTURA", "dim"))
        self.car_view = CarStatusView()
        sl.addWidget(self.car_view, 1)
        self.info = label("", "dim")
        self.info.setWordWrap(True)
        sl.addWidget(self.info)
        sl.addWidget(label("AVVISI", "dim"))
        self.alerts = label("")
        self.alerts.setWordWrap(True)
        self.alerts.setTextFormat(Qt.TextFormat.RichText)
        self.alerts.setMinimumHeight(110)
        self.alerts.setAlignment(Qt.AlignmentFlag.AlignTop)
        sl.addWidget(self.alerts)
        mid.addWidget(side)
        root.addLayout(mid, 1)

        hub.standings_changed.connect(self._fill_cars)
        hub.session_changed.connect(lambda _: self._fill_cars([]))
        hub.running_changed.connect(lambda _: self._refresh())

        self.timer = QTimer(self)
        self.timer.timeout.connect(self._tick)
        self.timer.start(33)
        self._ui_t = 0.0

    # ------------------------------------------------------------- controlli
    def _video_label(self):
        self.video_btn.setText("Video acceso" if self.video_btn.isChecked() else "Video spento")

    def _on_video_toggled(self, on: bool):
        self.hub.settings.setValue("onboard/video", on)
        self._video_label()
        self._push_request()

    def _fill_cars(self, rows):
        others = [(r.index, f"P{r.pos}  {r.driver or 'auto ' + str(r.index)}  ·  {r.model}") for r in rows
                  if not r.is_player]
        current = [(self.car.itemData(i), self.car.itemText(i)) for i in range(1, self.car.count())]
        if others == current:
            return
        sel = self.car.currentData()
        self.car.blockSignals(True)
        self.car.clear()
        self.car.addItem("La mia auto", -1)
        for idx, text in others:
            self.car.addItem(text, idx)
        self.car.setCurrentIndex(max(0, self.car.findData(sel)))
        self.car.blockSignals(False)
        if self.car.currentData() != sel:
            self._push_request()

    @property
    def _ac_live(self) -> bool:
        w = self.hub.worker
        return self.hub.running and w is not None and w.source == SOURCE_AC

    def _push_request(self) -> bool:
        if not self._ac_live:
            return False
        _name, w, h, fps = QUALITIES[self.quality.currentIndex()]
        self._beat_t = time.monotonic()
        return self.feed.request(self.video_btn.isChecked() and self.isVisible(), self.camera.currentIndex(),
                                 self.car.currentData(), w, h, fps)

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
            path = self.feed.new_frame()
            if path is not None:
                img = QImage(str(path))
                if not img.isNull():
                    self._img, self._frame_t = img, now
        elif self.feed.connected:
            self.feed.disconnect()
        if now - self._ui_t >= 0.066:       # grafica e stato a 15 Hz, il video a ogni fotogramma
            self._ui_t = now
            self._refresh()

    def _placeholder(self) -> str:
        if not self.hub.running:
            return "Acquisizione ferma: avvia la telemetria da Assetto Corsa per vedere l'onboard."
        if not self._ac_live:
            return "Il video onboard arriva solo da Assetto Corsa. In demo e replay restano grafica e stato vettura."
        if not self.video_btn.isChecked():
            return "Video spento: in AC non si rende la seconda vista (più FPS in gioco)."
        if not self.feed.connected:
            return ("App CSP Delta Suite Bridge non collegata o da aggiornare: installala da Box & Assetto "
                    "e riavvia la sessione in AC.")
        inf = self.feed.info()
        if inf is not None and inf.status.startswith("errore"):
            return f"L'app CSP non riesce a rendere l'onboard: {inf.status}"
        if self._img is None:
            return "In attesa del primo fotogramma dall'app CSP…"
        return ""

    def _refresh(self):
        live_video = self._img is not None and time.monotonic() - self._frame_t < STALE_S
        if not self._ac_live:
            self._img = None
        ph = self._placeholder()
        self.view.set_frame(self._img, live_video)
        s = self.hub.last_sample
        info = self.hub.session_info
        laps = self.hub.laps
        fpl = fuel_per_lap(laps) if laps else None
        alerts = cs.car_alerts(s, info, fpl) if s is not None and s.status == ACStatus.LIVE else []
        self.view.set_hud(self._hud(s, alerts), ph if not live_video else "")
        self.car_view.set_sample(s, info)
        self._fill_side(s, alerts, fpl)
        self._fill_status(live_video)

    def _hud(self, s, alerts) -> dict:
        idx = self.car.currentData()
        cam = CAMERAS[self.camera.currentIndex()][1]
        if idx is not None and idx >= 0:
            b = self.hub.bridge_state
            entry = next((c for c in (b.cars if b else []) if c.index == idx), None)
            row = next((r for r in self.hub.standings_rows if r.index == idx), None)
            if entry is None:
                return {"title": self.car.currentText(), "camera": cam}
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
                                        for a in alerts[:7]))

    def _fill_status(self, live_video: bool):
        parts = []
        if live_video:
            inf = self.feed.info()
            if inf is not None:
                parts.append(f"<span style='color:{C['green']}'>●</span>  Video in diretta "
                             f"{inf.width}×{inf.height}, render in AC {inf.render_ms:.1f} ms")
        elif self._ac_live and self.video_btn.isChecked() and self.feed.connected:
            parts.append(f"<span style='color:{C['yellow']}'>●</span>  Video non in diretta")
        if self.car.currentData() not in (None, -1):
            parts.append("lo stato vettura a destra è sempre quello della tua auto")
        self.status.setText("  ·  ".join(parts) if parts else
                            "Seconda telecamera resa da AC tramite l'app CSP; danni, gomme, freni e sospensioni "
                            "dalla shared memory.")
