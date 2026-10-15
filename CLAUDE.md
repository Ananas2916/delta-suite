# Mio Hub Motorsport — contesto di progetto

## Obiettivo
Suite software proprietaria "All-in-One Engineering & Strategy Suite" che raggruppa in un unico
ecosistema modulare le funzionalità dei software professionali F1/WEC/GTWC, interfacciata con
**Assetto Corsa originale (2014)** — NON ACC, NON AC EVO (hanno layout di shared memory diversi).
Codice proprietario dell'utente, nessuna dipendenza da licenze commerciali.

## Setup utente
- Windows 11, Desktop sincronizzato su OneDrive: progetto in `C:\Users\filip\OneDrive\Desktop\mio_hub_motorsport`
- Avvia AC tramite **Content Manager** (quasi certamente con Custom Shaders Patch)
- Lingua di lavoro: italiano

## Moduli previsti
1. **Telemetria & Live Data** (sostituisce MoTeC i2 / ATLAS / WinDARAB): acquisizione 60–100 Hz
   (velocità, input pedali/sterzo, temperature e pressioni gomme, sospensioni, G-force, KERS),
   storage su DuckDB/Parquet, grafici sovrapposti tra giri (Delta-T, traiettoria, pedali, RPM).
2. **Dinamica veicolo & pneumatici** (sostituisce ChassisSim / OptimumG / Adams): modello Pacejka
   (Magic Formula) con NumPy/SciPy, cinematica sospensioni (centri di rollio, camber/toe dinamici, ride height).
3. **Strategia & Timing** (sostituisce HH Timing / SBG RaceWatch): settori, gap/interval, consumo
   carburante medio, pit-window, predittore degrado gomme (scikit-learn/PyTorch) sui 10–20 giri successivi.
4. **CAD/FEA/CFD bridge**: niente solutori propri; viewer di geometrie `.stl`/`.obj` e import di
   coefficienti aero (CL, CD, mappe vs ride height) esportati da OpenFOAM/Ansys.
5. **AI Race Engineer** (Claude, modello `claude-opus-5-5`): riceve riassunto stint, restituisce
   strategia/setup (pressioni, lunghezza stint, ecc.).

## Struttura
```
ac_app/MioHubTelemetry.py      # app in-game (opzionale, vedi decisioni)
hub_core/telemetry_receiver.py # acquisizione dati
hub_core/vehicle_dynamics.py   # Pacejka & cinematica
hub_core/race_strategy.py      # carburante, pit, timing
hub_core/database.py           # DuckDB / SQLite
ai_engine/race_engineer_agent.py
ui/main_dashboard.py           # PyQt6 o Web/React (da decidere)
```

## Decisioni tecniche prese
- **Fonte dati primaria: shared memory di AC letta dall'esterno via `mmap`** (`Local\acpmf_physics`,
  `Local\acpmf_graphics`, `Local\acpmf_static`), come fanno SimHub/CrewChief. Funziona identico con
  Content Manager (CM è solo un launcher, la memoria la scrive `acs.exe`). Dati validi solo in sessione
  di guida, non nei menu.
- L'app in-game UDP (`ac_app/`) diventa **opzionale**; se serve, deve essere compatibile con il
  **Python 3.3 embedded** di AC (niente librerie moderne). Si attiva da CM → Impostazioni → Assetto Corsa → App Python.
- `hub_core` e il resto girano su **Python 3.11+** esterno.
- CSP può fornire dati extra via app Lua, da valutare più avanti.

## Build e ambiente
- venv di sviluppo fuori da OneDrive: `C:\Users\filip\.venvs\miohub` (Python 3.11).
- UI: **PyQt6 + pyqtgraph** (decisione presa). Entry point `run_hub.py`.
- Exe: `.\build_exe.ps1` → `dist\MioHubMotorsport.exe` (PyInstaller onefile, spec `MioHubMotorsport.spec`,
  workpath in `%LOCALAPPDATA%\MioHub\build`). scipy/pandas/pyarrow esclusi apposta: non servono.
- Autotest UI/exe: variabile `MIOHUB_SELFTEST=<cartella>` → demo, screenshot di ogni pagina, uscita.
- Archivio: `%LOCALAPPDATA%\MioHub\telemetry.duckdb`.
- Repo GitHub privato: `Ananas2916/mio_hub_motorsport`.

## Prossimo passo
1. Test reale in pista con AC: confrontare valori dell'hub con quelli in gioco (marcia, settori,
   `lastSectorTime`, pressioni in psi, `trackSPlineLength`).
2. Gap/interval avversari: richiede app in-game (`ac_app/`, Python 3.3) o plugin server.

## Stato
- [x] Lettore shared memory (`hub_core/ac_shared_memory.py`, `telemetry_receiver.py`)
- [x] Hub completo con 6 moduli + simulatore demo, exe compilato e autotestato
- [ ] Verifica con AC vero (finora testato solo con mapping simulate e simulatore demo)
- [ ] AI Race Engineer provato con chiave reale (verificato solo che la richiesta sia ben formata)
