"""
Recording and replay of the raw pages of AC's shared memory.

.dsr format (Delta Suite Recording), gzip compressed:
    b"DSR1", uint32 physics size, uint32 graphics size, uint32 static size, static page
    then, for each sample: float64 t (s from start), physics page, graphics page

Exactly what the hub reads is recorded, so replay goes through the same code
(sample_from_pages) and a real session becomes a repeatable test without AC running.
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

from hub_core.ac.receiver import sample_from_pages, session_info_from_static
from hub_core.ac.shared_memory import SPageFileGraphic, SPageFilePhysics, SPageFileStatic
from hub_core.model import ACStatus, TelemetrySample

MAGIC = b"DSR1"
_HEADER = struct.Struct("<4sIII")
_T = struct.Struct("<d")
PHY_SIZE = ctypes.sizeof(SPageFilePhysics)
GFX_SIZE = ctypes.sizeof(SPageFileGraphic)
STATIC_SIZE = ctypes.sizeof(SPageFileStatic)


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


class SessionRecorder:
    """Writes the raw pages read by the hub to a .dsr file."""

    def __init__(self, path: str | Path, static: SPageFileStatic):
        self.path = Path(path)
        self._f = gzip.open(self.path, "wb", compresslevel=5)
        self._f.write(_HEADER.pack(MAGIC, PHY_SIZE, GFX_SIZE, STATIC_SIZE))
        self._f.write(bytes(static))
        self._t0 = time.perf_counter()
        self.samples = 0

    def write(self, phy: SPageFilePhysics, gfx: SPageFileGraphic, t: float | None = None) -> None:
        t = (time.perf_counter() if t is None else t) - self._t0
        self._f.write(_T.pack(t))
        self._f.write(bytes(phy))
        self._f.write(bytes(gfx))
        self.samples += 1

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
        if magic != MAGIC:
            raise ValueError(f"{self.path.name} is not a Delta Suite recording")
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

    def next(self) -> tuple[float, SPageFilePhysics, SPageFileGraphic] | None:
        try:
            t = _T.unpack(self._read(_T.size))[0]
            phy = self._page(SPageFilePhysics, self._read(self._phy_size))
            gfx = self._page(SPageFileGraphic, self._read(self._gfx_size))
        except (EOFError, OSError):
            return None
        return t, phy, gfx

    def __iter__(self):
        while (rec := self.next()) is not None:
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

    speed_factor > 1 speeds up; intermediate samples are skipped to stay in real time.
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
        self._wall0 = 0.0
        self._t0 = 0.0
        self.last_pages = None

    def connect(self) -> bool:
        if self.finished:
            return False
        if self._reader is None:
            self._reader = RecordingReader(self.path)
            self._next_rec = self._reader.next()
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

    def sample(self) -> TelemetrySample:
        target = self._t0 + (time.perf_counter() - self._wall0) * self.speed_factor
        while self._next_rec is not None and self._next_rec[0] <= target:
            self._last = self._next_rec
            self._next_rec = self._reader.next()
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
