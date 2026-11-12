"""
Instant radio: local rules that speak without an AI model (latency < 1 s, zero tokens).

Lap and delta, fuel, tyres out of the window (once per stint), gaps with their trend, flags,
hybrid battery; the F1-game-style race calls (positions, rivals, yellows, damage, race end) are in
ai_engine.race_calls. Phrases with several variants ("a|b") change on every call.
The real reasoning (setup, strategy, "where am I losing time") is done by the agent, on request:
like the engineer in F1 games, plus an AI where the script cannot reach.
The language is the one of the chosen voice (ai_engine.lang).
"""

from __future__ import annotations

import random
from dataclasses import dataclass

from hub_core.analysis import car_status as cs
from hub_core.analysis import race_strategy as rs
from hub_core.analysis.lap_recorder import LapData
from hub_core.model import ACFlag
from ai_engine.lang import LANGUAGES, Language, same_time, speak_delta, speak_lap_time, speak_number
from ai_engine.voice import PRIO_HIGH, PRIO_LOW, PRIO_NORMAL, PRIO_URGENT


@dataclass
class Msg:
    text: str
    priority: int = PRIO_NORMAL
    ttl_s: float = 20.0
    key: str | None = None


@dataclass
class RadioConfig:
    lap_times: bool = True
    fuel: bool = True
    tyres: bool = True
    gaps: bool = True
    flags: bool = True
    hybrid: bool = True
    positions: bool = True          # first lap, positions gained/lost, fastest lap, finish
    rivals: bool = True             # close car ahead/behind, rivals in the pits
    car: bool = True                # punctures, damage, worn tyres, limiter
    tyre_temp_lo: float = 75.0
    tyre_temp_hi: float = 100.0
    tyre_press_lo: float = 25.5     # hot psi
    tyre_press_hi: float = 28.5


_FLAGS = {
    ACFlag.YELLOW: ("flag_yellow", PRIO_URGENT),
    ACFlag.BLUE: ("flag_blue", PRIO_HIGH),
    ACFlag.CHECKERED: ("flag_checkered", PRIO_HIGH),
    ACFlag.PENALTY: ("flag_penalty", PRIO_HIGH),
    ACFlag.BLACK: ("flag_black", PRIO_URGENT),
}


