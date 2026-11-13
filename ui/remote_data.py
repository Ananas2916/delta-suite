"""
Hub side of the remote access (hub_core.remote): what the remote page sees and what it can do.

The page polls `snapshot()` a few times per second from the server's threads: everything is read from lists the
hub replaces rather than modifies (as for the MCP server). Actions arrive on those threads too and go to the Qt
thread through a signal: confirming a proposal, discarding it, a message read out to the driver by the radio
voice, a question to the AI engineer, a live adjustment (it becomes a proposal to confirm, like the AI's).

What touches the CSP app's mappings (onboard video, car positions, F6 cameras) runs on the Qt thread in `_tick`,
and only while a page is looking:
- pit wall data (GPS cars and zones, camera list) is refreshed only while a page has polled in the last seconds;
- the onboard video is on demand: the page asks for frames (/api/frame) only while it shows the video, and the
  remote view (onboard_feed.REMOTE_VIEW) is reserved in AC only while those requests keep coming. When they stop
  (tab changed, browser closed, network gone) it is released after VIDEO_TIMEOUT_S and AC renders nothing more.
Frames are scaled to the requested size and sent as JPEG; there is no queue: the page always gets the newest frame.
"""

from __future__ import annotations

import collections
import itertools
import json
import threading
import time

from PyQt6.QtCore import QBuffer, QByteArray, QIODevice, QObject, Qt, QTimer, pyqtSignal

from ai_engine.voice import PRIO_HIGH
from hub_core.ac.onboard_feed import REMOTE_VIEW, ViewRequest, camera_menu
from hub_core.analysis import race_strategy as rs
from hub_core.i18n import tr
from hub_core.model import ACStatus
from hub_core.remote.auth import Pairing
from hub_core.remote.server import RemoteServer
from ui import race_view as rv
from ui.hub_data import _lap_dict
from ui.widgets.onboard_hud import frame_image

LOG_SIZE = 200
SAY_MAX = 200
ASK_MAX = 1000
AUDIO_KEEP = 12                 # spoken radio messages whose audio the page can still fetch
VIDEO_TIMEOUT_S = 3.0           # no frame request for this long: the remote view is released in AC
LOOK_WINDOW_S = 5.0             # pit wall data is refreshed only if a page polled within this time
JPEG_QUALITY = 75
# remote video: (name, width, height, fps); the remote view is a secondary one, so at most 640×360
QUALITIES = [("Low · 480×270 · 10 fps", 480, 270, 10),
             ("Medium · 640×360 · 15 fps", 640, 360, 15),
             ("Smooth · 640×360 · 20 fps", 640, 360, 20)]
DEFAULT_QUALITY = 1
ADJUST_KINDS = ("brake_bias", "abs", "tc", "engine_brake", "setup")


def encode_jpeg(img, max_w: int, max_h: int, quality: int = JPEG_QUALITY) -> bytes:
    """QImage → JPEG bytes, scaled down to fit max_w×max_h (never up)."""
    if img.width() > max_w or img.height() > max_h:
        img = img.scaled(max_w, max_h, Qt.AspectRatioMode.KeepAspectRatio,
                         Qt.TransformationMode.SmoothTransformation)
    data = QByteArray()
    buf = QBuffer(data)
    buf.open(QIODevice.OpenModeFlag.WriteOnly)
    img.save(buf, "JPG", quality)
    buf.close()
    return bytes(data)


