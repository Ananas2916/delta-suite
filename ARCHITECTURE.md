# Architettura di Delta Suite

Come sono divisi i pezzi, chi può usare chi e dove mettere le cose nuove. I confini tra i pacchetti li
controlla `tests/test_structure.py`: se un import li viola, i test falliscono.

## Livelli

```
Assetto Corsa (acs.exe)                 shared memory acpmf_physics / graphics / static
  └─ app CSP ac_app/DeltaSuiteBridge    ponte comandi, setup, avversari, tasti radio, video onboard
        │ file mappati in memoria (Local\...)
        ▼
hub_core/ac          parla con AC: legge le mapping, le registra, apre la texture condivisa
hub_core/model.py    tipi comuni: TelemetrySample, CarEntry, stati e bandiere di AC
hub_core/analysis    calcoli: giri, curve, classifica, strategia, dinamica, stato vettura
hub_core/database.py archivio DuckDB          hub_core/demo_source.py simulatore
        ▼
ai_engine            ingegnere (Claude Code / Codex / API), MCP, radio, voce, trascrizione
ui                   PyQt6: stato condiviso, thread, widget, una pagina per modulo
```

Regole (in `tests/test_structure.py`):

| Pacchetto | Non può importare |
|---|---|
| `hub_core` (tutto) | PyQt6, pyqtgraph, `ui`, `ai_engine` |
| `hub_core/analysis` | `hub_core.ac`, ctypes: gira uguale su dati veri, demo e replay |
| `hub_core/model.py` | niente del progetto, niente ctypes |
| `ai_engine` | PyQt6, pyqtgraph, `ui` |
| `ui/widgets` | `ui.pages`, `ui.hub_state`, `ui.main_dashboard` |
| `ui/pages/<pagina>` | le altre pagine |

`hub_core` si importa anche fuori da Windows: kernel32 si carica al primo uso (`hub_core/ac/win32.py`) e
lì aprire una mapping dà `FileNotFoundError`, come con AC spento. Così i test girano ovunque; quelli che
creano mapping vere sono marcati `windows_only`.

## hub_core/ac

| File | Cosa fa |
|---|---|
| `shared_memory.py` | strutture ctypes delle tre pagine di AC e lettura coerente (`wstr` per i testi) |
| `receiver.py` | `TelemetryReceiver`: pagine → `TelemetrySample` (`sample_from_pages`, usato anche dal replay) |
| `recording.py` | registrazione `.dsr` delle pagine grezze e `ReplaySource` |
| `csp_bridge.py` | ponte con l'app CSP (`DeltaSuite_Bridge_Out_v1` / `_In_v1`), installazione dell'app, cartella di AC |
| `onboard_feed.py` | video onboard (`DeltaSuite_Onboard_v6`): richieste, fotogrammi, posizioni, telecamere F6 |
| `d3d_shared.py` | apre e copia la texture D3D11 condivisa dall'app (ctypes, vtable COM) |
| `track_map.py` | linea AI del tracciato (`ai/fast_lane.ai`, `pit_lane.ai`) per il GPS |
| `setup_files.py` | setup `.ini` nei Documenti (anche rediretti su OneDrive) |
| `win32.py` | `MappedView`: vista su una mapping creata da un altro processo |

## hub_core/analysis

`lap_recorder.py` (giri e settori), `lap_analysis.py` (curve automatiche, confronto), `timing.py`
(classifica, gap, interval), `race_strategy.py` (carburante, pit, degrado gomme, giri mancanti),
`vehicle_dynamics.py` (Pacejka, cinematica), `car_status.py` (danni, gomme, freni, sospensioni, batteria →
avvisi; anche per l'MCP), `track_status.py` (linea della pista per posizione sul giro, velocità tipiche, auto
lente o ferme → tratti gialli/rossi, blu, bandiera per il pilota). `HubState.track` ne tiene una per sessione:
la linea AI arriva a inizio sessione, le zone si aggiornano a ogni stato dell'app CSP.

## App CSP (ac_app/DeltaSuiteBridge)

- `DeltaSuiteBridge.lua`: ponte comandi, setup, pit, avversari, tasti radio. È la parte da cui dipendono
  conferme e radio: niente di non indispensabile.
