## Delta Suite 0.6.2 — a new look

**New layout**: a top bar with the views (Home, Race, Onboard, Telemetry, Pit & Setup, Strategy, Analysis,
Engineer, Ambient) replaces the sidebar; a live strip shows position, lap and delta, gaps ahead and behind with
the trend, fuel margin and battery. Mode, language, theme and remote access moved to *Settings* (⚙).

- **Home**: ready to drive, status of everything Delta Suite needs, last session, personal bests, the track.
- **Race**: the track coloured where you gain or lose against your best lap, corner chips that explain why,
  standings, radio with suggested questions, car status, and a race timeline with the forecast to the finish.
- **Ambient**: full screen delta and gap ahead, for a second monitor.
- **Strategy**: no-stop, one-stop and two-stop plans compared.

To go back to the previous look, download 0.6.1.

---

## Delta Suite 0.6.1 — the whole pit wall in a browser

**Remote pit wall, now the full suite**: from another PC, a tablet or a phone — on your home network or from
anywhere through [Tailscale](https://tailscale.com) — open the address shown in *Remote access* and you get:
- *Pit wall*: position, lap and live delta, pedals, fuel, hybrid battery, tyres, track map with yellow/red/blue
  zones, standings with gap and interval, car alerts, the engineer's proposals and the radio;
- *Onboard*: the onboard video with camera, car and quality selection. It is rendered in AC **only while
  someone is watching**: switch tab or close the browser and it stops within 3 seconds (no FPS lost);
- *Pit & Setup*: the current setup and live adjustments (brake bias, ABS, TC, engine brake, setup items) sent as
  proposals to confirm — from the browser, Delta Suite or the wheel;
- *Strategy*: fuel plan and pit window, tyre degradation forecast, laps with sectors;
- *Engineer*: chat with the AI engineer, messages read out to the driver, and the radio audio played in the
  browser.

Plain HTML and JavaScript, no frameworks: it runs smoothly on an old laptop. The *Remote access* window now
lists the LAN address (lowest latency) and the Tailscale one separately.

**Interface themes**: pick one of seven colour themes under *Theme* in the sidebar.

**Fixes**
- The TV graphics over the onboard video failed to draw with live video from AC (demo and replay were fine).

**Under the hood**
- The exe is ~15 MB smaller (176 → 161 MB): only the pronunciation data of the six radio languages, no model
  tools that are never used.
- The memory layouts shared with the CSP app are now checked byte for byte by the tests, and a layout change
  without a new version fails the build.

The CSP app is unchanged: no need to update it from 0.6.0.

---

## Delta Suite 0.6.0 — easier to start, chattier on the radio, in your language

**Get started in minutes**
- A *Get started* list on the Overview shows what is ready and what is missing — Assetto Corsa, the CSP app,
  the wheel buttons, the AI engineer, the voice, push-to-talk — each with the button that fixes it. It hides
  itself when everything is green.
- **Download voice**: the engineer's voice (Kokoro, 34 voices, ~120 MB) now downloads with one click from
  *Race engineer → Settings*; no other program needed.
- Each release ships a SHA-256 checksum next to the exe. The exe is not signed yet: if Windows SmartScreen
  warns you, click *More info → Run anyway*.

**Italian interface**: *Language* in the sidebar switches between English and Italian (applied at the next
start). The radio keeps speaking the language of the chosen voice; the AI engineer writes its analysis in the
interface language.

**A chattier race engineer** (still all local, instant and free): lights out, overtakes and lost places by the
rival's name, rivals' pit stops with undercut/overcut, your stop and tyres up to temperature, purple sectors,
pace drops, half distance, "bring it home", practice timesheets, and short updates when the radio has been
quiet. Choose how much it talks in *Settings → Automatic radio → Engineer* (Essential, Normal, Chatty).
Optionally, every N race laps the AI engineer says one thing on its own (off by default). Your own best lap is
now called "Personal best", so it no longer sounds like the race's fastest lap.

**Remote pit wall**: follow the session from another PC, tablet or phone on the same network — live data,
standings, laps, radio — and act as the engineer: confirm proposals, talk to the driver, ask the AI engineer.
Pair with a 6-digit code that changes every 10 seconds (sidebar *Remote access*, off by default).

**Analysis**
- *Delta vs all-time best* (Live telemetry): the live delta can use your fastest lap ever for this car and
  track, not just today's.
- *Reference from the archive* (Lap analysis): overlay and compare against a lap from another session.
- *Strategy* fills race type, laps, time left and fuel from the session; untick it to try your own numbers.
- Recordings now also store the rivals: replaying a race brings back standings, gaps, yellow flags and race
  calls exactly as they happened.

**Also**
- The CSP app window has a new look and shows the connection and the radio transmitting. Update it from
  *Pit & Setup* (or the *Get started* list).
- The untested Codex and Antigravity options were removed: any agent can still be plugged in as a *custom
  command*.

---

## Delta Suite 0.5.9 — now in English, and open source

**Delta Suite speaks English.** The whole app is now in English: pages, buttons, alerts, flags, the TV
graphics, the CSP app window and the engineer's written analysis. The radio still speaks the language of the
voice you pick (English US/UK, Italian, Spanish, French, Portuguese), and the default voice is now
Michael (English US).

**Open source under the MIT license.** The code is public on GitHub; contributions are welcome.

What changes if you already use Delta Suite:
- **Update the CSP app** (*Pit & Setup → Update CSP app*) and **bind the wheel buttons again** in the
  Delta Suite Bridge window in game: they are now called *Engineer radio (hold)*, *Confirm proposal* and
  *Discard proposal*.
- The AI engineer's tools have English names (`live_state`, `session_laps`, `compare_laps`,
  `current_setup`, `standings`, `session_archive`, `propose_change`). If you copied the MCP configuration
  into an interactive agent, nothing to do: the address and token are the same as before.
