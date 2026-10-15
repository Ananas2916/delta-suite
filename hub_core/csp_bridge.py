"""
Lato Delta Suite del ponte con l'app Lua di CSP (ac_app/DeltaSuiteBridge).

L'app scrive DeltaSuite_Bridge_Out_v1 (regolazioni, setup, pit stop, avversari, tasti radio) e
legge DeltaSuite_Bridge_In_v1, dove qui si scrive un comando alla volta: prima i campi, poi `seq`.
L'app lo esegue nel frame successivo e ne riporta l'esito in ackSeq/ackOk/ackMsg.

I layout sono gli stessi dichiarati in DeltaSuiteBridge.lua: se si cambia uno, va cambiato l'altro
(e la versione nel nome delle mapping).
"""

from __future__ import annotations

import ctypes
import os
import shutil
import sys
import winreg
from ctypes import wintypes
from dataclasses import dataclass, field
from pathlib import Path

OUT_TAG = "Local\\DeltaSuite_Bridge_Out_v1"
IN_TAG = "Local\\DeltaSuite_Bridge_In_v1"
VERSION = 1
END_MARKER = 0x44535431

MAX_SETUP, MAX_PIT, MAX_CARS = 96, 16, 64

CMD_BRAKE_BIAS, CMD_ABS, CMD_TC, CMD_ENGINE_BRAKE = 1, 2, 3, 4
CMD_SETUP, CMD_PIT, CMD_LOAD_SETUP, CMD_SAVE_SETUP = 5, 6, 7, 8

c_int, c_float, c_char = ctypes.c_int, ctypes.c_float, ctypes.c_char


class BridgeOut(ctypes.Structure):
    _fields_ = [
        ("version", c_int), ("frame", c_int), ("ackSeq", c_int), ("ackOk", c_int), ("ackMsg", c_char * 64),
        ("focusedCar", c_int), ("carsCount", c_int), ("setupEditable", c_int), ("pttDown", c_int),
        ("confirmCount", c_int), ("cancelCount", c_int),
        ("brakeBias", c_float), ("brakeBiasStep", c_float), ("brakeBiasMin", c_float), ("brakeBiasMax", c_float),
        ("absMode", c_int), ("absModes", c_int), ("tcMode", c_int), ("tcModes", c_int),
        ("engineBrakeCount", c_int), ("setupCount", c_int), ("pitCount", c_int), ("pitPreset", c_int),
        ("setupName", (c_char * 32) * MAX_SETUP), ("setupLabel", (c_char * 48) * MAX_SETUP),
        ("setupUnits", (c_char * 12) * MAX_SETUP),
        ("setupValue", c_int * MAX_SETUP), ("setupMin", c_int * MAX_SETUP), ("setupMax", c_int * MAX_SETUP),
        ("setupStep", c_int * MAX_SETUP), ("setupMult", c_float * MAX_SETUP), ("setupReadOnly", c_int * MAX_SETUP),
        ("pitName", (c_char * 32) * MAX_PIT), ("pitType", (c_char * 12) * MAX_PIT),
        ("pitValue", c_int * MAX_PIT), ("pitMin", c_int * MAX_PIT), ("pitMax", c_int * MAX_PIT),
        ("pitReadOnly", c_int * MAX_PIT),
        ("carIndex", c_int * MAX_CARS), ("carConnected", c_int * MAX_CARS), ("carRacePos", c_int * MAX_CARS),
        ("carLapCount", c_int * MAX_CARS), ("carSpline", c_float * MAX_CARS), ("carLapTimeMs", c_int * MAX_CARS),
        ("carLastLapMs", c_int * MAX_CARS), ("carBestLapMs", c_int * MAX_CARS), ("carInPitlane", c_int * MAX_CARS),
        ("carInPit", c_int * MAX_CARS), ("carSpeed", c_float * MAX_CARS), ("carLastLapValid", c_int * MAX_CARS),
        ("carDriver", (c_char * 32) * MAX_CARS), ("carModel", (c_char * 32) * MAX_CARS),
        ("endMarker", c_int),
    ]


class BridgeIn(ctypes.Structure):
    _fields_ = [
        ("version", c_int), ("hostBeat", c_int), ("seq", c_int), ("cmd", c_int), ("value", c_float),
        ("name", c_char * 32), ("text", c_char * 512), ("endMarker", c_int),
    ]


def _s(raw: bytes) -> str:
    return raw.split(b"\0", 1)[0].decode("utf-8", errors="replace")


@dataclass
class SetupItem:
    name: str
    label: str
    units: str
    value: int
    min: int
    max: int
    step: int
    mult: float
    read_only: bool

    @property
    def display(self) -> float:
        return self.value * self.mult

    def as_dict(self) -> dict:
        return {"nome": self.name, "etichetta": self.label or self.name, "valore": self.value,
                "valore_mostrato": round(self.display, 4), "unita": self.units, "min": self.min, "max": self.max,
                "passo": self.step, "moltiplicatore": self.mult, "sola_lettura": self.read_only}


