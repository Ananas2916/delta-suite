"""
Reads the shared memory of Assetto Corsa (original, 2014).

AC (acs.exe) exposes three named file mappings:
    Local\\acpmf_physics   -> SPageFilePhysics  (updated every physics step, ~333 Hz)
    Local\\acpmf_graphics  -> SPageFileGraphic  (updated every frame)
    Local\\acpmf_static    -> SPageFileStatic   (written once at session start)

The layouts below follow the official AC 1.x shared memory documentation
(pack 4, 2-byte wchar). They are NOT compatible with ACC or AC EVO.

The mappings are opened with OpenFileMappingW (read only) and never created: if we used
mmap.mmap(-1, size, tagname) while AC was not running yet, Python would create a mapping
with our size and acs.exe would attach to it.
"""

from __future__ import annotations

import ctypes

from hub_core.ac.win32 import FILE_MAP_READ, MappedView

c_float = ctypes.c_float
c_int = ctypes.c_int
# Windows wchar is 2 bytes: outside Windows c_wchar has 4 and the layout would not match (recordings
# read in tests); there 16-bit integers are used and wstr() turns them back into a string
c_wchar = ctypes.c_wchar if ctypes.sizeof(ctypes.c_wchar) == 2 else ctypes.c_uint16


def wstr(value) -> str:
    """Text of a wchar[] field of AC pages, on any OS."""
    if isinstance(value, str):
        return value
    chars = []
    for code in value:
        if code == 0:
            break
        chars.append(chr(code))
    return "".join(chars)


def put_wstr(struct: ctypes.Structure, name: str, text: str) -> None:
    """Write a wchar[] field (for tests and hand-made recordings), on any OS."""
    if c_wchar is ctypes.c_wchar:
        setattr(struct, name, text)
        return
    arr = getattr(struct, name)
    codes = [ord(ch) for ch in text[:len(arr) - 1]]
    for i in range(len(arr)):
        arr[i] = codes[i] if i < len(codes) else 0


# ---------------------------------------------------------------------- structures

class SPageFilePhysics(ctypes.Structure):
    _pack_ = 4
    _fields_ = [
        ("packetId", c_int),
        ("gas", c_float),
        ("brake", c_float),
        ("fuel", c_float),
        ("gear", c_int),                      # 0 = R, 1 = N, 2 = 1st, ...
        ("rpms", c_int),
        ("steerAngle", c_float),
        ("speedKmh", c_float),
        ("velocity", c_float * 3),
        ("accG", c_float * 3),                # x lateral, y vertical, z longitudinal
        ("wheelSlip", c_float * 4),           # wheel order: FL, FR, RL, RR
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
        ("rideHeight", c_float * 2),          # front, rear
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
        ("normalizedCarPosition", c_float),   # 0..1 along the lap
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


class SharedMemoryNotAvailable(RuntimeError):
    """The mapping does not exist: AC is not running (or not in a session yet)."""


class _MappedPage:
    """Read-only view of an AC file mapping, read as a ctypes structure."""

    def __init__(self, tag: str, struct_type: type[ctypes.Structure]):
        self._struct_type = struct_type
        try:
            self._map = MappedView(tag, struct_type, FILE_MAP_READ, size=0)   # 0 = the whole mapping
        except FileNotFoundError as exc:
            raise SharedMemoryNotAvailable(str(exc)) from None
        self._view = self._map.ptr
        # Never read past the real size of the mapping.
        self._read_size = min(self._map.region_size(), ctypes.sizeof(struct_type))

    def read(self) -> ctypes.Structure:
        """Copy the current page into a new structure (independent snapshot)."""
        out = self._struct_type()
        ctypes.memmove(ctypes.addressof(out), self._view, self._read_size)
        return out

    def read_consistent(self, tries: int = 4) -> ctypes.Structure:
        """Like read(), but discards copies made while AC was writing the page.

        The first field is packetId: if it is the same before and after the copy (and in the copy),
        no write overlapped.
        """
        packet = ctypes.c_int.from_address(self._view)
        out = self._struct_type()
        for _ in range(tries):
            before = packet.value
            ctypes.memmove(ctypes.addressof(out), self._view, self._read_size)
            if packet.value == before and out.packetId == before:
                break
        return out

    def close(self) -> None:
        if getattr(self, "_map", None) is not None:
            self._map.close()
            self._map = None
            self._view = None

    def __del__(self):
        self.close()


class ACSharedMemory:
    """Access to AC's three shared memory pages.

    Usage:
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
        # AC (333 Hz) may write the page while we copy it: snapshot checked on packetId.
        return self._physics.read_consistent()

    def graphics(self) -> SPageFileGraphic:
        return self._graphics.read_consistent()

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
