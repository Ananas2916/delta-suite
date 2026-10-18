## Delta Suite 0.5.2 — parziali e un ingegnere che parla di più

**Parziali e delta**, come i cronometri delle dirette:
- *Tempo giro con delta live* sul tuo miglior giro valido (+0,71 in rosso se sei più lento, verde se più veloce),
  in Generale, in Telemetria e nella grafica TV;
- *settori S1, S2, S3* man mano che si chiudono: viola se è il tuo migliore, giallo se più lento, bianco quello in
  corso; a inizio giro restano per qualche secondo quelli del giro appena chiuso.
- In classifica la colonna *Int* (distacco dall'auto davanti); nella strategia mescola montata, giri sulle gomme,
  usura, temperatura di aria e asfalto; *bandiera verde* per qualche secondo quando la gialla finisce.

**Ingegnere di pista senza AI**, sullo stile dei giochi F1, in tutte le lingue della radio e con più varianti
per non ripetersi:
- fine del primo giro con le posizioni guadagnate o perse dalla griglia; sorpassi fatti e subiti; giro più
  veloce della gara;
- distacchi con la tendenza ("davanti 1,2, recuperi 3 decimi al giro"); auto davanti o dietro sotto il
  secondo; avversari che si fermano ai box;
- il leader all'ultimo giro; bandiera a scacchi con il risultato (vittoria, podio, posizione);
- carburante: "risparmia, lift and coast" quando non basta per finire, e il via libera quando torna a bastare;
- foratura (box, box), danni per zona, gomme finite, limitatore dimenticato in corsia box;
- gialla davanti con la distanza ("doppia gialla, auto ferma a 350 metri"), poi "pista libera";
- in prova e qualifica: 5 minuti e ultimo minuto della sessione.
Ogni gruppo si accende o spegne in *Ingegnere di pista → Impostazioni → Radio automatica*.

---

## Delta Suite 0.5.1 — giri alla fine, bandiere vere, mappa nuova

Dalla prima prova in gara con la 0.5.0:
- **Giri che mancano**: nella Generale ("Giro 9/25", "Mancano 16 giri", "ULTIMO GIRO"; nelle gare a tempo una
  stima con il tempo rimasto), nella grafica TV e in Telemetria; nella strategia il carburante al traguardo
  ("avanzano 3,2 L" o "serve una sosta"). La radio avvisa a 10, 5 e 3 giri dalla fine e all'ultimo giro.
- **Bandiere**: la gialla non resta più accesa a incidente passato. Delta Suite guarda le auto lente o ferme
  in pista (dall'app CSP) e la mostra solo se una è davanti a te, con la distanza ("auto lenta a 350 m";
  "DOPPIA GIALLA · auto ferma" se è ferma); la gialla di AC da sola vale pochi secondi. Blu, scacchi, nera e
  penalità come le dà AC, con il testo intero (prima restava un quadratino colorato).
- **Mappa nuova**: la pista disegnata come un tracciato, dalla linea del tracciato di AC (la stessa con cui AC
  calcola la posizione sul giro), con corsia box, traguardo e le auto come cerchi con la posizione: tu in
  giallo, il leader in viola, le auto ai box vuote. I tratti si colorano di giallo dove c'è un'auto lenta, di
  rosso dove una è ferma, di blu dietro di te quando hai la bandiera blu. Le auto sono sulla mappa anche a
  video spento.
- **Ibride**: le auto senza limite di energia per giro (es. la 499P) non mostrano più un limite di
  99999998430675 kJ.
- L'ingegnere AI vede anche giri mancanti, bandiera e carburante al traguardo.

---

## Delta Suite 0.5.0 — Generale, ibride, più onboard e GPS

**Nuova pagina Generale** (la prima, al posto della vecchia Home): tutto insieme, come al muretto.
Sessione e bandiera; posizione, giro, tempi, carburante e tempo rimasto; l'onboard con la grafica TV
(clic su un'auto in classifica o sul GPS per inquadrarla); classifica, GPS e stato vettura con gli avvisi;
strategia (consumo, giri di carburante, giro ideale, stint, usura); batteria delle ibride; le proposte
dell'ingegnere da confermare o scartare e il registro della radio. Le descrizioni dei moduli sono ora i
suggerimenti delle voci in barra laterale.

**Auto ibride**: se l'auto ha KERS o ERS, Delta Suite mostra la carica della batteria, se sta spingendo o
ricaricando, l'energia usata nel giro rispetto al limite, mappa di potenza, recupero e dove va l'MGU-H:
in Telemetria (riquadro Ibrido), nella grafica TV (barra accanto ai pedali), nello stato vettura e nella
Generale. Avvisi a batteria bassa (20%) e scarica, e a energia del giro finita; la radio lo dice (una
volta, finché non si ricarica) e si può spegnere tra le regole della radio. L'ingegnere AI vede gli stessi
dati. Il demo ora è una hypercar ibrida.

**Onboard live**
- *Niente più tremolio*: le telecamere seguono la carrozzeria disegnata da AC, non più il centro delle
  ruote (che si muove con le sospensioni).
- *Fino a 4 onboard insieme*, come nelle dirette con più feed: un riquadro principale con la grafica TV e
  fino a tre secondari con auto e telecamera a scelta; ▲ porta un secondario nel principale. Ogni
  riquadro è una vista in più resa da AC: le secondarie vanno a 640×360 o 480×270 e AC ne rende una per
  fotogramma, così il costo non fa picchi.
- *Telecamere F6 della tua auto* (quelle di CSP "Car": dietro il pilota, cruscotto, laterale…) con nomi
  ricavati da dove sono montate, e telecamere di Delta Suite raggruppate e con nomi più corti.
- *GPS*: la pista con tutte le auto e la loro posizione, presa dalla mappa di AC del tracciato (o
  disegnata dal percorso dell'auto in demo e replay); i riquadri aperti hanno un cerchio del loro colore
  sull'auto inquadrata, e un clic su un'auto la mette nel riquadro principale.
- *Classifica accanto agli onboard*: posizione, pilota, distacco e ultimo giro, con il colore del riquadro
  sulle auto inquadrate; anche i riquadri piccoli mostrano distacco e ultimo giro. Lo schema dell'auto è
  nella scheda "Stato vettura", la mappa sotto è più grande.

**Finestra**: su uno schermo scalato al 150% non si taglia più a destra; le pagine larghe scorrono. Nello
stato vettura le scritte delle gomme non escono più dalla colonna stretta.

**Sotto il cofano**: il codice è stato riordinato per crescere senza diventare un groviglio. Nessuna
funzione cambia, ma:
- l'app CSP ora è fatta di due file, il ponte (setup, comandi, radio) e il modulo onboard: se il video dà
  problemi, conferme e radio continuano a funzionare e la finestra dell'app dice cosa non va;
- Delta Suite si accorge se *uno qualsiasi* dei file dell'app in AC è vecchio, non solo quello principale.

Va aggiornata l'app CSP (*Box & Assetto → Aggiorna app CSP*), che ora installa anche
`DeltaSuiteOnboard.lua`.

---

## Delta Suite 0.4.0 — onboard live

**Nuova pagina Onboard live** (In pista, subito dopo la telemetria), come al muretto:
- *Video onboard*: l'app CSP rende una telecamera montata sull'auto — T-cam, cofano (vista pilota),
  posteriore, le quattro ruote o inseguimento — anche sulle auto degli avversari, con sopra la grafica
  stile TV: velocità, marcia, giri motore, pedali, sterzo, giro e tempi, e l'avviso più grave in evidenza;
- *Stato vettura*: l'auto vista dall'alto con i danni per zona, gomme (temperatura, pressione, usura,
  sporco), freni e corsa delle sospensioni, più l'elenco degli avvisi: danni, foratura, gomme fredde o
  surriscaldate, usura, freni, sospensione a fine corsa, carburante, fuori pista, limitatore inserito.
- Il video passa da AC a Delta Suite come texture condivisa della scheda video: in gioco costa circa 1 ms
  per fotogramma a ogni qualità (provato con una RTX 4060 Laptop); se non si può, passa dalla memoria.
  Colori ed esposizione sono regolati per somigliare al gioco (la seconda vista non ha i suoi filtri).
- Qualità da 480×270 a 1280×720 e luminosità regolabile; il video si rende solo con la pagina aperta e si
  spegne con un clic, così in pista non costa FPS quando non serve. In demo e replay resta lo stato vettura.
- L'ingegnere AI vede lo stesso stato vettura (danni, sporco, sospensioni, avvisi) in `stato_live`.

Va aggiornata l'app CSP (*Box & Assetto → Aggiorna app CSP*); CSP la ricarica da sola, altrimenti basta
riavviare la sessione in AC.

---

## Delta Suite 0.3.0 — più ordine

**Interfaccia riordinata.** Sei moduli in due gruppi, uguali in barra laterale e in Home:
- **In pista:** Telemetria live · Ingegnere di pista · Box & Assetto
- **Analisi e strategia:** Analisi giri · Strategia & Timing · Dinamica veicolo

**Ingegnere di pista in una pagina sola** (prima erano "AI Race Engineer" e "Radio & voce"):
- *Conversazione*: chat con l'ingegnere e, accanto, la radio in cuffia con il tasto push-to-talk; le
  domande fatte via radio compaiono nella chat, perché è la stessa conversazione;
- *Riepilogo stint*: i dati dello stint in tabella;
- *Impostazioni*: agente AI, collegamento MCP, voce e lingua, microfono e trascrizione, regole della radio
  automatica, tutto nello stesso posto.

**Tolto il CAD / CFD bridge**: non c'entrava con il resto della suite. L'exe è anche più leggero (niente
OpenGL).

---

Comprende anche le novità della 0.2.0, che non era stata pubblicata:

**Ingegnere in cuffia.** Come l'ingegnere dei giochi di F1, ma con un'AI dove lo script non arriva:
- radio immediata, senza AI e senza consumare token: tempo sul giro e delta, carburante, gomme fuori
  finestra, distacchi, bandiere; parla solo quando non sei in staccata o a centro curva;
- push-to-talk dal volante: fai la domanda, la trascrizione è locale (Whisper) e l'ingegnere AI risponde
  in cuffia con i dati veri della sessione;
- voce a scelta (Kokoro, 34 voci): la lingua parlata segue la voce: italiano, inglese US/UK, spagnolo,
  francese, portoghese.

**Ingegnere AI con il tuo abbonamento.** Claude Code (o Codex, Antigravity, comando personalizzato, API)
legge telemetria, giri, setup e classifica da Delta Suite tramite un server MCP locale, analizza curva per
curva e propone modifiche: non applica mai niente da solo, confermi tu (tasto al volante o pulsante).

**Box & Assetto** (app Lua per Custom Shaders Patch, installabile dall'hub): bias freni, ABS, TC e freno
motore in diretta, setup completo, menu pit stop, classifica con gap e interval.

**Altro**
- Modalità Pilota / Ingegnere / Analisi.
- Registrazione delle sessioni e replay.
- Analisi curva per curva: frenata, velocità minima, ripresa del gas, tempo perso.
- Correzioni sulla segmentazione dei giri trovate con AC vero (passaggio sul traguardo, giri parziali).

**Requisiti per la voce:** i modelli Kokoro di Tsukumo (o `kokoro-v1.0.onnx` + `voices-v1.0.bin` in una
cartella a scelta). Whisper usa la cache di Hugging Face e scarica il modello al primo uso se manca.
