# Delta Suite

Suite proprietaria di ingegneria e strategia per **Assetto Corsa** (originale, 2014).
Un'unica applicazione desktop che riunisce gli strumenti dei software professionali di
F1/WEC/GTWC, alimentata dalla telemetria letta in tempo reale dalla shared memory di AC,
con un ingegnere di pista AI che ti parla in cuffia.

**Generale**: la prima pagina, come al muretto. Tutto insieme: onboard con grafica TV, classifica, GPS,
stato vettura e avvisi, carburante e strategia, batteria delle ibride, radio e proposte dell'ingegnere da
confermare.

**In pista**

| Modulo | Cosa fa | Al posto di |
|---|---|---|
| Telemetria live | Cruscotto 60–200 Hz: velocità, RPM, pedali, sterzo, gomme, freni, G-G, batteria ed ERS delle ibride, giri e settori; registrazione delle sessioni e replay | MoTeC i2, ATLAS, WinDARAB |
| Onboard live | Fino a 4 onboard insieme (T-cam, cofano, posteriore, ruote, inseguimento, telecamere F6 della tua auto; anche sugli avversari) con grafica TV, classifica, GPS della pista e stato vettura dall'alto: danni per zona, gomme, freni, sospensioni, sporco, batteria e avvisi | feed onboard del muretto |
| Ingegnere di pista | Un solo agente (Claude Code, Codex, Antigravity o API) per chat di analisi e radio in cuffia: legge i dati di Delta Suite, analizza curva per curva, risponde al push-to-talk dal volante e propone setup e strategia; in più la radio automatica con voce Kokoro (giro, carburante, gomme, bandiere) | ingegnere e radio di squadra |
| Box & Assetto | Bias freni, ABS, TC e freno motore in diretta; setup completo; proposte dell'ingegnere da confermare; classifica con gap e interval | muretto box |

**Analisi e strategia**

| Modulo | Cosa fa | Al posto di |
|---|---|---|
| Analisi giri | Fino a 4 giri sovrapposti su distanza, Delta-T, traiettoria, archivio DuckDB, export Parquet | MoTeC i2, Pi Toolbox |
| Strategia & Timing | Consumo medio, piano carburante e finestra pit, degrado gomme, sosta ottimale, giro ideale | HH Timing, SBG RaceWatch |
| Dinamica veicolo | Pacejka, ellisse d'attrito, trasferimenti di carico, cinematica del quadrilatero | ChassisSim, OptimumG, Adams |

## Modalità

Si scelgono in alto nella barra laterale:

- **Pilota**: radio e voce attive; tieni premuto il tasto radio al volante, fai la domanda, l'ingegnere
  risponde in cuffia. Le modifiche che propone si confermano con un altro tasto.
- **Ingegnere**: regolazioni in diretta e setup dalla pagina Box & Assetto, radio spenta.
- **Analisi**: confronto giri e archivio, anche su sessioni registrate in replay.

## Uso rapido

- **Eseguibile:** dalle Releases di GitHub: lo compila GitHub Actions a ogni push (in locale, per debug,
  `.\build_exe.ps1`).
- **Da sorgente:** `pip install -r requirements.txt`, poi `python run_hub.py`.
- **Con AC:** avvia una sessione da Content Manager, poi *Telemetria live → Avvia acquisizione* con
  sorgente "Assetto Corsa". Con "Registra sessione" i dati finiscono in
  `%LOCALAPPDATA%\DeltaSuite\recordings` e si riguardano con la sorgente "Replay".
- **App CSP** (serve Custom Shaders Patch): *Box & Assetto → Installa app CSP in AC*. In gioco, dalla
  barra delle app apri **Delta Suite Bridge** e assegna i tasti: radio (tieni premuto), conferma
  proposta, scarta proposta.
- **Auto ibride:** se l'auto ha KERS o ERS compaiono batteria, spinta o ricarica, energia del giro e mappe
  ERS (Telemetria, Onboard, Generale); la radio avvisa a batteria bassa o scarica.
