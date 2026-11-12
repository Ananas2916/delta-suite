"""
Phrases of the "chatty" engineer (ai_engine.race_chatter): what a real F1 race engineer says between the
important calls — the start, overtakes with the rival's name, purple sectors, the pit stop and the out-lap,
rivals' lap times, undercut and overcut, the battery to attack or defend, pace drops and praise, half distance,
the timesheet in practice and qualifying, and the periodic updates when the radio has been quiet for a while.

Same format as phrases_race.py: one entry per phrase with every language side by side, "a|b|c" are variants.
Placeholders: {who} rival's surname (or "the car ahead/behind"), {pos} position, {t} spoken lap time,
{g} spoken gap, {d} spoken amount ("3 tenths"), {n} number, {temp}/{temp2} degrees.
"""

from __future__ import annotations

CHATTER_PHRASES: dict[str, dict[str, object]] = {
    # ---------------------------------------------------------------- who, when the name is unknown
    "who_ahead": {"it": "quello davanti", "en": "the car ahead", "es": "el de delante", "fr": "celui devant",
                  "pt": "o da frente"},
    "who_behind": {"it": "quello dietro", "en": "the car behind", "es": "el de detrás", "fr": "celui derrière",
                   "pt": "o de trás"},
    # ---------------------------------------------------------------- start and positions
    "race_start": {
        "it": "Via! Pulito in curva uno, la gara è lunga.|Partiti! Occhio ai contatti in curva uno.|"
              "Vai vai vai! Tieni la linea e stai fuori dai guai.",
        "en": "Lights out! Keep it clean into turn one.|Go go go! Careful into turn one, it's a long race.|"
              "Away we go. Stay out of trouble on lap one.",
        "es": "¡Salida! Limpio en la curva uno, la carrera es larga.|¡Vamos vamos! Cuidado en la curva uno.",
        "fr": "C'est parti ! Reste propre au premier virage.|Go go go ! Attention au premier virage.",
        "pt": "Largou! Limpo na curva um, a corrida é longa.|Vai vai vai! Cuidado na curva um.",
    },
    "pos_gained_on": {
        "it": "Grande sorpasso su {who}, P{pos}!|Fatto, {who} è dietro. P{pos}.|Dentro su {who}, bravo. P{pos}.",
        "en": "Great move on {who}, P{pos}!|You're past {who}, P{pos}. Well done.|Mega move on {who}, that's P{pos}.",
        "es": "¡Gran adelantamiento a {who}, P{pos}!|Hecho, {who} queda detrás. P{pos}.",
        "fr": "Superbe dépassement sur {who}, P{pos} !|C'est fait, {who} est derrière. P{pos}.",
        "pt": "Grande ultrapassagem em {who}, P{pos}!|Feito, {who} ficou para trás. P{pos}.",
    },
    "pos_lost_to": {
        "it": "{who} ti ha passato, P{pos}. Restagli attaccato.|Passati da {who}, P{pos}. Riprendiamocela.",
        "en": "{who} got by, P{pos}. Stay with him.|Lost it to {who}, P{pos}. Let's get it back.",
        "es": "{who} te ha pasado, P{pos}. Sigue pegado.|Nos ha pasado {who}, P{pos}. A recuperarla.",
        "fr": "{who} est passé, P{pos}. Reste dans sa roue.|Dépassé par {who}, P{pos}. On va la reprendre.",
        "pt": "{who} passou, P{pos}. Fica colado.|{who} passou a gente, P{pos}. Vamos recuperar.",
    },
    # ---------------------------------------------------------------- pit stops: ours and theirs
    "ahead_pitted_name": {
        "it": "{who} davanti è ai box. Spingi adesso, giri da qualifica per l'overcut.|"
              "{who} si ferma. Questo è il momento, dacci dentro.",
        "en": "{who} ahead has boxed. Push now, quali laps, we go for the overcut.|"
              "{who} is pitting. This is the moment, push push.",
        "es": "{who} entra en boxes. Aprieta ahora, vamos a por el overcut.",
        "fr": "{who} rentre au stand. Attaque maintenant, on tente l'overcut.",
        "pt": "{who} entrou nos boxes. Acelera agora, vamos de overcut.",
    },
    "behind_pitted_name": {
        "it": "{who} dietro si è fermato, proverà l'undercut. Spingi questo giro.|"
              "{who} ai box: avrà gomme nuove, sarà veloce. Dacci dentro.",
        "en": "{who} behind has pitted, he'll try the undercut. Push this lap.|"
              "{who} has boxed, expect him quick on new tyres. Push.",
        "es": "{who} ha parado, intentará el undercut. Aprieta esta vuelta.",
        "fr": "{who} s'est arrêté, il va tenter l'undercut. Attaque ce tour.",
        "pt": "{who} parou, vai tentar o undercut. Acelera nesta volta.",
    },
    "pit_exit": {
        "it": "Buona sosta. Rientri P{pos}, gomme fredde: occhio alle prime curve.|"
              "Sosta fatta, P{pos}. Scalda bene le gomme questo giro.",
        "en": "Good stop. You rejoin P{pos}, cold tyres, careful in the first corners.|"
              "That's a good stop, P{pos}. Get some heat into the tyres.",
        "es": "Buena parada. Sales P{pos}, neumáticos fríos, cuidado.",
        "fr": "Bon arrêt. Tu ressors P{pos}, pneus froids, attention.",
        "pt": "Boa parada. Você volta em P{pos}, pneus frios, cuidado.",
    },
    "tyres_warm": {
        "it": "Gomme in temperatura, adesso puoi spingere.|Le gomme sono pronte, spingi.",
        "en": "Tyres are in the window now, you can push.|Tyres are switched on, go.",
        "es": "Neumáticos en temperatura, ya puedes apretar.",
        "fr": "Pneus en température, tu peux attaquer.",
        "pt": "Pneus na temperatura, agora pode acelerar.",
    },
    # ---------------------------------------------------------------- pace
    "sector_best": {
        "it": "Settore {n} viola.|Viola nel settore {n}.|Migliore personale nel settore {n}.",
        "en": "Purple sector {n}.|Personal best in sector {n}.|Purple in sector {n}, nice.",
        "es": "Sector {n} morado.|Mejor personal en el sector {n}.",
        "fr": "Secteur {n} violet.|Record personnel dans le secteur {n}.",
        "pt": "Setor {n} roxo.|Melhor pessoal no setor {n}.",
    },
    "sector_best_by": {
        "it": "Settore {n} viola, {d} meglio.|Viola nel {n}, guadagni {d}.",
        "en": "Purple sector {n}, up {d}.|Sector {n} purple, {d} quicker.",
        "es": "Sector {n} morado, {d} mejor.", "fr": "Secteur {n} violet, {d} de mieux.",
        "pt": "Setor {n} roxo, {d} melhor.",
    },
    "pace_drop": {
        "it": "Giro più lento di {d}, tutto a posto?|Abbiamo perso {d} quel giro, problemi?",
        "en": "That one was {d} slower, everything ok?|We lost {d} that lap, any issues?",
        "es": "Esa vuelta fue {d} más lenta, ¿todo bien?", "fr": "Ce tour était {d} plus lent, tout va bien ?",
        "pt": "Essa volta foi {d} mais lenta, tudo bem?",
    },
    "consistent": {
        "it": "Ritmo costante, ottimo lavoro. Continua così.|Bel passo, giri tutti uguali. Avanti così.",
        "en": "Good consistent pace, keep it up.|Nice rhythm, lap times are very consistent.",
        "es": "Ritmo muy constante, buen trabajo.", "fr": "Rythme très régulier, beau travail.",
        "pt": "Ritmo bem constante, bom trabalho.",
    },
    "fastest_on_track": {
        "it": "Sei il più veloce in pista in questo momento.|Nessuno gira più forte di te adesso, bene.",
        "en": "You're the fastest car on track right now.|Quickest of anyone that lap, good job.",
        "es": "Eres el más rápido en pista ahora mismo.", "fr": "Tu es le plus rapide en piste en ce moment.",
        "pt": "Você é o mais rápido na pista agora.",
    },
    "rival_lap": {
        "it": "{who} davanti ha girato in {t}.|Il giro di {who}: {t}.",
        "en": "{who} ahead did a {t}.|{who} did {t} that lap.",
        "es": "{who} delante hizo {t}.", "fr": "{who} devant a fait {t}.", "pt": "{who} na frente fez {t}.",
    },
    "rival_lap_behind": {
        "it": "{who} dietro ha girato in {t}.", "en": "{who} behind did a {t}.", "es": "{who} detrás hizo {t}.",
        "fr": "{who} derrière a fait {t}.", "pt": "{who} atrás fez {t}.",
    },
    # ---------------------------------------------------------------- rivals and battery
    "rival_slow_ahead": {
        "it": "{who} davanti è lento, ha un problema!|Attenzione, {who} davanti sembra in difficoltà.",
        "en": "{who} ahead is slow, he has a problem!|Heads up, {who} ahead looks in trouble.",
        "es": "¡{who} delante va lento, tiene un problema!", "fr": "{who} devant est lent, il a un problème !",
        "pt": "{who} na frente está lento, tem um problema!",
    },
    "ers_attack": {
        "it": "Sei a {g} da {who} e la batteria è carica: usala per attaccare.|Batteria piena, {who} a {g}. Overtake!",
        "en": "You're {g} behind {who} with a full battery, use it.|Battery is full, {who} at {g}. Overtake mode.",
        "es": "Estás a {g} de {who} con la batería llena, úsala.",
        "fr": "Tu es à {g} de {who} avec la batterie pleine, utilise-la.",
        "pt": "Você está a {g} de {who} com a bateria cheia, use.",
    },
    "ers_defend": {
        "it": "{who} dietro a {g}: tieni un po' di batteria per difenderti in rettilineo.",
        "en": "{who} is {g} behind, keep some battery to defend on the straight.",
        "es": "{who} a {g} detrás, guarda batería para defenderte en la recta.",
        "fr": "{who} à {g} derrière, garde de la batterie pour défendre dans la ligne droite.",
        "pt": "{who} a {g} atrás, guarde bateria para defender na reta.",
    },
    # ---------------------------------------------------------------- race milestones
    "half_distance": {
        "it": "Metà gara, sei P{pos}. Gestisci le gomme.|Siamo a metà, P{pos}. Ottimo lavoro finora.",
        "en": "Half distance, P{pos}. Look after the tyres.|We're at half distance, P{pos}. Good job so far.",
        "es": "Mitad de carrera, P{pos}. Cuida los neumáticos.", "fr": "Mi-course, P{pos}. Gère les pneus.",
        "pt": "Metade da corrida, P{pos}. Cuide dos pneus.",
    },
    "bring_home": {
        "it": "Due giri, P{pos}. Portala a casa, niente rischi.|Ultimi due giri, P{pos}. Concentrato.",
        "en": "Two laps to go, P{pos}. Bring it home.|Two to go, P{pos}. No risks now.",
        "es": "Dos vueltas, P{pos}. Llévalo a casa.", "fr": "Deux tours, P{pos}. Ramène-la à la maison.",
        "pt": "Duas voltas, P{pos}. Traga para casa.",
    },
    # ---------------------------------------------------------------- practice and qualifying
    "session_pos": {
        "it": "Questo ti mette P{pos}, a {g} dal primo.|Sei P{pos}, a {g} dalla vetta.",
        "en": "That puts you P{pos}, {g} off the top.|P{pos}, {g} off the fastest time.",
        "es": "Eso te pone P{pos}, a {g} del primero.", "fr": "Ça te met P{pos}, à {g} du premier.",
        "pt": "Isso te coloca em P{pos}, a {g} do primeiro.",
    },
    "session_top": {
        "it": "Sei il più veloce della sessione!|P1 nei tempi, gran giro.",
        "en": "That's P1, top of the timesheets!|You're fastest in the session, mega lap.",
        "es": "¡Eres el más rápido de la sesión!", "fr": "Tu es le plus rapide de la session !",
        "pt": "Você é o mais rápido da sessão!",
    },
    # ---------------------------------------------------------------- updates when the radio is quiet
    "drip_ahead": {
        "it": "Tutto a posto. P{pos}, {who} davanti a {g}.|Aggiornamento: P{pos}, distacco da {who} {g}.",
        "en": "All good. P{pos}, {who} ahead at {g}.|Update: P{pos}, gap to {who} is {g}.",
        "es": "Todo bien. P{pos}, {who} delante a {g}.", "fr": "Tout va bien. P{pos}, {who} devant à {g}.",
        "pt": "Tudo certo. P{pos}, {who} na frente a {g}.",
    },
    "drip_behind": {
        "it": "Dietro {who} a {g}.|Margine su {who}: {g}.",
        "en": "{who} behind at {g}.|Gap back to {who} is {g}.",
        "es": "{who} detrás a {g}.", "fr": "{who} derrière à {g}.", "pt": "{who} atrás a {g}.",
    },
    "drip_fuel": {
        "it": "Carburante a posto, {n} giri di margine.|Benzina ok, ne hai per {n} giri in più.",
        "en": "Fuel is fine, {n} laps of margin.|Fuel looks good, {n} laps spare.",
        "es": "Combustible bien, {n} vueltas de margen.", "fr": "Carburant OK, {n} tours de marge.",
        "pt": "Combustível ok, {n} voltas de margem.",
    },
    "drip_tyres": {
        "it": "Gomme ok: {temp} gradi davanti, {temp2} dietro.|Le gomme stanno bene, {temp} e {temp2} gradi.",
        "en": "Tyres look good, fronts {temp}, rears {temp2}.|Tyre temps are fine, {temp} and {temp2} degrees.",
        "es": "Neumáticos bien, {temp} delante y {temp2} detrás.",
        "fr": "Pneus OK, {temp} à l'avant, {temp2} à l'arrière.",
        "pt": "Pneus ok, {temp} na frente e {temp2} atrás.",
    },
    "drip_push": {
        "it": "Stai andando forte, continua così.|Bene così, testa bassa e spingi.|Bel lavoro, mantieni il ritmo.",
        "en": "You're doing a great job, keep pushing.|Good stuff, head down.|Looking good, keep this pace.",
        "es": "Lo estás haciendo muy bien, sigue así.", "fr": "Tu fais du super boulot, continue.",
        "pt": "Você está indo muito bem, continue assim.",
    },
    "drip_alone": {
        "it": "Sei in aria pulita, guida il tuo ritmo.|Nessuno vicino, gestisci le gomme.",
        "en": "Clean air, drive your own race.|No one around you, manage the tyres.",
        "es": "Aire limpio, haz tu carrera.", "fr": "Air propre, fais ta course.", "pt": "Ar limpo, faça sua corrida.",
    },
}


def chatter_phrases_for(code: str) -> dict[str, object]:
    """The chatter phrases of one language ("it", "en", "es", "fr", "pt")."""
    return {key: texts[code] for key, texts in CHATTER_PHRASES.items()}
