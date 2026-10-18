"""
Video onboard dall'app Lua di CSP (ac_app/DeltaSuiteBridge).

L'app rende una telecamera montata sull'auto scelta (ac.GeometryShot, una seconda vista oltre a
quella del pilota), le applica esposizione e gamma (la seconda vista non passa dal post-processing
del gioco e senza esce scura; in alternativa YEBIS usa il post-processing del gioco) e pubblica i
fotogrammi a rotazione su SLOTS posti, in uno dei due modi:
  - memoria: il DDS grezzo di ExtraCanvas:encode() nella mapping stessa (in CSP 0.2.11 encode non
    comprime e non prende il formato), niente file né log;
  - file: un JPG nella cartella indicata da qui; CSP scrive una riga di log per ogni file.
Lo scambio passa da una mapping a parte, DeltaSuite_Onboard_v3, così il layout del ponte comandi
resta invariato:
  - Delta Suite scrive le richieste (attivo, telecamera, auto, risoluzione, fps, esposizione, curva,
    trasporto, cartella) e hostBeat;
  - l'app scrive frame (ultimo fotogramma pubblicato, nel posto frame % SLOTS), dimensioni, FPS del
    gioco e stato.
Si legge sempre il fotogramma precedente all'ultimo: l'ultimo può essere ancora in scrittura, quello
prima è chiuso e l'app non lo riscrive per altri SLOTS - 1 fotogrammi.

Il layout deve restare identico a ONBOARD_LAYOUT in DeltaSuiteBridge.lua.
"""

from __future__ import annotations

import ctypes
import os
from dataclasses import dataclass
from pathlib import Path

ONBOARD_TAG = "Local\\DeltaSuite_Onboard_v3"
ONBOARD_VERSION = 3
END_MARKER = 0x44534F31   # 'DSO1'
SLOTS = 3
DATA_MAX = 3686656        # byte per fotogramma nella mapping: DDS 1280×720 a 8 bit per canale + intestazione

# telecamere: (chiave, nome) nello stesso ordine degli indici in DeltaSuiteBridge.lua
CAMERAS = [
    ("tcam", "T-cam (sopra il roll-bar)"),
    ("hood", "Cofano (vista pilota)"),     # l'abitacolo in una seconda vista non viene reso
    ("rear", "Posteriore"),
    ("wheel_fl", "Ruota anteriore sinistra"),
    ("wheel_fr", "Ruota anteriore destra"),
    ("wheel_rl", "Ruota posteriore sinistra"),
    ("wheel_rr", "Ruota posteriore destra"),
    ("chase", "Inseguimento"),
]

# qualità: (nome, larghezza, altezza, fps)
QUALITIES = [
    ("Bassa · 480×270 · 10 fps", 480, 270, 10),
    ("Media · 640×360 · 15 fps", 640, 360, 15),
    ("Alta · 960×540 · 20 fps", 960, 540, 20),
    ("Massima · 1280×720 · 25 fps", 1280, 720, 25),
]

# esposizione e curva applicate dall'app: 0 niente, 1 solo gamma, 2 curva filmica + gamma,
# 3 YEBIS (antialiasing e post-processing del gioco fatti dalla GeometryShot)
TONEMAP_NONE, TONEMAP_GAMMA, TONEMAP_FILMIC, TONEMAP_YEBIS = 0, 1, 2, 3
DEFAULT_TONEMAP = TONEMAP_FILMIC
DEFAULT_EXPOSURE = 1.6        # provata il 18/10 al Red Bull Ring: la più simile al gioco con la filmica

TRANSPORT_FILE, TRANSPORT_MEMORY = 0, 1
DEFAULT_TRANSPORT = TRANSPORT_MEMORY

c_int, c_float, c_char = ctypes.c_int, ctypes.c_float, ctypes.c_char


class OnboardShared(ctypes.Structure):
    _fields_ = [
        ("version", c_int),
        # scritti da Delta Suite
        ("hostBeat", c_int), ("enabled", c_int), ("camera", c_int), ("carIndex", c_int),
        ("width", c_int), ("height", c_int), ("fps", c_int), ("exposure", c_float), ("tonemap", c_int),
        ("transport", c_int), ("folder", c_char * 260),
        # scritti dall'app
        ("frame", c_int), ("shotWidth", c_int), ("shotHeight", c_int), ("shotCar", c_int),
        ("renderMs", c_float), ("gameFps", c_float), ("status", c_char * 96),
        ("dataSize", c_int * SLOTS), ("data", (c_char * DATA_MAX) * SLOTS),
        ("endMarker", c_int),
    ]


def onboard_dir() -> Path:
    base = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
    return Path(base) / "DeltaSuite" / "onboard"


def frame_file(folder: Path, frame: int) -> Path:
    return folder / f"onboard_{frame % SLOTS}.jpg"


@dataclass
class Frame:
    """Un fotogramma: "jpg" (data è il file) oppure pixel grezzi "rgba"/"bgra" a 8 bit per canale."""

    kind: str
    data: bytes
    width: int = 0
    height: int = 0
    stride: int = 0