- **Onboard live:** serve l'app CSP aggiornata. Il video è una seconda vista resa da AC solo mentre la
  pagina è aperta e "Video acceso": se gli FPS in gioco calano, abbassa la qualità o spegnilo (lo stato
  vettura resta, anche in demo e replay).
- **Ingegnere AI:** *Ingegnere di pista → Impostazioni → Agente AI*. Con Claude Code basta averlo
  installato e aver fatto il login: usa il tuo abbonamento, senza chiave API. L'agente vede solo i dati
  di Delta Suite (server MCP locale), non può eseguire comandi né toccare file. Chat scritta e
  push-to-talk sono la stessa conversazione.
- **Voce e lingua:** Kokoro integrato usa i modelli già scaricati da Tsukumo (34 voci). La voce scelta
  decide la lingua parlata (italiano, inglese US/UK, spagnolo, francese, portoghese): frasi della radio,
  risposte dell'ingegnere via radio e trascrizione la seguono. In alternativa fa parlare Tsukumo.
- **Trascrizione (push-to-talk):** Whisper locale (`faster-whisper`, modello `base` di default, ~1 s su
  CPU); i modelli stanno nella cache di Hugging Face e si scaricano al primo uso se mancano. In
  alternativa il motore Ascolto di Tsukumo.
- **Agenti esterni:** *Ingegnere di pista → Impostazioni → Copia configurazione MCP* e incollala in
  Claude Code, Codex o Antigravity per interrogare la telemetria da una sessione interattiva.
- **Senza AC:** sorgente "Demo (simulatore)".

L'archivio dei giri è in `%LOCALAPPDATA%\DeltaSuite\telemetry.duckdb`.

## Struttura

```
run_hub.py                        entry point (anche dell'exe)
ac_app/DeltaSuiteBridge/          app Lua per CSP: ponte (setup, comandi, avversari, tasti radio) e
                                  modulo onboard (video, GPS, telecamere F6)
hub_core/model.py                 TelemetrySample, CarEntry, stati di AC: tipi usati da tutti
hub_core/ac/                      tutto ciò che parla con AC: shared memory, receiver, registrazioni,
                                  ponte CSP, video onboard, texture condivisa, mappe, setup
hub_core/analysis/                giri e settori, curve, classifica, strategia, dinamica, stato vettura
hub_core/database.py              DuckDB: sessioni, giri, campioni; export Parquet
hub_core/demo_source.py           simulatore con la stessa interfaccia del receiver
ai_engine/agent_cli.py            Claude Code / Codex / Antigravity come ingegnere
ai_engine/mcp_server.py           server MCP locale (7 strumenti) con token
ai_engine/radio.py                regole della radio immediata
ai_engine/voice.py                Kokoro / Tsukumo, coda a priorità
ai_engine/stt.py                  trascrizione: Whisper locale o Tsukumo
ai_engine/lang.py                 lingue, voci e frasi della radio
ai_engine/race_engineer_agent.py  backend API Anthropic (riepilogo stint)
ui/                               PyQt6 + pyqtgraph: stato, thread, widget riusabili, una pagina per modulo
tests/                            pytest (incluso un giro vero registrato al Red Bull Ring)
```

## Sviluppo

- Come sono divisi i pacchetti e chi può importare chi: [ARCHITECTURE.md](ARCHITECTURE.md).
- Test: `pip install -r requirements-dev.txt`, poi `python -m pytest`.
- Autotest dell'eseguibile: `set DELTA_SELFTEST=C:\cartella` prima di avviarlo; l'app avvia il demo,
  salva uno screenshot di ogni pagina, verifica voce, app CSP e server MCP e si chiude.
- `DELTA_MUTE=1` silenzia la voce.

## Limiti noti

- Il layout della shared memory è quello di AC 1.x: non compatibile con ACC né con AC EVO.
- Senza l'app CSP restano telemetria, analisi e radio, ma niente regolazioni dall'hub, setup live
  e avversari.
- Codex e Antigravity sono predisposti ma non verificati; per Antigravity l'MCP va configurato nel
  suo `mcp_config.json`.
