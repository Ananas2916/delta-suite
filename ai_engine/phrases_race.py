"""
Race radio phrases without AI, in the style of the engineers of F1 games and of real team radio:
positions, rivals, fastest lap, gaps, fuel, tyres and damage, yellows, race end, session time.

One entry per phrase with all languages side by side. "a|b|c" are variants: the radio picks one at random, so
it does not always repeat the same words. Placeholders: {pos} position, {n} number, {places} "place/s",
{g} spoken gap, {d} distance in metres or spoken tenths, {wheel} wheel, {zone} car zone.
"""

from __future__ import annotations

RACE_PHRASES: dict[str, dict[str, object]] = {
    # ---------------------------------------------------------------- positions
    "lap1": {
        "it": "Fine del primo giro, sei P{pos}.|Primo giro completato, P{pos}.",
        "en": "End of lap one, you're P{pos}.|That's lap one done, P{pos}.",
        "es": "Final de la primera vuelta, vas P{pos}.|Primera vuelta completada, P{pos}.",
        "fr": "Fin du premier tour, tu es P{pos}.|Premier tour bouclé, P{pos}.",
        "pt": "Fim da primeira volta, você está em P{pos}.|Primeira volta completa, P{pos}.",
    },
    "lap1_gained": {
        "it": "Fine del primo giro: P{pos}, guadagni {n} {places}. Ottima partenza!",
        "en": "End of lap one: P{pos}, up {n} {places}. Great start!",
        "es": "Final de la primera vuelta: P{pos}, subes {n} {places}. ¡Gran salida!",
        "fr": "Fin du premier tour : P{pos}, tu gagnes {n} {places}. Super départ !",
        "pt": "Fim da primeira volta: P{pos}, ganhou {n} {places}. Ótima largada!",
    },
    "lap1_lost": {
        "it": "Fine del primo giro: P{pos}, perdi {n} {places}. Resta concentrato, la gara è lunga.",
        "en": "End of lap one: P{pos}, down {n} {places}. Stay focused, it's a long race.",
        "es": "Final de la primera vuelta: P{pos}, bajas {n} {places}. Concéntrate, la carrera es larga.",
        "fr": "Fin du premier tour : P{pos}, tu perds {n} {places}. Reste concentré, la course est longue.",
        "pt": "Fim da primeira volta: P{pos}, perdeu {n} {places}. Foco, a corrida é longa.",
    },
    "places": {
        "it": ("posizione", "posizioni"), "en": ("place", "places"), "es": ("posición", "posiciones"),
        "fr": ("place", "places"), "pt": ("posição", "posições"),
    },
    "pos_gained": {
        "it": "Bel sorpasso, P{pos}.|Posizione guadagnata, ora sei P{pos}.|Dentro! P{pos}.",
        "en": "Nice move, P{pos}.|Position gained, you're P{pos}.|Good job, that's P{pos}.",
        "es": "Buen adelantamiento, P{pos}.|Posición ganada, vas P{pos}.",
        "fr": "Beau dépassement, P{pos}.|Place gagnée, tu es P{pos}.",
        "pt": "Boa ultrapassagem, P{pos}.|Posição ganha, você está em P{pos}.",
    },
    "pos_lost": {
        "it": "Posizione persa, P{pos}. Riprendiamola.|Ci hanno passato, sei P{pos}. Resta lì.",
        "en": "Lost a place, P{pos}. Let's get it back.|He's through, you're P{pos}. Stay with him.",
        "es": "Posición perdida, P{pos}. Vamos a recuperarla.|Te ha pasado, vas P{pos}. Sigue con él.",
        "fr": "Place perdue, P{pos}. On va la reprendre.|Il est passé, tu es P{pos}. Reste dans sa roue.",
        "pt": "Posição perdida, P{pos}. Vamos recuperar.|Ele passou, você está em P{pos}. Fica com ele.",
    },
    "fastest_lap": {
        "it": "Giro più veloce della gara!|È il giro più veloce in pista!",
        "en": "Fastest lap of the race!|That's the fastest lap of the race, mega!",
        "es": "¡Vuelta rápida de la carrera!|¡Es la vuelta más rápida de la carrera!",
        "fr": "Meilleur tour en course !|C'est le meilleur tour de la course !",
        "pt": "Volta mais rápida da corrida!|É a volta mais rápida da prova!",
    },
    # ---------------------------------------------------------------- gaps and rivals
    "closing": {
        "it": "recuperi {d} al giro", "en": "closing {d} a lap", "es": "recuperas {d} por vuelta",
        "fr": "tu reprends {d} au tour", "pt": "recuperando {d} por volta",
    },
    "dropping": {
        "it": "perdi {d} al giro", "en": "losing {d} a lap", "es": "pierdes {d} por vuelta",
        "fr": "tu perds {d} au tour", "pt": "perdendo {d} por volta",
    },
    "catching": {
        "it": "ti prende {d} al giro", "en": "he's catching {d} a lap", "es": "te recorta {d} por vuelta",
        "fr": "il revient de {d} au tour", "pt": "ele tira {d} por volta",
    },
    "pulling": {
        "it": "guadagni {d} al giro", "en": "you're pulling {d} a lap", "es": "le sacas {d} por vuelta",
        "fr": "tu creuses {d} au tour", "pt": "você abre {d} por volta",
    },
    "ahead_close": {
        "it": "Auto davanti a {g}, è nel mirino.|Sei a {g} da quello davanti, attacca.",
        "en": "Car ahead is {g} in front, he's in range.|You're {g} behind, go for it.",
        "es": "Coche de delante a {g}, lo tienes a tiro.|Estás a {g} del de delante, ataca.",
        "fr": "Voiture devant à {g}, elle est à portée.|Tu es à {g} de celui devant, attaque.",
        "pt": "Carro da frente a {g}, está ao seu alcance.|Você está a {g} do da frente, ataca.",
    },
    "behind_close": {
        "it": "Auto dietro a {g}, difendi la posizione.|Occhio agli specchietti, quello dietro è a {g}.",
        "en": "Car behind is {g} back, defend.|Watch your mirrors, car behind at {g}.",
        "es": "Coche de detrás a {g}, defiende la posición.|Ojo a los retrovisores, el de detrás a {g}.",
        "fr": "Voiture derrière à {g}, défends ta place.|Attention aux rétros, celui derrière est à {g}.",
        "pt": "Carro de trás a {g}, defenda a posição.|Olho no retrovisor, o de trás está a {g}.",
    },
    "ahead_pitted": {
        "it": "L'auto davanti è entrata ai box.|Quello davanti si ferma ai box.",
        "en": "Car ahead has pitted.|The car in front is boxing.",
        "es": "El coche de delante ha entrado en boxes.",
        "fr": "La voiture devant est rentrée au stand.",
        "pt": "O carro da frente entrou nos boxes.",
    },
    "behind_pitted": {
        "it": "L'auto dietro è entrata ai box.|Quello dietro si ferma ai box.",
        "en": "Car behind has pitted.|The car behind is boxing.",
        "es": "El coche de detrás ha entrado en boxes.",
        "fr": "La voiture derrière est rentrée au stand.",
        "pt": "O carro de trás entrou nos boxes.",
    },
    # ---------------------------------------------------------------- race end
    "leader_last_lap": {
        "it": "Il leader è all'ultimo giro.", "en": "Leader is on the final lap.",
        "es": "El líder está en la última vuelta.", "fr": "Le leader est dans le dernier tour.",
        "pt": "O líder está na última volta.",
    },
    "finish_win": {
        "it": "Bandiera a scacchi! Vittoria! Fantastico, che gara!|Bandiera a scacchi, hai vinto! Grandissimo!",
        "en": "Chequered flag! You win it! Fantastic job!|Chequered flag, P1! What a drive!",
        "es": "¡Bandera a cuadros! ¡Victoria! ¡Fantástico!", "fr": "Drapeau à damier ! Victoire ! Fantastique !",
        "pt": "Bandeira quadriculada! Vitória! Fantástico!",
    },
    "finish_podium": {
        "it": "Bandiera a scacchi, P{pos}! Podio, ottimo lavoro.",
        "en": "Chequered flag, P{pos}! That's a podium, great job.",
        "es": "¡Bandera a cuadros, P{pos}! Podio, gran trabajo.",
        "fr": "Drapeau à damier, P{pos} ! Podium, super boulot.",
        "pt": "Bandeira quadriculada, P{pos}! Pódio, ótimo trabalho.",
    },
    "finish": {
        "it": "Bandiera a scacchi, P{pos}. Bel lavoro, rientra ai box.|Fine gara, P{pos}. Grazie per oggi.",
        "en": "Chequered flag, P{pos}. Good job, bring it home.|That's the flag, P{pos}. Thanks for today.",
        "es": "Bandera a cuadros, P{pos}. Buen trabajo, vuelve a boxes.",
        "fr": "Drapeau à damier, P{pos}. Bon travail, rentre au stand.",
        "pt": "Bandeira quadriculada, P{pos}. Bom trabalho, volte aos boxes.",
    },
    # ---------------------------------------------------------------- fuel
    "fuel_save": {
        "it": "Il carburante non basta per finire: risparmia, alza prima delle frenate.|Dobbiamo risparmiare "
              "carburante, lift and coast.",
        "en": "We're short on fuel to the end: save fuel, lift and coast.|We need to save fuel, lift and coast "
              "into the corners.",
        "es": "No llegamos con el combustible: ahorra, levanta antes de frenar.",
        "fr": "Il manque du carburant pour finir : économise, lève le pied avant les freinages.",
        "pt": "O combustível não chega até o fim: economize, tire o pé antes das frenagens.",
    },
    "fuel_ok": {
        "it": "Carburante a posto fino alla fine, puoi spingere.", "en": "Fuel is fine to the end, you can push.",
        "es": "Combustible suficiente hasta el final, puedes apretar.",
        "fr": "Carburant OK jusqu'à la fin, tu peux attaquer.", "pt": "Combustível ok até o fim, pode acelerar.",
    },
    # ---------------------------------------------------------------- car
    "puncture": {
        "it": "Foratura {wheel}! Box, box.", "en": "Puncture, {wheel}! Box, box.", "es": "¡Pinchazo {wheel}! Box, box.",
        "fr": "Crevaison {wheel} ! Box, box.", "pt": "Furo no {wheel}! Box, box.",
    },
    "damage": {
        "it": "Abbiamo un danno {zone}, lo stiamo valutando.|Danno {zone}, guida con attenzione.",
        "en": "We have damage {zone}, we're checking it.|Damage {zone}, take care.",
        "es": "Tenemos daños {zone}, lo estamos revisando.", "fr": "On a des dégâts {zone}, on regarde.",
        "pt": "Temos dano {zone}, estamos verificando.",
    },
    "zones": {
        "it": ("all'anteriore", "al posteriore", "sul lato sinistro", "sul lato destro", "al fondo"),
        "en": ("at the front", "at the rear", "on the left side", "on the right side", "to the floor"),
        "es": ("en la parte delantera", "en la parte trasera", "en el lado izquierdo", "en el lado derecho",
               "en el fondo"),
        "fr": ("à l'avant", "à l'arrière", "sur le côté gauche", "sur le côté droit", "au fond plat"),
        "pt": ("na dianteira", "na traseira", "na lateral esquerda", "na lateral direita", "no assoalho"),
    },
    "tyre_worn": {
        "it": "Gomma {wheel} al limite, pensiamo al pit.", "en": "The {wheel} tyre is finished, think about pitting.",
        "es": "Neumático {wheel} al límite, piensa en parar.", "fr": "Pneu {wheel} à bout, pense à rentrer.",
        "pt": "Pneu {wheel} no limite, pense na parada.",
    },
    "tyres_worn": {
        "it": "Le gomme sono finite, pensiamo al pit.|Gomme al limite, valuta la sosta.",
        "en": "The tyres are gone, think about pitting.|Tyres are finished, consider a stop.",
        "es": "Los neumáticos están al límite, piensa en parar.", "fr": "Les pneus sont à bout, pense à rentrer.",
        "pt": "Os pneus acabaram, pense na parada.",
    },
    "limiter": {
        "it": "Limitatore!|Inserisci il limitatore!", "en": "Pit limiter!|Limiter, limiter!",
        "es": "¡Limitador!", "fr": "Limiteur !", "pt": "Limitador!",
    },
    # ---------------------------------------------------------------- track
    "yellow_ahead": {
        "it": "Gialla davanti, auto lenta a {d} metri.|Attenzione, gialla tra {d} metri.",
        "en": "Yellow flag ahead, slow car in {d} metres.|Careful, yellow in {d} metres.",
        "es": "Amarilla delante, coche lento a {d} metros.", "fr": "Drapeau jaune devant, voiture lente à {d} mètres.",
        "pt": "Amarela à frente, carro lento a {d} metros.",
    },
    "double_yellow": {
        "it": "Doppia gialla, auto ferma a {d} metri. Rallenta.",
        "en": "Double yellow, car stopped in {d} metres. Slow down.",
        "es": "Doble amarilla, coche parado a {d} metros. Reduce.",
        "fr": "Double drapeau jaune, voiture arrêtée à {d} mètres. Ralentis.",
        "pt": "Dupla amarela, carro parado a {d} metros. Reduza.",
    },
    "track_clear": {
        "it": "Pista libera, bandiera verde.|Verde, verde, pista libera.",
        "en": "Track is clear, green flag.|Green, green, track is clear.",
        "es": "Pista libre, bandera verde.", "fr": "Piste dégagée, drapeau vert.", "pt": "Pista livre, bandeira verde.",
    },
    # ---------------------------------------------------------------- race control (FCY / VSC)
    "rc_fcy_countdown": {
        "it": "Full course yellow tra {n} secondi. Preparati a rallentare a {kmh} all'ora.",
        "en": "Full course yellow in {n} seconds. Get ready to slow to {kmh} k p h.",
        "es": "Full course yellow en {n} segundos. Prepárate para bajar a {kmh} por hora.",
        "fr": "Full course yellow dans {n} secondes. Prépare-toi à ralentir à {kmh} à l'heure.",
        "pt": "Full course yellow em {n} segundos. Prepare-se para reduzir para {kmh} por hora.",
    },
    "rc_fcy_now": {
        "it": "FCY, FCY. Limite {kmh} all'ora, niente sorpassi.|Full course yellow attiva, {kmh} all'ora.",
        "en": "FCY, FCY. Limit {kmh}, no overtaking.|Full course yellow now, {kmh} k p h.",
        "es": "FCY, FCY. Límite {kmh} por hora, sin adelantar.",
        "fr": "FCY, FCY. Limite {kmh} à l'heure, pas de dépassement.",
        "pt": "FCY, FCY. Limite {kmh} por hora, sem ultrapassagens.",
    },
    "rc_vsc_now": {
        "it": "Virtual safety car, virtual safety car. Tieni il delta positivo.|VSC in pista, resta sopra il delta.",
        "en": "Virtual safety car, virtual safety car. Stay positive on the delta.|VSC deployed, keep the delta positive.",
        "es": "Virtual safety car, virtual safety car. Mantén el delta positivo.",
        "fr": "Virtual safety car, virtual safety car. Garde le delta positif.",
        "pt": "Virtual safety car, virtual safety car. Mantenha o delta positivo.",
    },
    "rc_vsc_ending": {
        "it": "VSC in chiusura, VSC in chiusura. Preparati a ripartire.",
        "en": "VSC ending, VSC ending. Get ready to go.",
        "es": "VSC terminando, VSC terminando. Prepárate.",
        "fr": "Fin de VSC, fin de VSC. Prépare-toi à repartir.",
        "pt": "VSC terminando, VSC terminando. Prepare-se.",
    },
    "rc_fcy_ending": {
        "it": "FCY in chiusura, ripartenza tra poco.",
        "en": "FCY ending, green coming up.",
        "es": "FCY terminando, verde en breve.",
        "fr": "Fin de FCY, le vert arrive.",
        "pt": "FCY terminando, verde em breve.",
    },
    "rc_green": {
        "it": "Verde, verde, verde! Si riparte.|Bandiera verde, spingi!",
        "en": "Green, green, green! Go, go.|Green flag, push now!",
        "es": "¡Verde, verde, verde! A fondo.",
        "fr": "Vert, vert, vert ! On attaque.",
        "pt": "Verde, verde, verde! Acelera.",
    },
    "rc_sc_now": {
        "it": "Safety car, safety car. Niente sorpassi, chiudi sulla macchina davanti.|Safety car in pista, mettiti in fila.",
        "en": "Safety car, safety car. No overtaking, close up to the car ahead.|Safety car deployed, get in line.",
        "es": "Safety car, safety car. Sin adelantar, acércate al coche de delante.",
        "fr": "Safety car, safety car. Pas de dépassement, recolle à la voiture devant.",
        "pt": "Safety car, safety car. Sem ultrapassagens, encoste no carro da frente.",
    },
    "rc_sc_in": {
        "it": "Safety car in this lap, safety car in this lap. Preparati alla ripartenza.",
        "en": "Safety car in this lap, safety car in this lap. Get ready for the restart.",
        "es": "Safety car en esta vuelta. Prepárate para la relanzada.",
        "fr": "Safety car dans ce tour. Prépare-toi pour la relance.",
        "pt": "Safety car nesta volta. Prepare-se para a relargada.",
    },
    "rc_sc_overtake": {
        "it": "Non puoi sorpassare in regime di safety car, restituisci la posizione!",
        "en": "No overtaking under the safety car, give that place back!",
        "es": "¡No se adelanta con safety car, devuelve la posición!",
        "fr": "Pas de dépassement sous safety car, rends la place !",
        "pt": "Sem ultrapassagem sob safety car, devolva a posição!",
    },
    "rc_cancelled": {
        "it": "Annullata, si resta in verde.", "en": "Cancelled, we stay green.",
        "es": "Anulado, seguimos en verde.", "fr": "Annulé, on reste au vert.", "pt": "Cancelado, seguimos no verde.",
    },
    "rc_delta_negative": {
        "it": "Delta negativo, rallenta!|Sei sotto il delta, alza il piede.",
        "en": "Delta negative, slow down!|You're under the delta, back off.",
        "es": "¡Delta negativo, reduce!", "fr": "Delta négatif, ralentis !", "pt": "Delta negativo, reduza!",
    },
    "rc_over_limit": {
        "it": "Troppo veloce, il limite è {kmh}!", "en": "Too fast, the limit is {kmh}!",
        "es": "¡Demasiado rápido, el límite es {kmh}!", "fr": "Trop rapide, la limite est {kmh} !",
        "pt": "Rápido demais, o limite é {kmh}!",
    },
    # ---------------------------------------------------------------- session
    "time_5min": {
        "it": "Mancano 5 minuti alla fine della sessione.", "en": "Five minutes left in the session.",
        "es": "Quedan 5 minutos de sesión.", "fr": "Il reste 5 minutes de session.", "pt": "Faltam 5 minutos de sessão.",
    },
    "time_1min": {
        "it": "Ultimo minuto, è il momento del giro buono.", "en": "Final minute, this is the one.",
        "es": "Último minuto, es el momento de la vuelta buena.", "fr": "Dernière minute, c'est le moment.",
        "pt": "Último minuto, é a hora da volta boa.",
    },
}


def phrases_for(code: str) -> dict[str, object]:
    """The race phrases of one language ("it", "en", "es", "fr", "pt")."""
    return {key: texts[code] for key, texts in RACE_PHRASES.items()}