@dataclass
class PitItem:
    name: str
    type: str
    value: int
    min: int
    max: int
    read_only: bool


@dataclass
class CarEntry:
    index: int
    connected: bool
    race_pos: int
    lap_count: int
    spline: float
    lap_time_ms: int
    last_lap_ms: int
    best_lap_ms: int
    in_pitlane: bool
    in_pit: bool
    speed_kmh: float
    last_lap_valid: bool
    driver: str
    model: str

    @property
    def progress(self) -> float:
        return self.lap_count + self.spline


@dataclass
class BridgeState:
    frame: int
    ack_seq: int
    ack_ok: bool
    ack_msg: str
    focused_car: int
    setup_editable: bool
    ptt_down: bool
    confirm_count: int
    cancel_count: int
    brake_bias: float
    brake_bias_step: float
    brake_bias_min: float
    brake_bias_max: float
    abs_mode: int
    abs_modes: int
    tc_mode: int
    tc_modes: int
    engine_brake_count: int
    pit_preset: int
    setup: list[SetupItem] = field(default_factory=list)
    pit: list[PitItem] = field(default_factory=list)
    cars: list[CarEntry] = field(default_factory=list)


def state_from_struct(o: BridgeOut) -> BridgeState:
    n_setup = max(0, min(o.setupCount, MAX_SETUP))
    n_pit = max(0, min(o.pitCount, MAX_PIT))
    n_cars = max(0, min(o.carsCount, MAX_CARS))
    return BridgeState(
        frame=o.frame, ack_seq=o.ackSeq, ack_ok=bool(o.ackOk), ack_msg=_s(o.ackMsg), focused_car=o.focusedCar,
        setup_editable=bool(o.setupEditable), ptt_down=bool(o.pttDown), confirm_count=o.confirmCount,
        cancel_count=o.cancelCount, brake_bias=o.brakeBias, brake_bias_step=o.brakeBiasStep,
        brake_bias_min=o.brakeBiasMin, brake_bias_max=o.brakeBiasMax, abs_mode=o.absMode, abs_modes=o.absModes,
        tc_mode=o.tcMode, tc_modes=o.tcModes, engine_brake_count=o.engineBrakeCount, pit_preset=o.pitPreset,
        setup=[SetupItem(_s(o.setupName[i].raw), _s(o.setupLabel[i].raw), _s(o.setupUnits[i].raw),
                         o.setupValue[i], o.setupMin[i], o.setupMax[i], max(1, o.setupStep[i]),
                         o.setupMult[i] or 1.0, bool(o.setupReadOnly[i])) for i in range(n_setup)],
        pit=[PitItem(_s(o.pitName[i].raw), _s(o.pitType[i].raw), o.pitValue[i], o.pitMin[i], o.pitMax[i],
                     bool(o.pitReadOnly[i])) for i in range(n_pit)],
        cars=[CarEntry(o.carIndex[i], bool(o.carConnected[i]), o.carRacePos[i], o.carLapCount[i], o.carSpline[i],
                       o.carLapTimeMs[i], o.carLastLapMs[i], o.carBestLapMs[i], bool(o.carInPitlane[i]),
                       bool(o.carInPit[i]), o.carSpeed[i], bool(o.carLastLapValid[i]), _s(o.carDriver[i].raw),
                       _s(o.carModel[i].raw)) for i in range(n_cars)],
    )


# ----------------------------------------------------------------------- Win32

_k32 = ctypes.WinDLL("kernel32", use_last_error=True)
_FILE_MAP_WRITE, _FILE_MAP_READ = 0x0002, 0x0004
_k32.OpenFileMappingW.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.LPCWSTR]
_k32.OpenFileMappingW.restype = wintypes.HANDLE
_k32.MapViewOfFile.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.DWORD, wintypes.DWORD, ctypes.c_size_t]
_k32.MapViewOfFile.restype = ctypes.c_void_p
_k32.UnmapViewOfFile.argtypes = [ctypes.c_void_p]
_k32.CloseHandle.argtypes = [wintypes.HANDLE]


class _View:
    """Vista su una mapping creata dall'app Lua (qui non si crea mai nulla)."""

    def __init__(self, tag: str, struct_type, access: int):
        self.handle = _k32.OpenFileMappingW(access, False, tag)
        if not self.handle:
            raise FileNotFoundError(tag)
        self.ptr = _k32.MapViewOfFile(self.handle, access, 0, 0, ctypes.sizeof(struct_type))
        if not self.ptr:
            _k32.CloseHandle(self.handle)
            raise OSError(ctypes.get_last_error(), f"MapViewOfFile fallita su {tag}")
        self.struct = struct_type.from_address(self.ptr)

    def close(self):
        if self.ptr:
            _k32.UnmapViewOfFile(self.ptr)
            self.ptr = None
        if self.handle:
            _k32.CloseHandle(self.handle)
            self.handle = None


