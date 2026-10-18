"""Thread dell'hub: acquisizione (AC, demo o replay) e lavori bloccanti fuori dal thread della UI."""

from __future__ import annotations

import time

from PyQt6.QtCore import QThread, pyqtSignal

from hub_core.ac.csp_bridge import CSPBridge
from hub_core.ac.receiver import TelemetryReceiver
from hub_core.ac.recording import ReplaySource, SessionRecorder, recording_path
from hub_core.analysis.lap_recorder import LapRecorder
from hub_core.demo_source import DemoSource
from hub_core.model import ACStatus

SOURCE_AC = "ac"
SOURCE_DEMO = "demo"
SOURCE_REPLAY = "replay"


class TelemetryWorker(QThread):
    sample_ready = pyqtSignal(object)
    lap_completed = pyqtSignal(object)
    session_started = pyqtSignal(dict)
    status = pyqtSignal(str, bool)
    bridge_state = pyqtSignal(object)
    recording = pyqtSignal(str)

    def __init__(self, source: str, hz: float, speed: float, replay_path: str | None = None, record: bool = False):
        super().__init__()
        self.source, self.hz, self.speed = source, hz, speed
        self.replay_path, self.record = replay_path, record
        self.bridge = CSPBridge() if source == SOURCE_AC else None
        self._running = False

    def stop(self):
        self._running = False
        self.wait(3000)

    def _make_source(self):
        if self.source == SOURCE_DEMO:
            return DemoSource(self.speed)
        if self.source == SOURCE_REPLAY:
            return ReplaySource(self.replay_path, self.speed)
        return TelemetryReceiver()

    def run(self):
        src = self._make_source()
        period = 1.0 / self.hz
        self._running = True
        waiting = False
        recorder: SessionRecorder | None = None
        while self._running and not src.finished:
            try:
                connected = src.connect()
            except (OSError, ValueError) as exc:
                self.status.emit(f"Sorgente non disponibile: {exc}", False)
                break
            if not connected:
                if not waiting:
                    self.status.emit(src.waiting_message, False)
                    waiting = True
                self.msleep(1000)
                continue
            waiting = False
            info = src.session_info()
            rec = LapRecorder(info.get("track_length") or 1.0, info.get("sector_count") or 3)
            self.session_started.emit(info)
            self.status.emit(f"{info['source']}: {info['car']} @ {info['track']}", True)
            if self.record and self.source == SOURCE_AC:
                path = recording_path(info)
                recorder = SessionRecorder(path, src.static_page())
                self.recording.emit(str(path))

            last_packet, stale_since, next_tick = None, time.perf_counter(), time.perf_counter()
            next_bridge = 0.0
            while self._running:
                s = src.sample()
                if s.packet_id != last_packet:
                    last_packet, stale_since = s.packet_id, s.t
                elif s.t - stale_since > 5.0 and s.status == ACStatus.OFF:
                    src.disconnect()
                    self.status.emit("Replay terminato" if src.finished else
                                     "AC non aggiorna più i dati, riaggancio...", False)
                    break
                if recorder is not None and src.last_pages is not None and s.status != ACStatus.OFF:
                    recorder.write(*src.last_pages, s.t)
                lap = rec.feed(s)
                if rec.session_reset:
                    self.session_started.emit(src.session_info())
                if lap is not None:
                    self.lap_completed.emit(lap)
                self.sample_ready.emit(s)
                if src.finished:
                    self.status.emit("Replay terminato", False)
                    break

                now = time.perf_counter()
                if self.bridge is not None and now >= next_bridge:
                    next_bridge = now + 0.1
                    self.bridge_state.emit(self.bridge.read())

                next_tick += period
                delay = next_tick - time.perf_counter()
                if delay > 0:
                    time.sleep(delay)
                else:
                    next_tick = time.perf_counter()
            if recorder is not None:
                recorder.close()
                recorder = None
        src.disconnect()
        if self.bridge is not None:
            self.bridge.disconnect()
            self.bridge_state.emit(None)
        if not src.finished:
            self.status.emit("Acquisizione ferma", False)


class Job(QThread):
    """Esegue una funzione bloccante fuori dal thread della UI."""

    text = pyqtSignal(str)
    done = pyqtSignal(object)
    failed = pyqtSignal(str)

    def __init__(self, fn):
        super().__init__()
        self.fn = fn

    def run(self):
        try:
            self.done.emit(self.fn(self.text.emit))
        except Exception as exc:
            self.failed.emit(f"{type(exc).__name__}: {exc}")
