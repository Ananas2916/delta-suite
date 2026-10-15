# Delta Suite

Suite proprietaria di ingegneria e strategia per **Assetto Corsa** (originale, 2014).
Un'unica applicazione desktop che riunisce gli strumenti dei software professionali di
F1/WEC/GTWC, alimentata dalla telemetria letta in tempo reale dalla shared memory di AC.

| Modulo | Cosa fa | Al posto di |
|---|---|---|
| Telemetria live | Cruscotto 60–200 Hz: velocità, RPM, pedali, sterzo, gomme (temp/pressione/usura), freni, G-G, tabella giri e settori | MoTeC i2, ATLAS, WinDARAB |
| Analisi giri | Fino a 4 giri sovrapposti su distanza, Delta-T, traiettoria, cursore sincronizzato, archivio DuckDB, export Parquet | MoTeC i2, Pi Toolbox |
| Dinamica veicolo | Pacejka (Magic Formula) laterale/longitudinale, ellisse d'attrito, trasferimenti di carico con aero e centri di rollio, cinematica del quadrilatero | ChassisSim, OptimumG, Adams |
| Strategia & Timing | Consumo medio robusto, piano carburante e finestra pit, degrado gomme con previsione, sosta ottimale, giro ideale | HH Timing, SBG RaceWatch |
| CAD / CFD bridge | Viewer STL/OBJ con area frontale, mappe aero CL/CD vs ride height da OpenFOAM/Ansys con calcolatore live | viewer CAD, post-processing CFD |
| AI Race Engineer | Claude (`claude-opus-5-5`) legge il riepilogo dello stint e propone pressioni, setup e strategia | ingegnere di pista |

## Uso rapido

- **Eseguibile:** `dist\DeltaSuite.exe` (si genera con `.\build_exe.ps1`).
- **Da sorgente:** `pip install -r requirements.txt`, poi `python run_hub.py`.
- **Con AC:** avvia una sessione da Content Manager, poi nell'hub *Telemetria live → Avvia acquisizione*
  con sorgente "Assetto Corsa". I dati sono validi solo in pista, non nei menu.
- **Senza AC:** sorgente "Demo (simulatore)": una GT3 virtuale su un circuito sintetico, con consumi,
  temperature, usura e pit stop, utile per provare tutti i moduli.
- **AI Race Engineer:** serve una chiave API Anthropic (campo nella pagina oppure variabile
  `ANTHROPIC_API_KEY`).

L'archivio dei giri è in `%LOCALAPPDATA%\DeltaSuite\telemetry.duckdb`.

## Struttura

```
run_hub.py                     entry point (anche dell'exe)
hub_core/ac_shared_memory.py   strutture ctypes della shared memory di AC, apertura in sola lettura
hub_core/telemetry_receiver.py TelemetryReceiver -> TelemetrySample (+ console: python -m hub_core.telemetry_receiver)
hub_core/demo_source.py        simulatore con la stessa interfaccia del receiver
hub_core/lap_recorder.py       segmentazione in giri, settori, statistiche gomme/freni
hub_core/database.py           DuckDB: sessioni, giri, campioni; export Parquet
hub_core/vehicle_dynamics.py   Pacejka, trasferimenti di carico, cinematica sospensione
hub_core/race_strategy.py      carburante, finestra pit, degrado gomme, timing
hub_core/cad_bridge.py         mesh STL/OBJ, mappe aerodinamiche
ai_engine/race_engineer_agent.py  riepilogo stint + conversazione con Claude
ui/                            PyQt6 + pyqtgraph: finestra principale e una pagina per modulo
```

## Limiti noti

- La shared memory di AC espone solo la vettura del giocatore: gap e interval sugli avversari
  richiederanno l'app in-game (`ac_app/`, Python 3.3) o un plugin server.
- Il layout della shared memory è quello di AC 1.x: non compatibile con ACC né con AC EVO.

Autotest dell'eseguibile: `set DELTA_SELFTEST=C:\cartella` prima di avviarlo; l'app avvia il demo,
salva uno screenshot di ogni pagina e si chiude.