- `DeltaSuiteOnboard.lua`: video onboard, posizioni delle auto, telecamere F6. Lo carica il ponte con
  `pcall(require, 'DeltaSuiteOnboard')`; se non parte, il ponte va lo stesso e la finestra dell'app dice
  perché. Espone solo `M.update(dt, sim)` e `M.window()`.
- `manifest.ini`: `LAZY = NONE`, l'app è attiva da quando AC carica la sessione.

Delta Suite installa e aggiorna tutti i file della cartella (*Box & Assetto → Aggiorna app CSP*);
`app_needs_update` li confronta uno per uno.

### Mapping

| Nome | Scrive | Lato Lua | Lato Python |
|---|---|---|---|
| `DeltaSuite_Bridge_Out_v1` | app | `OUT_LAYOUT` in DeltaSuiteBridge.lua | `BridgeOut` in csp_bridge.py |
| `DeltaSuite_Bridge_In_v1` | Delta Suite | `IN_LAYOUT` in DeltaSuiteBridge.lua | `BridgeIn` in csp_bridge.py |
| `DeltaSuite_Onboard_v6` | entrambi (richieste / fotogrammi) | `ONBOARD_LAYOUT` in DeltaSuiteOnboard.lua | `OnboardShared` in onboard_feed.py |

Per cambiare un layout: stessi campi nello stesso ordine nei due file (solo int/float a 4 byte e char[]),
nuova versione nel nome della mapping e nella costante. I test confrontano i layout Lua e Python campo
per campo.

## ui

- `main_dashboard.py`: finestra, barra laterale, pagine per chiave (`self.pages`, ognuna in uno
  `QScrollArea`). La prima voce è la pagina Generale; sezioni, ordine e descrizioni dei moduli stanno in
  `navigation.py`.
- `hub_state.py`: `HubState`, lo stato condiviso (sorgente attiva, giri, ponte CSP, radio, ingegnere,
  MCP) e i suoi segnali; `hub_data.py` fornisce i dati all'MCP e valida le proposte.
- `workers.py`: `TelemetryWorker` (thread di acquisizione: AC, demo o replay → campioni, giri, stato del
  ponte ogni 0,1 s) e `Job` (lavori bloccanti fuori dal thread della UI).
- `widgets/`: pezzi riusabili. `__init__` ha i widget di base (Card, ValueTile, grafici, tabelle);
  `car_status.py` (schema dell'auto), `gps.py` (mappa della pista), `timing_table.py` (classifica),
  `hybrid.py` (batteria ed ERS), `onboard_hud.py` (grafica TV sopra il video), `view_panel.py` (riquadro
  onboard con auto e telecamera).
- `race_view.py`: cosa mostrano le pagine "da muretto" (classifica, auto sul GPS, grafica TV, righe dello
  stato vettura, motivo del video assente), uguale in Onboard e Generale.
- `pages/`: una pagina per modulo; le pagine grandi sono pacchetti (`pages/onboard/`). `general_page.py`
  mette insieme i widget di gara.
- Testi lunghi nelle pagine: niente `setWordWrap` sulle etichette (in una `QScrollArea` l'altezza
  calcolata "per larghezza" allunga la pagina); righe spezzate a mano.

### Flusso dei dati

```
TelemetryWorker (thread)  ── sample_ready / lap_completed / bridge_state ──▶ HubState ──▶ pagine
Onboard / Generale (QTimer) ── hub.onboard_feed: richieste e fotogrammi, direttamente sulla mapping onboard
```

Il collegamento al video è uno solo (`hub.onboard_feed`), ma lo usa solo la pagina visibile: una pagina
nascosta non manda richieste e alla chiusura scollega, così AC rende le viste in più solo quando servono.

### Aggiungere una pagina

1. `ui/pages/<nome>_page.py` (o un pacchetto se cresce), con una classe che riceve `hub`.
2. Registrarla in `MainWindow.pages` e in `SECTIONS` di `navigation.py`.
3. Prendere i pezzi comuni da `ui/widgets`; se un widget serve a più pagine, va lì e non in una pagina.

## Test

`python -m pytest`. Su Linux girano tutti tranne quelli con mapping vere (`windows_only`) e quelli che
chiedono Whisper/Kokoro in locale. GitHub Actions li fa girare su Windows a ogni push su main, compila
l'exe e lo autotesta (`DELTA_SELFTEST`); si può lanciare a mano su un branch (workflow_dispatch).
