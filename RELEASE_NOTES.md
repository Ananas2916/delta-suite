## Delta Suite 0.4.0 — onboard live

**Nuova pagina Onboard live** (In pista, subito dopo la telemetria), come al muretto:
- *Video onboard*: l'app CSP rende una telecamera montata sull'auto — T-cam, abitacolo, posteriore, le
  quattro ruote o inseguimento — anche sulle auto degli avversari, con sopra la grafica stile TV: velocità,
  marcia, giri motore, pedali, sterzo, giro e tempi, e l'avviso più grave in evidenza (l'abitacolo in una
  seconda vista non viene reso: la vista del pilota diventa una telecamera sul cofano);
- *Stato vettura*: l'auto vista dall'alto con i danni per zona, gomme (temperatura, pressione, usura,
  sporco), freni e corsa delle sospensioni, più l'elenco degli avvisi: danni, foratura, gomme fredde o
  surriscaldate, usura, freni, sospensione a fine corsa, carburante, fuori pista, limitatore inserito.
- Il video passa ad AC→Delta Suite come texture condivisa della scheda video: in gioco costa circa 1 ms
  per fotogramma a ogni qualità (provato con una RTX 4060 Laptop); se non si può, passa dalla memoria.
- Qualità da 480×270 a 1280×720 e luminosità regolabile; il video si rende solo con la pagina aperta e si
  spegne con un clic, così in pista non costa FPS quando non serve. In demo e replay resta lo stato vettura.
- L'ingegnere AI vede lo stesso stato vettura (danni, sporco, sospensioni, avvisi) in `stato_live`.

Va reinstallata l'app CSP (*Box & Assetto → Aggiorna app CSP*) e riavviata la sessione in AC.

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
