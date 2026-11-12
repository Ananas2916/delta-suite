"""
Onboard video from the CSP Lua app (ac_app/DeltaSuiteBridge), up to VIEWS views at once.

For each view (0 = main, 1-3 = secondary, as in broadcasts with several onboards) the app renders a
camera mounted on the chosen car (ac.GeometryShot, one extra view besides the driver's), applies
exposure and gamma (the second view skips the game's post-processing and comes out dark without it;
alternatively YEBIS uses the game's post-processing) and publishes the frames in one of three ways:
  - shared: the canvas is a shared D3D11 texture, Delta Suite opens it and copies it on its own
    GPU (hub_core/d3d_shared.py); no GPU readback in AC, which costs 9-12 ms at 1280×720;
  - memory (main view only): the raw DDS from ExtraCanvas:encode() in the mapping itself, rotating
    over SLOTS slots (in CSP 0.2.11 encode does not compress and ignores the format);
  - file: a JPG in the folder given from here; CSP writes a log line for every file.
If the shared texture cannot be opened, it falls back to memory (main view) or files (the others).
The app renders at most one view per AC frame, the most overdue one, so the cost does not spike;
it also publishes the position of every car (GPS map) and the player's car F6 cameras, from
which f6_names derives readable names.

The exchange goes through a separate mapping, DeltaSuite_Onboard_v6, so the command bridge is unchanged.
The frame before the latest is always read: the latest may still be being written, the one
before is closed and the app does not rewrite it for another SLOTS - 1 frames.

The layout must stay identical to ONBOARD_LAYOUT in DeltaSuiteOnboard.lua.
"""

from __future__ import annotations

import ctypes
import os
from dataclasses import dataclass
from pathlib import Path

from hub_core.ac.win32 import FILE_MAP_READ, FILE_MAP_WRITE, MappedView

ONBOARD_TAG = "Local\\DeltaSuite_Onboard_v6"
ONBOARD_VERSION = 6
END_MARKER = 0x44534F31   # 'DSO1'
SLOTS = 3
VIEWS = 4                 # main + 3 secondary
MAX_CAR_CAMERAS = 16
MAX_CARS = 64
DATA_MAX = 3686656        # bytes per frame in the mapping: 1280×720 DDS at 8 bits per channel + header

# Delta Suite cameras: (key, name) in the same order as the indices in DeltaSuiteOnboard.lua
CAMERAS = [
    ("tcam", "T-cam"),
    ("hood", "Bonnet"),            # from the driver's eyes the cockpit is not rendered in an extra view
    ("rear", "Rear"),
    ("wheel_fl", "Front left wheel"),
    ("wheel_fr", "Front right wheel"),
    ("wheel_rl", "Rear left wheel"),
    ("wheel_rr", "Rear right wheel"),
    ("chase", "Chase"),
]
# groups for the camera list: indices in CAMERAS
CAMERA_GROUPS = [("Exterior", [0, 1, 2, 7]), ("Wheels", [3, 4, 5, 6])]
# after these, the F6 cameras of your car (cameras.ini, CSP's "Car" ones): index CAR_CAMERA_BASE + i
CAR_CAMERA_BASE = len(CAMERAS)

# main view quality: (name, width, height, fps); secondary views use SECONDARY_QUALITY
QUALITIES = [
    ("Low · 480×270 · 10 fps", 480, 270, 10),
    ("Medium · 640×360 · 15 fps", 640, 360, 15),
    ("High · 960×540 · 20 fps", 960, 540, 20),
    ("Maximum · 1280×720 · 25 fps", 1280, 720, 25),
]
SECONDARY_QUALITY = QUALITIES[1]

# exposure and curve applied by the app: 0 none, 1 gamma only, 2 filmic curve + gamma,
# 3 YEBIS (antialiasing and game post-processing done by the GeometryShot)
TONEMAP_NONE, TONEMAP_GAMMA, TONEMAP_FILMIC, TONEMAP_YEBIS = 0, 1, 2, 3
DEFAULT_TONEMAP = TONEMAP_FILMIC
DEFAULT_EXPOSURE = 1.6        # tested on 18/10 at the Red Bull Ring: closest to the game with the filmic curve

TRANSPORT_FILE, TRANSPORT_MEMORY, TRANSPORT_SHARED = 0, 1, 2
# tested on 18/10 (CSP 0.2.11, RTX 4060 Laptop): shared ~1 ms in AC at every quality, memory 5-9 ms,
# file 6-13 ms at 1280×720; if the texture cannot be opened it falls back to memory by itself
DEFAULT_TRANSPORT = TRANSPORT_SHARED

c_int, c_uint, c_float, c_char = ctypes.c_int, ctypes.c_uint, ctypes.c_float, ctypes.c_char


