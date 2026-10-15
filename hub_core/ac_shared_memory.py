"""
Lettura della shared memory di Assetto Corsa (originale, 2014).

AC (acs.exe) espone tre file mapping con nome:
    Local\\acpmf_physics   -> SPageFilePhysics  (aggiornata a ogni step fisico, ~333 Hz)
    Local\\acpmf_graphics  -> SPageFileGraphic  (aggiornata a ogni frame)
    Local\\acpmf_static    -> SPageFileStatic   (scritta una volta a inizio sessione)

I layout qui sotto seguono la documentazione ufficiale della shared memory di AC 1.x
(pack 4, wchar a 2 byte). NON sono compatibili con ACC o AC EVO.

Le mapping vengono aperte con OpenFileMappingW (sola lettura) e mai create: se usassimo
mmap.mmap(-1, size, tagname) e AC non fosse ancora avviato, Python creerebbe una mapping
con la nostra dimensione e acs.exe si aggancerebbe a quella.
"""

from __future__ import annotations

import ctypes
from ctypes import wintypes
from enum import IntEnum

c_float = ctypes.c_float
c_int = ctypes.c_int
c_wchar = ctypes.c_wchar


# --------------------------------------------------------------------------- enum

class ACStatus(IntEnum):
    OFF = 0
    REPLAY = 1
    LIVE = 2
    PAUSE = 3


class ACSessionType(IntEnum):
    UNKNOWN = -1
    PRACTICE = 0
    QUALIFY = 1
    RACE = 2
    HOTLAP = 3
    TIME_ATTACK = 4
    DRIFT = 5
    DRAG = 6


class ACFlag(IntEnum):
    NONE = 0
    BLUE = 1
    YELLOW = 2
    BLACK = 3
    WHITE = 4
    CHECKERED = 5
    PENALTY = 6


# ---------------------------------------------------------------------- strutture

class SPageFilePhysics(ctypes.Structure):
    _pack_ = 4
    _fields_ = [
        ("packetId", c_int),
        ("gas", c_float),
        ("brake", c_float),
        ("fuel", c_float),
        ("gear", c_int),                      # 0 = R, 1 = N, 2 = 1a, ...
        ("rpms", c_int),
        ("steerAngle", c_float),
        ("speedKmh", c_float),
        ("velocity", c_float * 3),
        ("accG", c_float * 3),                # x laterale, y verticale, z longitudinale
        ("wheelSlip", c_float * 4),           # ordine ruote: FL, FR, RL, RR
        ("wheelLoad", c_float * 4),
        ("wheelsPressure", c_float * 4),
        ("wheelAngularSpeed", c_float * 4),
        ("tyreWear", c_float * 4),
        ("tyreDirtyLevel", c_float * 4),
        ("tyreCoreTemperature", c_float * 4),
        ("camberRAD", c_float * 4),
        ("suspensionTravel", c_float * 4),
        ("drs", c_float),
        ("tc", c_float),
        ("heading", c_float),
        ("pitch", c_float),
        ("roll", c_float),
        ("cgHeight", c_float),
        ("carDamage", c_float * 5),
        ("numberOfTyresOut", c_int),
        ("pitLimiterOn", c_int),
        ("abs", c_float),
        ("kersCharge", c_float),
        ("kersInput", c_float),
        ("autoShifterOn", c_int),
        ("rideHeight", c_float * 2),          # anteriore, posteriore
        ("turboBoost", c_float),
        ("ballast", c_float),
        ("airDensity", c_float),
        ("airTemp", c_float),
        ("roadTemp", c_float),
        ("localAngularVel", c_float * 3),
        ("finalFF", c_float),
        ("performanceMeter", c_float),
        ("engineBrake", c_int),
        ("ersRecoveryLevel", c_int),
        ("ersPowerLevel", c_int),
        ("ersHeatCharging", c_int),
        ("ersIsCharging", c_int),
        ("kersCurrentKJ", c_float),
        ("drsAvailable", c_int),
        ("drsEnabled", c_int),
        ("brakeTemp", c_float * 4),
        ("clutch", c_float),
        ("tyreTempI", c_float * 4),
        ("tyreTempM", c_float * 4),
        ("tyreTempO", c_float * 4),
        ("isAIControlled", c_int),
        ("tyreContactPoint", (c_float * 3) * 4),
        ("tyreContactNormal", (c_float * 3) * 4),
        ("tyreContactHeading", (c_float * 3) * 4),
        ("brakeBias", c_float),
        ("localVelocity", c_float * 3),
    ]


