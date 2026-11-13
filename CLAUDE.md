# Delta Suite — project context

(former name: Mio Hub Motorsport; the local folder is still `mio_hub_motorsport`)

## Goal
"All-in-One Engineering & Strategy Suite": a modular desktop app that brings together the features of
professional F1/WEC/GTWC software, connected to **original Assetto Corsa (2014)** — NOT ACC, NOT AC EVO (their
shared memory layouts differ). Open source under the MIT license (public repo since 0.5.9, 12/11/2026); no
dependency on commercial licences.

## Owner's setup
- Windows 11, Desktop synced to OneDrive: project in `%USERPROFILE%\OneDrive\Desktop\mio_hub_motorsport`
- Launches AC through **Content Manager** (almost certainly with Custom Shaders Patch)
- Working language with the owner: **Italian** (replies, explanations). Code, comments and docs are in
  **English** since 0.5.9; UI texts are English in the code, wrapped in `tr()`, with an Italian catalog
  (`hub_core/locales/it.py`) since 0.6.0; the radio phrases stay multilingual.

## Modules
Seven modules in two sidebar groups (`SECTIONS` in `ui/navigation.py`; the descriptions are the tooltips),
preceded by the **Overview** page (`ui/pages/general_page.py`, page key "general"): everything at once like on
the pit wall: session and flag, key numbers, main onboard with TV graphics, standings, GPS, car status and
alerts, strategy, hybrid battery, engineer proposals to confirm and the radio log. The CAD/CFD bridge was
removed (16/10/2026).

**On track**
1. **Live telemetry** (replaces MoTeC i2 / ATLAS / WinDARAB): 60–100 Hz acquisition (speed, pedals/steering,
   tyre temperatures and pressures, suspension, G-force, hybrid battery/ERS), recording and replay. Hybrids
   (18/10/2026): `kersCharge`, `kersInput`, `kersCurrentKJ`, ERS levels, MGU-H from physics;
   `hasKERS`/`hasERS`, per-lap limit (`ersMaxJ`/`kersMaxJ`) and maps from static; state and alerts in
   `car_status.hybrid_state`, only if the car is hybrid. The demo is a hybrid hypercar.
