"""
Recording and replay of the raw pages of AC's shared memory, plus the rivals seen by the CSP app.

.dsr format (Delta Suite Recording), gzip compressed:
    b"DSR2", uint32 physics size, uint32 graphics size, uint32 static size, static page
    then a sequence of records, each starting with one byte:
      1  sample: float64 t (s from start), physics page, graphics page
      2  cars:   float64 t, uint16 count, count × CAR (the CSP app's standings: position, laps, spline,
                 times, pit, speed, names)
DSR1 files (before 0.6.0) have no record byte and only samples; they are still read.

Exactly what the hub reads is recorded, so replay goes through the same code (sample_from_pages, and the
same standings/flags/race calls fed by the cars) and a real race becomes a repeatable test without AC.
"""

from __future__ import annotations

import ctypes
import gzip
import os
import re
import struct
import time
from datetime import datetime
from pathlib import Path

from hub_core.ac.csp_bridge import BridgeState
from hub_core.ac.receiver import sample_from_pages, session_info_from_static
from hub_core.ac.shared_memory import SPageFileGraphic, SPageFilePhysics, SPageFileStatic
from hub_core.model import ACStatus, CarEntry, TelemetrySample

MAGIC_V1, MAGIC = b"DSR1", b"DSR2"
_HEADER = struct.Struct("<4sIII")
_T = struct.Struct("<d")
_COUNT = struct.Struct("<H")
_CAR = struct.Struct("<iBiifiiiBBfB32s32s")
REC_SAMPLE, REC_CARS = 1, 2
PHY_SIZE = ctypes.sizeof(SPageFilePhysics)
GFX_SIZE = ctypes.sizeof(SPageFileGraphic)
STATIC_SIZE = ctypes.sizeof(SPageFileStatic)
CARS_EVERY_S = 0.2           # rivals are recorded at 5 Hz: enough for gaps and flags, small files


def recordings_dir() -> Path:
    base = Path(os.environ.get("LOCALAPPDATA", Path.home())) / "DeltaSuite" / "recordings"
    base.mkdir(parents=True, exist_ok=True)
    return base


def recording_path(info: dict) -> Path:
    def clean(s: str) -> str:
        return re.sub(r"[^A-Za-z0-9_.-]+", "_", s or "x")[:40]
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    return recordings_dir() / f"{stamp}_{clean(info.get('car_id') or info.get('car'))}_" \
                              f"{clean(info.get('track_id') or info.get('track'))}.dsr"


def _pack_car(c: CarEntry) -> bytes:
    return _CAR.pack(c.index, c.connected, c.race_pos, c.lap_count, c.spline, c.lap_time_ms, c.last_lap_ms,
                     c.best_lap_ms, c.in_pitlane, c.in_pit, c.speed_kmh, c.last_lap_valid,
                     c.driver.encode("utf-8")[:32], c.model.encode("utf-8")[:32])


def _unpack_car(data: bytes) -> CarEntry:
    (index, connected, race_pos, laps, spline, lap_ms, last_ms, best_ms, pitlane, pit, speed, valid, driver,
     model) = _CAR.unpack(data)
    text = lambda b: b.split(b"\0", 1)[0].decode("utf-8", errors="replace")  # noqa: E731
    return CarEntry(index, bool(connected), race_pos, laps, spline, lap_ms, last_ms, best_ms, bool(pitlane),
                    bool(pit), speed, bool(valid), text(driver), text(model))


def bridge_state_from_cars(cars: list[CarEntry]) -> BridgeState:
    """A CSP app state with only the rivals, as replay provides it (no setup, no commands)."""
    return BridgeState(frame=0, ack_seq=0, ack_ok=False, ack_msg="", focused_car=0, setup_editable=False,
                       ptt_down=False, confirm_count=0, cancel_count=0, brake_bias=0.0, brake_bias_step=0.0,
                       brake_bias_min=0.0, brake_bias_max=0.0, abs_mode=0, abs_modes=0, tc_mode=0, tc_modes=0,
                       engine_brake_count=0, pit_preset=0, cars=list(cars))


class SessionRecorder:
    """Writes the raw pages read by the hub, and the CSP app's cars, to a .dsr file."""

    def __init__(self, path: str | Path, static: SPageFileStatic):
        self.path = Path(path)
        self._f = gzip.open(self.path, "wb", compresslevel=5)
        self._f.write(_HEADER.pack(MAGIC, PHY_SIZE, GFX_SIZE, STATIC_SIZE))
        self._f.write(bytes(static))
        self._t0 = time.perf_counter()
        self._cars_t = -1e9
        self.samples = 0

    def write(self, phy: SPageFilePhysics, gfx: SPageFileGraphic, t: float | None = None) -> None:
        t = (time.perf_counter() if t is None else t) - self._t0
        self._f.write(bytes([REC_SAMPLE]))
        self._f.write(_T.pack(t))
        self._f.write(bytes(phy))
        self._f.write(bytes(gfx))
        self.samples += 1

    def write_cars(self, cars: list[CarEntry], t: float | None = None) -> None:
        """The CSP app's cars; called at every bridge read, written at most every CARS_EVERY_S."""
        t = (time.perf_counter() if t is None else t) - self._t0
        if t - self._cars_t < CARS_EVERY_S:
            return
        self._cars_t = t
        cars = cars[:0xFFFF]
        self._f.write(bytes([REC_CARS]))
        self._f.write(_T.pack(t))
        self._f.write(_COUNT.pack(len(cars)))
        self._f.write(b"".join(_pack_car(c) for c in cars))

    def close(self) -> None:
        if self._f is not None:
            self._f.close()
            self._f = None


