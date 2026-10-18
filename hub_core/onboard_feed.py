"""
Video onboard dall'app Lua di CSP (ac_app/DeltaSuiteBridge), fino a VIEWS viste insieme.

Per ogni vista (0 = principale, 1-3 = secondarie come nelle dirette con più onboard) l'app rende una
telecamera montata sull'auto scelta (ac.GeometryShot, una vista in più oltre a quella del pilota), le
applica esposizione e gamma (la seconda vista non passa dal post-processing del gioco e senza esce
scura; in alternativa YEBIS usa il post-processing del gioco) e pubblica i fotogrammi in uno di tre modi:
  - condivisa: il canvas è una texture D3D11 condivisa, Delta Suite la apre e la copia sulla propria
    GPU (hub_core/d3d_shared.py); in AC nessuna lettura dalla GPU, che a 1280×720 costa 9-12 ms;
  - memoria (solo la vista principale): il DDS grezzo di ExtraCanvas:encode() nella mapping stessa, a
    rotazione su SLOTS posti (in CSP 0.2.11 encode non comprime e non prende il formato);
  - file: un JPG nella cartella indicata da qui; CSP scrive una riga di log per ogni file.
Se la texture condivisa non si apre si torna alla memoria (alla principale) o ai file (alle altre).
L'app rende al massimo una vista per fotogramma di AC, la più in ritardo, così il costo non fa picchi;
pubblica anche la posizione di ogni auto (mappa GPS) e le telecamere F6 dell'auto del giocatore, da
cui camera_names ricava nomi leggibili.

Lo scambio passa da una mapping a parte, DeltaSuite_Onboard_v6, così il ponte comandi resta invariato.
Si legge sempre il fotogramma precedente all'ultimo: l'ultimo può essere ancora in scrittura, quello
prima è chiuso e l'app non lo riscrive per altri SLOTS - 1 fotogrammi.

Il layout deve restare identico a ONBOARD_LAYOUT in DeltaSuiteBridge.lua.
"""

from __future__ import annotations

import ctypes
import os
from dataclasses import dataclass
from pathlib import Path

from hub_core.win32 import FILE_MAP_READ, FILE_MAP_WRITE, MappedView

ONBOARD_TAG = "Local\\DeltaSuite_Onboard_v6"
ONBOARD_VERSION = 6
END_MARKER = 0x44534F31   # 'DSO1'
SLOTS = 3
VIEWS = 4                 # principale + 3 secondarie
MAX_CAR_CAMERAS = 16
MAX_CARS = 64
DATA_MAX = 3686656        # byte per fotogramma nella mapping: DDS 1280×720 a 8 bit per canale + intestazione

# telecamere di Delta Suite: (chiave, nome) nello stesso ordine degli indici in DeltaSuiteBridge.lua
CAMERAS = [
    ("tcam", "T-cam"),
    ("hood", "Cofano"),            # dagli occhi del pilota: l'abitacolo in una vista in più non viene reso
    ("rear", "Posteriore"),
    ("wheel_fl", "Ruota ant. sx"),
    ("wheel_fr", "Ruota ant. dx"),
    ("wheel_rl", "Ruota post. sx"),
    ("wheel_rr", "Ruota post. dx"),
    ("chase", "Inseguimento"),
]
# gruppi per l'elenco delle telecamere: indici in CAMERAS
CAMERA_GROUPS = [("Esterne", [0, 1, 2, 7]), ("Ruote", [3, 4, 5, 6])]
# dopo queste, le telecamere F6 della tua auto (cameras.ini, quelle di CSP "Car"): indice CAR_CAMERA_BASE + i
CAR_CAMERA_BASE = len(CAMERAS)

# qualità della vista principale: (nome, larghezza, altezza, fps); le secondarie usano SECONDARY_QUALITY
QUALITIES = [
    ("Bassa · 480×270 · 10 fps", 480, 270, 10),
    ("Media · 640×360 · 15 fps", 640, 360, 15),
    ("Alta · 960×540 · 20 fps", 960, 540, 20),
    ("Massima · 1280×720 · 25 fps", 1280, 720, 25),
]
SECONDARY_QUALITY = QUALITIES[1]

