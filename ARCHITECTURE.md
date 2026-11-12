# Delta Suite architecture

How the pieces are split, who may use whom and where new things go. The package boundaries are checked by
`tests/test_structure.py`: if an import breaks them, the tests fail.

## Layers

```
Assetto Corsa (acs.exe)                 shared memory acpmf_physics / graphics / static
  └─ CSP app ac_app/DeltaSuiteBridge    command bridge, setup, rivals, radio buttons, onboard video
        │ memory-mapped files (Local\...)
        ▼
hub_core/ac          talks to AC: reads the mappings, records them, opens the shared texture
hub_core/model.py    shared types: TelemetrySample, CarEntry, AC states and flags
hub_core/analysis    calculations: laps, corners, standings, strategy, dynamics, car status
hub_core/database.py DuckDB archive          hub_core/demo_source.py simulator
        ▼
ai_engine            engineer (Claude Code / Codex / API), MCP, radio, voice, transcription; radio without AI
                     in radio.py (lap, fuel, tyres, flags) + race_calls.py (F1-game-style race calls,
                     phrases in phrases_race.py) + race_chatter.py (the "chatty" engineer between the
                     important calls, chattiness 0-2, phrases in phrases_chatter.py)
hub_core/remote      remote access: rotating-code pairing (auth.py) and LAN web server + page (server.py, web/)
ui                   PyQt6: shared state, threads, widgets, one page per module
```

Rules (in `tests/test_structure.py`):

| Package | May not import |
|---|---|
| `hub_core` (all of it) | PyQt6, pyqtgraph, `ui`, `ai_engine` |
| `hub_core/analysis` | `hub_core.ac`, ctypes: it runs the same on real data, demo and replay |
| `hub_core/model.py` | nothing from the project, no ctypes |
| `ai_engine` | PyQt6, pyqtgraph, `ui` |
| `ui/widgets` | `ui.pages`, `ui.hub_state`, `ui.main_dashboard` |
| `ui/pages/<page>` | the other pages |

`hub_core` can be imported outside Windows too: kernel32 is loaded on first use (`hub_core/ac/win32.py`) and
there opening a mapping raises `FileNotFoundError`, as with AC not running. So the tests run anywhere; those
that create real mappings are marked `windows_only`.

## hub_core/ac

| File | What it does |
|---|---|
| `shared_memory.py` | ctypes structures of AC's three pages and consistent reads (`wstr` for text) |
| `receiver.py` | `TelemetryReceiver`: pages → `TelemetrySample` (`sample_from_pages`, also used by replay) |
| `recording.py` | `.dsr` recording of the raw pages and `ReplaySource` |
| `csp_bridge.py` | bridge with the CSP app (`DeltaSuite_Bridge_Out_v1` / `_In_v1`), app installation, AC folder |
| `onboard_feed.py` | onboard video (`DeltaSuite_Onboard_v6`): requests, frames, positions, F6 cameras |
| `d3d_shared.py` | opens and copies the D3D11 texture shared by the app (ctypes, COM vtable) |
| `track_map.py` | the track's AI line (`ai/fast_lane.ai`, `pit_lane.ai`) for the GPS |
| `setup_files.py` | `.ini` setups in Documents (also when redirected to OneDrive) |
| `win32.py` | `MappedView`: view of a mapping created by another process |

## hub_core/analysis

