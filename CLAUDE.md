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
Sette moduli in due gruppi in barra laterale (`SECTIONS` in `ui/navigation.py`; le descrizioni sono i
suggerimenti delle voci), preceduti dalla pagina **Generale** (18/10/2026, al posto della vecchia Home con le
schede dei moduli): tutto insieme come al muretto, per la squadra: sessione e bandiera, numeri chiave, onboard
principale con grafica TV, classifica, GPS, stato vettura e avvisi, strategia, batteria delle ibride, proposte
dell'ingegnere da confermare e registro della radio (`ui/pages/general_page.py`). Il CAD/CFD bridge è stato
tolto (16/10/2026): non c'entrava con la suite.

**In pista**
1. **Telemetria live** (sostituisce MoTeC i2 / ATLAS / WinDARAB): acquisizione 60–100 Hz (velocità,
   pedali/sterzo, temperature e pressioni gomme, sospensioni, G-force, batteria/ERS delle ibride),
   registrazione e replay. Ibride (18/10/2026): `kersCharge`, `kersInput`, `kersCurrentKJ`, livelli ERS,
   MGU-H dalla fisica; `hasKERS`/`hasERS`, limite per giro (`ersMaxJ`/`kersMaxJ`) e mappe dalla statica;
   stato e avvisi in `car_status.hybrid_state`, solo se l'auto è ibrida. Il demo è una hypercar ibrida.