class SPageFileGraphic(ctypes.Structure):
    _pack_ = 4
    _fields_ = [
        ("packetId", c_int),
        ("status", c_int),                    # ACStatus
        ("session", c_int),                   # ACSessionType
        ("currentTime", c_wchar * 15),
        ("lastTime", c_wchar * 15),
        ("bestTime", c_wchar * 15),
        ("split", c_wchar * 15),
        ("completedLaps", c_int),
        ("position", c_int),
        ("iCurrentTime", c_int),              # ms
        ("iLastTime", c_int),                 # ms
        ("iBestTime", c_int),                 # ms
        ("sessionTimeLeft", c_float),
        ("distanceTraveled", c_float),
        ("isInPit", c_int),
        ("currentSectorIndex", c_int),
        ("lastSectorTime", c_int),
        ("numberOfLaps", c_int),
        ("tyreCompound", c_wchar * 33),
        ("replayTimeMultiplier", c_float),
        ("normalizedCarPosition", c_float),   # 0..1 lungo il giro
        ("carCoordinates", c_float * 3),
        ("penaltyTime", c_float),
        ("flag", c_int),                      # ACFlag
        ("idealLineOn", c_int),
        ("isInPitLane", c_int),
        ("surfaceGrip", c_float),
        ("mandatoryPitDone", c_int),
        ("windSpeed", c_float),
        ("windDirection", c_float),
    ]


class SPageFileStatic(ctypes.Structure):
    _pack_ = 4
    _fields_ = [
        ("smVersion", c_wchar * 15),
        ("acVersion", c_wchar * 15),
        ("numberOfSessions", c_int),
        ("numCars", c_int),
        ("carModel", c_wchar * 33),
        ("track", c_wchar * 33),
        ("playerName", c_wchar * 33),
        ("playerSurname", c_wchar * 33),
        ("playerNick", c_wchar * 33),
        ("sectorCount", c_int),
        ("maxTorque", c_float),
        ("maxPower", c_float),
        ("maxRpm", c_int),
        ("maxFuel", c_float),
        ("suspensionMaxTravel", c_float * 4),
        ("tyreRadius", c_float * 4),
        ("maxTurboBoost", c_float),
        ("deprecated_1", c_float),
        ("deprecated_2", c_float),
        ("penaltiesEnabled", c_int),
        ("aidFuelRate", c_float),
        ("aidTireRate", c_float),
        ("aidMechanicalDamage", c_float),
        ("aidAllowTyreBlankets", c_int),
        ("aidStability", c_float),
        ("aidAutoClutch", c_int),
        ("aidAutoBlip", c_int),
        ("hasDRS", c_int),
        ("hasERS", c_int),
        ("hasKERS", c_int),
        ("kersMaxJ", c_float),
        ("engineBrakeSettingsCount", c_int),
        ("ersPowerControllerCount", c_int),
        ("trackSPlineLength", c_float),
        ("trackConfiguration", c_wchar * 33),
        ("ersMaxJ", c_float),
        ("isTimedRace", c_int),
        ("hasExtraLap", c_int),
        ("carSkin", c_wchar * 33),
        ("reversedGridPositions", c_int),
        ("pitWindowStart", c_int),
        ("pitWindowEnd", c_int),
    ]


PHYSICS_TAG = "Local\\acpmf_physics"
GRAPHICS_TAG = "Local\\acpmf_graphics"
STATIC_TAG = "Local\\acpmf_static"


# -------------------------------------------------------------------- Win32 API

_kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

_FILE_MAP_READ = 0x0004

_kernel32.OpenFileMappingW.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.LPCWSTR]
_kernel32.OpenFileMappingW.restype = wintypes.HANDLE
_kernel32.MapViewOfFile.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.DWORD,
                                    wintypes.DWORD, ctypes.c_size_t]
_kernel32.MapViewOfFile.restype = ctypes.c_void_p
_kernel32.UnmapViewOfFile.argtypes = [ctypes.c_void_p]
_kernel32.UnmapViewOfFile.restype = wintypes.BOOL
_kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
_kernel32.CloseHandle.restype = wintypes.BOOL


