"""
Stato della pista per il GPS e le bandiere: linea della pista per posizione sul giro, auto lente o ferme e zone
gialle, rosse (auto ferma, doppia gialla) e blu.

AC non dice dove è esposta una gialla, e la sua `flag` a volte resta gialla quando l'incidente è passato: le
zone si ricavano qui dalle velocità delle auto (app CSP), confrontate con la velocità tipica in quel punto della
pista, imparata durante la sessione.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

from hub_core.model import ACFlag

BINS = 500                       # punti della linea e celle delle velocità tipiche, a passo costante sul giro
STOPPED_KMH = 8.0
SLOW_KMH = 30.0                  # lenta comunque, anche dove la velocità tipica non è ancora nota
SLOW_FRACTION = 0.4              # lenta se sotto il 40% della velocità tipica in quel punto
TYPICAL_MIN_KMH = 60.0           # velocità tipica considerata nota da qui in su
TYPICAL_DECAY = 0.9995           # il massimo imparato cala piano (gomme usurate, pioggia...)
CROWD_FRACTION = 0.4             # oltre questa quota di auto lente è una partenza o una neutralizzazione
ZONE_BEFORE, ZONE_AFTER = 0.025, 0.006      # tratto colorato attorno all'auto, in frazione di giro
ZONE_HOLD_S = 3.0                # la zona resta un po' dopo che l'auto è ripartita: niente lampeggi
BLUE_BEHIND = 0.02
WARN_AHEAD_M = 800.0             # gialla per il pilota se la zona è entro questa distanza davanti
AC_FLAG_FRESH_S = 8.0            # gialla di AC senza auto lente che la confermino: vale solo per qualche secondo
GREEN_S = 5.0                    # dopo una gialla: bandiera verde per qualche secondo, come in TV

ZONE_COLORS = ("yellow", "red", "blue")


@dataclass(frozen=True)
class Zone:
    start: float        # posizione sul giro (può uscire da 0..1: si avvolge sul traguardo)
    end: float
    kind: str           # "yellow", "red" o "blue"
    car: int = -1       # auto che l'ha causata

    def contains(self, pos: float) -> bool:
        return (pos - self.start) % 1.0 <= (self.end - self.start)


@dataclass(frozen=True)
class FlagStatus:
    kind: str           # "yellow", "red", "blue", "checkered", "black", "white", "penalty"
    text: str


class TrackLine:
    """Punti della pista a passo costante sul giro: il punto i è alla posizione i / n."""

    def __init__(self, xs: np.ndarray, zs: np.ndarray):
        self.xs, self.zs = np.asarray(xs, float), np.asarray(zs, float)
        seg = np.hypot(np.diff(np.append(self.xs, self.xs[0])), np.diff(np.append(self.zs, self.zs[0])))
        self.length = float(seg.sum())

    @classmethod
    def from_points(cls, pts: list[tuple[float, float]], n: int = BINS) -> TrackLine | None:
        """Linea AI (punti fitti in ordine di giro) ricampionata a passo costante sulla distanza percorsa."""
        if len(pts) < 10:
            return None
        a = np.asarray(pts, float)
        closed = np.vstack([a, a[:1]])
        dist = np.concatenate([[0.0], np.cumsum(np.hypot(*np.diff(closed, axis=0).T))])
        if dist[-1] <= 0:
            return None
        t = np.linspace(0.0, dist[-1], n, endpoint=False)
        return cls(np.interp(t, dist, closed[:, 0]), np.interp(t, dist, closed[:, 1]))

    @property
    def n(self) -> int:
        return len(self.xs)

    def point(self, pos: float) -> tuple[float, float]:
        f = (pos % 1.0) * self.n
        i = int(f) % self.n
        j = (i + 1) % self.n
        k = f - int(f)
        return (self.xs[i] + (self.xs[j] - self.xs[i]) * k, self.zs[i] + (self.zs[j] - self.zs[i]) * k)

    def points(self, start: float, end: float, step: float | None = None) -> list[tuple[float, float]]:
        """Punti dal tratto start → end (posizioni sul giro, end > start, anche oltre il traguardo)."""
        step = step or 1.0 / self.n
        count = max(2, int(math.ceil((end - start) / step)) + 1)
        return [self.point(start + (end - start) * i / (count - 1)) for i in range(count)]


class LineLearner:
    """Linea imparata dalle posizioni delle auto quando la linea AI del tracciato non c'è (demo, tracciato
    non installato): media di (x, z) per cella di posizione sul giro."""

    def __init__(self, n: int = BINS):
        self.sx, self.sz, self.cnt = np.zeros(n), np.zeros(n), np.zeros(n)

    def add(self, pos: float, x: float, z: float) -> None:
        if not 0.0 <= pos <= 1.0:
            return
        b = int(pos * len(self.cnt)) % len(self.cnt)
        self.sx[b] += x
        self.sz[b] += z
        self.cnt[b] += 1

    @property
    def coverage(self) -> float:
        return float((self.cnt > 0).mean())

    def max_gap(self) -> int:
        """Celle vuote consecutive più lunghe (a cavallo del traguardo compreso)."""
        known = np.flatnonzero(self.cnt > 0)
        if known.size == 0:
            return len(self.cnt)
        return int(np.diff(np.append(known, known[0] + len(self.cnt))).max()) - 1

    def line(self, max_gap: int = 8) -> TrackLine | None:
        """La linea quando il giro è coperto a meno di buchi corti (campioni radi: demo accelerato, scatti)."""
        if self.max_gap() > max_gap:
            return None
        n = len(self.cnt)
        known = np.flatnonzero(self.cnt > 0)
        xs, zs = self.sx[known] / self.cnt[known], self.sz[known] / self.cnt[known]
        # celle vuote: interpolazione tra le vicine, anche a cavallo del traguardo
        idx = np.arange(n)
        ext = np.concatenate([known - n, known, known + n])
        return TrackLine(np.interp(idx, ext, np.tile(xs, 3)), np.interp(idx, ext, np.tile(zs, 3)))


class TrackWatch:
    """Linea della pista, velocità tipiche e zone di incidente per una sessione."""

    def __init__(self, ai_line: list[tuple[float, float]] | None = None,
                 pit_line: list[tuple[float, float]] | None = None, track_length: float = 0.0):
        self.ai = TrackLine.from_points(ai_line or [])
        self.pit = list(pit_line or [])
        self.learner = LineLearner()
        self._learned: TrackLine | None = None
        self._learn_count = 0
        self.typical = np.zeros(BINS)
        self.track_length = track_length or (self.ai.length if self.ai else 0.0)
        self.zones: list[Zone] = []
        self._slow_since: dict[int, tuple[float, str, float]] = {}   # auto → (ultimo istante lenta, tipo, pos)
        self._ac_flag, self._ac_flag_t = ACFlag.NONE, -1e9
        self._warned_t = -1e9            # ultima volta che il pilota aveva una gialla

    @property
    def line(self) -> TrackLine | None:
        return self.ai or self._learned

    # ------------------------------------------------------------- dati in ingresso
    def feed_position(self, pos: float, x: float, z: float) -> None:
        """Posizione di un'auto (pos sul giro e coordinate): serve solo a imparare la linea senza linea AI."""
        if self.ai is not None:
            return
        self.learner.add(pos, x, z)
        self._learn_count += 1
        if self._learn_count % 200 == 0:        # ricalcolo ogni tanto: costa poco ma non serve a ogni campione
            self._learned = self.learner.line() or self._learned

    def update_cars(self, cars, now: float, race_laps: int = 0, live: bool = True) -> None:
        """Velocità tipiche e zone dalle auto in pista (`CarEntry` dell'app CSP, ~10 volte al secondo)."""
        on_track = [c for c in cars if c.connected and not c.in_pitlane and not c.in_pit and 0.0 <= c.spline <= 1.0
                    and not (race_laps and c.lap_count >= race_laps)]
        slow_now = []
        for c in on_track:
            b = int(c.spline * BINS) % BINS
            typ = self.typical[b]
            stopped = c.speed_kmh < STOPPED_KMH
            slow = stopped or c.speed_kmh < SLOW_KMH or (typ >= TYPICAL_MIN_KMH and c.speed_kmh < SLOW_FRACTION * typ)
            if slow:
                slow_now.append((c, "red" if stopped else "yellow"))
            else:
                for k in (b - 1, b, (b + 1) % BINS):
                    self.typical[k] = max(self.typical[k] * TYPICAL_DECAY, c.speed_kmh)
        if not live or not on_track or len(slow_now) > CROWD_FRACTION * len(on_track):
            self._slow_since.clear()             # partenza, neutralizzazione, pausa: nessuna zona
            self.zones = []
            return
        for c, kind in slow_now:
            self._slow_since[c.index] = (now, kind, c.spline)
        self._slow_since = {i: v for i, v in self._slow_since.items() if now - v[0] <= ZONE_HOLD_S}
        self.zones = [Zone(pos - ZONE_BEFORE, pos + ZONE_AFTER, kind, i)
                      for i, (_t, kind, pos) in sorted(self._slow_since.items())]

    # ------------------------------------------------------------- uscite
    def display_zones(self, player_pos: float | None, ac_flag: int) -> list[Zone]:
        """Zone da colorare sul GPS: incidenti, più la blu dietro la tua auto se AC la espone."""
        zones = list(self.zones)
        if ac_flag == ACFlag.BLUE and player_pos is not None:
            zones.append(Zone(player_pos - BLUE_BEHIND, player_pos + 0.002, "blue", 0))
        return zones

    def player_flag(self, player_pos: float | None, ac_flag: int, now: float, cars_known: bool) -> FlagStatus | None:
        """Bandiera per il pilota. La gialla viene dalle zone davanti; quella di AC conta da sola solo se non ci
        sono i dati delle altre auto, o per pochi secondi dopo che è comparsa. Finita la gialla, verde per poco."""
        flag = self._player_flag(player_pos, ac_flag, now, cars_known)
        if flag is not None and flag.kind in ("yellow", "red"):
            self._warned_t = now
        elif flag is None and now - self._warned_t < GREEN_S:
            return FlagStatus("green", "BANDIERA VERDE · pista libera")
        return flag

    def _player_flag(self, player_pos: float | None, ac_flag: int, now: float, cars_known: bool) -> FlagStatus | None:
        if ac_flag != self._ac_flag:
            self._ac_flag, self._ac_flag_t = ac_flag, now
        fixed = {ACFlag.BLUE: ("blue", "BANDIERA BLU · fai passare"),
                 ACFlag.CHECKERED: ("checkered", "BANDIERA A SCACCHI"),
                 ACFlag.BLACK: ("black", "BANDIERA NERA"), ACFlag.PENALTY: ("penalty", "PENALITÀ"),
                 ACFlag.WHITE: ("white", "BANDIERA BIANCA")}
        if ac_flag in fixed:
            return FlagStatus(*fixed[ac_flag])
        ahead = self.zone_ahead(player_pos)
        if ahead is not None:
            zone, dist = ahead
            where = "nel tratto" if dist <= 0 else f"a {dist:.0f} m"
            if zone.kind == "red":
                return FlagStatus("red", f"DOPPIA GIALLA · auto ferma {where}")
            return FlagStatus("yellow", f"BANDIERA GIALLA · auto lenta {where}")
        if ac_flag == ACFlag.YELLOW and (not cars_known or now - self._ac_flag_t < AC_FLAG_FRESH_S):
            return FlagStatus("yellow", "BANDIERA GIALLA")
        return None

    def zone_ahead(self, player_pos: float | None) -> tuple[Zone, float] | None:
        """La zona più vicina davanti alla tua auto entro WARN_AHEAD_M, con la distanza (0 = ci sei dentro)."""
        if player_pos is None or not self.zones or self.track_length <= 0:
            return None
        best = None
        for z in self.zones:
            if z.car == 0:          # la tua auto non si fa la gialla da sola
                continue
            dist = 0.0 if z.contains(player_pos) else ((z.start - player_pos) % 1.0) * self.track_length
            if dist <= WARN_AHEAD_M and (best is None or dist < best[1]):
                best = (z, dist)
        return best
