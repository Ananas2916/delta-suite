"""
The chatty engineer: what a real F1 race engineer says between the important calls, without AI.

Studied on real F1 team radio: the engineer talks to the driver all race long, not only for gaps and fuel.
Lights out, overtakes with the rival's name, purple sectors, "good stop, you rejoin P5", "tyres are in the
window, push", "Leclerc ahead did a 32.4", undercut and overcut when a rival boxes, "battery is full, use it",
"we lost half a second that lap, any issues?", "good consistent pace", half distance, "bring it home"; in
practice and qualifying where the lap puts you on the timesheet; and when nothing has been said for a while, a
short update (position and gaps, fuel margin, tyres, a word of encouragement), as engineers do on long stints.

Chattiness (RadioConfig.chatter): 0 = only the essential calls of radio.py and race_calls.py, 1 = also the
event calls of this module, 2 = also the minor ones (every purple sector, rivals' lap times, praise) and the
periodic updates when the radio is quiet. Everything is said once or with a cooldown: chatty, not a loop.
"""

from __future__ import annotations

import time

from hub_core.analysis import car_status as cs
from hub_core.analysis import race_strategy as rs
from hub_core.analysis.timing import neighbours
from ai_engine.lang import speak_amount, speak_lap_time, speak_number
from ai_engine.radio import Msg
from ai_engine.voice import PRIO_HIGH, PRIO_LOW, PRIO_NORMAL

QUIET, NORMAL, CHATTY = 0, 1, 2

START_KMH = 40.0             # race start: the car is moving on lap zero
PIT_EXIT_DELAY_S = 5.0       # rejoin position: positions settle a few seconds after the pit exit
SECTOR_GAIN_NORMAL_S = 0.2   # purple sector said at chattiness 1 only when it is worth it
ERS_CLOSE_S, ERS_FULL = 1.0, 0.75
ERS_DEFEND_S = 0.8
ERS_REPEAT_S = 120.0
PACE_DROP_S = 1.0            # lap slower than the stint average by this much: "any issues?"
CONSISTENT_SPREAD_S = 0.3
CONSISTENT_EVERY = 6         # laps
FASTEST_EVERY = 5
RIVAL_LAP_EVERY = 3
DRIP_QUIET_S = 70.0          # periodic update after this much radio silence (chattiness 2)
CLOSE_GAP_S = 3.0            # in the update: rival close enough to be worth naming

# Spontaneous AI comment (RadioConfig.ai_comment_laps): what the local phrases cannot do, reasoning on the data
AI_COMMENT_PROMPT = (
    "The driver did not ask anything: this is a spontaneous radio message from you, the race engineer, as on F1 "
    "team radio. Look at the data (live_state, standings, session_laps) and say ONE thing that matters now and "
    "that the automatic radio does not already say: strategy (pit window, undercut threat, fuel or tyre plan), "
    "pace against the cars around and where the gap is going, a tyre or brake trend, or a concrete tip. "
    "One or two short spoken sentences. Do not just read out the lap time, the position or the gaps.")


def surname(driver: str | None) -> str | None:
    """'Max Verstappen' -> 'Verstappen': on the radio rivals are called by surname."""
    parts = (driver or "").replace("_", " ").split()
    return parts[-1] if parts else None