class CSPBridge:
    """Collegamento all'app Lua. Tutti i metodi sono non bloccanti."""

    def __init__(self):
        self._out: _View | None = None
        self._in: _View | None = None
        self.layout_error: str | None = None

    @property
    def connected(self) -> bool:
        return self._out is not None

    def connect(self) -> bool:
        if self._out is not None:
            return True
        try:
            out = _View(OUT_TAG, BridgeOut, _FILE_MAP_READ)
        except (FileNotFoundError, OSError):
            return False
        try:
            inp = _View(IN_TAG, BridgeIn, _FILE_MAP_READ | _FILE_MAP_WRITE)
        except (FileNotFoundError, OSError):
            out.close()
            return False
        self._out, self._in = out, inp
        return True

    def disconnect(self) -> None:
        for v in (self._out, self._in):
            if v is not None:
                v.close()
        self._out = self._in = None

    def read(self) -> BridgeState | None:
        """Copia lo stato pubblicato dall'app; None se non collegata o layout diverso."""
        if not self.connect():
            return None
        snap = BridgeOut()
        ctypes.memmove(ctypes.addressof(snap), self._out.ptr, ctypes.sizeof(BridgeOut))
        if snap.version == 0:
            return None   # mapping appena creata, l'app non ha ancora scritto
        if snap.version != VERSION or snap.endMarker != END_MARKER:
            self.layout_error = (f"app CSP versione {snap.version} / layout diverso: "
                                 "reinstalla l'app da Delta Suite")
            return None
        self.layout_error = None
        self._in.struct.hostBeat = (self._in.struct.hostBeat + 1) & 0x7FFFFFFF
        return state_from_struct(snap)

    def send(self, cmd: int, value: float = 0.0, name: str = "", text: str = "") -> int | None:
        """Scrive un comando e ritorna il suo numero di sequenza (l'esito arriva in BridgeState.ack_*)."""
        if not self.connect():
            return None
        s = self._in.struct
        s.version = VERSION
        s.endMarker = END_MARKER
        s.cmd = cmd
        s.value = float(value)
        s.name = name.encode("utf-8")[:31]
        s.text = text.encode("utf-8")[:511]
        seq = (s.seq + 1) & 0x7FFFFFFF or 1
        s.seq = seq      # per ultimo: l'app esegue quando vede cambiare seq
        return seq


# -------------------------------------------------------------- installazione

APP_NAME = "DeltaSuiteBridge"


def bundled_app_dir() -> Path:
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[1]))
    return base / "ac_app" / APP_NAME


def find_ac_root() -> Path | None:
    """Cartella di installazione di AC: librerie di Steam dal registro, poi percorso standard."""
    candidates: list[Path] = []
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Valve\Steam") as k:
            steam = Path(winreg.QueryValueEx(k, "SteamPath")[0])
        candidates.append(steam)
        vdf = steam / "steamapps" / "libraryfolders.vdf"
        if vdf.is_file():
            for line in vdf.read_text(encoding="utf-8", errors="replace").splitlines():
                parts = line.strip().split('"')
                if len(parts) >= 4 and parts[1] == "path":
                    candidates.append(Path(parts[3].replace("\\\\", "\\")))
    except OSError:
        pass
    candidates.append(Path(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")) / "Steam")
    for lib in candidates:
        root = lib / "steamapps" / "common" / "assettocorsa"
        if (root / "acs.exe").is_file():
            return root
    return None


def installed_app_dir(ac_root: Path | None = None) -> Path | None:
    root = ac_root or find_ac_root()
    return root / "apps" / "lua" / APP_NAME if root else None


def install_app(ac_root: Path | None = None) -> Path:
    """Copia l'app Lua in <AC>/apps/lua/DeltaSuiteBridge. Va riavviata la sessione di AC per caricarla."""
    target = installed_app_dir(ac_root)
    if target is None:
        raise FileNotFoundError("Cartella di Assetto Corsa non trovata")
    src = bundled_app_dir()
    target.mkdir(parents=True, exist_ok=True)
    for f in src.iterdir():
        if f.is_file():
            shutil.copy2(f, target / f.name)
    return target


def app_needs_update(ac_root: Path | None = None) -> bool:
    target = installed_app_dir(ac_root)
    if target is None:
        return False
    src = bundled_app_dir() / f"{APP_NAME}.lua"
    dst = target / f"{APP_NAME}.lua"
    return not dst.is_file() or dst.read_bytes() != src.read_bytes()