- Your settings are kept, including the mode (Driver / Engineer / Analysis) and the chosen voice.
- Fixed: closing the app while a lap was being saved could print an error.

---

## Delta Suite 0.5.2 — splits and a more talkative engineer

**Splits and delta**, like broadcast timing:
- *Lap time with live delta* to your best valid lap (+0.71 in red if you are slower, green if faster), on the
  Overview, in Telemetry and in the TV graphics;
- *sectors S1, S2, S3* as they close: purple if it is your best, yellow if slower, white for the one in
  progress; at the start of a lap those of the lap just closed stay for a few seconds.
- The *Int* column in the standings (gap to the car ahead); in the strategy the fitted compound, laps on the
  tyres, wear, air and track temperature; a *green flag* for a few seconds when the yellow ends.

**Race engineer without AI**, in the style of the F1 games, in every radio language and with more variants so
it does not repeat itself:
- end of the first lap with the places gained or lost from the grid; overtakes made and suffered; fastest lap
  of the race;
- gaps with the trend ("ahead 1.2, closing 3 tenths a lap"); a car ahead or behind within a second; rivals
  pitting;
- the leader on the last lap; chequered flag with the result (win, podium, position);
- fuel: "save fuel, lift and coast" when it is not enough to finish, and the all clear when it is again;
- puncture (box, box), damage per zone, worn tyres, limiter forgotten in the pit lane;
- yellow ahead with the distance ("double yellow, stopped car in 350 metres"), then "track clear";
- in practice and qualifying: 5 minutes and final minute of the session.
Each group can be switched on or off in *Race engineer → Settings → Automatic radio*.

---

## Delta Suite 0.5.1 — laps to go, real flags, new map

From the first race with 0.5.0:
- **Laps to go**: on the Overview ("Lap 9/25", "16 laps", "FINAL LAP"; in timed races an estimate with the
  time left), in the TV graphics and in Telemetry; in the strategy, the fuel at the finish ("3.2 L spare" or
  "a stop is needed"). The radio warns at 10, 5 and 3 laps from the end and on the last lap.
- **Flags**: the yellow no longer stays on after the incident is over. Delta Suite watches for slow or stopped
  cars on track (from the CSP app) and shows the yellow only if one is ahead of you, with the distance ("slow
  car in 350 m"; "DOUBLE YELLOW · stopped car" if it is stopped); AC's yellow on its own lasts a few seconds.
  Blue, chequered, black and penalty as AC gives them, with the full text (before it was a small coloured box).
- **New map**: the track drawn like a circuit, from AC's track line (the same AC uses to compute the lap
  position), with pit lane, finish line and the cars as circles with their position: you in yellow, the
  leader in purple, cars in the pits hollow. Stretches turn yellow where a car is slow, red where one is
  stopped, blue behind you when you have the blue flag. The cars are on the map even with the video off.
- **Hybrids**: cars with no per-lap energy limit (e.g. the 499P) no longer show a limit of
  99999998430675 kJ.
- The AI engineer also sees laps to go, the flag and the fuel at the finish.

---

## Delta Suite 0.5.0 — Overview, hybrids, more onboards and GPS

**New Overview page** (the first one, replacing the old Home): everything at once, like on the pit wall.
Session and flag; position, lap, times, fuel and time left; the onboard with TV graphics (click a car in the
standings or on the GPS to watch it); standings, GPS and car status with alerts; strategy (fuel use, laps of
fuel, ideal lap, stint, wear); hybrid battery; the engineer's proposals to confirm or discard and the radio
log. The module descriptions are now the sidebar tooltips.

**Hybrid cars**: if the car has KERS or ERS, Delta Suite shows the battery charge, whether it is deploying or
charging, the energy used in the lap against the limit, power map, recovery and where the MGU-H goes: in
Telemetry (Hybrid card), in the TV graphics (bar next to the pedals), in the car status and on the Overview.
Alerts at low (20%) and empty battery and when the lap energy is used up; the radio says it (once, until it
recharges) and it can be switched off in the radio rules. The AI engineer sees the same data. The demo is now
a hybrid hypercar.

**Live onboard**
- *No more shaking*: the cameras follow the bodywork drawn by AC, no longer the wheel centre (which moves with
  the suspension).