2. **Onboard live** (18/10/2026): fino a 4 onboard insieme (principale + 3 secondari, come le dirette
   SRO; ▲ scambia con il principale), telecamere di Delta Suite (T-cam, cofano, posteriore, 4 ruote,
   inseguimento; anche sugli avversari) e F6 dell'auto con nomi ricavati da posizione e direzione
   (`f6_names`), grafica TV sopra, GPS della pista (0.5.1: linea AI `ai/fast_lane.ai` del tracciato in
   `hub_core/ac/track_map.py`, stessa spline della posizione sul giro delle auto, che si mettono sulla mappa da
   `splinePosition`; senza linea AI la si impara girando; tratti gialli/rossi/blu da
   `hub_core/analysis/track_status.py`; clic su un'auto → riquadro principale) e vista
   dall'alto dello stato vettura: danni per zona (`carDamage`), gomme, freni, corsa sospensioni, sporco e avvisi
   (`hub_core/analysis/car_status.py`). Il video lo rende l'app CSP con `ac.GeometryShot` (seconda vista, costa
   FPS), gli dà esposizione + curva filmica + gamma con `ui.renderShader` (la seconda vista non ha il
   post-processing del gioco: senza esce molto scura; in alternativa YEBIS = post-processing del gioco)
   e li passa a Delta Suite tramite la mapping a parte `DeltaSuite_Onboard_v6` (`hub_core/ac/onboard_feed.py`;
   una vista resa per fotogramma di AC, la più in ritardo; secondarie al massimo 640×360)
   in tre modi: texture D3D11 condivisa (`hub_core/ac/d3d_shared.py`, Delta Suite la apre provando tutte
   le GPU e la copia lei: niente lettura dalla GPU in AC; se non si apre si torna alla memoria), in
   memoria come DDS grezzo a rotazione su 3 posti (`ExtraCanvas:encode()` in CSP 0.2.11 dà
   solo DDS non compresso, ~0,9 MB a 640×360) oppure JPG in `%LOCALAPPDATA%\DeltaSuite\onboard` (CSP
   logga una riga per ogni file). Il ponte comandi resta v1. Rende solo con la pagina aperta e il video
   acceso. Prove del 18/10 (CSP 0.2.11 b3465, PC: Iris Xe + RTX 4060 Laptop): v1 scura e abitacolo non
   reso (→ "Cofano"); v2 filmica 1.6 la più simile al gioco, AC da 180 a ~150–165 FPS col video, T-cam e
   ruote ok, posteriore coperta dalla coda (→ v3); v4 texture condivisa aperta sulla GPU 1 (NVIDIA),
   render in AC ~1 ms a ogni qualità contro 5–9 ms in memoria e 6–13 ms su file → predefinita, con
   ritorno automatico alla memoria. `sharedHandle(true)` (crossProcess): con false è un id interno
   agli script e OpenSharedResource dà E_INVALIDARG. Prova a mano:
   `python tools/onboard_probe.py $env:LOCALAPPDATA\DeltaSuite\onboard_probe 6 [trasporti]`.
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
Dettagli e regole sugli import in `ARCHITECTURE.md` (controllate da `tests/test_structure.py`).
```
ac_app/DeltaSuiteBridge/        # app Lua per CSP: DeltaSuiteBridge.lua (ponte comandi/setup/avversari/
                                # tasti radio) + DeltaSuiteOnboard.lua (video, caricato con pcall(require))
hub_core/model.py              # TelemetrySample, CarEntry, enum di AC (nessuna dipendenza)
hub_core/ac/                   # parla con AC; si importa anche fuori da Windows (kernel32 al primo uso)
  shared_memory.py, receiver.py  # pagine di AC → TelemetrySample (sample_from_pages condiviso col replay)
  recording.py                 # registrazione .dsr delle pagine grezze e ReplaySource
  csp_bridge.py                # ponte CSP (layout = DeltaSuiteBridge.lua), installazione app, cartella AC
  onboard_feed.py              # video onboard (DeltaSuite_Onboard_v6 = DeltaSuiteOnboard.lua, 4 viste)
  d3d_shared.py                # lettura della texture condivisa D3D11 (ctypes, vtable COM)
  track_map.py                 # linea AI del tracciato (fast_lane.ai, pit_lane.ai) per il GPS
  setup_files.py, win32.py     # setup .ini in Documenti (OneDrive); MappedView
hub_core/analysis/             # calcoli, senza AC: lap_recorder, lap_analysis, timing, race_strategy
                               # (anche giri mancanti), vehicle_dynamics, car_status (avvisi per pagina
                               # Onboard e MCP), track_status (linea della pista, auto lente/ferme, bandiere)
hub_core/database.py           # DuckDB / SQLite
ai_engine/race_engineer_agent.py  # backend API (riepilogo stint)
ai_engine/agent_cli.py         # Claude Code / Codex / Antigravity in modalità non interattiva
ai_engine/mcp_server.py        # server MCP HTTP locale con token (7 strumenti)
ai_engine/radio.py, voice.py   # regole radio, Kokoro/Tsukumo, coda a priorità
ai_engine/stt.py               # trascrizione push-to-talk (Whisper locale / Tsukumo)
ui/hub_state.py, hub_data.py   # stato hub, proposte, fornitore dati per l'MCP
ui/workers.py                  # TelemetryWorker (thread di acquisizione) e Job
ui/widgets/                    # widget riusabili: base, car_status, gps, timing_table, hybrid,
                               # onboard_hud (grafica TV), view_panel (riquadro onboard)
ui/race_view.py                # dati per classifica/GPS/grafica TV/stato vettura (Onboard e Generale)
ui/navigation.py               # sezioni e moduli della barra laterale
ui/main_dashboard.py           # PyQt6 + pyqtgraph, una pagina per modulo in ui/pages/
                               # (pagine per chiave: "general", "telemetry", "onboard", ...; onboard/ è un pacchetto)
tests/                         # pytest, incluso un giro vero registrato al Red Bull Ring
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
4. Onboard (0.5.0): telecamere calcolate nello spazio dell'auto e portate nel mondo con
   `ac.findNodes('carRoot:N'):getWorldTransformationRaw()` (prima: centro ruote + stato fisico → forte
   tremolio; con le F6 l'utente l'ha visto sparire); F6 da `ac.accessCarCamera(i)` (solo auto 0, `.look`
   all'indietro). Da verificare in AC: v6 con più riquadri (FPS con 2-4 viste:
   `onboard_probe.py <cartella> 6 riquadri`), nomi delle F6, GPS con gli avversari. Soglie dei danni
   (`DAMAGE_THRESHOLDS`, prese da CrewChief) con un urto vero e danni attivi.
   Da 0.5.0 il video sta in `DeltaSuiteOnboard.lua`: verificare in AC che il `require` lo carichi.
5. Provato dall'utente il 18/10 (Barcellona layout_moto, gara con IA, trr_lmh_ferrari_499p ibrida): Generale
   con video ok. Visti e corretti in 0.5.1: mancavano i giri alla fine; la `flag` di AC restava gialla a
   incidente passato (ora la gialla viene dalle auto lente/ferme dell'app CSP, quella di AC vale solo ~8 s se
   nessuna auto la conferma); mappa map.png troppo spoglia (ora linea AI disegnata come un tracciato, auto con
   la posizione, tratti gialli/rossi/blu); la 499P dichiara `ersMaxJ` = 9.99e16 (= nessun limite per giro).
   Da verificare in AC: lettura di `fast_lane.ai` su piste vere (se il formato non torna si impara girando),
   soglie delle auto lente (`SLOW_FRACTION`, `SLOW_KMH`) in gara vera.

## Stato
- [x] Lettore shared memory (`hub_core/ac/shared_memory.py`, `receiver.py`)
- [x] Hub completo con 6 moduli (7 con l'Onboard) + simulatore demo, exe compilato e autotestato
- [x] Riordino (16/10/2026): via il CAD/CFD, ingegnere AI e radio in un'unica pagina, barra laterale in sezioni
- [x] Riordino del codice (18/10/2026): `hub_core/ac` e `hub_core/analysis`, app CSP in ponte + modulo
      onboard, UI in widget/pagine/thread, confini controllati da `tests/test_structure.py`; build Windows ok
- [x] Pagina Generale e dati delle ibride (18/10/2026), provata dall'utente in gara con la 499P
- [x] 0.5.1: giri mancanti, bandiere dalle auto lente/ferme, mappa dalla linea AI (provato in demo)
- [x] Verifica con AC vero (15/10/2026, Red Bull Ring, BMW M4 GT3): giri, settori, carburante ok
- [x] App CSP: lettura setup/pit/auto e comandi con conferma provati dal vivo (valori invariati)
- [x] Claude Code via MCP provato con dati veri (risposta radio in ~8 s)
- [ ] Push-to-talk e voce in cuffia provati in pista dall'utente
- [x] Onboard live: video dall'app CSP provato con AC vero (18/10, texture condivisa, 8 telecamere, 4 qualità)
- [ ] Onboard: danni con un urto vero e pagina completa provata dall'utente
