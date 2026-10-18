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

from hub_core.ac.win32 import FILE_MAP_READ, MappedView

c_float = ctypes.c_float
c_int = ctypes.c_int
# wchar di Windows a 2 byte: fuori da Windows c_wchar ne ha 4 e il layout non tornerebbe (registrazioni
# lette nei test); lì si usano interi a 16 bit e wstr() li riporta a stringa
c_wchar = ctypes.c_wchar if ctypes.sizeof(ctypes.c_wchar) == 2 else ctypes.c_uint16


def wstr(value) -> str:
    """Testo di un campo wchar[] delle pagine di AC, su qualunque sistema."""
    if isinstance(value, str):
        return value
    chars = []
    for code in value:
        if code == 0:
            break
        chars.append(chr(code))
    return "".join(chars)


def put_wstr(struct: ctypes.Structure, name: str, text: str) -> None:
    """Scrive un campo wchar[] (per test e registrazioni create a mano), su qualunque sistema."""
    if c_wchar is ctypes.c_wchar:
        setattr(struct, name, text)
        return
    arr = getattr(struct, name)
    codes = [ord(ch) for ch in text[:len(arr) - 1]]
    for i in range(len(arr)):
        arr[i] = codes[i] if i < len(codes) else 0


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


class SharedMemoryNotAvailable(RuntimeError):
    """La mapping non esiste: AC non è in esecuzione (o non è ancora in sessione)."""


class _MappedPage:
    """Vista in sola lettura su una file mapping di AC, letta come struttura ctypes."""

    def __init__(self, tag: str, struct_type: type[ctypes.Structure]):
        self._struct_type = struct_type
        try:
            self._map = MappedView(tag, struct_type, FILE_MAP_READ, size=0)   # 0 = tutta la mapping
        except FileNotFoundError as exc:
            raise SharedMemoryNotAvailable(str(exc)) from None
        self._view = self._map.ptr
        # Non leggere mai oltre la dimensione reale della mapping.
        self._read_size = min(self._map.region_size(), ctypes.sizeof(struct_type))

    def read(self) -> ctypes.Structure:
        """Copia la pagina corrente in una nuova struttura (snapshot indipendente)."""
        out = self._struct_type()
        ctypes.memmove(ctypes.addressof(out), self._view, self._read_size)
        return out

    def read_consistent(self, tries: int = 4) -> ctypes.Structure:
        """Come read(), ma scarta le copie fatte mentre AC stava scrivendo la pagina.

        Il primo campo è packetId: se vale lo stesso prima e dopo la copia (e nella copia),
        nessuna scrittura si è sovrapposta.
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
        # AC (333 Hz) può scrivere la pagina mentre la copiamo: snapshot verificato su packetId.
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
