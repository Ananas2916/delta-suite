# Delta Suite — contesto di progetto

(nome precedente: Mio Hub Motorsport; la cartella resta `mio_hub_motorsport`)

## Obiettivo
Suite software proprietaria "All-in-One Engineering & Strategy Suite" che raggruppa in un unico
ecosistema modulare le funzionalità dei software professionali F1/WEC/GTWC, interfacciata con
**Assetto Corsa originale (2014)** — NON ACC, NON AC EVO (hanno layout di shared memory diversi).
Codice proprietario dell'utente, nessuna dipendenza da licenze commerciali.

## Setup utente
- Windows 11, Desktop sincronizzato su OneDrive: progetto in `C:\Users\filip\OneDrive\Desktop\mio_hub_motorsport`
- Avvia AC tramite **Content Manager** (quasi certamente con Custom Shaders Patch)
- Lingua di lavoro: italiano

## Moduli
Sette moduli in due gruppi, nello stesso ordine in barra laterale e in Home (`SECTIONS` in
`ui/pages/home_page.py`). Il CAD/CFD bridge è stato tolto (16/10/2026): non c'entrava con la suite.

**In pista**
1. **Telemetria live** (sostituisce MoTeC i2 / ATLAS / WinDARAB): acquisizione 60–100 Hz (velocità,
   pedali/sterzo, temperature e pressioni gomme, sospensioni, G-force, KERS), registrazione e replay.
2. **Onboard live** (18/10/2026): video da una telecamera sull'auto (T-cam, abitacolo, posteriore, 4
   ruote, inseguimento; anche sugli avversari) con grafica TV sopra, più vista dall'alto dello stato
   vettura: danni per zona (`carDamage`), gomme, freni, corsa sospensioni, sporco e avvisi
   (`hub_core/car_status.py`). Il video lo rende l'app CSP con `ac.GeometryShot` (seconda vista, costa
   FPS) e lo salva in JPG a rotazione su 3 file in `%LOCALAPPDATA%\DeltaSuite\onboard`; scambio su una
   mapping a parte `DeltaSuite_Onboard_v1` (`hub_core/onboard_feed.py`), il ponte comandi resta v1.
   Rende solo con la pagina aperta e il video acceso.
3. **Ingegnere di pista** (ex "AI Race Engineer" + "Radio & voce", unite): un solo agente per chat
   scritta e radio. Agente a riga di comando (Claude Code con l'abbonamento dell'utente; Codex,
   Antigravity o comando personalizzato, API Anthropic come ultima opzione) che legge i dati via MCP e
   propone modifiche da confermare. Radio a regole locali (giro/delta, carburante, gomme, bandiere) letta
   da Kokoro; push-to-talk dal volante → Whisper locale → agente in modalità RADIO → risposta parlata
   nella lingua della voce. Pagina a schede: Conversazione (chat + radio in cuffia), Riepilogo stint,
   Impostazioni (agente, MCP, voce, microfono, regole radio).
4. **Box & Assetto**: bias/ABS/TC/freno motore in diretta, setup, proposte dell'ingegnere, pit stop e
   classifica con gap tramite l'app Lua CSP `ac_app/DeltaSuiteBridge`.

**Analisi e strategia**
5. **Analisi giri**: giri sovrapposti (Delta-T, traiettoria, pedali, RPM), confronto curva per curva,
   archivio DuckDB ed export Parquet.
6. **Strategia & Timing** (sostituisce HH Timing / SBG RaceWatch): settori, consumo medio, pit-window,
   degrado gomme sui 10–20 giri successivi.
7. **Dinamica veicolo** (sostituisce ChassisSim / OptimumG / Adams): Pacejka (Magic Formula),
   cinematica sospensioni (centri di rollio, camber/toe dinamici, ride height).

## Struttura
```
ac_app/DeltaSuiteBridge/        # app Lua per CSP: ponte comandi/setup/avversari/tasti radio
hub_core/telemetry_receiver.py # acquisizione dati (sample_from_pages condiviso con il replay)
hub_core/session_recording.py  # registrazione .dsr delle pagine grezze e ReplaySource
hub_core/csp_bridge.py         # lato Python del ponte CSP (layout = DeltaSuiteBridge.lua)
hub_core/timing.py             # classifica, gap e interval
hub_core/onboard_feed.py       # video onboard dall'app CSP (mapping DeltaSuite_Onboard_v1 + JPG)
hub_core/car_status.py         # danni, gomme, freni, sospensioni → avvisi (pagina Onboard e MCP)
hub_core/lap_analysis.py       # curve automatiche e confronto curva per curva
hub_core/setup_files.py        # setup .ini in Documenti (rediretti su OneDrive)
hub_core/vehicle_dynamics.py   # Pacejka & cinematica
hub_core/race_strategy.py      # carburante, pit, timing
hub_core/database.py           # DuckDB / SQLite
ai_engine/race_engineer_agent.py  # backend API (riepilogo stint)
ai_engine/agent_cli.py         # Claude Code / Codex / Antigravity in modalità non interattiva
ai_engine/mcp_server.py        # server MCP HTTP locale con token (7 strumenti)
ai_engine/radio.py, voice.py   # regole radio, Kokoro/Tsukumo, coda a priorità
ai_engine/stt.py               # trascrizione push-to-talk (Whisper locale / Tsukumo)
ui/hub_state.py, hub_data.py   # stato hub, proposte, fornitore dati per l'MCP
tests/                         # pytest, incluso un giro vero registrato al Red Bull Ring
ui/main_dashboard.py           # PyQt6 + pyqtgraph, una pagina per modulo in ui/pages/
                               # (pagine per chiave: "telemetry", "engineer", "box", ...)
```

