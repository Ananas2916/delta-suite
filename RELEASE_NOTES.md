## Delta Suite 0.2.0 — l'ingegnere di pista

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
