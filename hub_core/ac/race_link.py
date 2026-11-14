"""
Delta Suite side of race control and of the in-game HUD (ac_app/DeltaSuiteBridge/DeltaSuiteRace.lua).

The app writes DeltaSuite_Race_Out_v1 (neutralisation state, VSC delta, speed check) and reads
DeltaSuite_Race_In_v1, where Delta Suite writes commands (FCY, VSC, end), the race control settings and the data
the HUD shows (radio message, proposal to confirm, fuel and strategy). A command is written field first, `seq` last,
as on the bridge; the app acknowledges it in ackSeq.

The layouts are the same as declared in DeltaSuiteRace.lua: if you change one, change the other (and the version
in the mapping names). tests/test_layouts.py checks them byte for byte.
"""

from __future__ import annotations

import ctypes
from dataclasses import dataclass

from hub_core.ac.win32 import FILE_MAP_READ, FILE_MAP_WRITE, MappedView

RACE_OUT_TAG = "Local\\DeltaSuite_Race_Out_v1"
RACE_IN_TAG = "Local\\DeltaSuite_Race_In_v1"
RACE_VERSION = 1
RACE_END_MARKER = 0x44535231

# states and modes, same numbers as DeltaSuiteRace.lua
GREEN, PENDING, ACTIVE, ENDING, GREEN_FLASH = 0, 1, 2, 3, 4
MODE_NONE, MODE_FCY, MODE_VSC, MODE_SC = 0, 1, 2, 3
SC_NONE, SC_PARKED, SC_OUT, SC_IN, SC_MISSING, SC_WAITING = 0, 1, 2, 3, 4, 5      # safety car phases
CMD_FCY, CMD_VSC, CMD_END, CMD_CANCEL, CMD_SC = 1, 2, 3, 4, 5

c_int, c_float, c_char = ctypes.c_int, ctypes.c_float, ctypes.c_char


class RaceOut(ctypes.Structure):
    _fields_ = [
        ("version", c_int), ("frame", c_int), ("available", c_int), ("state", c_int), ("mode", c_int),
        ("stateTime", c_float), ("countdown", c_float), ("delta", c_float), ("limitKmh", c_float),
        ("playerKmh", c_float), ("overLimit", c_int), ("infractionS", c_float), ("ackSeq", c_int),
        ("requestSeq", c_int), ("requestCmd", c_int), ("scCar", c_int), ("scPhase", c_int), ("scGapM", c_float),
        ("endMarker", c_int),
    ]


class RaceIn(ctypes.Structure):
    _fields_ = [
        ("version", c_int), ("hostBeat", c_int), ("seq", c_int), ("cmd", c_int),
        ("vscFactor", c_float), ("vscAiKmh", c_float), ("fcyKmh", c_float), ("countdownS", c_float),
        ("endingS", c_float), ("scKmh", c_float), ("scCarId", c_char * 64), ("pitExitSpline", c_float),
        ("scWaveLaps", c_int), ("pitLaneX", c_float), ("pitLaneZ", c_float), ("pitLaneDirX", c_float),
        ("pitLaneDirZ", c_float), ("pitLaneKnown", c_int),
        ("lapsToGo", c_int), ("fuelLapsLeft", c_float), ("fuelToEnd", c_float), ("fuelPerLap", c_float),
        ("pitWindowOpen", c_int), ("pitWindowClose", c_int), ("pitStopsLeft", c_int),
        ("radioSeq", c_int), ("radioText", c_char * 256), ("proposalPending", c_int),
        ("proposalText", c_char * 160), ("engineerText", c_char * 96), ("strategyText", c_char * 96),
        ("endMarker", c_int),
    ]


@dataclass(frozen=True)
class RaceControlState:
    available: bool
    state: int
    mode: int
    state_time: float
    countdown: float
    delta: float
    limit_kmh: float
    player_kmh: float
    over_limit: bool
    infraction_s: float
    ack_seq: int
    request_seq: int        # neutralisations asked for from the CSP buttons
    request_cmd: int
    sc_car: int = -1        # safety car index in the session, -1 = none
    sc_phase: int = SC_NONE
    sc_gap_m: float = 0.0   # under SC: the player's gap to the car ahead in the queue

    @property
    def neutralised(self) -> bool:
        """Cars slowed down (the FCY countdown not yet): laps run now are not representative."""
        return self.state in (ACTIVE, ENDING)

    @property
    def active(self) -> bool:
        return self.state in (PENDING, ACTIVE, ENDING)


def state_from_struct(o: RaceOut) -> RaceControlState:
    return RaceControlState(
        available=bool(o.available), state=o.state, mode=o.mode, state_time=o.stateTime, countdown=o.countdown,
        delta=o.delta, limit_kmh=o.limitKmh, player_kmh=o.playerKmh, over_limit=bool(o.overLimit),
        infraction_s=o.infractionS, ack_seq=o.ackSeq, request_seq=o.requestSeq, request_cmd=o.requestCmd,
        sc_car=o.scCar, sc_phase=o.scPhase, sc_gap_m=o.scGapM)


