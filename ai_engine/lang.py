"""
Radio language: the voice decides it.

Kokoro voices declare their language in the first letter of the name (im_nicola = Italian, male).
The voice determines Kokoro's pronunciation, the radio phrases, the language the agent
answers in and the transcription language (Whisper).
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ai_engine.phrases_chatter import chatter_phrases_for
from ai_engine.phrases_race import phrases_for


@dataclass(frozen=True)
class Language:
    code: str           # short code, also for Whisper
    name: str           # name in the language itself (also goes in the agent prompt)
    kokoro: str         # code for kokoro-onnx / espeak
    phrases: dict = field(compare=False, hash=False, default_factory=dict)


# ----------------------------------------------------------------- phrases

_IT = {
    "lap_invalid": "{t}, giro non valido.",
    "best_lap": "Giro migliore! {t}{gain}.",
    "lap": "{t}, {delta}.",
    "laps_to_go": "Mancano {n} giri.", "last_lap": "Ultimo giro, spingi.",
    "fuel_box": "Box, box. Carburante per un giro.",
    "fuel_n": "Carburante per {n} giri.",
    "front": "Anteriori", "rear": "Posteriori",
    "cold": "{axle} fredde, {temp} gradi.",
    "hot": "{axle} surriscaldate, {temp} gradi. Gestisci.",
    "wheels": ("anteriore sinistra", "anteriore destra", "posteriore sinistra", "posteriore destra"),
    "press_hi": "Pressione alta {wheel}, {p}.",
    "press_lo": "Pressione bassa {wheel}, {p}.",
    "gaps": "Distacchi: {parts}.", "ahead": "davanti {g}", "behind": "dietro {g}",
    "flag_yellow": "Bandiera gialla.", "flag_blue": "Bandiera blu, fai passare.",
    "flag_checkered": "Bandiera a scacchi. Bel lavoro, rientra ai box.", "flag_penalty": "Penalità.",
    "flag_black": "Bandiera nera.",
    "battery_low": "Batteria al {n} per cento.", "battery_empty": "Batteria scarica.",
    "lap_energy": "Energia elettrica del giro finita.",
    "proposal": "Proposta: {what}. {reason} Conferma con il tasto.",
    "at_box": "Confermato, la applico ai box.", "discarded": "Ricevuto, lasciamo così.",
    "done": "Fatto, {what}.", "failed": "Non riesco: {msg}.",
    "busy": "Un attimo, sto ancora rispondendo.", "agent_error": "Problema di collegamento con l'ingegnere.",
    "stt_error": "Non ti ho sentito, ripeti.", "radio_check": "Radio check. Mi senti? Gomme in temperatura, spingi.",
    "kinds": {"brake_bias": "bias freni", "abs": "ABS", "tc": "TC", "engine_brake": "freno motore"},
    "to": "{what} a {v}",
    "stt_prompt": "Radio di squadra in gara: box, gomme, pressioni, bias freni, ABS, TC, freno motore, "
                  "carburante, giro, settore, sottosterzo, sovrasterzo, distacco.",
}

_EN = {
    "lap_invalid": "{t}, lap invalid.",
    "best_lap": "Fastest lap! {t}{gain}.",
    "lap": "{t}, {delta}.",
    "laps_to_go": "{n} laps to go.", "last_lap": "Last lap, push.",
    "fuel_box": "Box, box. Fuel for one lap.",
    "fuel_n": "Fuel for {n} laps.",
    "front": "Fronts", "rear": "Rears",
    "cold": "{axle} are cold, {temp} degrees.",
    "hot": "{axle} are overheating, {temp} degrees. Manage them.",
    "wheels": ("front left", "front right", "rear left", "rear right"),
    "press_hi": "High pressure {wheel}, {p}.",
    "press_lo": "Low pressure {wheel}, {p}.",
    "gaps": "Gaps: {parts}.", "ahead": "ahead {g}", "behind": "behind {g}",
    "flag_yellow": "Yellow flag.", "flag_blue": "Blue flag, let him by.",
    "flag_checkered": "Chequered flag. Good job, box this lap.", "flag_penalty": "Penalty.",
    "flag_black": "Black flag.",
    "battery_low": "Battery at {n} percent.", "battery_empty": "Battery is empty.",
    "lap_energy": "Deployment for this lap is used up.",
    "proposal": "Proposal: {what}. {reason} Confirm with the button.",
    "at_box": "Copy, I'll apply it in the pits.", "discarded": "Copy, we leave it.",
    "done": "Done, {what}.", "failed": "Can't do it: {msg}.",
    "busy": "Stand by, still answering.", "agent_error": "Lost contact with the engineer.",
    "stt_error": "Didn't get that, say again.", "radio_check": "Radio check. Do you copy? Tyres are in the window, push.",
    "kinds": {"brake_bias": "brake bias", "abs": "ABS", "tc": "TC", "engine_brake": "engine braking"},
    "to": "{what} to {v}",
    "stt_prompt": "Race team radio: box, tyres, pressures, brake bias, ABS, TC, engine braking, fuel, lap, "
                  "sector, understeer, oversteer, gap.",
}

_ES = {
    "lap_invalid": "{t}, vuelta no válida.",
    "best_lap": "¡Vuelta rápida! {t}{gain}.",
    "lap": "{t}, {delta}.",
    "laps_to_go": "Quedan {n} vueltas.", "last_lap": "Última vuelta, empuja.",
    "fuel_box": "Box, box. Combustible para una vuelta.",
    "fuel_n": "Combustible para {n} vueltas.",
    "front": "Delanteros", "rear": "Traseros",
    "cold": "{axle} fríos, {temp} grados.",
    "hot": "{axle} sobrecalentados, {temp} grados. Gestiona.",
    "wheels": ("delantero izquierdo", "delantero derecho", "trasero izquierdo", "trasero derecho"),
    "press_hi": "Presión alta {wheel}, {p}.",
    "press_lo": "Presión baja {wheel}, {p}.",
    "gaps": "Diferencias: {parts}.", "ahead": "delante {g}", "behind": "detrás {g}",
    "flag_yellow": "Bandera amarilla.", "flag_blue": "Bandera azul, déjale pasar.",
    "flag_checkered": "Bandera a cuadros. Buen trabajo, entra a boxes.", "flag_penalty": "Penalización.",
    "flag_black": "Bandera negra.",
    "battery_low": "Batería al {n} por ciento.", "battery_empty": "Batería descargada.",
    "lap_energy": "Energía eléctrica de la vuelta agotada.",
    "proposal": "Propuesta: {what}. {reason} Confirma con el botón.",
    "at_box": "Recibido, lo aplico en boxes.", "discarded": "Recibido, lo dejamos así.",
    "done": "Hecho, {what}.", "failed": "No puedo: {msg}.",
    "busy": "Un momento, todavía estoy respondiendo.", "agent_error": "Problema de conexión con el ingeniero.",
    "stt_error": "No te he oído, repite.", "radio_check": "Prueba de radio. ¿Me oyes? Neumáticos en temperatura, empuja.",
    "kinds": {"brake_bias": "reparto de frenada", "abs": "ABS", "tc": "TC", "engine_brake": "freno motor"},
    "to": "{what} a {v}",
    "stt_prompt": "Radio del equipo: box, neumáticos, presiones, reparto de frenada, ABS, TC, combustible, "
                  "vuelta, sector, subviraje, sobreviraje.",
}

_FR = {
    "lap_invalid": "{t}, tour invalide.",
    "best_lap": "Meilleur tour ! {t}{gain}.",
    "lap": "{t}, {delta}.",
    "laps_to_go": "Encore {n} tours.", "last_lap": "Dernier tour, attaque.",
    "fuel_box": "Box, box. Carburant pour un tour.",
    "fuel_n": "Carburant pour {n} tours.",
    "front": "Les avant", "rear": "Les arrière",
    "cold": "{axle} sont froids, {temp} degrés.",
    "hot": "{axle} surchauffent, {temp} degrés. Gère.",
    "wheels": ("avant gauche", "avant droit", "arrière gauche", "arrière droit"),
    "press_hi": "Pression haute {wheel}, {p}.",
    "press_lo": "Pression basse {wheel}, {p}.",
    "gaps": "Écarts : {parts}.", "ahead": "devant {g}", "behind": "derrière {g}",
    "flag_yellow": "Drapeau jaune.", "flag_blue": "Drapeau bleu, laisse passer.",
    "flag_checkered": "Drapeau à damier. Bon travail, rentre au stand.", "flag_penalty": "Pénalité.",
    "flag_black": "Drapeau noir.",
    "battery_low": "Batterie à {n} pour cent.", "battery_empty": "Batterie vide.",
    "lap_energy": "Énergie électrique du tour épuisée.",
    "proposal": "Proposition : {what}. {reason} Confirme avec le bouton.",
    "at_box": "Reçu, je l'applique au stand.", "discarded": "Reçu, on laisse comme ça.",
    "done": "C'est fait, {what}.", "failed": "Impossible : {msg}.",
    "busy": "Un instant, je réponds encore.", "agent_error": "Problème de liaison avec l'ingénieur.",
    "stt_error": "Je ne t'ai pas entendu, répète.", "radio_check": "Essai radio. Tu me reçois ? Pneus en température, attaque.",
    "kinds": {"brake_bias": "répartition de freinage", "abs": "ABS", "tc": "TC", "engine_brake": "frein moteur"},
    "to": "{what} à {v}",
    "stt_prompt": "Radio de l'équipe : box, pneus, pressions, répartition de freinage, ABS, TC, carburant, "
                  "tour, secteur, sous-virage, survirage.",
}

_PT = {
    "lap_invalid": "{t}, volta inválida.",
    "best_lap": "Volta mais rápida! {t}{gain}.",
    "lap": "{t}, {delta}.",
    "laps_to_go": "Faltam {n} voltas.", "last_lap": "Última volta, força.",
    "fuel_box": "Box, box. Combustível para uma volta.",
    "fuel_n": "Combustível para {n} voltas.",
    "front": "Dianteiros", "rear": "Traseiros",
    "cold": "{axle} frios, {temp} graus.",
    "hot": "{axle} superaquecidos, {temp} graus. Administre.",
    "wheels": ("dianteiro esquerdo", "dianteiro direito", "traseiro esquerdo", "traseiro direito"),
    "press_hi": "Pressão alta {wheel}, {p}.",
    "press_lo": "Pressão baixa {wheel}, {p}.",
    "gaps": "Diferenças: {parts}.", "ahead": "à frente {g}", "behind": "atrás {g}",
    "flag_yellow": "Bandeira amarela.", "flag_blue": "Bandeira azul, deixe passar.",
    "flag_checkered": "Bandeira quadriculada. Bom trabalho, entre nos boxes.", "flag_penalty": "Penalidade.",
    "flag_black": "Bandeira preta.",
    "battery_low": "Bateria a {n} por cento.", "battery_empty": "Bateria descarregada.",
    "lap_energy": "Energia elétrica da volta esgotada.",
    "proposal": "Proposta: {what}. {reason} Confirme com o botão.",
    "at_box": "Entendido, aplico nos boxes.", "discarded": "Entendido, deixamos assim.",
    "done": "Feito, {what}.", "failed": "Não consigo: {msg}.",
    "busy": "Um momento, ainda estou respondendo.", "agent_error": "Problema de conexão com o engenheiro.",
    "stt_error": "Não te ouvi, repete.", "radio_check": "Teste de rádio. Está me ouvindo? Pneus na temperatura, acelera.",
    "kinds": {"brake_bias": "balanço de freio", "abs": "ABS", "tc": "TC", "engine_brake": "freio motor"},
    "to": "{what} em {v}",
    "stt_prompt": "Rádio da equipe: box, pneus, pressões, balanço de freio, ABS, TC, combustível, volta, "
                  "setor, subesterço, sobre-esterço.",
}

# race radio phrases (positions, rivals, yellows, race end...) and the chatty engineer's ones: all languages in
# separate files
for _phrases, _code in ((_IT, "it"), (_EN, "en"), (_ES, "es"), (_FR, "fr"), (_PT, "pt")):
    _phrases.update(phrases_for(_code))
    _phrases.update(chatter_phrases_for(_code))

LANGUAGES = {
    "it": Language("it", "italiano", "it", _IT),
    "en-us": Language("en", "English", "en-us", _EN),
    "en-gb": Language("en", "English", "en-gb", _EN),
    "es": Language("es", "español", "es", _ES),
    "fr": Language("fr", "français", "fr-fr", _FR),
    "pt": Language("pt", "português", "pt-br", _PT),
}

# first letter of the Kokoro voice -> language (h, j, z: Hindi, Japanese, Chinese not supported by the radio)
_PREFIX = {"i": "it", "a": "en-us", "b": "en-gb", "e": "es", "f": "fr", "p": "pt"}
_FLAG = {"it": "Italiano", "en-us": "English (US)", "en-gb": "English (UK)", "es": "Español", "fr": "Français",
         "pt": "Português (BR)"}

DEFAULT_VOICE = "am_michael"


def language_of(voice: str | None) -> Language:
    key = _PREFIX.get((voice or DEFAULT_VOICE)[:1].lower(), "en-us")
    return LANGUAGES[key]


def is_supported(voice: str) -> bool:
    return voice[:1].lower() in _PREFIX and voice[1:2] in ("f", "m") and voice[2:3] == "_"


def voice_label(voice: str) -> str:
    """'im_nicola' -> 'Nicola — Italiano, male'."""
    key = _PREFIX.get(voice[:1].lower())
    sex = {"f": "female", "m": "male"}.get(voice[1:2], "")
    name = voice.split("_", 1)[-1].replace("_", " ").title()
    return f"{name} — {_FLAG.get(key, '?')}{', ' + sex if sex else ''}"


# Kokoro v1.0 voices usable by the radio (the same as in voices-v1.0.bin)
KOKORO_VOICES = (
    "im_nicola", "if_sara",
    "am_michael", "am_adam", "am_eric", "am_liam", "am_onyx", "am_puck", "am_echo", "am_fenrir",
    "af_heart", "af_bella", "af_nicole", "af_sarah", "af_sky", "af_nova", "af_river", "af_jessica", "af_kore",
    "af_alloy", "af_aoede",
    "bm_george", "bm_lewis", "bm_daniel", "bm_fable", "bf_emma", "bf_isabella", "bf_alice", "bf_lily",
    "em_alex", "ef_dora", "ff_siwis", "pm_alex", "pf_dora",
)


# -------------------------------------------------------------- spoken numbers

def speak_number(v: float, lang: Language, decimals: int = 1) -> str:
    """29.1 -> '29 point 1' / '29 e 1' (so the synthesis does not read the decimal point its own way)."""
    v = round(v, decimals)
    whole = int(v)
    frac = round(abs(v - whole) * 10 ** decimals)
    if frac == 0:
        return f"{whole}"
    sep = {"it": "e", "en": "point", "es": "coma", "fr": "virgule", "pt": "vírgula"}[lang.code]
    return f"{whole} {sep} {frac}"


def speak_lap_time(ms: int, lang: Language) -> str:
    """90461 -> '1 30 point 5' / '1, 30 e 5': minutes, seconds and tenths as on the pit wall."""
    tenths = int(round(ms / 100.0))
    m, rest = divmod(tenths, 600)
    s, d = divmod(rest, 10)
    if lang.code == "en":
        head = f"{m} {s:02d}" if m else f"{s}"
        return f"{head} point {d}" if d else head
    head = f"{m}, {s}" if m else f"{s}"
    joiner = {"it": "e", "es": "y", "fr": "et", "pt": "e"}[lang.code]
    return f"{head} {joiner} {d}" if d else head


_DELTA = {
    #       plus/minus          same             1 tenth            N tenths            seconds
    "it": (("più", "meno"), "stesso tempo", "un decimo", "{n} decimi", ("secondo", "secondi"), "e"),
    "en": (("plus", "minus"), "same time", "a tenth", "{n} tenths", ("second", "seconds"), "point"),
    "es": (("más", "menos"), "mismo tiempo", "una décima", "{n} décimas", ("segundo", "segundos"), "coma"),
    "fr": (("plus", "moins"), "même temps", "un dixième", "{n} dixièmes", ("seconde", "secondes"), "virgule"),
    "pt": (("mais", "menos"), "mesmo tempo", "um décimo", "{n} décimos", ("segundo", "segundos"), "vírgula"),
}


def speak_amount(seconds: float, lang: Language) -> str:
    """An unsigned time: 0.3 → "3 tenths", 0.1 → "a tenth", 1.4 → "1 point 4" ("" if under a tenth)."""
    _signs, _same, one, many, (sec1, secn), sep = _DELTA[lang.code]
    tenths = int(round(abs(seconds) * 10))
    if tenths == 0:
        return ""
    if tenths < 10:
        return one if tenths == 1 else many.format(n=tenths)
    secs, d = divmod(tenths, 10)
    if d == 0:
        return f"{secs} {sec1 if secs == 1 else secn}"
    return f"{secs} {sep} {d}"


def speak_delta(delta_s: float, lang: Language) -> str:
    (plus, minus), same = _DELTA[lang.code][:2]
    amount = speak_amount(delta_s, lang)
    return f"{plus if delta_s > 0 else minus} {amount}" if amount else same


def same_time(lang: Language) -> str:
    return _DELTA[lang.code][1]