def decode_dds(raw: bytes) -> Frame:
    """Pixel del primo livello di un DDS non compresso a 32 bit (quello che dà ExtraCanvas:encode)."""
    if len(raw) < 128 or raw[:4] != b"DDS ":
        raise ValueError("non è un DDS")
    u32 = lambda off: int.from_bytes(raw[off:off + 4], "little")  # noqa: E731
    height, width, flags, pitch = u32(12), u32(16), u32(8), u32(20)
    fourcc, bits, rmask = raw[84:88], u32(88), u32(92)
    start = 128
    if fourcc == b"DX10":
        dxgi = u32(128)
        start = 148
        if dxgi in (28, 29):        # R8G8B8A8_UNORM(_SRGB)
            kind = "rgba"
        elif dxgi in (87, 88, 91):  # B8G8R8A8 / B8G8R8X8
            kind = "bgra"
        else:
            raise ValueError(f"formato DXGI {dxgi} non gestito")
    elif bits == 32 and rmask in (0x000000FF, 0x00FF0000):
        kind = "rgba" if rmask == 0x000000FF else "bgra"
    else:
        raise ValueError(f"DDS a {bits} bit con maschera {rmask:#x} non gestito")
    stride = pitch if flags & 0x8 and pitch >= width * 4 else width * 4
    if len(raw) < start + stride * height:
        raise ValueError("DDS troncato")
    return Frame(kind, raw[start:start + stride * height], width, height, stride)


def readable_frame(frame: int) -> int | None:
    """Fotogramma sicuro da leggere quando l'app ha appena pubblicato `frame`."""
    return frame - 1 if frame >= 2 else None


@dataclass
class OnboardInfo:
    frame: int
    width: int
    height: int
    car: int
    render_ms: float
    game_fps: float
    status: str


class OnboardFeed:
    """Lato Delta Suite del video onboard. Non bloccante: si chiama da un QTimer della UI."""

    def __init__(self, folder: Path | None = None):
        self.folder = folder or onboard_dir()
        self._view = None
        self._last_read = None

    @property
    def connected(self) -> bool:
        return self._view is not None

    def connect(self) -> bool:
        if self._view is not None:
            return True
        from hub_core.csp_bridge import _FILE_MAP_READ, _FILE_MAP_WRITE, _View
        try:
            self._view = _View(ONBOARD_TAG, OnboardShared, _FILE_MAP_READ | _FILE_MAP_WRITE)
        except (FileNotFoundError, OSError):
            return False
        self.folder.mkdir(parents=True, exist_ok=True)
        return True

    def disconnect(self) -> None:
        if self._view is not None:
            try:
                self._view.struct.enabled = 0
            except (OSError, ValueError):
                pass
            self._view.close()
            self._view = None
        self._last_read = None

    def request(self, enabled: bool, camera: int, car_index: int, width: int, height: int, fps: int,
                exposure: float = DEFAULT_EXPOSURE, tonemap: int = DEFAULT_TONEMAP,
                transport: int = DEFAULT_TRANSPORT) -> bool:
        """Aggiorna le richieste e il battito (va chiamata almeno una volta al secondo)."""
        if not self.connect():
            return False
        s = self._view.struct
        s.version = ONBOARD_VERSION
        s.endMarker = END_MARKER
        s.folder = str(self.folder).encode("utf-8")[:259]
        s.camera, s.carIndex = camera, car_index
        s.width, s.height, s.fps = width, height, fps
        s.exposure, s.tonemap, s.transport = exposure, tonemap, transport
        s.enabled = 1 if enabled else 0
        s.hostBeat = (s.hostBeat + 1) & 0x7FFFFFFF
        return True

    def info(self) -> OnboardInfo | None:
        if self._view is None:
            return None
        s = self._view.struct
        if s.version != ONBOARD_VERSION:
            return None
        return OnboardInfo(s.frame, s.shotWidth, s.shotHeight, s.shotCar, s.renderMs, s.gameFps,
                           s.status.split(b"\0", 1)[0].decode("utf-8", errors="replace"))

    def new_frame(self) -> Frame | None:
        """Fotogramma da mostrare, se ce n'è uno nuovo dall'ultima chiamata."""
        inf = self.info()
        if inf is None:
            return None
        n = readable_frame(inf.frame)
        if n is None or n == self._last_read:
            return None
        self._last_read = n
        size = self._view.struct.dataSize[n % SLOTS]
        in_memory = 0 < size <= DATA_MAX
        if in_memory:
            off = OnboardShared.data.offset + (n % SLOTS) * DATA_MAX
            data = ctypes.string_at(self._view.ptr + off, size)
        else:
            try:
                data = frame_file(self.folder, n).read_bytes()
            except OSError:
                return None
        # se nel frattempo l'app ha pubblicato n + 2, può aver già cominciato a riscrivere questo posto
        if self._view.struct.frame > n + 1:
            return None
        if not in_memory:
            return Frame("jpg", data)
        try:
            return decode_dds(data)
        except ValueError:
            return None