class RadioRules:
    def __init__(self, cfg: RadioConfig | None = None, lang: Language | None = None, seed: int | None = None):
        from ai_engine.race_calls import RaceCalls      # here: race_calls uses this module's Msg
        self.cfg = cfg or RadioConfig()
        self.lang = lang or LANGUAGES["en-us"]
        self.rng = random.Random(seed)
        self.race = RaceCalls(self)
        self.reset()

    def reset(self):
        self._fuel_left_prev: float | None = None
        self._stint_first: int | None = None
        self._tyre_said: set[str] = set()
        self._flag = ACFlag.NONE
        self._battery_said: set[str] = set()
        self._lap_energy_said = False
        self.race.reset()

    def _p(self, key: str, **kw) -> str:
        """Phrase in the voice's language; if it has variants ("a|b|c") one is picked."""
        text = self.lang.phrases[key]
        if "|" in text:
            text = self.rng.choice(text.split("|"))
        return text.format(**kw)

    # ------------------------------------------------------------- per lap
    def on_lap(self, lap: LapData, laps: list[LapData], neighbours=None, race: bool = False,
               to_go: int | None = None, position: int | None = None, field_best_ms: int | None = None) -> list[Msg]:
        """`laps` are the session laps, with `lap` (just completed) last; `to_go` the laps left until the end
        of the race (from the leader, including the one just started); `field_best_ms` the rivals' best lap,
        for the race's fastest lap."""
        out: list[Msg] = []
        c, lg = self.cfg, self.lang
        previous = laps[-2] if len(laps) >= 2 else None
        pit_lap = rs.is_pit_stop_lap(lap, previous)

        if c.lap_times and not pit_lap:
            older = [l.lap_time_ms for l in laps if l.valid and l is not lap]
            t = speak_lap_time(lap.lap_time_ms, lg)
            if not lap.valid:
                out.append(Msg(self._p("lap_invalid", t=t), PRIO_LOW, 25, "lap"))
            elif not older or lap.lap_time_ms < min(older):
                delta = speak_delta((lap.lap_time_ms - min(older)) / 1000, lg) if older else same_time(lg)
                gain = f", {delta}" if delta != same_time(lg) else ""
                text = self._p("best_lap", t=t, gain=gain)
                if c.positions and race and field_best_ms and lap.lap_time_ms < field_best_ms:
                    text += " " + self._p("fastest_lap")
                out.append(Msg(text, PRIO_HIGH, 25, "lap"))
            else:
                delta = speak_delta((lap.lap_time_ms - min(older)) / 1000, lg)
                out.append(Msg(self._p("lap", t=t, delta=delta), PRIO_NORMAL, 25, "lap"))
        if c.positions and race and lap.lap_no == 1 and position:
            out.append(self.race.lap1(position))
        if c.lap_times and race and to_go == 1:
            out.append(Msg(self._p("last_lap"), PRIO_HIGH, 30, "to_go"))
        elif c.lap_times and race and to_go in (10, 5, 3):
            out.append(Msg(self._p("laps_to_go", n=to_go), PRIO_NORMAL, 30, "to_go"))

        if c.fuel:
            fpl = rs.fuel_per_lap(laps)
            if fpl:
                left = lap.fuel_end / fpl
                prev = self._fuel_left_prev
                if left <= 1.2 and (prev is None or prev > 1.2):
                    out.append(Msg(self._p("fuel_box"), PRIO_URGENT, 60, "fuel"))
                else:
                    for th in (5, 3, 2):
                        if left <= th + 0.2 and (prev is None or prev > th + 0.2):
                            out.append(Msg(self._p("fuel_n", n=th), PRIO_HIGH, 40, "fuel"))
                            break
                self._fuel_left_prev = left
                if race and to_go:
                    out += self.race.fuel(lap.fuel_end, fpl, to_go)

        if c.tyres:
            out += self._tyre_messages(laps)

        if c.gaps and race and neighbours:
            parts = self.race.gap_parts(*neighbours)
            if parts:
                out.append(Msg(self._p("gaps", parts=", ".join(parts)), PRIO_LOW, 20, "gap"))
        return out

    def _tyre_messages(self, laps: list[LapData]) -> list[Msg]:
        stint = rs.current_stint(laps)
        if not stint:
            return []
        if self._stint_first != stint[0].lap_no:
            self._stint_first = stint[0].lap_no
            self._tyre_said.clear()
        if len(stint) < 2:          # first stint lap: tyres still warming up
            return []
        c, last, lg = self.cfg, stint[-1], self.lang
        out = []
        temps = last.tyre_temp_avg
        for axle_key, idx in (("front", (0, 1)), ("rear", (2, 3))):
            axle = lg.phrases[axle_key]
            t = sum(temps[i] for i in idx) / 2
            if t < c.tyre_temp_lo and f"{axle_key}-cold" not in self._tyre_said:
                self._tyre_said.add(f"{axle_key}-cold")
                out.append(Msg(self._p("cold", axle=axle, temp=f"{t:.0f}"), PRIO_NORMAL, 60))
            elif t > c.tyre_temp_hi and f"{axle_key}-hot" not in self._tyre_said:
                self._tyre_said.add(f"{axle_key}-hot")
                out.append(Msg(self._p("hot", axle=axle, temp=f"{t:.0f}"), PRIO_HIGH, 60))
        wheels = lg.phrases["wheels"]
        for i, p in enumerate(last.tyre_press_avg):
            if p > c.tyre_press_hi and f"p{i}-hi" not in self._tyre_said:
                self._tyre_said.add(f"p{i}-hi")
                out.append(Msg(self._p("press_hi", wheel=wheels[i], p=speak_number(p, lg)), PRIO_LOW, 60))
            elif p < c.tyre_press_lo and f"p{i}-lo" not in self._tyre_said:
                self._tyre_said.add(f"p{i}-lo")
                out.append(Msg(self._p("press_lo", wheel=wheels[i], p=speak_number(p, lg)), PRIO_LOW, 60))
        return out

    # --------------------------------------------------------- per sample
    def on_sample(self, s, info: dict | None = None, ctx=None) -> list[Msg]:
        """`ctx` (RaceContext) carries standings, yellows and laps to go: without it, only flags and battery."""
        out = self._flag_messages(s, ctx) if self.cfg.flags else []
        if self.cfg.hybrid:
            out += self._hybrid_messages(s, info)
        if ctx is not None:
            out += self.race.on_sample(s, info, ctx)
        return out

    def _flag_messages(self, s, ctx=None) -> list[Msg]:
        try:
            flag = ACFlag(s.flag)
        except ValueError:
            return []
        if flag == self._flag:
            return []
        self._flag = flag
        if flag == ACFlag.YELLOW and ctx is not None and ctx.cars_known:
            return []           # with the cars known, race_calls calls the yellow, with the distance
        if flag == ACFlag.CHECKERED and ctx is not None and ctx.race and s.position > 0:
            key = "finish_win" if s.position == 1 else "finish_podium" if s.position <= 3 else "finish"
            return [Msg(self._p(key, pos=s.position), PRIO_HIGH, 15, "flag")]
        if flag in _FLAGS:
            key, prio = _FLAGS[flag]
            return [Msg(self._p(key), prio, 10, "flag")]
        return []

    def _hybrid_messages(self, s, info: dict | None) -> list[Msg]:
        """Battery at 20% and empty: once, until it recharges. Lap energy used up: once per
        stint (with a per-lap limit it happens almost every lap, knowing once is enough)."""
        h = cs.hybrid_state(s, info)
        if h is None:
            return []
        if s.is_in_pit:
            self._lap_energy_said = False
            return []
        out = []
        if h.charge >= cs.BATTERY_WARN + 0.15:
            self._battery_said.clear()          # recharged: may warn again
        if h.charge < cs.BATTERY_CRIT and "empty" not in self._battery_said:
            self._battery_said.update(("empty", "low"))
            out.append(Msg(self._p("battery_empty"), PRIO_HIGH, 15, "battery"))
        elif h.charge < cs.BATTERY_WARN and "low" not in self._battery_said:
            self._battery_said.add("low")
            out.append(Msg(self._p("battery_low", n=round(h.charge * 100)), PRIO_NORMAL, 15, "battery"))
        if h.lap_left_kj is not None and h.lap_left_kj <= 0.5 and not self._lap_energy_said:
            self._lap_energy_said = True
            out.append(Msg(self._p("lap_energy"), PRIO_LOW, 8, "lap_energy"))
        return out