## Decisioni tecniche prese
- **Fonte dati primaria: shared memory di AC letta dall'esterno via `mmap`** (`Local\acpmf_physics`,
  `Local\acpmf_graphics`, `Local\acpmf_static`), come fanno SimHub/CrewChief. Funziona identico con
  Content Manager (CM è solo un launcher, la memoria la scrive `acs.exe`). Dati validi solo in sessione
  di guida, non nei menu.
- Dati extra e comandi: **app Lua CSP** (non l'app Python 3.3), due file mappati
  `DeltaSuite_Bridge_Out_v1` / `_In_v1` con layout solo int/float/char[]; se si cambia il layout va
  cambiato in entrambi i file e alzata la versione. CSP 0.2.11 la carica a caldo (`LAZY = NONE`).
  Il setup risulta modificabile anche in pista nelle sessioni di prova (`isSetupAvailableToEdit`).
- Agente via CLI invece che API: `claude -p --output-format stream-json --tools "" --allowedTools
  mcp__deltasuite --strict-mcp-config`, sessione ripresa con `--resume`. Le modifiche passano sempre da
  `proponi_modifica` → conferma del pilota (tasto CSP o pulsante): mai applicate dall'agente.
- Voce: Kokoro (`kokoro-onnx`) in processo con i modelli di Tsukumo
  (`%LOCALAPPDATA%\Programs\Tsukumo\resources\tsukumo\models`). Trascrizione: `faster-whisper` locale,
  modello `base` (~1 s su CPU) dalla cache HF `~\.cache\huggingface\hub` (l'utente ha già tiny, base,
  large-v3); alternativa Tsukumo `/api/transcribe`. `DELTA_MUTE=1` silenzia la voce (test).
- Lingua: la voce scelta decide la lingua (it, en-us, en-gb, es, fr, pt; frasi in `ai_engine/lang.py`).
  Via radio l'agente risponde in quella lingua (`[RADIO] [English]`); l'analisi scritta resta in
  italiano come l'interfaccia.
- `hub_core` e il resto girano su **Python 3.11+** esterno.

## Build e ambiente
- venv di sviluppo fuori da OneDrive: `C:\Users\filip\.venvs\miohub` (Python 3.11).
- UI: **PyQt6 + pyqtgraph** (decisione presa). Entry point `run_hub.py`.
- **L'utente non vuole l'exe sul PC**: lo compila GitHub Actions (`.github/workflows/build.yml`) a ogni
  push su main; un tag `v*` crea una release in **bozza** che l'utente pubblica quando vuole (note in
  `RELEASE_NOTES.md`). Compilare in locale solo per debug, poi cancellare `dist\`.
- Exe: `.\build_exe.ps1` → `dist\DeltaSuite.exe` (PyInstaller onefile, spec `DeltaSuite.spec`,
  workpath in `%LOCALAPPDATA%\DeltaSuite\build`). scipy/pandas/pyarrow esclusi apposta: non servono.
- Build da bash se PowerShell si ferma sugli INFO di PyInstaller su stderr:
  `python -m PyInstaller DeltaSuite.spec --noconfirm --clean --workpath "$LOCALAPPDATA/DeltaSuite/build" --distpath dist`.
- Test: `python -m pytest` (dipendenze in `requirements-dev.txt`).
- Autotest UI/exe: variabile `DELTA_SELFTEST=<cartella>` → demo, screenshot di ogni pagina, verifica
  voce/app CSP/MCP in `selftest.txt`, uscita.
- Registrazioni: `%LOCALAPPDATA%\DeltaSuite\recordings\*.dsr`.
- Archivio: `%LOCALAPPDATA%\DeltaSuite\telemetry.duckdb`.
- Repo GitHub privato: `Ananas2916/delta-suite`.

## Prossimo passo
1. Prova in pista con l'utente al volante: push-to-talk (tasto assegnato nell'app CSP), voce in cuffia,
   conferma proposte dal volante.
2. Verificare ABS/TC: con la BMW M4 GT3 (mod trr) `absMode`/`tcMode` restano 0 mentre il setup dice 5/3.
3. Classifica con avversari veri (sessione con IA o online) e gap in gara.
4. Onboard in AC vero: verificare che `ac.GeometryShot` + `save` JPG funzionino con la CSP dell'utente,
   inquadrature delle telecamere (posizioni stimate dalle ruote), costo in FPS per qualità, soglie dei
   danni (`DAMAGE_THRESHOLDS`, prese da CrewChief) con un urto vero e danni attivi.

## Stato
- [x] Lettore shared memory (`hub_core/ac_shared_memory.py`, `telemetry_receiver.py`)
- [x] Hub completo con 6 moduli (7 con l'Onboard) + simulatore demo, exe compilato e autotestato
- [x] Riordino (16/10/2026): via il CAD/CFD, ingegnere AI e radio in un'unica pagina, barra laterale in sezioni
- [x] Verifica con AC vero (15/10/2026, Red Bull Ring, BMW M4 GT3): giri, settori, carburante ok
- [x] App CSP: lettura setup/pit/auto e comandi con conferma provati dal vivo (valori invariati)
- [x] Claude Code via MCP provato con dati veri (risposta radio in ~8 s)
- [ ] Push-to-talk e voce in cuffia provati in pista dall'utente
- [ ] Onboard live (video da app CSP + stato vettura) provato con AC vero