class _MEMORY_BASIC_INFORMATION(ctypes.Structure):
    _fields_ = [
        ("BaseAddress", ctypes.c_void_p),
        ("AllocationBase", ctypes.c_void_p),
        ("AllocationProtect", wintypes.DWORD),
        ("PartitionId", wintypes.WORD),
        ("RegionSize", ctypes.c_size_t),
        ("State", wintypes.DWORD),
        ("Protect", wintypes.DWORD),
        ("Type", wintypes.DWORD),
    ]


_kernel32.VirtualQuery.argtypes = [ctypes.c_void_p, ctypes.POINTER(_MEMORY_BASIC_INFORMATION),
                                   ctypes.c_size_t]
_kernel32.VirtualQuery.restype = ctypes.c_size_t


class SharedMemoryNotAvailable(RuntimeError):
    """La mapping non esiste: AC non è in esecuzione (o non è ancora in sessione)."""


class _MappedPage:
    """Vista in sola lettura su una file mapping di AC, letta come struttura ctypes."""

    def __init__(self, tag: str, struct_type: type[ctypes.Structure]):
        self._struct_type = struct_type
        self._view = None
        self._handle = _kernel32.OpenFileMappingW(_FILE_MAP_READ, False, tag)
        if not self._handle:
            raise SharedMemoryNotAvailable(f"{tag} non trovata (errore {ctypes.get_last_error()})")
        self._view = _kernel32.MapViewOfFile(self._handle, _FILE_MAP_READ, 0, 0, 0)
        if not self._view:
            err = ctypes.get_last_error()
            _kernel32.CloseHandle(self._handle)
            self._handle = None
            raise OSError(err, f"MapViewOfFile fallita su {tag}")

        # Non leggere mai oltre la dimensione reale della mapping.
        mbi = _MEMORY_BASIC_INFORMATION()
        _kernel32.VirtualQuery(self._view, ctypes.byref(mbi), ctypes.sizeof(mbi))
        self._read_size = min(mbi.RegionSize, ctypes.sizeof(struct_type))

    def read(self) -> ctypes.Structure:
        """Copia la pagina corrente in una nuova struttura (snapshot indipendente)."""
        out = self._struct_type()
        ctypes.memmove(ctypes.addressof(out), self._view, self._read_size)
        return out

    def close(self) -> None:
        if self._view:
            _kernel32.UnmapViewOfFile(self._view)
            self._view = None
        if self._handle:
            _kernel32.CloseHandle(self._handle)
            self._handle = None

    def __del__(self):
        self.close()


class ACSharedMemory:
    """Accesso alle tre pagine di shared memory di AC.

    Uso:
        with ACSharedMemory() as sm:
            phy = sm.physics()
            print(phy.speedKmh, phy.rpms)
    """

    def __init__(self):
        self._physics = _MappedPage(PHYSICS_TAG, SPageFilePhysics)
        try:
            self._graphics = _MappedPage(GRAPHICS_TAG, SPageFileGraphic)
            self._static = _MappedPage(STATIC_TAG, SPageFileStatic)
        except Exception:
            self.close()
            raise

    def physics(self) -> SPageFilePhysics:
        # AC scrive la pagina mentre la copiamo: se packetId cambia durante la copia
        # lo snapshot può essere misto, quindi riproviamo.
        for _ in range(4):
            first = self._physics.read()
            second = self._physics.read()
            if first.packetId == second.packetId:
                return second
        return second

    def graphics(self) -> SPageFileGraphic:
        return self._graphics.read()

    def static(self) -> SPageFileStatic:
        return self._static.read()

    def close(self) -> None:
        for page in ("_physics", "_graphics", "_static"):
            if hasattr(self, page):
                getattr(self, page).close()

    def __enter__(self) -> "ACSharedMemory":
        return self

    def __exit__(self, *exc) -> None:
        self.close()


def gear_label(gear: int) -> str:
    """Converte la marcia di AC (0=R, 1=N, 2=1a...) in etichetta leggibile."""
    if gear == 0:
        return "R"
    if gear == 1:
        return "N"
    return str(gear - 1)
