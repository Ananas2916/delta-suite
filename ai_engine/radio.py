"""
Radio immediata: regole locali che parlano senza modello AI (latenza < 1 s, zero token).

Giro e delta, carburante, gomme fuori finestra (una volta per stint), distacchi, bandiere, batteria
delle ibride.
Il ragionamento vero (setup, strategia, "dove perdo tempo") lo fa l'agente, a richiesta:
come l'ingegnere dei giochi di F1, più un'AI dove lo script non arriva.
La lingua è quella della voce scelta (ai_engine.lang).
"""

from __future__ import annotations

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
    tyre_temp_lo: float = 75.0
    tyre_temp_hi: float = 100.0
    tyre_press_lo: float = 25.5     # psi a caldo
    tyre_press_hi: float = 28.5


_FLAGS = {
    ACFlag.YELLOW: ("flag_yellow", PRIO_URGENT),
    ACFlag.BLUE: ("flag_blue", PRIO_HIGH),
    ACFlag.CHECKERED: ("flag_checkered", PRIO_HIGH),
    ACFlag.PENALTY: ("flag_penalty", PRIO_HIGH),
    ACFlag.BLACK: ("flag_black", PRIO_URGENT),
}


class RadioRules:
    def __init__(self, cfg: RadioConfig | None = None, lang: Language | None = None):
        self.cfg = cfg or RadioConfig()
        self.lang = lang or LANGUAGES["it"]
        self.reset()

    def reset(self):
        self._fuel_left_prev: float | None = None
        self._stint_first: int | None = None
        self._tyre_said: set[str] = set()
        self._flag = ACFlag.NONE
        self._battery_said: set[str] = set()
        self._lap_energy_said = False

    def _p(self, key: str, **kw) -> str:
        return self.lang.phrases[key].format(**kw)

    # ------------------------------------------------------------- per giro
    def on_lap(self, lap: LapData, laps: list[LapData], neighbours=None, race: bool = False,
               to_go: int | None = None) -> list[Msg]:
        """`laps` sono i giri della sessione, con `lap` (appena completato) in fondo; `to_go` i giri che mancano
        alla fine della gara (dal leader, compreso quello appena iniziato)."""
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
                out.append(Msg(self._p("best_lap", t=t, gain=gain), PRIO_HIGH, 25, "lap"))
            else:
                delta = speak_delta((lap.lap_time_ms - min(older)) / 1000, lg)
                out.append(Msg(self._p("lap", t=t, delta=delta), PRIO_NORMAL, 25, "lap"))
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

        if c.tyres:
            out += self._tyre_messages(laps)

        if c.gaps and race and neighbours:
            ahead, me, behind = neighbours
            parts = []
            if ahead is not None and me is not None and me.interval_s is not None:
                parts.append(self._p("ahead", g=speak_number(me.interval_s, lg)))
            if behind is not None and behind.interval_s is not None:
                parts.append(self._p("behind", g=speak_number(behind.interval_s, lg)))
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
        if len(stint) < 2:          # primo giro di stint: gomme ancora in temperatura
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

    # --------------------------------------------------------- per campione
    def on_sample(self, s, info: dict | None = None) -> list[Msg]:
        out = self._flag_messages(s) if self.cfg.flags else []
        if self.cfg.hybrid:
            out += self._hybrid_messages(s, info)
        return out

    def _flag_messages(self, s) -> list[Msg]:
        try:
            flag = ACFlag(s.flag)
        except ValueError:
            return []
        if flag == self._flag:
            return []
        self._flag = flag
        if flag in _FLAGS:
            key, prio = _FLAGS[flag]
            return [Msg(self._p(key), prio, 10, "flag")]
        return []

    def _hybrid_messages(self, s, info: dict | None) -> list[Msg]:
        """Batteria al 20% e scarica: una volta, finché non si ricarica. Energia del giro finita: una volta per
        stint (con un limite per giro succede quasi a ogni giro, basta saperlo)."""
        h = cs.hybrid_state(s, info)
        if h is None:
            return []
        if s.is_in_pit:
            self._lap_energy_said = False
            return []
        out = []
        if h.charge >= cs.BATTERY_WARN + 0.15:
            self._battery_said.clear()          # ricaricata: si può riavvisare
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