class RaceChatter:
    def __init__(self, rules):
        self.rules = rules          # RadioRules: language, configuration, phrase choice
        self.reset()

    def reset(self):
        self._started = False
        self._last_talk: float | None = None
        self._was_in_pit = False
        self._pit_exit_t: float | None = None
        self._sector: int | None = None
        self._sector_said_lap: int | None = None
        self.best_sectors: list[int | None] = []
        self._slow_said: set[int] = set()
        self._ers_t = -1e9
        self._drip_i = 0
        self._consistent_lap = -99
        self._fastest_lap = -99
        self._rival_lap_lap = -99
        self._half_said = False
        self._home_said = False
        self._fuel_per_lap: float | None = None
        self._to_go: int | None = None

    @property
    def level(self) -> int:
        return int(getattr(self.rules.cfg, "chatter", CHATTY))

    def p(self, key: str, **kw) -> str:
        text = self.rules._p(key, **kw)
        return text[:1].upper() + text[1:]

    def who(self, row, side: str) -> str:
        return surname(row.driver if row is not None else None) or self.rules.lang.phrases[f"who_{side}"]

    def heard(self, now: float | None = None) -> None:
        """The radio has just said something: the periodic update waits for a quiet moment again."""
        self._last_talk = time.monotonic() if now is None else now

    # ------------------------------------------------------------- per sample
    def on_sample(self, s, info: dict | None, ctx) -> list[Msg]:
        if self.level <= QUIET:
            return []
        now = ctx.now
        if self._last_talk is None:
            self._last_talk = now
        out: list[Msg] = []
        if ctx.race:
            out += self._start(s)
            out += self._pit_exit(s, now)
        out += self._sectors(s)
        if ctx.race and ctx.cars_known and not s.is_in_pit:
            ahead, me, behind = neighbours(ctx.rows)
            out += self._rival_slow(ahead, ctx)
            if self.level >= CHATTY:
                out += self._battery(s, info, ahead, me, behind, now)
                if not out and now - self._last_talk > DRIP_QUIET_S and s.completed_laps >= 1:
                    out += self._update(s, info, ahead, me, behind)
        if out:
            self._last_talk = now
        return out

    def _start(self, s) -> list[Msg]:
        if self._started:
            return []
        if s.completed_laps > 0:
            self._started = True        # joined a race already under way
            return []
        if s.speed_kmh > START_KMH and not s.is_in_pit:
            self._started = True
            return [Msg(self.p("race_start"), PRIO_HIGH, 6, "race_start")]
        return []

    def _pit_exit(self, s, now: float) -> list[Msg]:
        if self._was_in_pit and not s.is_in_pit and s.completed_laps >= 1:
            self._pit_exit_t = now
        self._was_in_pit = s.is_in_pit
        if self._pit_exit_t is not None and now - self._pit_exit_t > PIT_EXIT_DELAY_S:
            self._pit_exit_t = None
            if s.position > 0:
                return [Msg(self.p("pit_exit", pos=s.position), PRIO_NORMAL, 15, "pit_exit")]
        return []

    def _sectors(self, s) -> list[Msg]:
        """Purple sector as soon as it closes (the last one is in the lap call). One per lap."""
        prev, self._sector = self._sector, s.sector_index
        if prev is None or s.sector_index != prev + 1 or s.is_in_pit or s.last_sector_ms <= 0:
            return []
        if self._sector_said_lap == s.completed_laps or prev >= len(self.best_sectors):
            return []
        best = self.best_sectors[prev]
        if best is None or s.last_sector_ms >= best:
            return []
        gain = (best - s.last_sector_ms) / 1000.0
        if self.level < CHATTY and gain < SECTOR_GAIN_NORMAL_S:
            return []
        self._sector_said_lap = s.completed_laps
        amount = speak_amount(gain, self.rules.lang)
        text = self.p("sector_best_by", n=prev + 1, d=amount) if amount else self.p("sector_best", n=prev + 1)
        return [Msg(text, PRIO_LOW, 6, "sector")]

    def _rival_slow(self, ahead, ctx) -> list[Msg]:
        slow = getattr(ctx, "slow_cars", None) or set()
        self._slow_said &= slow                 # back up to speed: can be said again next time
        if ahead is None or ahead.index not in slow or ahead.index in self._slow_said or ahead.in_pit:
            return []
        self._slow_said.add(ahead.index)
        return [Msg(self.p("rival_slow_ahead", who=self.who(ahead, "ahead")), PRIO_HIGH, 8, "rival_slow")]

    def _battery(self, s, info, ahead, me, behind, now: float) -> list[Msg]:
        h = cs.hybrid_state(s, info)
        if h is None or me is None or now - self._ers_t < ERS_REPEAT_S:
            return []
        lg = self.rules.lang
        if ahead is not None and me.interval_s is not None and me.interval_s < ERS_CLOSE_S and h.charge > ERS_FULL:
            self._ers_t = now
            return [Msg(self.p("ers_attack", who=self.who(ahead, "ahead"), g=speak_number(me.interval_s, lg)),
                        PRIO_NORMAL, 6, "battery")]
        gap = behind.interval_s if behind is not None else None
        if gap is not None and gap < ERS_DEFEND_S and cs.BATTERY_WARN < h.charge < 0.5:
            self._ers_t = now
            return [Msg(self.p("ers_defend", who=self.who(behind, "behind"), g=speak_number(gap, lg)),
                        PRIO_NORMAL, 6, "battery")]
        return []

    def _update(self, s, info, ahead, me, behind) -> list[Msg]:
        """A short update when the radio has been quiet: the topics take turns, skipping those with no data."""
        lg = self.rules.lang
        topics = []
        if me is not None and ahead is not None and me.interval_s is not None and me.interval_s < CLOSE_GAP_S:
            topics.append(lambda: self.p("drip_ahead", pos=s.position, who=self.who(ahead, "ahead"),
                                         g=speak_number(me.interval_s, lg)))
        gap_b = behind.interval_s if behind is not None else None
        if gap_b is not None and gap_b < CLOSE_GAP_S:
            topics.append(lambda: self.p("drip_behind", who=self.who(behind, "behind"), g=speak_number(gap_b, lg)))
        if not topics and me is not None:
            topics.append(lambda: self.p("drip_alone"))
        to_go = self._to_go
        if self._fuel_per_lap and to_go:
            spare = s.fuel / self._fuel_per_lap - to_go
            if spare >= 1:
                topics.append(lambda: self.p("drip_fuel", n=int(spare)))
        temps = s.tyre_core_temp
        cfg = self.rules.cfg
        front, rear = (temps[0] + temps[1]) / 2, (temps[2] + temps[3]) / 2
        if all(cfg.tyre_temp_lo <= t <= cfg.tyre_temp_hi for t in (front, rear)):
            topics.append(lambda: self.p("drip_tyres", temp=f"{front:.0f}", temp2=f"{rear:.0f}"))
        topics.append(lambda: self.p("drip_push"))
        self._drip_i += 1
        return [Msg(topics[self._drip_i % len(topics)](), PRIO_LOW, 10, "update")]

    # ------------------------------------------------------------- at the end of a lap
    def on_lap(self, lap, laps: list, rows: list | None, race: bool, to_go: int | None,
               position: int | None) -> list[Msg]:
        count = len(lap.sectors_ms) or 3
        self.best_sectors = rs.best_sectors(laps, count)
        self._fuel_per_lap = rs.fuel_per_lap(laps)
        self._to_go = to_go
        if self.level <= QUIET:
            return []
        previous = laps[-2] if len(laps) >= 2 else None
        if rs.is_pit_stop_lap(lap, previous):
            return []
        rows = rows or []
        out: list[Msg] = []
        if race:
            out += self._race_lap(lap, laps, rows, to_go, position)
        elif lap.valid:
            out += self._timesheet(lap, laps, rows)
        if out:
            self.heard()
        return out

    def _race_lap(self, lap, laps, rows, to_go, position) -> list[Msg]:
        out: list[Msg] = []
        lg = self.rules.lang
        stint = rs.current_stint(laps)
        # tyres up to temperature on the first full lap after a stop (the stop lap includes the out-lap)
        if len(stint) == 1 and len(laps) > 1:
            t = lap.tyre_temp_avg
            if min((t[0] + t[1]) / 2, (t[2] + t[3]) / 2) >= self.rules.cfg.tyre_temp_lo:
                out.append(Msg(self.p("tyres_warm"), PRIO_LOW, 15, "tyres_warm"))
        # pace: a lap well off the stint average, or very consistent laps
        clean = [l for l in stint[:-1] if l.valid][-3:]
        if lap.valid and len(clean) >= 2:
            avg = sum(l.lap_time_ms for l in clean) / len(clean) / 1000.0
            drop = lap.lap_time_ms / 1000.0 - avg
            if drop > PACE_DROP_S:
                out.append(Msg(self.p("pace_drop", d=speak_amount(drop, lg)), PRIO_NORMAL, 20, "pace"))
            elif (self.level >= CHATTY and len(clean) == 3 and lap.lap_no - self._consistent_lap >= CONSISTENT_EVERY
                  and max(l.lap_time_ms for l in clean + [lap]) - min(l.lap_time_ms for l in clean + [lap])
                  < CONSISTENT_SPREAD_S * 1000):
                self._consistent_lap = lap.lap_no
                out.append(Msg(self.p("consistent"), PRIO_LOW, 20, "pace"))
        # fastest car on track this lap
        others = [r.last_ms for r in rows if not r.is_player and r.last_ms > 0]
        if (lap.valid and lap.lap_no >= 2 and others and lap.lap_time_ms < min(others)
                and lap.lap_no - self._fastest_lap >= FASTEST_EVERY):
            self._fastest_lap = lap.lap_no
            out.append(Msg(self.p("fastest_on_track"), PRIO_LOW, 20, "pace"))
        # rival's lap time, every few laps
        ahead, _me, behind = neighbours(rows)
        if self.level >= CHATTY and lap.lap_no - self._rival_lap_lap >= RIVAL_LAP_EVERY and lap.lap_no >= 2:
            for r, key, side in ((ahead, "rival_lap", "ahead"), (behind, "rival_lap_behind", "behind")):
                if r is not None and r.last_ms > 0 and not r.in_pit:
                    self._rival_lap_lap = lap.lap_no
                    out.append(Msg(self.p(key, who=self.who(r, side), t=speak_lap_time(r.last_ms, lg)),
                                   PRIO_LOW, 20, "rival_lap"))
                    break
        # milestones
        if position and to_go and not self._half_said and lap.lap_no >= 3 and lap.lap_no >= to_go:
            self._half_said = True
            out.append(Msg(self.p("half_distance", pos=position), PRIO_NORMAL, 25, "milestone"))
        if position and to_go == 2 and not self._home_said:
            self._home_said = True
            out.append(Msg(self.p("bring_home", pos=position), PRIO_NORMAL, 25, "to_go"))
        return out

    def _timesheet(self, lap, laps, rows) -> list[Msg]:
        """Practice and qualifying: where a personal best puts you, from the rivals' best laps."""
        older = [l.lap_time_ms for l in laps if l.valid and l is not lap]
        if older and lap.lap_time_ms >= min(older):
            return []
        others = [r.best_ms for r in rows if not r.is_player and r.best_ms > 0]
        if not others:
            return []
        faster = sum(1 for t in others if t < lap.lap_time_ms)
        if faster == 0:
            return [Msg(self.p("session_top"), PRIO_NORMAL, 20, "timesheet")]
        gap = (lap.lap_time_ms - min(others)) / 1000.0
        return [Msg(self.p("session_pos", pos=faster + 1, g=speak_number(gap, self.rules.lang, 2 if gap < 1 else 1)),
                    PRIO_NORMAL, 20, "timesheet")]