2. **Live onboard** (18/10/2026): up to 4 onboards at once (main + 3 secondary, like SRO broadcasts; ▲ swaps
   with the main one), Delta Suite cameras (T-cam, bonnet, rear, 4 wheels, chase; rivals too) and the car's F6
   cameras with names derived from position and direction (`f6_names`), TV graphics on top, track GPS (0.5.1:
   AI line `ai/fast_lane.ai` of the track in `hub_core/ac/track_map.py`, the same spline as the cars' lap
   position, cars placed on the map from `splinePosition`; without an AI line it is learned while driving;
   yellow/red/blue stretches from `hub_core/analysis/track_status.py`; click a car → main view) and a top-down
   car status: damage per zone (`carDamage`), tyres, brakes, suspension travel, dirt and alerts
   (`hub_core/analysis/car_status.py`). The video is rendered by the CSP app with `ac.GeometryShot` (an extra
   view, costs FPS), gets exposure + filmic curve + gamma via `ui.renderShader` (the extra view has none of the
   game's post-processing: without it it is very dark; alternatively YEBIS = game post-processing) and is
   handed to Delta Suite through the separate mapping `DeltaSuite_Onboard_v6` (`hub_core/ac/onboard_feed.py`;
   one view rendered per AC frame, the most overdue; secondary views at most 640×360) in three ways: shared
   D3D11 texture (`hub_core/ac/d3d_shared.py`, Delta Suite opens it trying every GPU and copies it itself: no
   GPU readback in AC; if it cannot be opened it falls back to memory), in memory as raw DDS rotating over 3
   slots (`ExtraCanvas:encode()` in CSP 0.2.11 only gives uncompressed DDS, ~0.9 MB at 640×360) or JPG in
   `%LOCALAPPDATA%\DeltaSuite\onboard` (CSP logs one line per file). The command bridge stays v1. Renders only
   with the page open and the video on. Tests on 18/10 (CSP 0.2.11 b3465, PC: Iris Xe + RTX 4060 Laptop):
   v1 dark and cockpit not rendered (→ "Bonnet"); v2 filmic 1.6 closest to the game, AC from 180 to ~150–165
   FPS with video, T-cam and wheels ok, rear covered by the tail (→ v3); v4 shared texture opened on GPU 1
   (NVIDIA), render in AC ~1 ms at every quality vs 5–9 ms in memory and 6–13 ms on file → default, with
   automatic fallback to memory. `sharedHandle(true)` (crossProcess): with false it is an id internal to the
   scripts and OpenSharedResource gives E_INVALIDARG. Manual test:
   `python tools/onboard_probe.py $env:LOCALAPPDATA\DeltaSuite\onboard_probe 6 [transports|views]`.
   Recordings (.dsr v2, 0.6.0) also hold the CSP app's cars at 5 Hz: a recorded race replays standings,
   flags and race calls — the way to turn a real race into a test.
3. **Race engineer** (former "AI Race Engineer" + "Radio & voice", merged): one agent for written chat and
   radio. Command-line agent (Claude Code with the owner's subscription; Codex, Antigravity or a custom
   command, Anthropic API as last option) that reads the data via MCP and proposes changes to confirm. Local
   rule-based radio (lap/delta, fuel, tyres, flags, and since 0.5.2 the F1-game-style calls in
   `ai_engine/race_calls.py`: first lap, overtakes, fastest lap, gap trends, close cars and cars pitting,
   leader on the last lap, finish, fuel saving, punctures, damage, worn tyres, limiter, yellows with the
   distance, session time; phrases in `ai_engine/phrases_race.py`, all languages side by side, variants
   separated by "|") read by Kokoro; push-to-talk from the wheel → local Whisper → agent in RADIO mode →
   spoken answer in the voice's language. Tabbed page: Conversation (chat + headset radio), Stint summary,
   Settings (agent, MCP, voice, microphone, radio rules).
4. **Pit & Setup** (page key "box"): live bias/ABS/TC/engine brake, setup, engineer proposals, pit stop and
   standings with gaps through the CSP Lua app `ac_app/DeltaSuiteBridge`.

**Analysis & strategy**
5. **Lap analysis**: overlaid laps (Delta-T, racing line, pedals, RPM), corner-by-corner comparison, DuckDB
   archive and Parquet export.
6. **Strategy & Timing** (replaces HH Timing / SBG RaceWatch): sectors, average fuel use, pit window, tyre
   degradation over the next 10–20 laps.
7. **Vehicle dynamics** (replaces ChassisSim / OptimumG / Adams): Pacejka (Magic Formula), suspension
   kinematics (roll centres, dynamic camber/toe, ride height).

## Structure
Details and import rules in `ARCHITECTURE.md` (checked by `tests/test_structure.py`).
```
ac_app/DeltaSuiteBridge/        # CSP Lua app: DeltaSuiteBridge.lua (command bridge/setup/rivals/radio
                                # buttons) + DeltaSuiteOnboard.lua (video, loaded with pcall(require))
hub_core/model.py              # TelemetrySample, CarEntry, AC enums (no dependencies)
hub_core/ac/                   # talks to AC; importable outside Windows too (kernel32 on first use)
  shared_memory.py, receiver.py  # AC pages → TelemetrySample (sample_from_pages shared with replay)
  recording.py                 # .dsr recording of the raw pages and ReplaySource
  csp_bridge.py                # CSP bridge (layout = DeltaSuiteBridge.lua), app installation, AC folder
  onboard_feed.py              # onboard video (DeltaSuite_Onboard_v6 = DeltaSuiteOnboard.lua, 4 views)
  d3d_shared.py                # reading the shared D3D11 texture (ctypes, COM vtable)
  track_map.py                 # track AI line (fast_lane.ai, pit_lane.ai) for the GPS
  setup_files.py, win32.py     # .ini setups in Documents (OneDrive); MappedView
hub_core/analysis/             # calculations, no AC: lap_recorder, lap_analysis, timing, race_strategy
                               # (also laps to go), vehicle_dynamics, car_status (alerts for the Onboard
                               # page and MCP), track_status (track line, slow/stopped cars, flags),
                               # live_lap (splits of the current lap and live delta to the best lap)
hub_core/database.py           # DuckDB / SQLite (best_laps: all-time best per car and track)
hub_core/i18n.py, locales/     # interface language: tr() + Italian catalog (tests/test_i18n.py checks it)
hub_core/remote/               # remote pit wall: rotating-code pairing (auth.py), web server (LAN + Tailscale),
                               # web app in plain JS (web/: index.html, app.js, app.css; on-demand onboard)
ai_engine/race_engineer_agent.py  # API backend (stint summary)
ai_engine/agent_cli.py         # Claude Code (or a custom command) in non-interactive mode
ai_engine/mcp_server.py        # local HTTP MCP server with token (7 tools: live_state, session_laps,
                               # compare_laps, current_setup, standings, session_archive, propose_change)
ai_engine/radio.py, voice.py   # radio rules, Kokoro/Tsukumo, priority queue
ai_engine/race_calls.py        # F1-game-style race calls (RaceContext from standings and yellows)
ai_engine/phrases_race.py      # phrases for those calls in it/en/es/fr/pt, with variants
ai_engine/stt.py               # push-to-talk transcription (local Whisper / Tsukumo)
ai_engine/voice_models.py      # Kokoro model location and one-click download (%LOCALAPPDATA%\DeltaSuite\models)
ai_engine/race_chatter.py      # the "chatty" engineer between the important calls (phrases_chatter.py)
ui/hub_state.py, hub_data.py   # hub state and signals, data provider for the MCP
ui/radio_controller.py, proposals.py, engineer_controller.py   # owned by HubState: radio+PTT, proposals, agent
ui/first_run.py                # get-started checklist on the Overview
ui/remote_data.py, remote_dialog.py   # hub side of the remote pit wall
ui/workers.py                  # TelemetryWorker (acquisition thread) and Job
ui/widgets/                    # reusable widgets: base, car_status, gps, timing_table, hybrid, sectors
                               # (splits and time with delta), onboard_hud (TV graphics), view_panel
ui/race_view.py                # data for standings/GPS/TV graphics/car status (Onboard and Overview)
ui/navigation.py               # sidebar sections and modules
ui/main_dashboard.py           # PyQt6 + pyqtgraph, one page per module in ui/pages/
                               # (pages by key: "general", "telemetry", "onboard", ...; onboard/ is a package)
tests/                         # pytest, including a real lap recorded at the Red Bull Ring
docs/                          # logo and README screenshots
```

## Technical decisions
- **Primary data source: AC's shared memory read from outside via `mmap`** (`Local\acpmf_physics`,
  `Local\acpmf_graphics`, `Local\acpmf_static`), like SimHub/CrewChief. Works the same with Content Manager
  (CM is just a launcher, `acs.exe` writes the memory). Data only valid in a driving session, not in menus.