`lap_recorder.py` (laps and sectors), `lap_analysis.py` (automatic corners, comparison), `timing.py`
(standings, gap, interval), `race_strategy.py` (fuel, pit, tyre degradation, laps to go),
`vehicle_dynamics.py` (Pacejka, kinematics), `live_lap.py` (splits of the current lap, live delta to the best
lap), `car_status.py` (damage, tyres, brakes, suspension, battery → alerts; also for the MCP),
`track_status.py` (track line by lap position, typical speeds, slow or stopped cars → yellow/red stretches,
blue, the driver's flag). `HubState.track` keeps one per session: the AI line arrives at session start, the
zones update with every CSP app state.

## CSP app (ac_app/DeltaSuiteBridge)

- `DeltaSuiteBridge.lua`: command bridge, setup, pit, rivals, radio buttons. Confirmations and radio depend
  on it: nothing that is not essential goes here.
- `DeltaSuiteOnboard.lua`: onboard video, car positions, F6 cameras. The bridge loads it with
  `pcall(require, 'DeltaSuiteOnboard')`; if it fails, the bridge keeps working and the app window says why.
  It only exposes `M.update(dt, sim)` and `M.window()`.
- `manifest.ini`: `LAZY = NONE`, the app is active as soon as AC loads the session.

Delta Suite installs and updates every file in the folder (*Pit & Setup → Update CSP app*);
`app_needs_update` compares them one by one.

### Mappings

| Name | Written by | Lua side | Python side |
|---|---|---|---|
| `DeltaSuite_Bridge_Out_v1` | app | `OUT_LAYOUT` in DeltaSuiteBridge.lua | `BridgeOut` in csp_bridge.py |
| `DeltaSuite_Bridge_In_v1` | Delta Suite | `IN_LAYOUT` in DeltaSuiteBridge.lua | `BridgeIn` in csp_bridge.py |
| `DeltaSuite_Onboard_v6` | both (requests / frames) | `ONBOARD_LAYOUT` in DeltaSuiteOnboard.lua | `OnboardShared` in onboard_feed.py |

To change a layout: same fields in the same order in both files (only 4-byte int/float and char[]), a new
version in the mapping name and in the constant. The tests compare the Lua and Python layouts field by field.

## ui

- `main_dashboard.py`: window, sidebar, pages by key (`self.pages`, each in a `QScrollArea`). The first entry
  is the Overview page; sections, order and module descriptions live in `navigation.py`.
- `hub_state.py`: `HubState`, the shared state (active source, laps, CSP bridge, radio, engineer, MCP) and
  its signals; `hub_data.py` serves the data to the MCP and validates proposals.
- `remote_data.py`: `RemoteAccess`, the hub side of `hub_core/remote` (snapshot for the web page, actions
  routed to the Qt thread); `remote_dialog.py` shows the 10-second code, the addresses and the paired devices.
- `workers.py`: `TelemetryWorker` (acquisition thread: AC, demo or replay → samples, laps, bridge state
  every 0.1 s) and `Job` (blocking work off the UI thread).
- `widgets/`: reusable pieces. `__init__` has the base widgets (Card, ValueTile, plots, tables);
  `car_status.py` (car diagram), `gps.py` (track map), `timing_table.py` (standings), `hybrid.py` (battery
  and ERS), `onboard_hud.py` (TV graphics over the video), `view_panel.py` (onboard view with car and camera),
  `sectors.py` (splits and lap time with delta).
- `race_view.py`: what the "pit wall" pages show (standings, cars on the GPS, TV graphics, car status lines,
  why the video is missing), the same on Onboard and Overview.
- `pages/`: one page per module; large pages are packages (`pages/onboard/`). `general_page.py` (Overview)
  puts the race widgets together.
- Long text in pages: no `setWordWrap` on labels (inside a `QScrollArea` the height-for-width makes the page
  taller); lines are broken by hand.

### Data flow

```
TelemetryWorker (thread)  ── sample_ready / lap_completed / bridge_state ──▶ HubState ──▶ pages
Onboard / Overview (QTimer) ── hub.onboard_feed: requests and frames, straight on the onboard mapping
```

There is a single video link (`hub.onboard_feed`), but only the visible page uses it: a hidden page sends no
requests and disconnects when it closes, so AC renders the extra views only when needed.

### Adding a page

1. `ui/pages/<name>_page.py` (or a package if it grows), with a class that takes `hub`.
2. Register it in `MainWindow.pages` and in `SECTIONS` in `navigation.py`.
3. Take the common pieces from `ui/widgets`; if a widget is used by several pages, it goes there and not in a
   page.

## Tests

`python -m pytest`. On Linux everything runs except the tests with real mappings (`windows_only`) and the
ones that need local Whisper/Kokoro. GitHub Actions runs them on Windows at every push to main, builds the
exe and self-tests it (`DELTA_SELFTEST`); it can be run by hand on a branch (workflow_dispatch).
