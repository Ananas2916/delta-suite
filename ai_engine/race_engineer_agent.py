"""
AI Race Engineer: summarises the stint and asks Claude for strategy and setup.

The API key comes from ANTHROPIC_API_KEY (or the `ant auth login` profile) or
is passed explicitly by the UI.
"""

from __future__ import annotations

from collections.abc import Callable

import anthropic

from hub_core.analysis import race_strategy as rs
from hub_core.analysis.lap_recorder import LapData

MODEL = "claude-opus-5-5"

SYSTEM_PROMPT = """You are the race engineer of a driver racing in Assetto Corsa (a simulator with realistic \
physics). You receive a data summary of a stint: lap times, sectors, fuel use, tyre temperatures, \
pressures and wear, brake temperatures, degradation forecast and fuel plan computed by the \
strategy software.

How you work:
- Use the dry tone of an engineer on the pit wall.
- Base every recommendation on the numbers in the summary and quote the data behind it.
- When you suggest setup changes (cold pressures, camber, wings, anti-roll bars, brakes, \
balance), give the estimated current value, the proposed value and the expected effect.
- For tyres, reason about hot pressure windows and front/rear and left/right imbalances.
- For strategy, give stint length, pit lap and fuel to add.
- If the data is not enough for a conclusion, say so and say what to collect in the next run.
- Finish with a short list of actions in order of priority.

Questions may start with mode and language, e.g. "[RADIO] [English]": always reply in \
that language. Modes:
[RADIO] the driver is driving and hears you in the headset: two short spoken sentences at most, no lists, \
symbols or markdown, rounded numbers. In this case skip the final list rule.
[ANALYSIS] the driver is stopped and reading: a complete answer as above."""

WHEELS = ("FL", "FR", "RL", "RR")


def build_stint_summary(info: dict, laps: list[LapData], fuel_now: float | None = None,
                        race_laps_left: int | None = None, pit_loss_s: float = 25.0) -> str:
    """Compact text summary of the stint, meant for the model."""
    lines = [
        f"Car: {info.get('car', '?')} | Track: {info.get('track', '?')} "
        f"({info.get('track_length', 0):.0f} m) | Source: {info.get('source', '?')}",
        f"Max tank: {info.get('max_fuel', 0):.0f} L",
    ]
    if not laps:
        lines.append("No lap completed in this stint.")
        return "\n".join(lines)

    lines.append("")
    lines.append("Lap | Time | S1 | S2 | S3 | Valid | Fuel used L | Avg tyre T °C (FL/FR/RL/RR) | "
                 "Avg tyre P psi | Wear at lap end | Max brake T °C | Vmax km/h")
    for lap in laps:
        sect = [rs.fmt_ms(s) for s in lap.sectors_ms] + ["-"] * (3 - len(lap.sectors_ms))
        lines.append(
            f"{lap.lap_no} | {rs.fmt_ms(lap.lap_time_ms)} | {' | '.join(sect[:3])} | "
            f"{'yes' if lap.valid else 'no'} | {lap.fuel_used:.2f} | "
            f"{'/'.join(f'{v:.0f}' for v in lap.tyre_temp_avg)} | "
            f"{'/'.join(f'{v:.1f}' for v in lap.tyre_press_avg)} | "
            f"{'/'.join(f'{v:.1f}' for v in lap.tyre_wear_end)} | "
            f"{'/'.join(f'{v:.0f}' for v in lap.brake_temp_max)} | {lap.max_speed:.0f}"
        )

    valid = [l for l in laps if l.valid]
    lines.append("")
    if valid:
        best = min(valid, key=lambda l: l.lap_time_ms)
        lines.append(f"Best valid lap: {rs.fmt_ms(best.lap_time_ms)} (lap {best.lap_no})")
        theo = rs.theoretical_best(laps)
        if theo:
            lines.append(f"Ideal lap (sum of best sectors): {rs.fmt_ms(theo)}")
    fpl = rs.fuel_per_lap(laps)
    if fpl:
        lines.append(f"Average fuel use: {fpl:.2f} L/lap")
        if fuel_now is not None and race_laps_left:
            plan = rs.fuel_plan(fuel_now, fpl, race_laps_left, info.get("max_fuel", 0) or 100.0,
                                laps[-1].lap_no)
            lines.append(
                f"Fuel on board: {fuel_now:.1f} L, race laps left: {race_laps_left}, "
                f"range: {plan.laps_on_current_fuel:.1f} laps, to add: {plan.fuel_to_add:.1f} L, "
                f"stops: {plan.stops_needed}, pit window: {plan.pit_window}"
            )
    stint = rs.current_stint(laps)
    fc = rs.forecast_degradation(stint)
    if fc:
        lines.append(
            f"Estimated degradation (fuel corrected): {fc.deg_per_lap:+.3f} s/lap at end of stint; "
            f"forecast for the next laps: {', '.join(rs.fmt_ms(t * 1000) for t in fc.forecast_times[:8])}"
        )
        if fc.cliff_lap:
            lines.append(f"Expected drop-off (>1.5 s from best) on stint lap {fc.cliff_lap}")
        if race_laps_left:
            opt = rs.optimal_pit_lap(fc, race_laps_left, pit_loss_s)
            lines.append(f"Optimal tyre stop (pit loss {pit_loss_s:.0f} s): "
                         f"{'stint lap ' + str(opt) if opt else 'no worthwhile stop'}")
    return "\n".join(lines)


class RaceEngineer:
    """Multi-turn conversation with Claude; every answer is streamed."""

    def __init__(self, api_key: str | None = None):
        self.client = anthropic.Anthropic(api_key=api_key) if api_key else anthropic.Anthropic()
        self.history: list[dict] = []

    def reset(self):
        self.history = []

    def ask(self, question: str, summary: str | None = None,
            on_text: Callable[[str], None] | None = None) -> str:
        content = question if not summary else f"<stint_data>\n{summary}\n</stint_data>\n\n{question}"
        self.history.append({"role": "user", "content": content})
        try:
            with self.client.beta.messages.stream(
                model=MODEL,
                max_tokens=32000,
                system=SYSTEM_PROMPT,
                messages=self.history,
                thinking={"type": "adaptive"},
                output_config={"effort": "high"},
                betas=["server-side-fallback-2026-07-01"],
                fallbacks="default",
            ) as stream:
                for text in stream.text_stream:
                    if on_text:
                        on_text(text)
                final = stream.get_final_message()
        except Exception:
            self.history.pop()   # the question got no answer: drop it from the history
            raise

        # The full content (thinking included) goes back into the history as is.
        self.history.append({"role": "assistant", "content": final.content})
        if final.stop_reason == "refusal":
            return "The model declined the request. Rephrase the question."
        return "".join(b.text for b in final.content if b.type == "text")