# esposizione e curva applicate dall'app: 0 niente, 1 solo gamma, 2 curva filmica + gamma,
# 3 YEBIS (antialiasing e post-processing del gioco fatti dalla GeometryShot)
TONEMAP_NONE, TONEMAP_GAMMA, TONEMAP_FILMIC, TONEMAP_YEBIS = 0, 1, 2, 3
DEFAULT_TONEMAP = TONEMAP_FILMIC
DEFAULT_EXPOSURE = 1.6        # provata il 18/10 al Red Bull Ring: la più simile al gioco con la filmica

TRANSPORT_FILE, TRANSPORT_MEMORY, TRANSPORT_SHARED = 0, 1, 2
# provata il 18/10 (CSP 0.2.11, RTX 4060 Laptop): condivisa ~1 ms in AC a ogni qualità, memoria 5-9 ms,
# file 6-13 ms a 1280×720; se la texture non si apre si torna da soli alla memoria
DEFAULT_TRANSPORT = TRANSPORT_SHARED

c_int, c_uint, c_float, c_char = ctypes.c_int, ctypes.c_uint, ctypes.c_float, ctypes.c_char


class OnboardShared(ctypes.Structure):
    _fields_ = [
        ("version", c_int),
        # scritti da Delta Suite
        ("hostBeat", c_int), ("exposure", c_float), ("tonemap", c_int), ("transport", c_int),
        ("folder", c_char * 260),
        ("viewEnabled", c_int * VIEWS), ("viewCamera", c_int * VIEWS), ("viewCar", c_int * VIEWS),
        ("viewWidth", c_int * VIEWS), ("viewHeight", c_int * VIEWS), ("viewFps", c_int * VIEWS),
        # scritti dall'app
        ("gameFps", c_float), ("carCameras", c_int), ("carCamData", c_float * (MAX_CAR_CAMERAS * 6)),
        ("wheelData", c_float * 12), ("carCount", c_int),
        ("carPosX", c_float * MAX_CARS), ("carPosZ", c_float * MAX_CARS),
        ("frame", c_int * VIEWS), ("shotWidth", c_int * VIEWS), ("shotHeight", c_int * VIEWS),
        ("shotCar", c_int * VIEWS), ("renderMs", c_float * VIEWS),
        ("sharedHandleLo", c_uint * VIEWS), ("sharedHandleHi", c_uint * VIEWS),
        ("status", (c_char * 96) * VIEWS),
        ("dataSize", c_int * SLOTS), ("data", (c_char * DATA_MAX) * SLOTS),
        ("endMarker", c_int),
    ]


def onboard_dir() -> Path:
    base = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
    return Path(base) / "DeltaSuite" / "onboard"


def frame_file(folder: Path, frame: int, view: int = 0) -> Path:
    name = f"onboard_{frame % SLOTS}.jpg" if view == 0 else f"onboard_v{view}_{frame % SLOTS}.jpg"
    return folder / name


# ------------------------------------------------------------------ nomi delle telecamere F6

Vec = tuple[float, float, float]


def _f6_name(pos: Vec, look: Vec, wheels: list[Vec]) -> str:
    """Nome di una telecamera F6 dalla sua posizione e direzione nello spazio dell'auto."""
    fl, fr, rl, rr = wheels
    cx, cy, cz = ((fl[i] + fr[i] + rl[i] + rr[i]) / 4 for i in range(3))
    half_track = max(0.3, abs(fl[0] - fr[0]) / 2)
    front_z, rear_z = (fl[2] + fr[2]) / 2, (rl[2] + rr[2]) / 2
    left_sign = 1.0 if fl[0] >= cx else -1.0           # da che parte sta la sinistra nello spazio dell'auto
    x, y, z = pos[0] - cx, pos[1] - cy, pos[2] - cz
    dx, _dy, dz = look
    side = "sx" if x * left_sign > 0 else "dx"
    inside = abs(x) < 0.8 * half_track and rear_z < pos[2] < front_z and y < 0.95
    if inside:
        if abs(dx) > abs(dz):
            return "Abitacolo · laterale"
        if dz < 0:
            return "Abitacolo · verso il retro"
        if z > 0.35:
            return "Cruscotto"
        return "Abitacolo · dietro il pilota" if z < -0.35 else "Abitacolo · vista pilota"
    if y >= 0.95:
        return "Tetto · indietro" if dz < -0.5 else "Tetto"
    if pos[2] > front_z + 0.3:
        return "Muso · verso l'auto" if dz < -0.5 else "Muso"
    if pos[2] < rear_z - 0.3:
        return "Coda · verso l'auto" if dz > 0.5 else "Coda"
    direction = " · avanti" if dz > 0.5 else " · indietro" if dz < -0.5 else ""
    return f"Fiancata {side}{direction}"