- Extra data and commands: **CSP Lua app** (not the Python 3.3 app), two mapped files
  `DeltaSuite_Bridge_Out_v1` / `_In_v1` with int/float/char[] only layouts; if the layout changes, change it
  in both files and bump the version. CSP 0.2.11 hot-loads it (`LAZY = NONE`). The setup is editable on track
  too in practice sessions (`isSetupAvailableToEdit`). CSP buttons (0.5.9): `DeltaSuite/Engineer radio
  (hold)`, `DeltaSuite/Confirm proposal`, `DeltaSuite/Discard proposal`.
- Codex/Antigravity backends removed in 0.6.0 (untestable here): any agent works as a custom command.
- Agent via CLI instead of API: `claude -p --output-format stream-json --tools "" --allowedTools
  mcp__deltasuite --strict-mcp-config`, session resumed with `--resume`. Changes always go through
  `propose_change` → driver confirmation (CSP button or app button): never applied by the agent. Proposal
  kinds: brake_bias, abs, tc, engine_brake, setup.
- Voice: Kokoro (`kokoro-onnx`) in-process with Tsukumo's models
  (`%LOCALAPPDATA%\Programs\Tsukumo\resources\tsukumo\models`). Transcription: local `faster-whisper`, `base`
  model (~1 s on CPU) from the HF cache `~\.cache\huggingface\hub` (the owner already has tiny, base,
  large-v3); alternative Tsukumo `/api/transcribe`. `DELTA_MUTE=1` silences the voice (tests).