class RemoteAccess(QObject):
    action_requested = pyqtSignal(str, str, object)     # (device, kind, payload): handled in the Qt thread
    changed = pyqtSignal()                              # devices or server state changed (for the dialog)

    def __init__(self, hub):
        super().__init__()
        self.hub = hub
        self.pairing = Pairing()
        try:
            self.pairing.load(json.loads(hub.setting("remote/devices", "[]") or "[]"))
        except ValueError:
            pass
        self.pairing.on_change = self._save_devices
        self.server = RemoteServer(self, self.pairing, int(hub.setting("remote/port", 8790, int)))
        self._log: collections.deque = collections.deque(maxlen=LOG_SIZE)
        self._seq = itertools.count(1)
        self._log_lock = threading.Lock()
        self._audio: collections.OrderedDict[int, bytes] = collections.OrderedDict()

        # pit wall data computed on the Qt thread, read by the server threads (replaced, never modified)
        self._poll_t = -1e9
        self._cache_t = self._cameras_t = -1e9
        self._pitwall: dict = {"gps": {"cars": [], "zones": []}, "track_rev": 0}
        self._cameras: list = []
        self._video_cars: list = []
        self._track: dict = {"rev": 0, "line": [], "pit": []}
        self._track_line = None

        # onboard video on demand
        self._video = threading.Condition()
        self._video_want: tuple[int, int, int] | None = None      # (camera, car, quality)
        self._video_t = -1e9
        self._jpeg: tuple[int, bytes] | None = None
        self._jpeg_seq = 0
        self._video_status = ""
        self._enc_n: int | None = None
        self._enc_t = self._beat_t = -1e9
        self._reserved: ViewRequest | None = None

        hub.radio_log.connect(self._on_radio_log)
        hub.engineer_started.connect(lambda q, mode: self.log("question", q) if mode != "RADIO" else None)
        hub.engineer_done.connect(self._on_engineer_done)
        self.action_requested.connect(self._do_action)
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        if hub.setting("remote/enabled", False, bool):
            self.set_enabled(True)

    # ----------------------------------------------------------- on/off
    @property
    def enabled(self) -> bool:
        return self.server.running

    def set_enabled(self, on: bool) -> bool:
        ok = self.server.start() if on else (self.server.stop() or True)
        self.hub.settings.setValue("remote/enabled", bool(on and ok))
        if self.server.running:
            self._timer.start(25)
        else:
            self._timer.stop()
            self._release_video()
        self.changed.emit()
        return ok

    def _save_devices(self):
        # called from the server's threads too: QSettings is thread-safe, the dialog is refreshed via signal
        self.hub.settings.setValue("remote/devices", json.dumps(self.pairing.export()))
        self.changed.emit()

    # ----------------------------------------------------------- radio log for the page
    def log(self, who: str, text: str, audio: bytes | None = None) -> int:
        with self._log_lock:
            seq = next(self._seq)
            entry = {"seq": seq, "t": time.time(), "who": who, "text": text}
            if audio:
                entry["audio"] = True
                self._audio[seq] = audio
                while len(self._audio) > AUDIO_KEEP:
                    self._audio.popitem(last=False)
            self._log.append(entry)
        return seq

    def _on_radio_log(self, who: str, text: str):
        audio = None
        if who == "radio":                 # spoken by the radio voice: its audio is still in the voice's cache
            try:
                audio = self.hub.radio.voice.cached_wav(text)
            except AttributeError:
                audio = None
        self.log(who, text, audio)

    def _on_engineer_done(self, answer: str):
        if answer and getattr(self.hub, "_job_mode", "") != "RADIO":      # radio answers are logged when spoken
            self.log("engineer", answer)

    # ----------------------------------------------------------- Qt thread: video and pit wall data
    def _tick(self):
        now = time.monotonic()
        try:
            self._video_tick(now)
        except Exception as exc:             # the remote page must never break the hub
            self._set_status(f"{type(exc).__name__}: {exc}")
        if now - self._poll_t < LOOK_WINDOW_S and now - self._cache_t >= 0.2:
            self._cache_t = now
            try:
                self._refresh_pitwall(now)
            except Exception:
                pass

    def _set_status(self, text: str):
        with self._video:
            self._video_status = text
            if text:
                self._video.notify_all()

    def _release_video(self):
        if self._reserved is not None:
            self.hub.onboard_feed.release(REMOTE_VIEW)
            self._reserved = None
            self._enc_n = None

    def _video_tick(self, now: float):
        with self._video:
            want, t = self._video_want, self._video_t
        if want is None or now - t > VIDEO_TIMEOUT_S:
            self._release_video()
            return
        hub, feed = self.hub, self.hub.onboard_feed
        if not hub.ac_live:
            self._release_video()
            self._set_status(rv.video_placeholder(hub, True, False, True))
            return
        cam, car, q = want
        _name, w, h, fps = QUALITIES[q]
        req = ViewRequest(True, cam, car, w, h, fps)
        if req != self._reserved:
            feed.reserve(REMOTE_VIEW, req)
            self._reserved, self._beat_t, self._enc_n = req, -1e9, None
        if now - self._beat_t > 0.5:
            self._beat_t = now
            if not feed.heartbeat():
                self._set_status(rv.video_placeholder(hub, True, False, True, REMOTE_VIEW))
                return
        if now - self._enc_t < 1.0 / fps:
            return
        got = feed.latest_frame(REMOTE_VIEW)
        if got is None or got[0] == self._enc_n:
            if got is None:
                self._set_status(rv.video_placeholder(hub, True, False, True, REMOTE_VIEW))
            return
        n, frame = got
        img = frame_image(frame)
        if img.isNull():
            return
        data = encode_jpeg(img, w, h)
        self._enc_n, self._enc_t = n, now
        with self._video:
            self._jpeg_seq += 1
            self._jpeg = (self._jpeg_seq, data)
            self._video_status = ""
            self._video.notify_all()

    def _refresh_pitwall(self, now: float):
        hub = self.hub
        s = hub.last_sample
        live = s is not None and s.status == ACStatus.LIVE
        line = hub.track.line
        if line is not self._track_line:
            self._track_line = line
            pts = [] if line is None else [[round(float(x), 1), round(float(z), 1)] for x, z in zip(line.xs, line.zs)]
            self._track = {"rev": self._track["rev"] + 1, "line": pts,
                           "pit": [[round(x, 1), round(z, 1)] for x, z in (hub.track.pit or [])]}
        zones = hub.track.display_zones(s.lap_position if live else None, s.flag if s is not None else 0)
        self._pitwall = {
            "gps": {"cars": rv.gps_cars(hub, s, {}),
                    "zones": [{"start": z.start, "end": z.end, "kind": z.kind} for z in zones]},
            "track_rev": self._track["rev"],
        }
        if now - self._cameras_t >= 1.0:
            self._cameras_t = now
            feed = hub.onboard_feed
            f6 = feed.f6_cameras() if feed.connected else [n for n in hub.setting("onboard/f6_names", "").split("|") if n]
            self._cameras = [[text, idx] for text, idx in camera_menu(f6)]
            self._video_cars = [[-1, tr("Your car")]] + [
                [r.index, f"P{r.pos}  {r.driver or tr('car {n}', n=r.index)}"]
                for r in list(hub.standings_rows) if not r.is_player]

    # ----------------------------------------------------------- RemoteProvider (server threads)
    def snapshot(self, since: int, laps_known: int) -> dict:
        self._poll_t = time.monotonic()
        hub = self.hub
        s = hub.last_sample
        live = hub.provider.live_state()
        if s is not None:
            live["position"] = s.position
            live["delta_s"] = None if hub.live_lap.delta_s is None else round(hub.live_lap.delta_s, 2)
            live["current_lap_ms"] = s.lap_time_ms
            live["tyre_compound"] = s.tyre_compound
            live["gas"], live["brake"] = round(s.gas, 2), round(s.brake, 2)
        with self._log_lock:
            radio = [e for e in self._log if e["seq"] > since]
        with self._video:
            video_status = self._video_status
        laps = list(hub.laps)
        out = {
            "time": time.time(),
            "running": hub.running,
            "ac_live": hub.ac_live,
            "race": hub.is_race,
            "live": live,
            "standings": [r.as_dict() for r in list(hub.standings_rows)],
            "proposals": [p.as_dict() for p in list(hub.proposals)[-12:]],
            "radio": radio,
            "engineer_busy": hub.engineer_busy,
            "laps_n": len(laps),
            **self._pitwall,
            "video": {"cameras": self._cameras, "cars": self._video_cars, "status": video_status,
                      "qualities": [q[0] for q in QUALITIES], "default_quality": DEFAULT_QUALITY},
        }
        if laps_known != len(laps):
            valid = [l for l in laps if l.valid]
            out["laps"] = [_lap_dict(l) for l in laps[-60:]]
            out["best_lap"] = rs.fmt_ms(min(l.lap_time_ms for l in valid)) if valid else None
            out["theoretical_best"] = rs.fmt_ms(rs.theoretical_best(laps)) if laps else None
            out["best_sectors_ms"] = rs.best_sectors(laps) if laps else []
        return out

    def video_frame(self, camera: int, car: int, quality: int, after: int, wait_s: float) -> dict:
        """Newest JPEG different from `after` (waits up to wait_s for one), or why there is none."""
        want = (int(camera), int(car), max(0, min(len(QUALITIES) - 1, int(quality))))
        deadline = time.monotonic() + wait_s
        with self._video:
            if want != self._video_want:
                self._video_want, self._jpeg = want, None          # never a frame of the previous camera
            self._video_t = time.monotonic()
            while (self._jpeg is None or self._jpeg[0] == after) and not self._video_status:
                left = deadline - time.monotonic()
                if left <= 0:
                    break
                self._video.wait(left)
            if self._jpeg is not None and self._jpeg[0] != after:
                return {"seq": self._jpeg[0], "jpeg": self._jpeg[1]}
            return {"status": self._video_status or tr("Waiting for the first frame…")}

    def audio(self, seq: int) -> bytes | None:
        with self._log_lock:
            return self._audio.get(seq)

    def data(self, name: str) -> dict | None:
        if name == "track":
            return self._track
        if name == "setup":
            return self._setup()
        if name == "strategy":
            return self._strategy()
        return None

    def _setup(self) -> dict:
        b, s = self.hub.bridge_state, self.hub.last_sample
        out = self.hub.provider.current_setup()
        if b is None:
            out["controls"] = None
            return out
        out["controls"] = {
            "brake_bias": round(b.brake_bias * 100, 1), "brake_bias_min": round(b.brake_bias_min * 100, 1),
            "brake_bias_max": round(b.brake_bias_max * 100, 1),
            "brake_bias_step": round((b.brake_bias_step or 0.005) * 100, 2),
            "abs": b.abs_mode, "abs_levels": b.abs_modes, "tc": b.tc_mode, "tc_levels": b.tc_modes,
            "engine_brake": s.engine_brake if s is not None else None, "engine_brake_levels": b.engine_brake_count,
        }
        return out

    def _strategy(self) -> dict:
        hub = self.hub
        s, b, info = hub.last_sample, hub.bridge_state, hub.session_info
        laps = list(hub.laps)
        fpl = rs.fuel_per_lap(laps)
        out: dict = {"fuel_per_lap_l": round(fpl, 3) if fpl else None, "laps": len(laps),
                     "ideal_lap": rs.fmt_ms(rs.theoretical_best(laps)) if laps else None,
                     "best_sectors_ms": rs.best_sectors(laps) if laps else []}
        prog = None
        if s is not None:
            prog = rs.race_progress_for(s, b.cars if b else [], hub.is_race, info.get("extra_lap", False))
            out.update({"fuel_l": round(s.fuel, 1), "laps_to_go": prog.to_go, "laps_to_go_estimated": prog.estimated,
                        "time_left_s": round(prog.time_left_s) if prog.time_left_s is not None else None,
                        "tyre_wear_pct": [round(v, 1) for v in s.tyre_wear]})
        tank = float(info.get("max_fuel") or 0)
        if s is not None and fpl and prog is not None and prog.to_go and tank > 0:
            plan = rs.fuel_plan(s.fuel, fpl, prog.to_go, tank, s.completed_laps)
            out["plan"] = {"fuel_needed_l": round(plan.fuel_needed, 1), "fuel_to_add_l": round(plan.fuel_to_add, 1),
                           "laps_on_fuel": round(plan.laps_on_current_fuel, 1), "stops": plan.stops_needed,
                           "pit_window": list(plan.pit_window) if plan.pit_window else None}
        stint = rs.current_stint(laps)
        out["stint_laps"] = len(stint)
        fc = rs.forecast_degradation(stint)
        if fc is not None:
            out["degradation"] = {"s_per_lap": round(fc.deg_per_lap, 3), "drop_off_at_stint_lap": fc.cliff_lap,
                                  "forecast": [rs.fmt_ms(t * 1000) for t in fc.forecast_times[:10]]}
            if prog is not None and prog.to_go:
                out["optimal_pit_stint_lap"] = rs.optimal_pit_lap(
                    fc, prog.to_go, hub.setting("strategy/pit_loss", 25.0, float))
        return out

    def action(self, device: str, kind: str, payload: dict) -> dict:
        if kind in ("confirm", "discard"):
            try:
                pid = int(payload.get("id"))
            except (TypeError, ValueError):
                return {"ok": False, "error": "proposal id missing"}
            if not any(p.id == pid and p.status in ("pending", "in pits", "error") for p in list(self.hub.proposals)):
                return {"ok": False, "error": "the proposal is no longer pending"}
            self.action_requested.emit(device, kind, pid)
            return {"ok": True}
        if kind in ("say", "ask"):
            text = " ".join(str(payload.get("text", "")).split())[: SAY_MAX if kind == "say" else ASK_MAX]
            if not text:
                return {"ok": False, "error": "empty message"}
            if kind == "ask" and self.hub.engineer_busy:
                return {"ok": False, "error": "the engineer is still answering"}
            self.action_requested.emit(device, kind, text)
            return {"ok": True}
        if kind == "adjust":
            # a live change from the remote pit wall is a proposal like the AI's: confirmed before it is sent
            what = str(payload.get("what", ""))
            if what not in ADJUST_KINDS:
                return {"ok": False, "error": f"unknown adjustment {what!r}"}
            try:
                value = float(payload.get("value"))
            except (TypeError, ValueError):
                return {"ok": False, "error": "value missing"}
            if what == "brake_bias":
                value /= 100.0                    # the page works in %
            res = self.hub.provider.propose(what, value, str(payload.get("name", ""))[:40],
                                            tr("From the remote pit wall ({device})", device=device))
            if not res.get("accepted"):
                return {"ok": False, "error": res.get("reason", "not accepted")}
            return {"ok": True, "id": res["id"], "description": res["description"]}
        return {"ok": False, "error": f"unknown action {kind!r}"}

    def _do_action(self, device: str, kind: str, payload):
        hub = self.hub
        if kind == "confirm":
            hub.apply_proposal(payload)
            hub.radio_log.emit("system", tr("Proposal confirmed from {device}", device=device))
        elif kind == "discard":
            hub.discard_proposal(payload)
            hub.radio_log.emit("system", tr("Proposal discarded from {device}", device=device))
        elif kind == "say":
            # the remote engineer talks to the driver through the radio voice (logged as "radio" when spoken)
            hub.radio_log.emit("remote", f"{device}: {payload}")
            hub.say(payload, PRIO_HIGH, 60)       # a person talking: before the scripted calls
        elif kind == "ask":
            if not hub.ask_engineer(f"[{device}, from the remote pit wall] {payload}", "ANALYSIS"):
                self.log("system", "The engineer is busy or not available")

    def shutdown(self):
        self._timer.stop()
        self._release_video()
        self.server.stop()