def f6_names(cams: list[tuple[Vec, Vec]], wheels: list[Vec] | None) -> list[str]:
    """Nomi delle telecamere F6, numerati quando si ripetono ("Cruscotto", "Cruscotto 2")."""
    names = []
    for i, (pos, look) in enumerate(cams):
        base = _f6_name(pos, look, wheels) if wheels and any(any(w) for w in wheels) else f"Telecamera {i + 1}"
        n = sum(1 for prev in names if prev == base or prev.startswith(base + " "))
        names.append(base if n == 0 else f"{base} {n + 1}")
    return names


def camera_menu(f6: list[str]) -> list[tuple[str | None, int | None]]:
    """Voci dell'elenco telecamere: (testo, indice da chiedere all'app); indice None = intestazione."""
    items: list[tuple[str | None, int | None]] = []
    for group, indices in CAMERA_GROUPS:
        items.append((group, None))
        items += [(CAMERAS[i][1], i) for i in indices]
    if f6:
        items.append(("Auto (F6)", None))
        items += [(name, CAR_CAMERA_BASE + i) for i, name in enumerate(f6)]
    return items


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
class ViewRequest:
    enabled: bool
    camera: int
    car: int                  # -1 = auto inquadrata in AC (di solito la tua)
    width: int
    height: int
    fps: int


@dataclass
class OnboardInfo:
    frame: int
    width: int
    height: int
    car: int
    render_ms: float
    game_fps: float
    status: str
    car_cameras: int = 0