class RecordingReader:
    """Sequential reading of a .dsr file."""

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self._f = gzip.open(self.path, "rb")
        magic, phy, gfx, st = _HEADER.unpack(self._read(_HEADER.size))
        if magic not in (MAGIC, MAGIC_V1):
            raise ValueError(f"{self.path.name} is not a Delta Suite recording")
        self.version = 2 if magic == MAGIC else 1
        self._phy_size, self._gfx_size = phy, gfx
        self.static = self._page(SPageFileStatic, self._read(st))

    def _read(self, n: int) -> bytes:
        data = self._f.read(n)
        if len(data) < n:
            raise EOFError
        return data

    @staticmethod
    def _page(cls, data: bytes):
        # pages recorded by versions with a shorter/longer structure: copy the common part
        out = cls()
        n = min(len(data), ctypes.sizeof(cls))
        ctypes.memmove(ctypes.addressof(out), data, n)
        return out

    def next_record(self):
        """("sample", t, phy, gfx), ("cars", t, [CarEntry]) or None at the end."""
        try:
            kind = REC_SAMPLE if self.version == 1 else self._read(1)[0]
            t = _T.unpack(self._read(_T.size))[0]
            if kind == REC_CARS:
                n = _COUNT.unpack(self._read(_COUNT.size))[0]
                data = self._read(n * _CAR.size)
                return "cars", t, [_unpack_car(data[i * _CAR.size:(i + 1) * _CAR.size]) for i in range(n)]
            if kind != REC_SAMPLE:
                return None         # unknown record: a newer format, stop here rather than misread
            phy = self._page(SPageFilePhysics, self._read(self._phy_size))
            gfx = self._page(SPageFileGraphic, self._read(self._gfx_size))
        except (EOFError, OSError):
            return None
        return "sample", t, phy, gfx

    def next(self) -> tuple[float, SPageFilePhysics, SPageFileGraphic] | None:
        """Next sample, skipping the car records."""
        while (rec := self.next_record()) is not None:
            if rec[0] == "sample":
                return rec[1:]
        return None

    def __iter__(self):
        while (rec := self.next()) is not None:
            yield rec

    def records(self):
        while (rec := self.next_record()) is not None:
            yield rec

    def close(self) -> None:
        self._f.close()


def read_samples(path: str | Path) -> tuple[dict, list[TelemetrySample]]:
    """The whole recording in memory (for tests and offline analysis)."""
    r = RecordingReader(path)
    try:
        info = session_info_from_static(r.static, "Replay")
        return info, [sample_from_pages(phy, gfx, t) for t, phy, gfx in r]
    finally:
        r.close()


class ReplaySource:
    """Source with the same interface as TelemetryReceiver that plays back a .dsr file.

    speed_factor > 1 speeds up; intermediate samples are skipped to stay in real time. Recordings with the
    CSP app's cars also replay the standings (bridge_state()).
    """

    name = "Replay"
    waiting_message = "Opening the recording..."

    def __init__(self, path: str | Path, speed_factor: float = 1.0):
        self.path = Path(path)
        self.speed_factor = max(0.1, speed_factor)
        self.finished = False
        self._reader: RecordingReader | None = None
        self._next_rec = None
        self._last = None
        self._cars: list[CarEntry] | None = None
        self._wall0 = 0.0
        self._t0 = 0.0
        self.last_pages = None

    def _advance(self):
        """Next sample record, remembering the car records met on the way."""
        while (rec := self._reader.next_record()) is not None:
            if rec[0] == "cars":
                self._cars = rec[2]
                continue
            return rec[1:]
        return None

    def connect(self) -> bool:
        if self.finished:
            return False
        if self._reader is None:
            self._reader = RecordingReader(self.path)
            self._next_rec = self._advance()
            if self._next_rec is None:
                self.finished = True
                return False
            self._t0 = self._next_rec[0]
            self._wall0 = time.perf_counter()
        return True

    def disconnect(self) -> None:
        if self._reader is not None:
            self._reader.close()
            self._reader = None

    def session_info(self) -> dict:
        info = session_info_from_static(self._reader.static, f"Replay {self.path.name}")
        return info

    def bridge_state(self) -> BridgeState | None:
        """The rivals at the current replay time, or None if the recording has none."""
        return None if self._cars is None else bridge_state_from_cars(self._cars)

    def sample(self) -> TelemetrySample:
        target = self._t0 + (time.perf_counter() - self._wall0) * self.speed_factor
        while self._next_rec is not None and self._next_rec[0] <= target:
            self._last = self._next_rec
            self._next_rec = self._advance()
        if self._last is None:
            self._last = self._next_rec
        t, phy, gfx = self._last
        if self._next_rec is None:
            self.finished = True
        self.last_pages = (phy, gfx)
        s = sample_from_pages(phy, gfx, time.perf_counter())
        if self.finished:
            # end of recording: like AC going back to the menus
            s = TelemetrySample(**{**s.__dict__, "status": ACStatus.OFF})
        return s
