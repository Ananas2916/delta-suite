"""
AI Race Engineer: riassume lo stint e chiede a Claude strategia e setup.

La chiave API si prende da ANTHROPIC_API_KEY (o profilo `ant auth login`) oppure
viene passata esplicitamente dalla UI.
"""

from __future__ import annotations

from collections.abc import Callable

import anthropic

from hub_core.analysis import race_strategy as rs
from hub_core.analysis.lap_recorder import LapData

MODEL = "claude-opus-5-5"

SYSTEM_PROMPT = """Sei l'ingegnere di pista di un pilota che corre in Assetto Corsa (simulatore, fisica \
realistica). Ricevi il riepilogo dati di uno stint: tempi giro, settori, consumi, temperature, \
pressioni e usura gomme, temperature freni, previsione di degrado e piano carburante calcolati \
dal software di strategia.

Come lavori:
- Rispondi in italiano, con il tono asciutto di un ingegnere al muretto.
- Basa ogni raccomandazione sui numeri del riepilogo e cita il dato che la giustifica.
- Quando suggerisci modifiche di setup (pressioni a freddo, campanatura, ali, barre, freni, \
ripartizione), indica valore attuale stimato, valore proposto e l'effetto atteso.
- Per le gomme ragiona su finestre di pressione a caldo e su squilibri anteriore/posteriore e \
sinistra/destra.
- Per la strategia indica lunghezza stint, giro di sosta e carburante da imbarcare.
- Se i dati non bastano per una conclusione, dillo e indica cosa raccogliere nel prossimo run.
- Chiudi con una lista breve di azioni in ordine di priorità.

Le domande possono iniziare con modalità e lingua, es. "[RADIO] [English]": rispondi sempre in \nquella lingua. Modalità:
[RADIO] il pilota sta guidando e ti sente in cuffia: al massimo due frasi brevi, parlate, senza elenchi, \
simboli o markdown, numeri arrotondati. In questo caso ignora la regola della lista finale.
[ANALISI] il pilota è fermo e legge: risposta completa come sopra."""

WHEELS = ("AS", "AD", "PS", "PD")   # anteriore sx/dx, posteriore sx/dx


def build_stint_summary(info: dict, laps: list[LapData], fuel_now: float | None = None,
                        race_laps_left: int | None = None, pit_loss_s: float = 25.0) -> str:
    """Riepilogo testuale compatto dello stint, pensato per il modello."""
    lines = [
        f"Auto: {info.get('car', '?')} | Pista: {info.get('track', '?')} "
        f"({info.get('track_length', 0):.0f} m) | Sorgente: {info.get('source', '?')}",
        f"Serbatoio max: {info.get('max_fuel', 0):.0f} L",
    ]
    if not laps:
        lines.append("Nessun giro completato in questo stint.")
        return "\n".join(lines)

    lines.append("")
    lines.append("Giro | Tempo | S1 | S2 | S3 | Valido | Carb. usato L | T gomme medie °C (AS/AD/PS/PD) | "
                 "P gomme medie psi | Usura fine giro | T freni max °C | Vmax km/h")
    for lap in laps:
        sect = [rs.fmt_ms(s) for s in lap.sectors_ms] + ["-"] * (3 - len(lap.sectors_ms))
        lines.append(
            f"{lap.lap_no} | {rs.fmt_ms(lap.lap_time_ms)} | {' | '.join(sect[:3])} | "
            f"{'si' if lap.valid else 'no'} | {lap.fuel_used:.2f} | "
            f"{'/'.join(f'{v:.0f}' for v in lap.tyre_temp_avg)} | "
            f"{'/'.join(f'{v:.1f}' for v in lap.tyre_press_avg)} | "
            f"{'/'.join(f'{v:.1f}' for v in lap.tyre_wear_end)} | "
            f"{'/'.join(f'{v:.0f}' for v in lap.brake_temp_max)} | {lap.max_speed:.0f}"
        )

    valid = [l for l in laps if l.valid]
    lines.append("")
    if valid:
        best = min(valid, key=lambda l: l.lap_time_ms)
        lines.append(f"Miglior giro valido: {rs.fmt_ms(best.lap_time_ms)} (giro {best.lap_no})")
        theo = rs.theoretical_best(laps)
        if theo:
            lines.append(f"Giro ideale (somma migliori settori): {rs.fmt_ms(theo)}")
    fpl = rs.fuel_per_lap(laps)
    if fpl:
        lines.append(f"Consumo medio: {fpl:.2f} L/giro")
        if fuel_now is not None and race_laps_left:
            plan = rs.fuel_plan(fuel_now, fpl, race_laps_left, info.get("max_fuel", 0) or 100.0,
                                laps[-1].lap_no)
            lines.append(
                f"Carburante a bordo: {fuel_now:.1f} L, giri gara rimanenti: {race_laps_left}, "
                f"autonomia: {plan.laps_on_current_fuel:.1f} giri, da aggiungere: {plan.fuel_to_add:.1f} L, "
                f"soste: {plan.stops_needed}, finestra pit: {plan.pit_window}"
            )
    stint = rs.current_stint(laps)
    fc = rs.forecast_degradation(stint)
    if fc:
        lines.append(
            f"Degrado stimato (corretto per carburante): {fc.deg_per_lap:+.3f} s/giro a fine stint; "
            f"previsione prossimi giri: {', '.join(rs.fmt_ms(t * 1000) for t in fc.forecast_times[:8])}"
        )
        if fc.cliff_lap:
            lines.append(f"Crollo previsto (>1.5 s dal migliore) al giro di stint {fc.cliff_lap}")
        if race_laps_left:
            opt = rs.optimal_pit_lap(fc, race_laps_left, pit_loss_s)
            lines.append(f"Sosta ottimale per gomme (perdita pit {pit_loss_s:.0f} s): "
                         f"{'giro di stint ' + str(opt) if opt else 'nessuna sosta conveniente'}")
    return "\n".join(lines)


class RaceEngineer:
    """Conversazione multi-turno con Claude; ogni risposta arriva in streaming."""

    def __init__(self, api_key: str | None = None):
        self.client = anthropic.Anthropic(api_key=api_key) if api_key else anthropic.Anthropic()
        self.history: list[dict] = []

    def reset(self):
        self.history = []

    def ask(self, question: str, summary: str | None = None,
            on_text: Callable[[str], None] | None = None) -> str:
        content = question if not summary else f"<dati_stint>\n{summary}\n</dati_stint>\n\n{question}"
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
            self.history.pop()   # la domanda non ha avuto risposta: non resta nello storico
            raise

        # Il contenuto completo (incluso il thinking) torna nello storico così com'è.
        self.history.append({"role": "assistant", "content": final.content})
        if final.stop_reason == "refusal":
            return "La richiesta è stata rifiutata dal modello. Riformula la domanda."
        return "".join(b.text for b in final.content if b.type == "text")