class OnboardFeed:
    """Lato Delta Suite del video onboard. Non bloccante: si chiama da un QTimer della UI."""

    def __init__(self, folder: Path | None = None):
        self.folder = folder or onboard_dir()
        self._view = None
        self._last_read: list[int | None] = [None] * VIEWS
        self._shared: list = [None] * VIEWS       # SharedTextureReader aperto sull'handle di ogni vista
        self.shared_error: str | None = None      # perché la texture condivisa non va (si usa la memoria)

    @property
    def connected(self) -> bool:
        return self._view is not None

    def connect(self) -> bool:
        if self._view is not None:
            return True
        try:
            self._view = MappedView(ONBOARD_TAG, OnboardShared, FILE_MAP_READ | FILE_MAP_WRITE)
        except (FileNotFoundError, OSError):
            return False
        self.folder.mkdir(parents=True, exist_ok=True)
        return True

    def disconnect(self) -> None:
        if self._view is not None:
            try:
                for k in range(VIEWS):
                    self._view.struct.viewEnabled[k] = 0
            except (OSError, ValueError):
                pass
            self._view.close()
            self._view = None
        self._last_read = [None] * VIEWS
        for k, reader in enumerate(self._shared):
            if reader is not None:
                reader.close()
            self._shared[k] = None

    def request(self, views: list[ViewRequest], exposure: float = DEFAULT_EXPOSURE,
                tonemap: int = DEFAULT_TONEMAP, transport: int = DEFAULT_TRANSPORT) -> bool:
        """Aggiorna le richieste e il battito (va chiamata almeno una volta al secondo)."""
        if not self.connect():
            return False
        s = self._view.struct
        s.version = ONBOARD_VERSION
        s.endMarker = END_MARKER
        s.folder = str(self.folder).encode("utf-8")[:259]
        if transport == TRANSPORT_SHARED and self.shared_error:
            transport = TRANSPORT_MEMORY
        s.exposure, s.tonemap, s.transport = exposure, tonemap, transport
        for k in range(VIEWS):
            v = views[k] if k < len(views) else None
            if v is None or not v.enabled:
                s.viewEnabled[k] = 0
                continue
            s.viewCamera[k], s.viewCar[k] = v.camera, v.car
            s.viewWidth[k], s.viewHeight[k], s.viewFps[k] = v.width, v.height, v.fps
            s.viewEnabled[k] = 1
        s.hostBeat = (s.hostBeat + 1) & 0x7FFFFFFF
        return True

    def _ok(self) -> bool:
        return self._view is not None and self._view.struct.version == ONBOARD_VERSION

    def info(self, view: int = 0) -> OnboardInfo | None:
        if not self._ok():
            return None
        s = self._view.struct
        return OnboardInfo(s.frame[view], s.shotWidth[view], s.shotHeight[view], s.shotCar[view],
                           s.renderMs[view], s.gameFps,
                           s.status[view].value.decode("utf-8", errors="replace"), s.carCameras)

    def f6_cameras(self) -> list[str]:
        """Nomi delle telecamere F6 dell'auto del giocatore (vuoto se l'app non ne ha trovate)."""
        if not self._ok():
            return []
        s = self._view.struct
        n = max(0, min(s.carCameras, MAX_CAR_CAMERAS))
        d, w = s.carCamData, s.wheelData
        cams = [((d[i * 6], d[i * 6 + 1], d[i * 6 + 2]), (d[i * 6 + 3], d[i * 6 + 4], d[i * 6 + 5])) for i in range(n)]
        wheels = [(w[i * 3], w[i * 3 + 1], w[i * 3 + 2]) for i in range(4)]
        return f6_names(cams, wheels)

    def car_positions(self) -> dict[int, tuple[float, float]]:
        """Posizione (x, z) di ogni auto, per indice d'auto di AC."""
        if not self._ok():
            return {}
        s = self._view.struct
        return {i: (s.carPosX[i], s.carPosZ[i]) for i in range(max(0, min(s.carCount, MAX_CARS)))}

    def new_frame(self, view: int = 0) -> Frame | None:
        """Fotogramma da mostrare per la vista, se ce n'è uno nuovo dall'ultima chiamata."""
        inf = self.info(view)
        if inf is None:
            return None
        n = readable_frame(inf.frame)
        if n is None or n == self._last_read[view]:
            return None
        self._last_read[view] = n
        s = self._view.struct
        handle = s.sharedHandleLo[view] | (s.sharedHandleHi[view] << 32)
        if handle:
            return self._read_shared(view, handle)
        size = s.dataSize[n % SLOTS] if view == 0 else 0
        in_memory = 0 < size <= DATA_MAX
        if in_memory:
            off = OnboardShared.data.offset + (n % SLOTS) * DATA_MAX
            data = ctypes.string_at(self._view.ptr + off, size)
        else:
            try:
                data = frame_file(self.folder, n, view).read_bytes()
            except OSError:
                return None
        # se nel frattempo l'app ha pubblicato n + 2, può aver già cominciato a riscrivere questo posto
        if s.frame[view] > n + 1:
            return None
        if not in_memory:
            return Frame("jpg", data)
        try:
            return decode_dds(data)
        except ValueError:
            return None

    def _read_shared(self, view: int, handle: int) -> Frame | None:
        """Contenuto attuale della texture condivisa; al primo errore si torna a memoria/file."""
        reader = self._shared[view]
        try:
            if reader is None:
                from hub_core.d3d_shared import SharedTextureReader
                reader = self._shared[view] = SharedTextureReader()
            if reader.handle != handle:
                reader.open(handle)
            data, pitch = reader.read()
        except OSError as exc:
            self.shared_error = str(exc)
            if reader is not None:
                reader.close()
            return None
        return Frame(reader.kind, data, reader.width, reader.height, pitch)