class OnboardShared(ctypes.Structure):
    _fields_ = [
        ("version", c_int),
        # written by Delta Suite
        ("hostBeat", c_int), ("exposure", c_float), ("tonemap", c_int), ("transport", c_int),
        ("folder", c_char * 260),
        ("viewEnabled", c_int * VIEWS), ("viewCamera", c_int * VIEWS), ("viewCar", c_int * VIEWS),
        ("viewWidth", c_int * VIEWS), ("viewHeight", c_int * VIEWS), ("viewFps", c_int * VIEWS),
        # written by the app
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


# ------------------------------------------------------------------ F6 camera names

Vec = tuple[float, float, float]


def _f6_name(pos: Vec, look: Vec, wheels: list[Vec]) -> str:
    """Name of an F6 camera from its position and direction in car space."""
    fl, fr, rl, rr = wheels
    cx, cy, cz = ((fl[i] + fr[i] + rl[i] + rr[i]) / 4 for i in range(3))
    half_track = max(0.3, abs(fl[0] - fr[0]) / 2)
    front_z, rear_z = (fl[2] + fr[2]) / 2, (rl[2] + rr[2]) / 2
    left_sign = 1.0 if fl[0] >= cx else -1.0           # which side is left in car space
    x, y, z = pos[0] - cx, pos[1] - cy, pos[2] - cz
    dx, _dy, dz = look
    side = "left" if x * left_sign > 0 else "right"
    inside = abs(x) < 0.8 * half_track and rear_z < pos[2] < front_z and y < 0.95
    if inside:
        if abs(dx) > abs(dz):
            return "Cockpit · side"
        if dz < 0:
            return "Cockpit · rear-facing"
        if z > 0.35:
            return "Dashboard"
        return "Cockpit · behind the driver" if z < -0.35 else "Cockpit · driver view"
    if y >= 0.95:
        return "Roof · rear-facing" if dz < -0.5 else "Roof"
    if pos[2] > front_z + 0.3:
        return "Nose · facing the car" if dz < -0.5 else "Nose"
    if pos[2] < rear_z - 0.3:
        return "Tail · facing the car" if dz > 0.5 else "Tail"
    direction = " · forward" if dz > 0.5 else " · rear-facing" if dz < -0.5 else ""
    return f"Side {side}{direction}"


def f6_names(cams: list[tuple[Vec, Vec]], wheels: list[Vec] | None) -> list[str]:
    """F6 camera names, numbered when repeated ("Dashboard", "Dashboard 2")."""
    names = []
    for i, (pos, look) in enumerate(cams):
        base = _f6_name(pos, look, wheels) if wheels and any(any(w) for w in wheels) else f"Camera {i + 1}"
        n = sum(1 for prev in names if prev == base or prev.startswith(base + " "))
        names.append(base if n == 0 else f"{base} {n + 1}")
    return names


def camera_menu(f6: list[str]) -> list[tuple[str | None, int | None]]:
    """Camera list entries: (text, index to request from the app); index None = header."""
    items: list[tuple[str | None, int | None]] = []
    for group, indices in CAMERA_GROUPS:
        items.append((group, None))
        items += [(CAMERAS[i][1], i) for i in indices]
    if f6:
        items.append(("Car (F6)", None))
        items += [(name, CAR_CAMERA_BASE + i) for i, name in enumerate(f6)]
    return items


@dataclass
class Frame:
    """A frame: "jpg" (data is the file) or raw "rgba"/"bgra" pixels at 8 bits per channel."""

    kind: str
    data: bytes
    width: int = 0
    height: int = 0
    stride: int = 0


def decode_dds(raw: bytes) -> Frame:
    """Pixels of the first level of an uncompressed 32-bit DDS (what ExtraCanvas:encode produces)."""
    if len(raw) < 128 or raw[:4] != b"DDS ":
        raise ValueError("not a DDS")
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
            raise ValueError(f"DXGI format {dxgi} not supported")
    elif bits == 32 and rmask in (0x000000FF, 0x00FF0000):
        kind = "rgba" if rmask == 0x000000FF else "bgra"
    else:
        raise ValueError(f"{bits}-bit DDS with mask {rmask:#x} not supported")
    stride = pitch if flags & 0x8 and pitch >= width * 4 else width * 4
    if len(raw) < start + stride * height:
        raise ValueError("truncated DDS")
    return Frame(kind, raw[start:start + stride * height], width, height, stride)


def readable_frame(frame: int) -> int | None:
    """Frame that is safe to read when the app has just published `frame`."""
    return frame - 1 if frame >= 2 else None


@dataclass
class ViewRequest:
    enabled: bool
    camera: int
    car: int                  # -1 = car focused in AC (usually yours)
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
    """Delta Suite side of the onboard video. Non-blocking: called from a UI QTimer."""

    def __init__(self, folder: Path | None = None):
        self.folder = folder or onboard_dir()
        self._view = None
        self._last_read: list[int | None] = [None] * VIEWS
        self._shared: list = [None] * VIEWS       # SharedTextureReader opened on each view's handle
        self.shared_error: str | None = None      # why the shared texture does not work (memory is used)

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
        """Update the requests and the heartbeat (call at least once per second)."""
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
        """Names of the player's car F6 cameras (empty if the app found none)."""
        if not self._ok():
            return []
        s = self._view.struct
        n = max(0, min(s.carCameras, MAX_CAR_CAMERAS))
        d, w = s.carCamData, s.wheelData
        cams = [((d[i * 6], d[i * 6 + 1], d[i * 6 + 2]), (d[i * 6 + 3], d[i * 6 + 4], d[i * 6 + 5])) for i in range(n)]
        wheels = [(w[i * 3], w[i * 3 + 1], w[i * 3 + 2]) for i in range(4)]
        return f6_names(cams, wheels)

    def car_positions(self) -> dict[int, tuple[float, float]]:
        """(x, z) position of every car, by AC car index."""
        if not self._ok():
            return {}
        s = self._view.struct
        return {i: (s.carPosX[i], s.carPosZ[i]) for i in range(max(0, min(s.carCount, MAX_CARS)))}

    def new_frame(self, view: int = 0) -> Frame | None:
        """Frame to show for the view, if there is a new one since the last call."""
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
        # if the app has meanwhile published n + 2, it may already be rewriting this slot
        if s.frame[view] > n + 1:
            return None
        if not in_memory:
            return Frame("jpg", data)
        try:
            return decode_dds(data)
        except ValueError:
            return None

    def _read_shared(self, view: int, handle: int) -> Frame | None:
        """Current contents of the shared texture; on the first error fall back to memory/file."""
        reader = self._shared[view]
        try:
            if reader is None:
                from hub_core.ac.d3d_shared import SharedTextureReader
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
