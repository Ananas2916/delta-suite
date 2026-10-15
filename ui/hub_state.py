"""Stato condiviso dell'hub: thread di acquisizione, giri della sessione, archivio."""

from __future__ import annotations

import time

from PyQt6.QtCore import QObject, QThread, pyqtSignal

from hub_core.ac_shared_memory import ACStatus
from hub_core.database import TelemetryDB
from hub_core.demo_source import DemoSource
from hub_core.lap_recorder import LapData, LapRecorder
from hub_core.telemetry_receiver import TelemetryReceiver

SOURCE_AC = "ac"
SOURCE_DEMO = "demo"


class TelemetryWorker(QThread):
    sample_ready = pyqtSignal(object)
    lap_completed = pyqtSignal(object)
    session_started = pyqtSignal(dict)
    status = pyqtSignal(str, bool)

    def __init__(self, source: str, hz: float, demo_speed: float):
        super().__init__()
        self.source, self.hz, self.demo_speed = source, hz, demo_speed
        self._running = False

    def stop(self):
        self._running = False
        self.wait(3000)

    def run(self):
        src = DemoSource(self.demo_speed) if self.source == SOURCE_DEMO else TelemetryReceiver()
        period = 1.0 / self.hz
        self._running = True
        waiting = False
        while self._running:
            if not src.connect():
                if not waiting:
                    self.status.emit("In attesa di Assetto Corsa: avvia una sessione da Content Manager", False)
                    waiting = True
                self.msleep(1000)
                continue
            waiting = False
            info = src.session_info()
            rec = LapRecorder(info.get("track_length") or 1.0, info.get("sector_count") or 3)
            self.session_started.emit(info)
            self.status.emit(f"{info['source']}: {info['car']} @ {info['track']}", True)

            last_packet, stale_since, next_tick = None, time.perf_counter(), time.perf_counter()
            while self._running:
                s = src.sample()
                if s.packet_id != last_packet:
                    last_packet, stale_since = s.packet_id, s.t
                elif s.t - stale_since > 5.0 and s.status == ACStatus.OFF:
                    src.disconnect()
                    self.status.emit("AC non aggiorna più i dati, riaggancio...", False)
                    break
                lap = rec.feed(s)
                if rec.session_reset:
                    self.session_started.emit(src.session_info())
                if lap is not None:
                    self.lap_completed.emit(lap)
                self.sample_ready.emit(s)

                next_tick += period
                delay = next_tick - time.perf_counter()
                if delay > 0:
                    time.sleep(delay)
                else:
                    next_tick = time.perf_counter()
        src.disconnect()
        self.status.emit("Acquisizione ferma", False)


class HubState(QObject):
    sample = pyqtSignal(object)
    lap_completed = pyqtSignal(object)
    session_changed = pyqtSignal(dict)
    status = pyqtSignal(str, bool)
    running_changed = pyqtSignal(bool)
    db_changed = pyqtSignal()

    def __init__(self):
        super().__init__()
        try:
            self.db = TelemetryDB()
            self.db_error = None
        except Exception as exc:   # es. DB bloccato da un'altra istanza dell'hub
            self.db = TelemetryDB(":memory:")
            self.db_error = str(exc)
        self.session_info: dict = {}
        self.session_id: int | None = None
        self.laps: list[LapData] = []
        self.last_sample = None
        self.worker: TelemetryWorker | None = None

    @property
    def running(self) -> bool:
        return self.worker is not None and self.worker.isRunning()

    def start(self, source: str, hz: float = 60.0, demo_speed: float = 1.0):
        self.stop()
        self.worker = TelemetryWorker(source, hz, demo_speed)
        self.worker.sample_ready.connect(self._on_sample)
        self.worker.lap_completed.connect(self._on_lap)
        self.worker.session_started.connect(self._on_session)
        self.worker.status.connect(self.status)
        self.worker.start()
        self.running_changed.emit(True)

    def stop(self):
        if self.worker is not None:
            self.worker.stop()
            self.worker = None
            self.running_changed.emit(False)

    def _on_session(self, info: dict):
        self.session_info = info
        self.session_id = None          # la riga in archivio nasce al primo giro completato
        self.laps = []
        self.session_changed.emit(info)

    def _on_lap(self, lap: LapData):
        if self.session_id is None:
            self.session_id = self.db.new_session(self.session_info)
        self.db.save_lap(self.session_id, lap)
        self.laps.append(lap)
        self.lap_completed.emit(lap)
        self.db_changed.emit()

    def _on_sample(self, s):
        self.last_sample = s
        self.sample.emit(s)

    def shutdown(self):
        self.stop()
        self.db.close()