@dataclass
class RaceSettings:
    vsc_factor: float = 1.4     # VSC reference = best lap × factor
    vsc_ai_kmh: float = 0.0     # AI speed cap under VSC; 0 = auto, from the reference lap's average speed
    fcy_kmh: float = 80.0       # FCY speed limit (AI and driver)
    countdown_s: float = 10.0   # "FCY in 10 seconds"
    ending_s: float = 12.0      # "VSC ending" → green
    sc_kmh: float = 120.0       # safety car speed cap
    sc_car_id: str = ""         # car folder of the safety car; "" = the first car whose name says "safety"
    sc_wave_laps: int = 1       # laps behind the SC before the lapped cars may unlap themselves (0 = never)


@dataclass
class HudInfo:
    """What Delta Suite knows and the in-game HUD shows (engineer window, fuel, strategy)."""

    laps_to_go: int = 0
    fuel_laps_left: float = 0.0
    fuel_to_end: float = 0.0          # litres in hand (+) or short (-) at the finish
    fuel_per_lap: float = 0.0
    pit_window_open: int = 0          # lap numbers, 0 = no window
    pit_window_close: int = 0
    pit_stops_left: int = 0
    radio_text: str = ""              # last radio message: a new text is shown for a while
    proposal_text: str = ""           # pending engineer proposal, "" = none
    engineer_text: str = ""           # engineer status (e.g. "thinking…")
    strategy_text: str = ""           # one line of strategy


class RaceLink:
    """Link to race control in the Lua app. All methods are non-blocking."""

    def __init__(self):
        self._out: MappedView | None = None
        self._in: MappedView | None = None
        self._radio_text = ""
        self.layout_error: str | None = None

    @property
    def connected(self) -> bool:
        return self._out is not None

    def connect(self) -> bool:
        if self._out is not None:
            return True
        try:
            out = MappedView(RACE_OUT_TAG, RaceOut, FILE_MAP_READ)
        except (FileNotFoundError, OSError):
            return False
        try:
            inp = MappedView(RACE_IN_TAG, RaceIn, FILE_MAP_READ | FILE_MAP_WRITE)
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

    def read(self) -> RaceControlState | None:
        """Race control state; also beats the heartbeat the HUD uses to show "connected"."""
        if not self.connect():
            return None
        snap = RaceOut()
        ctypes.memmove(ctypes.addressof(snap), self._out.ptr, ctypes.sizeof(RaceOut))
        if snap.version == 0:
            return None
        if snap.version != RACE_VERSION or snap.endMarker != RACE_END_MARKER:
            self.layout_error = f"CSP race control version {snap.version}: reinstall the app from Delta Suite"
            return None
        self.layout_error = None
        s = self._in.struct
        s.version, s.endMarker = RACE_VERSION, RACE_END_MARKER
        s.hostBeat = (s.hostBeat + 1) & 0x7FFFFFFF
        return state_from_struct(snap)

    def send(self, cmd: int) -> int | None:
        if not self.connect():
            return None
        s = self._in.struct
        s.version, s.endMarker = RACE_VERSION, RACE_END_MARKER
        s.cmd = cmd
        seq = (s.seq + 1) & 0x7FFFFFFF or 1
        s.seq = seq          # last: the app acts when it sees seq change
        return seq

    def write_settings(self, rs: RaceSettings) -> None:
        if not self.connect():
            return
        s = self._in.struct
        s.vscFactor, s.vscAiKmh, s.fcyKmh = rs.vsc_factor, rs.vsc_ai_kmh, rs.fcy_kmh
        s.countdownS, s.endingS = rs.countdown_s, rs.ending_s
        s.scKmh, s.scCarId = rs.sc_kmh, _enc(rs.sc_car_id, 64)
        s.scWaveLaps = rs.sc_wave_laps if rs.sc_wave_laps > 0 else -1     # 0 would mean "default" in the app

    def write_pit_exit(self, pos: float | None, lane: tuple[float, float, float, float] | None = None) -> None:
        """Lap position of the pit exit (from the track's pit_lane.ai; -1 = unknown, the app learns it) and the
        point in the pit lane, before the exit, where the safety car starts (x, z, heading)."""
        if self.connect():
            s = self._in.struct
            s.pitExitSpline = -1.0 if pos is None else float(pos)
            if lane is None:
                s.pitLaneKnown = 0
            else:
                s.pitLaneX, s.pitLaneZ, s.pitLaneDirX, s.pitLaneDirZ = lane
                s.pitLaneKnown = 1

    def write_hud(self, h: HudInfo) -> None:
        if not self.connect():
            return
        s = self._in.struct
        s.lapsToGo, s.fuelLapsLeft, s.fuelToEnd, s.fuelPerLap = h.laps_to_go, h.fuel_laps_left, h.fuel_to_end, \
            h.fuel_per_lap
        s.pitWindowOpen, s.pitWindowClose, s.pitStopsLeft = h.pit_window_open, h.pit_window_close, h.pit_stops_left
        s.proposalPending = 1 if h.proposal_text else 0
        s.proposalText = _enc(h.proposal_text, 160)
        s.engineerText = _enc(h.engineer_text, 96)
        s.strategyText = _enc(h.strategy_text, 96)
        if h.radio_text and h.radio_text != self._radio_text:
            s.radioText = _enc(h.radio_text, 256)
            s.radioSeq = (s.radioSeq + 1) & 0x7FFFFFFF
        self._radio_text = h.radio_text


def _enc(text: str, size: int) -> bytes:
    """UTF-8 cut to fit the char array without splitting a character."""
    raw = (text or "").encode("utf-8")[: size - 1]
    return raw.decode("utf-8", errors="ignore").encode("utf-8")
