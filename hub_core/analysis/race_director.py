"""
Automatic race director: decides when to neutralise the race (FCY or VSC) and when to end it, from the cars on
track (CSP app `CarEntry`). The CSP app's race control carries it out (DeltaSuiteRace.lua).

A car stopped on track for a few seconds (not in the pit lane) is an incident; once no car has been stopped for a
while and the neutralisation has lasted long enough, it ends. The director only ends the neutralisations it
started: those called by hand (Delta Suite or CSP buttons) are ended by hand.

Its own stopped-car tracking, not TrackWatch's zones: those are cleared when many cars are slow, which is exactly
what happens under FCY and VSC.
"""

from __future__ import annotations

from dataclasses import dataclass

MODES = ("off", "fcy", "vsc")

STOPPED_KMH = 8.0            # below this a car on track is stopped
MOVING_KMH = 30.0            # above this it has moved off again
STOP_CONFIRM_S = 8.0         # stopped this long → incident (a spin that rejoins does not neutralise)
CLEAR_S = 12.0               # no stopped car for this long → the track is clear
MIN_ACTIVE_S = 40.0          # a neutralisation lasts at least this long
REQUEST_TIMEOUT_S = 5.0      # the app did not start it (not available): give up
COOLDOWN_S = 60.0            # after green, no new automatic neutralisation for a while
CROWD_FRACTION = 0.4         # this share of cars stopped: race start or red flag, not an incident


@dataclass(frozen=True)
class Decision:
    action: str              # "fcy", "vsc" or "end"
    reason: str
    car: int = -1            # car that caused it (for "fcy"/"vsc")


class RaceDirector:
    def __init__(self, mode: str = "off"):
        self.mode = mode if mode in MODES else "off"
        self.reset()

    def reset(self) -> None:
        self._stopped_since: dict[int, float] = {}    # car → time it stopped
        self._incident_cars: set[int] = set()
        self._clear_since: float | None = None
        self._active_since: float | None = None       # neutralisation started by us
        self._waiting: str | None = None              # request sent, not yet seen active
        self._green_t = -1e9

    def stopped_cars(self, now: float) -> list[int]:
        """Cars stopped on track for at least STOP_CONFIRM_S."""
        return sorted(i for i, t in self._stopped_since.items() if now - t >= STOP_CONFIRM_S)

    def update(self, cars, now: float, race: bool, rc_active: bool, race_laps: int = 0) -> Decision | None:
        """One step (~10 Hz). rc_active: a neutralisation is running in the app (by anyone)."""
        self._track_stopped(cars, now, race_laps)
        if self._waiting and rc_active:
            self._waiting = None
        elif self._waiting and now - self._active_since > REQUEST_TIMEOUT_S:
            self._waiting, self._active_since = None, None
            self._green_t = now
        if self._active_since is not None and not rc_active and self._waiting is None:
            self._active_since = None              # ended by hand, or the session restarted
            self._green_t = now
        if self.mode == "off" or not race:
            return None

        stopped = self.stopped_cars(now)
        if self._active_since is not None:
            self._incident_cars |= set(stopped)
            if stopped:
                self._clear_since = None
                return None
            if self._clear_since is None:
                self._clear_since = now
            if now - self._clear_since >= CLEAR_S and now - self._active_since >= MIN_ACTIVE_S:
                self._active_since, self._clear_since = None, None
                self._incident_cars.clear()
                self._green_t = now
                return Decision("end", "track clear")
            return None

        if rc_active or self._waiting or now - self._green_t < COOLDOWN_S or not stopped:
            return None
        self._active_since, self._clear_since, self._waiting = now, None, self.mode
        self._incident_cars = set(stopped)
        return Decision(self.mode, "car stopped on track", stopped[0])

    def _track_stopped(self, cars, now: float, race_laps: int) -> None:
        on_track = [c for c in cars if c.connected and not c.in_pitlane and not c.in_pit
                    and not (race_laps and c.lap_count >= race_laps)]
        seen = set()
        stopped_now = [c for c in on_track if c.speed_kmh < STOPPED_KMH]
        if on_track and len(stopped_now) > CROWD_FRACTION * len(on_track):
            self._stopped_since.clear()           # grid, race start, everyone parked: not incidents
            return
        for c in on_track:
            seen.add(c.index)
            if c.speed_kmh < STOPPED_KMH:
                self._stopped_since.setdefault(c.index, now)
            elif c.speed_kmh > MOVING_KMH:
                self._stopped_since.pop(c.index, None)
        for i in list(self._stopped_since):
            if i not in seen:                     # into the pits, retired, disconnected
                del self._stopped_since[i]
