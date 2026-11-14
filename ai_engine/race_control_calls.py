"""
Radio calls for the race control of the CSP app (FCY, VSC, safety car): countdown, neutralisation, ending, green,
and a warning when the driver is too fast (negative VSC delta, over the FCY limit) or overtakes under the SC. They follow the state changes of
hub_core.ac.race_link.RaceControlState, read about ten times per second.
"""

from __future__ import annotations

from hub_core.ac import race_link as rl
from ai_engine.radio import Msg
from ai_engine.voice import PRIO_HIGH, PRIO_URGENT

OVER_CONFIRM_S = 1.5         # over the limit this long before the warning (a moment over is not worth a call)
OVER_REPEAT_S = 10.0         # then again at most every few seconds while it lasts


class RaceControlCalls:
    def __init__(self, rules):
        self.rules = rules          # RadioRules: language and phrase picking
        self.reset()

    def reset(self) -> None:
        self._state: int | None = None
        self._over_since: float | None = None
        self._over_said = -1e9

    def p(self, key: str, **kw) -> str:
        return self.rules._p(key, **kw)

    def update(self, rc: rl.RaceControlState | None, now: float, fcy_kmh: float, countdown_s: float) -> list[Msg]:
        if rc is None or not rc.available:
            self._state = None
            return []
        out: list[Msg] = []
        prev, self._state = self._state, rc.state
        kmh = int(round(rc.limit_kmh or fcy_kmh))
        if prev is not None and rc.state != prev:
            vsc = rc.mode == rl.MODE_VSC
            if rc.state == rl.PENDING:
                out.append(Msg(self.p("rc_fcy_countdown", n=int(round(countdown_s)), kmh=int(round(fcy_kmh))),
                               PRIO_URGENT, 4, "race_control"))
            elif rc.state == rl.ACTIVE:
                if rc.mode == rl.MODE_SC:
                    text = self.p("rc_sc_now")
                else:
                    text = self.p("rc_vsc_now") if vsc else self.p("rc_fcy_now", kmh=kmh)
                out.append(Msg(text, PRIO_URGENT, 5, "race_control"))
            elif rc.state == rl.ENDING:
                key = "rc_sc_in" if rc.mode == rl.MODE_SC else "rc_vsc_ending" if vsc else "rc_fcy_ending"
                out.append(Msg(self.p(key), PRIO_URGENT, 5, "race_control"))
            elif rc.state == rl.GREEN_FLASH:
                out.append(Msg(self.p("rc_green"), PRIO_URGENT, 4, "race_control"))
            elif rc.state == rl.GREEN and prev == rl.PENDING:
                out.append(Msg(self.p("rc_cancelled"), PRIO_HIGH, 5, "race_control"))

        if rc.over_limit and rc.state in (rl.ACTIVE, rl.ENDING):
            if self._over_since is None:
                self._over_since = now
            if now - self._over_since >= OVER_CONFIRM_S and now - self._over_said >= OVER_REPEAT_S:
                self._over_said = now
                if rc.mode == rl.MODE_SC:
                    text = self.p("rc_sc_overtake")
                elif rc.mode == rl.MODE_VSC:
                    text = self.p("rc_delta_negative")
                else:
                    text = self.p("rc_over_limit", kmh=kmh)
                out.append(Msg(text, PRIO_URGENT, 3, "race_control_over"))
        else:
            self._over_since = None
        return out