- *Up to 4 onboards at once*, as in broadcasts with several feeds: a main view with the TV graphics and up to
  three secondary ones with the car and camera of your choice; ▲ brings a secondary view into the main one.
  Each view is an extra one rendered by AC: secondary views run at 640×360 or 480×270 and AC renders one per
  frame, so the cost does not spike.
- *Your car's F6 cameras* (CSP's "Car" ones: behind the driver, dashboard, side…) with names derived from
  where they are mounted, and Delta Suite's cameras grouped and with shorter names.
- *GPS*: the track with every car and its position, from AC's map of the track (or drawn from the car's path
  in demo and replay); open views get a circle in their colour on the car they show, and clicking a car puts
  it in the main view.
- *Standings next to the onboards*: position, driver, gap and last lap, with the view colour on the cars on
  screen; the small views also show gap and last lap. The car diagram is in the "Car status" tab, the map
  below is bigger.

**Window**: on a screen scaled to 150% it is no longer cut on the right; wide pages scroll. In the car status
the tyre labels no longer spill out of the narrow column.

**Under the hood**: the code was reorganised to grow without becoming a tangle. No feature changes, but:
- the CSP app is now made of two files, the bridge (setup, commands, radio) and the onboard module: if the
  video has problems, confirmations and radio keep working and the app window says what is wrong;
- Delta Suite notices if *any* of the app files in AC is outdated, not just the main one.

The CSP app must be updated (*Pit & Setup → Update CSP app*), which now also installs
`DeltaSuiteOnboard.lua`.

---

## Delta Suite 0.4.0 — live onboard

**New Live onboard page** (On track, right after telemetry), like on the pit wall:
- *Onboard video*: the CSP app renders a camera mounted on the car — T-cam, bonnet (driver view), rear, the
  four wheels or chase — on rivals' cars too, with TV-style graphics on top: speed, gear, RPM, pedals,
  steering, lap and times, and the most severe alert highlighted;
- *Car status*: the car seen from above with damage per zone, tyres (temperature, pressure, wear, dirt),
  brakes and suspension travel, plus the list of alerts: damage, puncture, cold or overheating tyres, wear,
  brakes, suspension bottoming out, fuel, off track, limiter on.
- The video goes from AC to Delta Suite as a texture shared on the graphics card: in game it costs about 1 ms
  per frame at every quality (tested with an RTX 4060 Laptop); if that is not possible, it goes through
  memory. Colours and exposure are tuned to look like the game (the second view has none of its filters).
- Quality from 480×270 to 1280×720 and adjustable brightness; the video is only rendered with the page open
  and turns off with a click, so it costs no FPS on track when not needed. In demo and replay the car status
  remains.
- The AI engineer sees the same car status (damage, dirt, suspension, alerts) in its live state.

The CSP app must be updated (*Pit & Setup → Update CSP app*); CSP reloads it by itself, otherwise just
restart the session in AC.

---

## Delta Suite 0.3.0 — tidier

**Reorganised interface.** Six modules in two groups, the same in the sidebar and on the Home page:
- **On track:** Live telemetry · Race engineer · Pit & Setup
- **Analysis & strategy:** Lap analysis · Strategy & Timing · Vehicle dynamics

**Race engineer on a single page** (previously "AI Race Engineer" and "Radio & voice"):
- *Conversation*: chat with the engineer and, next to it, the headset radio with the push-to-talk button;
  questions asked over the radio show up in the chat, because it is the same conversation;
- *Stint summary*: the stint data in a table;
- *Settings*: AI agent, MCP link, voice and language, microphone and transcription, automatic radio rules,
  all in one place.

**Removed the CAD / CFD bridge**: it did not belong with the rest of the suite. The exe is also lighter
(no OpenGL).

---

Also includes the 0.2.0 changes, which were never published:

**Engineer in your headset.** Like the engineer in the F1 games, but with an AI where the script cannot
reach:
- instant radio, without AI and without spending tokens: lap time and delta, fuel, tyres out of the window,
  gaps, flags; it only speaks when you are not braking or mid-corner;
- push-to-talk from the wheel: ask the question, the transcription is local (Whisper) and the AI engineer
  answers in your headset with the real session data;
- voice of your choice (Kokoro, 34 voices): the spoken language follows the voice: Italian, English US/UK,
  Spanish, French, Portuguese.

**AI engineer with your subscription.** Claude Code (or Codex, Antigravity, a custom command, the API) reads
telemetry, laps, setup and standings from Delta Suite through a local MCP server, analyses corner by corner
and proposes changes: it never applies anything by itself, you confirm (wheel button or app button).

**Pit & Setup** (Lua app for Custom Shaders Patch, installable from the hub): live brake bias, ABS, TC and
engine brake, full setup, pit stop menu, standings with gap and interval.

**Other**
- Driver / Engineer / Analysis modes.
- Session recording and replay.
- Corner-by-corner analysis: braking, minimum speed, throttle pick-up, time lost.
- Fixes to lap splitting found with real AC (line crossing, partial laps).

**Voice requirements:** the Kokoro models from Tsukumo (or `kokoro-v1.0.onnx` + `voices-v1.0.bin` in a folder
of your choice). Whisper uses the Hugging Face cache and downloads the model on first use if missing.