- Language: the chosen voice decides the language (it, en-us, en-gb, es, fr, pt; phrases in
  `ai_engine/lang.py`). Over the radio the agent answers in that language (`[RADIO] [English]`); the written
  analysis is in English like the interface (`[ANALYSIS] [English]`). Default voice `am_michael`.
- Modes: driver / engineer / analysis (values saved before 0.5.9 as pilota/ingegnere/analisi are migrated).
- `hub_core` and the rest run on external **Python 3.11+**.

## Build and environment
- Development venv outside OneDrive: `%USERPROFILE%\.venvs\miohub` (Python 3.11).
- UI: **PyQt6 + pyqtgraph** (decided). Entry point `run_hub.py`.
- **The owner does not want the exe on the PC**: GitHub Actions builds it (`.github/workflows/build.yml`) at
  every push to main; a `v*` tag creates a **draft** release that the owner publishes when they want (notes in
  `RELEASE_NOTES.md`). From cloud sessions tags do not get through (the git proxy only accepts the working
  branch): run the workflow by hand on the branch with the input `release` = `v0.6.0`, which creates the draft
  pointing at that commit (the tag is created on publish). Build locally only for debugging, then delete
  `dist\`.
- Spec trimmed on 13/11/2026: espeak dictionaries only for the radio languages (`ESPEAK_DICTS`, checked by
  `tests/test_build_spec.py`), no onnxruntime tools/quantization, no .py sources in datas: 176 → 161 MB.
- Exe: `.\build_exe.ps1` → `dist\DeltaSuite.exe` (PyInstaller onefile, spec `DeltaSuite.spec`, workpath in
  `%LOCALAPPDATA%\DeltaSuite\build`). scipy/pandas/pyarrow excluded on purpose: not needed.
- Build from bash if PowerShell stops on PyInstaller's INFO lines on stderr:
  `python -m PyInstaller DeltaSuite.spec --noconfirm --clean --workpath "$LOCALAPPDATA/DeltaSuite/build" --distpath dist`.
- Tests: `python -m pytest` (dependencies in `requirements-dev.txt`). With AC running and the CSP app loaded,
  `test_onboard_roundtrip_with_fake_app` attaches to the real onboard mapping and fails: environmental.
- UI/exe self-test: variable `DELTA_SELFTEST=<folder>` → demo, a screenshot of every page, voice/CSP app/MCP
  check in `selftest.txt`, exit. README screenshots: run it with `QT_QPA_PLATFORM=offscreen`,
  `QT_QPA_FONTDIR=C:/Windows/Fonts` and a 1920×1080 window (no window shows up; isolate QSettings and the DB).
- Recordings: `%LOCALAPPDATA%\DeltaSuite\recordings\*.dsr`.
- Archive: `%LOCALAPPDATA%\DeltaSuite\telemetry.duckdb`.
- GitHub repo (public since 0.5.9): `Ananas2916/delta-suite`.

## Next steps
1. On-track test with the owner driving: push-to-talk (button bound in the CSP app — rebind after 0.5.9),
   voice in the headset, confirming proposals from the wheel.
2. ABS/TC: with the BMW M4 GT3 (trr mod) `absMode`/`tcMode` stay 0 while the setup says 5/3; on 12/11/2026
   with the Mercedes-AMG GT3 Evo (trr) the CSP app read ABS 5/12 and TC 3/12, matching the setup: it is
   specific to that M4 mod, not to Delta Suite.
3. Standings with real rivals (session with AI or online) and race gaps.
4. Onboard (0.5.0): cameras computed in car space and brought into the world with
   `ac.findNodes('carRoot:N'):getWorldTransformationRaw()` (before: wheel centre + physics state → strong
   shaking; with the F6 cameras the owner saw it disappear); F6 from `ac.accessCarCamera(i)` (car 0 only,
   `.look` backwards). To check in AC: v6 with several views (FPS with 2-4 views:
   `onboard_probe.py <folder> 6 views`), F6 names, GPS with rivals. Damage thresholds
   (`DAMAGE_THRESHOLDS`, taken from CrewChief) with a real crash and damage on.
   Since 0.5.0 the video lives in `DeltaSuiteOnboard.lua`: check in AC that the `require` loads it.
5. Tested by the owner on 18/10 (Barcelona layout_moto, race with AI, trr_lmh_ferrari_499p hybrid): Overview
   with video ok. Seen and fixed in 0.5.1: laps to go were missing; AC's `flag` stayed yellow after the
   incident (now the yellow comes from the slow/stopped cars of the CSP app, AC's lasts only ~8 s if no car
   confirms it); map.png too bare (now the AI line drawn like a circuit, cars with position,
   yellow/red/blue stretches); the 499P declares `ersMaxJ` = 9.99e16 (= no per-lap limit).
   To check in AC: reading `fast_lane.ai` on real tracks (if the format does not match it is learned while
   driving), slow-car thresholds (`SLOW_FRACTION`, `SLOW_KMH`) in a real race.

## Status
- [x] Shared memory reader (`hub_core/ac/shared_memory.py`, `receiver.py`)
- [x] Full hub with 6 modules (7 with Onboard) + demo simulator, exe built and self-tested
- [x] Reorganisation (16/10/2026): CAD/CFD removed, AI engineer and radio on one page, sidebar in sections
- [x] Code reorganisation (18/10/2026): `hub_core/ac` and `hub_core/analysis`, CSP app split into bridge +
      onboard module, UI in widgets/pages/threads, boundaries checked by `tests/test_structure.py`; Windows build ok
- [x] Overview page and hybrid data (18/10/2026), tested by the owner in a race with the 499P
- [x] 0.5.1: laps to go, flags from slow/stopped cars, map from the AI line (tested in demo)
- [x] 0.5.2: live splits and delta, Int column, compound, green flag; F1-game-style engineer lexicon
      (tested in demo; to be heard in a real race)
- [x] 0.5.9 (12/11/2026): everything in English, MIT license, public repo, README with screenshots
- [x] 0.6.0 (13/11/2026): get-started checklist, voice download, Italian UI (tr), HubState split into
      controllers, rivals in recordings (.dsr v2), archive reference lap, strategy from the session,
      chatty engineer and remote pit wall (merged from claude/chatty-engineer-remote)
- [x] Test with real AC (15/10/2026, Red Bull Ring, BMW M4 GT3): laps, sectors, fuel ok
- [x] CSP app: setup/pit/car reading and commands with confirmation tested live (values unchanged)
- [x] Claude Code via MCP tested with real data (radio answer in ~8 s)
- [ ] Push-to-talk and headset voice tested on track by the owner
- [x] Live onboard: video from the CSP app tested with real AC (18/10, shared texture, 8 cameras, 4 qualities)
- [ ] Onboard: damage with a real crash and the full page tested by the owner
