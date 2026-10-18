"""
Chiamate di gara dell'ingegnere senza AI, come nei giochi F1: posizioni guadagnate o perse, auto vicina davanti o
dietro, avversari ai box, leader all'ultimo giro, forature, danni, gomme finite, limitatore, gialle davanti e
pista libera, tempo della sessione; a fine giro: primo giro, tendenza dei distacchi, carburante per finire.

Ogni chiamata ha una soglia d'isteresi o un "già detto": la radio deve parlare quando serve, non a ogni campione.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from hub_core.analysis import car_status as cs
from hub_core.analysis.timing import neighbours
from hub_core.model import ACFlag
from ai_engine.lang import speak_amount, speak_number
from ai_engine.radio import Msg
from ai_engine.voice import PRIO_HIGH, PRIO_LOW, PRIO_NORMAL, PRIO_URGENT

POS_CONFIRM_S = 2.5          # la posizione nuova deve restare per qualche istante (sorpassi a metà curva)
POS_GAP_S = 8.0              # al massimo una chiamata di posizione ogni tot secondi
PIT_QUIET_S = 30.0           # dopo la sosta le posizioni ballano: niente chiamate
CLOSE_S, FAR_S = 1.0, 1.5    # auto vicina sotto il secondo; si riavvisa solo dopo che si è allontanata
CLOSE_REPEAT_S = 45.0
CAR_CHECK_S = 0.5
LIMITER_KMH = 70.0
CLEAR_AFTER_S = 4.0          # pista libera: dopo qualche secondo senza zone davanti
TREND_MIN_S = 0.1            # tendenza dei distacchi detta da un decimo al giro in su
FUEL_SHORT_LAPS, FUEL_OK_LAPS = 0.3, 0.5


@dataclass
class RaceContext:
    """Quello che la radio sa della gara oltre al campione: classifica, zone gialle, giri alla fine."""

    now: float
    race: bool = False
    rows: list = field(default_factory=list)       # classifica (StandingRow)
    zone_ahead: tuple | None = None                # (Zone, metri) dalla TrackWatch
    to_go: int | None = None                       # giri alla fine, dal leader
    cars_known: bool = False                       # dati degli avversari dall'app CSP


class RaceCalls:
    def __init__(self, rules):
        self.rules = rules          # RadioRules: lingua, configurazione e scelta delle frasi
        self.reset()

    def reset(self):
        self.start_pos: int | None = None
        self.pos: int | None = None
        self._cand: int | None = None
        self._cand_t = 0.0
        self._last_pos_call = -1e9
        self._was_in_pit = False
        self._pit_t0: float | None = None
        self._pit_exit_t = -1e9
        self._ahead_far = self._behind_far = True
        self._ahead_t = self._behind_t = -1e9
        self._pitted_seen: set[int] = set()
        self._leader_last_said = False
        self._car_said: set[str] = set()
        self._car_t = -1e9
        self._limiter_said = False
        self._yellow_said: set[tuple[int, str]] = set()
        self._clear_t: float | None = None
        self._time_prev: float | None = None
        self._fuel_short = False
        self._gaps: dict[str, tuple[int, float]] = {}   # "ahead"/"behind" → (auto, distacco al giro scorso)

    def p(self, key: str, **kw) -> str:
        return self.rules._p(key, **kw)

    def _places(self, n: int) -> str:
        one, many = self.rules.lang.phrases["places"]
        return one if n == 1 else many

    # ------------------------------------------------------------- per campione
    def on_sample(self, s, info: dict | None, ctx: RaceContext) -> list[Msg]:
        c, now = self.rules.cfg, ctx.now
        if s.is_in_pit and not self._was_in_pit:
            self._pit_t0, self._limiter_said = now, False
            self._car_said = {k for k in self._car_said if k.startswith("damage_")}   # gomme nuove ai box
        elif not s.is_in_pit and self._was_in_pit:
            self._pit_exit_t = now
        self._was_in_pit = s.is_in_pit
        out: list[Msg] = []
        if ctx.race and self.start_pos is None and s.completed_laps == 0 and s.position > 0:
            self.start_pos = s.position
        if ctx.race and c.positions:
            out += self._positions(s, now)
        if ctx.race and c.rivals and not s.is_in_pit:
            out += self._rivals(s, ctx, now)
        if ctx.race and c.lap_times:
            out += self._leader_last_lap(s, ctx)
        if c.car:
            out += self._car(s, info, now)
        if c.flags and ctx.cars_known:
            out += self._track(ctx, now)
        if not ctx.race and c.lap_times:
            out += self._session_time(s)
        return out

    def _positions(self, s, now: float) -> list[Msg]:
        if s.position <= 0:
            return []
        if self.pos is None:
            self.pos = s.position
            return []
        if s.position == self.pos:
            self._cand = None
            return []
        if s.position != self._cand:
            self._cand, self._cand_t = s.position, now
            return []
        if now - self._cand_t < POS_CONFIRM_S:
            return []
        old, self.pos, self._cand = self.pos, s.position, None
        if (s.completed_laps < 1 or s.is_in_pit or now - self._pit_exit_t < PIT_QUIET_S
                or s.flag == ACFlag.CHECKERED or now - self._last_pos_call < POS_GAP_S):
            return []           # primo giro (lo riassume la chiamata di fine giro), soste, arrivo
        self._last_pos_call = now
        key = "pos_gained" if self.pos < old else "pos_lost"
        return [Msg(self.p(key, pos=self.pos), PRIO_NORMAL, 10, "position")]

    def _rivals(self, s, ctx: RaceContext, now: float) -> list[Msg]:
        ahead, me, behind = neighbours(ctx.rows)
        if me is None:
            return []
        out = []
        lg = self.rules.lang
        if s.completed_laps >= 1:
            gap = me.interval_s if ahead is not None and not ahead.in_pit else None
            if gap is not None and gap > FAR_S:
                self._ahead_far = True
            elif gap is not None and gap < CLOSE_S and self._ahead_far and now - self._ahead_t > CLOSE_REPEAT_S:
                self._ahead_far, self._ahead_t = False, now
                out.append(Msg(self.p("ahead_close", g=speak_number(gap, lg)), PRIO_LOW, 8, "ahead_close"))
            gap = behind.interval_s if behind is not None and not behind.in_pit else None
            if gap is not None and gap > FAR_S:
                self._behind_far = True
            elif gap is not None and gap < CLOSE_S and self._behind_far and now - self._behind_t > CLOSE_REPEAT_S:
                self._behind_far, self._behind_t = False, now
                out.append(Msg(self.p("behind_close", g=speak_number(gap, lg)), PRIO_NORMAL, 8, "behind_close"))
        for r, key in ((ahead, "ahead_pitted"), (behind, "behind_pitted")):
            if r is not None and r.in_pit and r.index not in self._pitted_seen:
                out.append(Msg(self.p(key), PRIO_LOW, 15, key))
        self._pitted_seen = {r.index for r in ctx.rows if r.in_pit}
        return out

    def _leader_last_lap(self, s, ctx: RaceContext) -> list[Msg]:
        if ctx.to_go is None or ctx.to_go > 1:
            self._leader_last_said = False
            return []
        if ctx.to_go == 1 and not self._leader_last_said:
            self._leader_last_said = True
            if s.position != 1:         # se il leader sei tu, l'ultimo giro lo dice la chiamata di fine giro
                return [Msg(self.p("leader_last_lap"), PRIO_NORMAL, 20, "to_go")]
        return []

    def _car(self, s, info: dict | None, now: float) -> list[Msg]:
        out: list[Msg] = []
        lg = self.rules.lang
        if (s.is_in_pit and self._pit_t0 is not None and now - self._pit_t0 > 1.5 and not s.pit_limiter
                and s.speed_kmh > LIMITER_KMH and not self._limiter_said):
            self._limiter_said = True
            out.append(Msg(self.p("limiter"), PRIO_URGENT, 4, "limiter"))
        if now - self._car_t < CAR_CHECK_S:
            return out
        self._car_t = now
        worn = []
        for a in cs.car_alerts(s, info):
            if a.level != cs.CRIT or a.key in self._car_said:
                continue
            if a.key.startswith("flat_"):
                wheel = lg.phrases["wheels"][int(a.key[5:])]
                out.append(Msg(self.p("puncture", wheel=wheel), PRIO_URGENT, 20, a.key))
            elif a.key.startswith("damage_"):
                zone = lg.phrases["zones"][cs.DAMAGE_ZONES.index(a.key[7:])]
                out.append(Msg(self.p("damage", zone=zone), PRIO_HIGH, 20, a.key))
            elif a.key.startswith("wear_"):
                worn.append(int(a.key[5:]))
            else:
                continue
            self._car_said.add(a.key)
        if len(worn) == 1:
            out.append(Msg(self.p("tyre_worn", wheel=lg.phrases["wheels"][worn[0]]), PRIO_NORMAL, 30, "wear"))
        elif worn:
            out.append(Msg(self.p("tyres_worn"), PRIO_NORMAL, 30, "wear"))
        return out

    def _track(self, ctx: RaceContext, now: float) -> list[Msg]:
        if ctx.zone_ahead is not None:
            zone, dist = ctx.zone_ahead
            self._clear_t = None
            key = (zone.car, zone.kind)
            if key in self._yellow_said:
                return []
            self._yellow_said.add(key)
            d = max(50, int(round(dist / 50.0)) * 50)       # metri, arrotondati come li direbbe un ingegnere
            phrase = "double_yellow" if zone.kind == "red" else "yellow_ahead"
            return [Msg(self.p(phrase, d=d), PRIO_URGENT, 6, "yellow")]
        if not self._yellow_said:
            return []
        if self._clear_t is None:
            self._clear_t = now
        elif now - self._clear_t > CLEAR_AFTER_S:
            self._yellow_said.clear()
            self._clear_t = None
            return [Msg(self.p("track_clear"), PRIO_LOW, 6, "yellow")]
        return []

    def _session_time(self, s) -> list[Msg]:
        left, prev = s.session_time_left, self._time_prev
        self._time_prev = left
        if prev is None or left <= 0:
            return []
        for threshold, key in ((300_000, "time_5min"), (60_000, "time_1min")):
            if prev > threshold >= left:
                return [Msg(self.p(key), PRIO_NORMAL, 20, "session_time")]
        return []

    # ------------------------------------------------------------- a fine giro
    def lap1(self, position: int) -> Msg:
        """Fine del primo giro: posizione e quante se ne sono guadagnate o perse dalla griglia."""
        n = (self.start_pos or position) - position
        if n > 0:
            text = self.p("lap1_gained", pos=position, n=n, places=self._places(n))
        elif n < 0:
            text = self.p("lap1_lost", pos=position, n=-n, places=self._places(-n))
        else:
            text = self.p("lap1", pos=position)
        return Msg(text, PRIO_HIGH, 25, "lap1")

    def gap_parts(self, ahead, me, behind) -> list[str]:
        """Distacchi davanti e dietro con la tendenza rispetto al giro scorso (stessa auto)."""
        lg = self.rules.lang
        parts = []
        for side, car, gap in (("ahead", ahead, me.interval_s if me is not None else None),
                               ("behind", behind, behind.interval_s if behind is not None else None)):
            if car is None or gap is None:
                self._gaps.pop(side, None)
                continue
            text = self.p(side, g=speak_number(gap, lg))
            prev = self._gaps.get(side)
            if prev is not None and prev[0] == car.index:
                change = prev[1] - gap          # > 0: il distacco si accorcia
                amount = speak_amount(change, lg)
                if abs(change) >= TREND_MIN_S and amount:
                    if side == "ahead":
                        text += ", " + self.p("closing" if change > 0 else "dropping", d=amount)
                    else:
                        text += ", " + self.p("catching" if change > 0 else "pulling", d=amount)
            self._gaps[side] = (car.index, gap)
            parts.append(text)
        return parts

    def fuel(self, fuel_end: float, fpl: float, to_go: int) -> list[Msg]:
        """Carburante per finire: risparmio se non basta, via libera quando torna a bastare."""
        margin = fuel_end - to_go * fpl
        if margin < -FUEL_SHORT_LAPS * fpl and not self._fuel_short:
            self._fuel_short = True
            return [Msg(self.p("fuel_save"), PRIO_HIGH, 40, "fuel_save")]
        if margin > FUEL_OK_LAPS * fpl and self._fuel_short:
            self._fuel_short = False
            return [Msg(self.p("fuel_ok"), PRIO_NORMAL, 40, "fuel_save")]
        return []

