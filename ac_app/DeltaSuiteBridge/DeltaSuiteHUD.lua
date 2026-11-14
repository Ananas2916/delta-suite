-- Delta Suite HUD (loaded by DeltaSuiteBridge.lua with a protected require).
--
-- Our own in-game HUD, one CSP window per element (manifest.ini), so each can be moved, resized and switched on
-- or off from the CSP apps bar without touching anyone else's HUD. Everything that changes every frame is
-- computed here from the sim, so the HUD works without Delta Suite; strategy, engineer and radio come from Delta
-- Suite through DeltaSuite_Race_In_v1 and show "offline" when it is not running.
-- Content scales with the window width: resize the window to resize the element.
--
-- Look: dark translucent capsules, wide type (Archivo SemiExpanded, SIL OFL, see OFL-Archivo.txt; Bahnschrift if
-- it cannot be loaded), lights with a soft halo, colour only where it means something. Everything is drawn with
-- primitives: no images.

local H = {}
local R = nil -- DeltaSuiteRace module (may be nil if it failed to load)

-- ------------------------------------------------------------------ palette and type
local function col(r, g, b, a) return rgbm(r / 255, g / 255, b / 255, a or 1) end

local C = {
  bg = rgbm(0.02, 0.025, 0.035, 0.74), bgDark = rgbm(0.01, 0.012, 0.018, 0.88), bgLight = rgbm(0.05, 0.055, 0.07, 0.5),
  edge = rgbm(1, 1, 1, 0.08), track = rgbm(1, 1, 1, 0.13), faint = rgbm(1, 1, 1, 0.22),
  white = rgbm(1, 1, 1, 1), text = rgbm(0.95, 0.96, 0.97, 1), label = rgbm(0.78, 0.8, 0.84, 0.72),
  dim = rgbm(1, 1, 1, 0.42), black = rgbm(0, 0, 0, 1),
  green = col(16, 214, 92), lime = col(0, 255, 133), yellow = col(255, 214, 0), amber = col(255, 150, 20),
  red = col(255, 38, 38), blue = col(30, 110, 255), cyan = col(24, 190, 255), purple = col(200, 70, 255),
  accent = rgbm(0.88, 0.02, 0, 1),
}
H.colors = C

local function fontSet()
  local dir = '.'
  local ok, f = pcall(function()
    return {
      label = ui.DWriteFont('Archivo SemiExpanded', dir):weight(ui.DWriteFont.Weight.Medium),
      bold = ui.DWriteFont('Archivo SemiExpanded', dir):weight(ui.DWriteFont.Weight.Bold),
      black = ui.DWriteFont('Archivo SemiExpanded', dir):weight(ui.DWriteFont.Weight.Black),
    }
  end)
  if ok then return f end
  return {
    label = ui.DWriteFont('Bahnschrift'):weight(ui.DWriteFont.Weight.SemiBold),
    bold = ui.DWriteFont('Bahnschrift'):weight(ui.DWriteFont.Weight.Bold),
    black = ui.DWriteFont('Bahnschrift'):weight(ui.DWriteFont.Weight.Bold),
  }
end
local F = fontSet()

-- ------------------------------------------------------------------ drawing kit (coordinates in design pixels)
local S = 1          -- scale of the element being drawn: window width / design width
local now, frameDt = 0, 0.016
-- animation clock: the real clock when CSP has one, so lamps keep flashing even if H.update is not reached
-- in some frame (it only runs at the end of the bridge's script.update); else the sum of the frame times
local wallClock = type(os) == 'table' and type(os.preciseClock) == 'function' and os.preciseClock or nil
local wallStart = wallClock and wallClock() or 0
local function syncClock() if wallClock then now = wallClock() - wallStart end end

local function clamp(x, a, b) return math.max(a, math.min(b, x)) end
local function v(x, y) return vec2(x * S, y * S) end
local function alpha(c, a) return rgbm(c.r, c.g, c.b, c.mult * a) end
local function mix(a, b, t)
  t = clamp(t, 0, 1)
  return rgbm(a.r + (b.r - a.r) * t, a.g + (b.g - a.g) * t, a.b + (b.b - a.b) * t, a.mult + (b.mult - a.mult) * t)
end
local function blink(period) period = period or 0.6; return (now % period) < period / 2 end
local function ease(t) t = clamp(t, 0, 1); return 1 - (1 - t) ^ 3 end

local function rect(x, y, w, h, c, r, flags)
  if w <= 0 or h <= 0 then return end
  ui.drawRectFilled(v(x, y), v(x + w, y + h), c, (r or 0) * S, flags or ui.CornerFlags.All)
end
local function outline(x, y, w, h, c, r, thick)
  ui.drawRect(v(x, y), v(x + w, y + h), c, (r or 0) * S, ui.CornerFlags.All, (thick or 1) * S)
end
local function pill(x, y, w, h, c) rect(x, y, w, h, c, h / 2) end
-- horizontal gradient: c1 at the left, c2 at the right
local function hgrad(x, y, w, h, c1, c2)
  if w <= 0 or h <= 0 then return end
  ui.drawRectFilledMultiColor(v(x, y), v(x + w, y + h), c1, c2, c2, c1)
end
local function vgrad(x, y, w, h, c1, c2)
  if w <= 0 or h <= 0 then return end
  ui.drawRectFilledMultiColor(v(x, y), v(x + w, y + h), c1, c1, c2, c2)
end
local function circle(x, y, r, c, segs) ui.drawCircleFilled(v(x, y), r * S, c, segs or 24) end
local function ring(x, y, r, c, thick, segs) ui.drawCircle(v(x, y), r * S, c, segs or 32, thick * S) end
local function arc(x, y, r, a0, a1, c, thick, segs)
  if math.abs(a1 - a0) < 1e-3 then return end
  ui.pathClear()
  ui.pathArcTo(v(x, y), r * S, a0, a1, segs or 48)
  ui.pathStroke(c, false, thick * S)
end
-- a light: solid dot with a soft halo when lit
local function lamp(x, y, r, c, lit)
  if lit then
    circle(x, y, r * 2.6, alpha(c, 0.08), 20)
    circle(x, y, r * 1.8, alpha(c, 0.16), 20)
  end
  circle(x, y, r, c, 16)
end

-- text at (x, y); ax 0 = left, 0.5 = centre, 1 = right; ay 0 = top, 0.5 = middle, 1 = bottom
local function text(s, font, size, x, y, c, ax, ay)
  s = tostring(s)
  ui.pushDWriteFont(font)
  local fs = size * S
  local m = ui.measureDWriteText(s, fs)
  ui.dwriteDrawText(s, fs, vec2(x * S - m.x * (ax or 0), y * S - m.y * (ay or 0)), c or C.text)
  ui.popDWriteFont()
  return m.x / S
end
local function measure(s, font, size)
  ui.pushDWriteFont(font)
  local m = ui.measureDWriteText(tostring(s), size * S)
  ui.popDWriteFont()
  return m.x / S, m.y / S
end
-- wrapped text in a box; returns the height used
local function paragraph(s, font, size, x, y, w, c)
  ui.pushDWriteFont(font)
  local m = ui.measureDWriteText(s, size * S, w * S)
  ui.dwriteDrawTextClipped(s, size * S, v(x, y), vec2((x + w) * S, y * S + m.y), ui.Alignment.Start,
    ui.Alignment.Start, true, c or C.text)
  ui.popDWriteFont()
  return m.y / S
end
-- small rounded label: filled when lit, outlined otherwise
local function badge(s, x, y, w, h, c, lit)
  if lit then
    rect(x, y, w, h, c, 4)
    text(s, F.bold, h * 0.5, x + w / 2, y + h / 2, C.black, 0.5, 0.5)
  else
    rect(x, y, w, h, rgbm(1, 1, 1, 0.06), 4)
    text(s, F.bold, h * 0.5, x + w / 2, y + h / 2, C.dim, 0.5, 0.5)
  end
end

local function hovered()
  local ok, h = pcall(ui.windowHovered)
  return ok and h
end
local function placeholder(w, h, name)
  if hovered() then
    rect(0, 0, w, h, C.bgLight, 10)
    outline(0, 0, w, h, C.edge, 10, 1)
    text(name, F.bold, 12, w / 2, h / 2, C.dim, 0.5, 0.5)
  end
end

-- ------------------------------------------------------------------ formatting
local function lapTime(ms)
  if not ms or ms <= 0 then return '-:--.---' end
  local m = math.floor(ms / 60000)
  return string.format('%d:%06.3f', m, (ms - m * 60000) / 1000)
end
local function clockTime(s)
  s = math.max(0, math.floor(s))
  local h, m = math.floor(s / 3600), math.floor(s / 60) % 60
  if h > 0 then return string.format('%d:%02d:%02d', h, m, s % 60) end
  return string.format('%d:%02d', m, s % 60)
end
local function signed(x, digits) return string.format('%+.' .. (digits or 1) .. 'f', x) end

local function lastName(i)
  local name = ac.getDriverName(i) or ''
  return name:match('(%S+)%s*$') or name
end
local function tla(i) return (lastName(i):sub(1, 3)):upper() end

-- a steady colour per car model, used as the "team" stripe
local brandColor = {}
local function hsv(h, s, v2)
  local i = math.floor(h * 6)
  local f = h * 6 - i
  local p, q, t = v2 * (1 - s), v2 * (1 - f * s), v2 * (1 - (1 - f) * s)
  i = i % 6
  if i == 0 then return rgbm(v2, t, p, 1) elseif i == 1 then return rgbm(q, v2, p, 1)
  elseif i == 2 then return rgbm(p, v2, t, 1) elseif i == 3 then return rgbm(p, q, v2, 1)
  elseif i == 4 then return rgbm(t, p, v2, 1) end
  return rgbm(v2, p, q, 1)
end
local function teamColor(i)
  local key = ac.getCarID(i) or tostring(i)
  local c = brandColor[key]
  if not c then
    local h = 0
    for k = 1, #key do h = (h * 31 + key:byte(k)) % 1000003 end
    c = hsv((h * 0.618034) % 1, 0.75, 0.98)
    brandColor[key] = c
  end
  return c
end

-- temperature colour: blue cold, green in the window, red hot. opt = ideal, width = half window as a fraction
local function heat(t, opt, width)
  local d = (t - opt) / (opt * (width or 0.1))
  if d <= -2.5 then return C.blue end
  if d <= -1 then return mix(C.blue, C.cyan, (d + 2.5) / 1.5) end
  if d <= 0 then return mix(C.cyan, C.green, d + 1) end
  if d <= 1 then return mix(C.green, C.yellow, d) end
  if d <= 2 then return mix(C.yellow, C.red, d - 1) end
  return C.red
end

local function isRace(sim) return sim.raceSessionType == ac.SessionType.Race end
local function sessionName(sim)
  local t = sim.raceSessionType
  if t == ac.SessionType.Race then return 'RACE' end
  if t == ac.SessionType.Qualify then return 'QUALIFYING' end
  if t == ac.SessionType.Practice then return 'PRACTICE' end
  if t == ac.SessionType.Hotlap then return 'HOTLAP' end
  return 'SESSION'
end

-- ------------------------------------------------------------------ live state kept between frames
-- Timing loops: the lap is cut into BINS marks; the first car to cross each mark writes the time it crossed it
-- (interpolated between frames, so the marks are exact at any frame rate). A car's gap to the leader is how long
-- ago the leader was where that car is now, interpolated between the two marks around it: no steps, so two cars
-- 10 m apart under VSC do not both read +0.0. Works in every session type and needs nothing from Delta Suite.
local BINS = 200
local first, timingClock, lastPrune = {}, 0, 0
local carTrack = {}             -- by car index: { pos = continuous lap position * BINS, skips = n }
local startPos = {}             -- grid positions (race), to show places gained
local stintStartLap = 0         -- player's lap count when leaving the box: laps on these tyres
local lastLapCount, lapFlash = -1, nil
local rowY = {}                 -- smoothed row positions, by car index

local function resetSession()
  first, timingClock, lastPrune, carTrack = {}, 0, 0, {}
  startPos, rowY, lapFlash, lastLapCount = {}, {}, nil, -1
  stintStartLap = 0
end
ac.onSessionStart(function() resetSession() end)

-- the safety car is a car of the session: kept out of standings, relative and the map's numbered dots
local function scIndex()
  local st = R and R.state
  return (st and type(st.scCar) == 'number') and st.scCar or -1
end
local function isSC(i)
  local s = scIndex()
  return s >= 0 and i == s
end
-- race position as if the safety car were not there
local function place(c)
  local s = scIndex()
  if s >= 0 and c.index ~= s then
    local sc = ac.getCar(s)
    if sc and sc.racePosition > 0 and sc.racePosition < c.racePosition then return c.racePosition - 1 end
  end
  return c.racePosition
end

local function lapPos(c) return (c.lapCount + clamp(c.splinePosition, 0, 0.99999)) * BINS end

-- marks crossed by a car since the last frame get the interpolated crossing time
local function trackCar(i, c)
  local pos = lapPos(c)
  local tr = carTrack[i]
  if not tr then carTrack[i] = { pos = pos, skips = 0 }; return end
  local d = pos - tr.pos
  -- lap counter and spline do not always flip on the same frame: ignore a one-frame jump of half a lap
  if math.abs(d) > BINS / 2 and tr.skips < 10 then tr.skips = tr.skips + 1; return end
  tr.skips = 0
  if d > 0 and d < BINS / 2 then
    for k = math.floor(tr.pos) + 1, math.floor(pos) do
      if first[k] == nil then first[k] = timingClock - frameDt * (pos - k) / d end
    end
  end
  tr.pos = pos
end

local function updateLive(dt, sim)
  timingClock = timingClock + dt
  local race = isRace(sim)
  local preStart = race and (not sim.isSessionStarted or sim.timeToSessionStart > 0)
  for i = 0, sim.carsCount - 1 do
    local c = ac.getCar(i)
    if c and c.isConnected and not isSC(i) and not c.isInPitlane then trackCar(i, c)
    elseif carTrack[i] then carTrack[i] = nil end
    if c and c.isConnected and preStart and c.racePosition > 0 and not isSC(i) then startPos[i] = place(c) end
  end
  if timingClock - lastPrune > 30 then
    lastPrune = timingClock
    local maxKey = -1
    for k in pairs(first) do if k > maxKey then maxKey = k end end
    for k in pairs(first) do if k < maxKey - 4 * BINS then first[k] = nil end end
  end
  local me = ac.getCar(0)
  if me then
    if me.isInPit then stintStartLap = me.lapCount end
    if lastLapCount >= 0 and me.lapCount > lastLapCount and me.previousLapTimeMs > 0 then
      lapFlash = { untilT = now + 5, ms = me.previousLapTimeMs, valid = me.isLastLapValid, lap = me.lapCount }
    end
    lastLapCount = me.lapCount
  end
end

local function gapToLeader(c)
  local pos = lapPos(c)
  local k = math.floor(pos)
  local t0 = first[k]
  if not t0 then return nil end
  local f = pos - k
  local t1 = first[k + 1]
  local tAt
  if t1 then
    tAt = t0 + (t1 - t0) * f
  else
    -- nobody past the next mark yet: the leader is in this stretch too, use the previous stretch's pace
    local tp = first[k - 1]
    tAt = math.min(timingClock, t0 + (tp and (t0 - tp) or 0) * f)
  end
  return timingClock - tAt
end

local function raceOrder(sim)
  local cars = {}
  for i = 0, sim.carsCount - 1 do
    local c = ac.getCar(i)
    if c and c.isConnected and c.racePosition > 0 and not isSC(i) then cars[#cars + 1] = c end
  end
  table.sort(cars, function(a, b) return a.racePosition < b.racePosition end)
  return cars
end

local function sessionBest(cars)
  local best = nil
  for _, c in ipairs(cars) do
    if c.bestLapTimeMs > 0 and (not best or c.bestLapTimeMs < best) then best = c.bestLapTimeMs end
  end
  return best
end

-- smooth a value towards a target (exponential, frame-rate independent)
local function approach(cur, target, speed)
  if cur == nil then return target end
  return cur + (target - cur) * (1 - math.exp(-frameDt * speed))
end

-- ------------------------------------------------------------------ element wrapper
-- Scales the element to its window and plays a short wipe-in when the window appears.
local shown = {}
local function element(name, W, draw)
  H[name] = function()
    syncClock()
    S = math.max(0.3, ui.windowSize().x / W)
    local st = shown[name]
    if not st then st = { last = -1, since = 0 }; shown[name] = st end
    if now - st.last > 0.5 then st.since = now end
    st.last = now
    local t = (now - st.since) / 0.35
    local clip = t < 1
    if clip then
      local ws = ui.windowSize()
      ui.pushClipRect(vec2(0, 0), vec2(ws.x * ease(t), ws.y), true)
    end
    local ok, err = pcall(draw, W)
    if clip then ui.popClipRect() end
    if not ok then error(err, 0) end
  end
end

-- ------------------------------------------------------------------ race control banner
local RC_W, RC_H, RC_BLOCK = 600, 100, 104
local rcState, rcSince = -1, 0

local function rcSetting(name, default)
  local ok, val = pcall(R.setting, name)
  return (ok and type(val) == 'number') and val or default
end

-- countdown ring: frac of the circle left, number inside
local function countdownRing(x, y, r, frac, secs, c)
  circle(x, y, r + 6, C.bgDark, 40)
  ring(x, y, r, C.track, 6, 48)
  arc(x, y, r, -math.pi / 2, -math.pi / 2 + math.pi * 2 * clamp(frac, 0, 1), c, 6, 48)
  text(string.format('%d', math.max(0, math.ceil(secs))), F.black, 26, x, y, C.white, 0.5, 0.5)
end

-- Marshal light panel on the left of the banner: two big lamps flashing alternately (c1 / c2) for as long as a
-- neutralisation runs, the label under them. steady = both lamps on (green flag after its first flashes).
local LAMP_OFF = rgbm(0.17, 0.15, 0.11, 1)
local function lightPanel(label, c1, c2, steady)
  c2 = c2 or c1
  rect(0, 0, RC_BLOCK, RC_H, rgbm(0.045, 0.045, 0.05, 0.97), 12, ui.CornerFlags.Left)
  rect(RC_BLOCK - 2, 0, 2, RC_H, alpha(c1, 0.55))
  local phase = (now % 0.8) < 0.4
  local function bigLamp(x, on, c)
    circle(x, 34, 17.5, C.black, 32)
    if on then
      circle(x, 34, 27, alpha(c, 0.1), 32)
      circle(x, 34, 21, alpha(c, 0.22), 32)
      circle(x, 34, 14, c, 32)
      circle(x - 4, 30, 4, rgbm(1, 1, 1, 0.45), 12)
    else
      circle(x, 34, 14, LAMP_OFF, 32)
    end
  end
  bigLamp(30, steady or phase, c1)
  bigLamp(74, steady or not phase, c2)
  text(label, F.black, 22, RC_BLOCK / 2, 78, c1, 0.5, 0.5)
end

-- the whole banner's edge pulses with the lamps (overLimit draws its red border on top)
local function bannerPulse(c)
  outline(1, 1, RC_W - 2, RC_H - 2, alpha(c, (now % 0.8) < 0.4 and 0.85 or 0.2), 12, 2)
end

local function rcBlock(label, St)
  local over = St.overLimit and St.state ~= R.PENDING
  if over then lightPanel(label, C.red, C.red)
  elseif St.state == R.ENDING then lightPanel(label, C.yellow, C.green)
  else lightPanel(label, C.yellow) end
  if not over then bannerPulse(C.yellow) end
end

-- tag at the top right; skipped if it would touch the title (minX = end of the title)
local function rcTag(s, c, filled, minX)
  local w = measure(s, F.bold, 12) + 22
  local x = RC_W - 18 - w
  if minX and x < minX + 12 then return end
  if filled then
    pill(x, 16, w, 24, c)
    text(s, F.bold, 12, x + w / 2, 28, C.black, 0.5, 0.5)
  else
    pill(x, 16, w, 24, alpha(c, 0.16))
    text(s, F.bold, 12, x + w / 2, 28, c, 0.5, 0.5)
  end
end

local function fcyGauge(St)
  local over = St.overLimit
  local limit = math.max(1, St.limitKmh)
  local spd = St.playerKmh
  local c = over and C.red or (spd > limit - 3 and C.yellow or C.green)
  local x = RC_BLOCK + 20
  local w = text(string.format('%d', math.floor(spd + 0.5)), F.black, 36, x, 72, c, 0, 0.5)
  text('KM/H', F.label, 11, x + w + 6, 80, C.label, 0, 0.5)
  -- bar from 0 to 1.5 x limit, white tick on the limit
  local bx, bw, by = RC_BLOCK + 150, RC_W - RC_BLOCK - 172, 66
  local maxV = limit * 1.5
  pill(bx, by, bw, 12, C.track)
  local fLim = limit / maxV
  local f = clamp(spd / maxV, 0, 1)
  hgrad(bx, by, bw * math.min(f, fLim), 12, alpha(C.green, 0.35), C.green)
  if f > fLim then rect(bx + bw * fLim, by, bw * (f - fLim), 12, C.red, 6, ui.CornerFlags.Right) end
  rect(bx + bw * fLim - 1.5, by - 6, 3, 24, C.white, 1)
  text(string.format('%d', math.floor(limit + 0.5)), F.bold, 11, bx + bw * fLim, by + 26, C.white, 0.5, 0.5)
  if St.infraction and St.infraction > 0.05 then
    text(string.format('OVER %.1f s', St.infraction), F.bold, 11, bx + bw, by + 26, C.red, 1, 0.5)
  end
end

local function vscGauge(St)
  local d = St.delta
  local c = St.overLimit and C.red or (d < 0.3 and C.yellow or C.green)
  local x = RC_BLOCK + 20
  text(signed(d, 1), F.black, 36, x, 72, c, 0, 0.5)
  -- centre-zero bar, +-2 s: right = time in hand (good), left = too fast
  local bx, bw, by = RC_BLOCK + 150, RC_W - RC_BLOCK - 172, 66
  local cx = bx + bw / 2
  pill(bx, by, bw, 12, C.track)
  local f = clamp(d / 2, -1, 1)
  if f >= 0 then hgrad(cx, by, bw / 2 * f, 12, alpha(C.green, 0.25), C.green)
  else hgrad(cx + bw / 2 * f, by, -bw / 2 * f, 12, C.red, alpha(C.red, 0.25)) end
  rect(cx - 1.5, by - 6, 3, 24, C.white, 1)
  text('TOO FAST', F.label, 10, bx, by + 26, C.label, 0, 0.5)
  text('IN HAND', F.label, 10, bx + bw, by + 26, C.label, 1, 0.5)
end

-- safety car (a real car of the session): queue behind it, gap to the car ahead, no overtaking
local SC_CLOSE_M = 60

local function scBanner(St)
  local over = St.overLimit
  local ending = St.state == R.ENDING
  local waiting = R.SC_WAITING ~= nil and St.scPhase == R.SC_WAITING and not ending
  rect(0, 0, RC_W, RC_H, C.bgDark, 12)
  rcBlock('SC', St)

  local tx = RC_BLOCK + 20
  local tw
  if over then
    local msg = (now % 2) < 1 and 'NO OVERTAKING' or 'GIVE THE PLACE BACK'
    tw = text(msg, F.black, 22, tx, 28, blink(0.4) and C.red or C.white, 0, 0.5)
    outline(1.5, 1.5, RC_W - 3, RC_H - 3, C.red, 12, 3)
  else
    tw = text(ending and 'SAFETY CAR IN THIS LAP' or waiting and 'SAFETY CAR DEPLOYED' or 'SAFETY CAR', F.black, 22,
      tx, 28, C.white, 0, 0.5)
  end
  if ending then
    rcTag('GREEN AT THE LINE', C.green, true, tx + tw)
  elseif not waiting and St.limitKmh and St.limitKmh > 0 then
    rcTag(string.format('SC %d KM/H', math.floor(St.limitKmh + 0.5)), C.yellow, false, tx + tw)
  end

  -- deployed but still in the pits: the field slows down and catches it at the pit exit, no gap yet
  if waiting then
    text('SLOW DOWN  ·  CATCH THE SAFETY CAR', F.black, 15, tx, 66, blink(0.8) and C.yellow or C.white, 0, 0.5)
    text('It joins at the pit exit ahead of the leader', F.label, 11, tx, 86, C.label, 0, 0.5)
    return
  end

  -- gap to the car ahead in the queue: green when closed up, amber beyond SC_CLOSE_M
  local gap = math.max(0, St.scGapM or 0)
  local far = gap > SC_CLOSE_M
  local c = far and C.amber or C.green
  local w = text(string.format('%d', math.floor(gap + 0.5)), F.black, 36, tx, 72, c, 0, 0.5)
  text('M', F.label, 11, tx + w + 6, 80, C.label, 0, 0.5)
  local bx, bw, by = RC_BLOCK + 150, RC_W - RC_BLOCK - 172, 66
  local maxM = SC_CLOSE_M * 2.5
  pill(bx, by, bw, 12, C.track)
  local fClose = SC_CLOSE_M / maxM
  rect(bx, by, bw * fClose, 12, alpha(C.green, 0.18), 6, ui.CornerFlags.Left)
  local f = clamp(gap / maxM, 0, 1)
  if f > 0.01 then hgrad(bx, by, bw * f, 12, alpha(c, 0.3), c) end
  rect(bx + bw * fClose - 1.5, by - 6, 3, 24, C.white, 1)
  text('CAR AHEAD', F.label, 10, bx, by + 26, C.label, 0, 0.5)
  if far then
    text('CLOSE UP', F.black, 11, bx + bw, by + 26, blink(0.6) and C.amber or C.white, 1, 0.5)
  else
    text(string.format('%d M', SC_CLOSE_M), F.bold, 10, bx + bw * fClose, by + 26, C.white, 0.5, 0.5)
  end
end

element('raceControl', RC_W, function()
  if not R then placeholder(RC_W, RC_H, 'RACE CONTROL: module not loaded'); return end
  local St = R.state
  if St.state ~= rcState then rcState, rcSince = St.state, now end
  if St.state == R.GREEN then
    placeholder(RC_W, RC_H, (St.available or St.reason == '') and 'RACE CONTROL' or ('RACE CONTROL: ' .. St.reason))
    return
  end
  -- slide in from the left on every state change
  local t = ease((now - rcSince) / 0.3)
  local ws = ui.windowSize()
  ui.pushClipRect(vec2(0, 0), vec2(ws.x * t, ws.y), true)
  local ok, err = pcall(function()
    local vsc = St.mode == R.VSC
    local short = vsc and 'VSC' or 'FCY'
    local name = vsc and 'VIRTUAL SAFETY CAR' or 'FULL COURSE YELLOW'

    if St.state == R.GREEN_FLASH then
      rect(RC_BLOCK, 0, RC_W - RC_BLOCK, RC_H, C.green, 12, ui.CornerFlags.Right)
      vgrad(RC_BLOCK, 0, RC_W - RC_BLOCK, RC_H * 0.5, rgbm(1, 1, 1, 0.22), rgbm(1, 1, 1, 0))
      local sx = ((now - rcSince) * 700) % (RC_W + 300) - 150
      ui.pushClipRect(v(RC_BLOCK, 0), v(RC_W, RC_H), true)
      hgrad(sx - 120, 0, 120, RC_H, rgbm(1, 1, 1, 0), rgbm(1, 1, 1, 0.28))
      hgrad(sx, 0, 120, RC_H, rgbm(1, 1, 1, 0.28), rgbm(1, 1, 1, 0))
      ui.popClipRect()
      -- green lamps: flashing for the first 1.5 s, then steady
      lightPanel('GO', C.green, C.green, now - rcSince > 1.5)
      text('GREEN FLAG', F.black, 38, RC_BLOCK + 22, 42, C.black, 0, 0.5)
      text('TRACK CLEAR  ·  RACING RESUMES', F.bold, 13, RC_BLOCK + 24, 74, rgbm(0, 0, 0, 0.7), 0, 0.5)
      return
    end

    if R.SC and St.mode == R.SC then scBanner(St); return end

    local over = St.overLimit and St.state ~= R.PENDING
    rect(0, 0, RC_W, RC_H, C.bgDark, 12)
    rcBlock(short, St)

    local tx = RC_BLOCK + 20
    if St.state == R.PENDING then
      text(name, F.black, 22, tx, 34, C.white, 0, 0.5)
      local sub = vsc and 'Keep the delta positive when the countdown ends'
        or string.format('Slow to %d km/h when the countdown ends', math.floor(rcSetting('fcyKmh', 80) + 0.5))
      text(sub, F.label, 13, tx, 66, C.label, 0, 0.5)
      local total = math.max(1, rcSetting('countdownS', 10))
      countdownRing(RC_W - 52, RC_H / 2, 30, St.countdown / total, St.countdown, C.yellow)
      return
    end

    local tw
    if over then
      tw = text(vsc and 'TOO FAST' or 'SLOW DOWN', F.black, 22, tx, 28, blink(0.4) and C.red or C.white, 0, 0.5)
      outline(1.5, 1.5, RC_W - 3, RC_H - 3, C.red, 12, 3)
    elseif St.state == R.ENDING then
      tw = text(short .. ' ENDING', F.black, 22, tx, 28, C.white, 0, 0.5)
    else
      tw = text(name, F.black, 22, tx, 28, C.white, 0, 0.5)
    end
    local titleEnd = tx + tw
    if St.state == R.ENDING then
      rcTag(string.format('GREEN IN %d', math.max(0, math.ceil(St.countdown))), C.green, true, titleEnd)
    elseif vsc then
      rcTag('DELTA ABOVE 0', C.yellow, false, titleEnd)
    else
      rcTag(string.format('LIMIT %d KM/H', math.floor(St.limitKmh + 0.5)), C.yellow, false, titleEnd)
    end
    if vsc then vscGauge(St) else fcyGauge(St) end
  end)
  ui.popClipRect()
  if not ok then error(err, 0) end
end)

-- ------------------------------------------------------------------ dash: gear, rpm, speed, lights, pedals
local DASH_W, DASH_H = 420, 128
local LEDS = 14

element('dash', DASH_W, function()
  local car = ac.getCar(0)
  if not car then return end
  local limit = car.rpmLimiter > 0 and car.rpmLimiter or 8000
  local f = car.rpm / limit
  local shift = clamp((f - 0.9) / 0.07, 0, 1)
  local atLimit = f >= 0.975

  -- capsule, turning red towards the shift point
  local cx, cy, cr = 60, 60, 56
  local body = mix(C.bg, rgbm(0.75, 0.04, 0.04, 0.8), shift)
  if atLimit and blink(0.12) then body = C.bg end
  rect(cx, 16, DASH_W - 6 - cx, 88, body, 44)
  outline(cx, 16, DASH_W - 6 - cx, 88, C.edge, 44, 1)
  -- info strip under the capsule
  local sx, sy, sw, sh = 118, 106, DASH_W - 128, 22
  pill(sx, sy, sw, sh, C.bgDark)
  local aids = {
    { 'TC', car.tractionControlInAction, C.yellow }, { 'ABS', car.absInAction, C.amber },
    { 'LIM', car.isEngineLimiterOn or car.speedLimiterInAction or car.manualPitsSpeedLimiterEnabled, C.blue },
    { 'DRS', car.drsActive, C.green },
  }
  for k, a in ipairs(aids) do badge(a[1], sx + 8 + (k - 1) * 40, sy + 4, 36, 14, a[3], a[2]) end
  local fuelLow = car.maxFuel > 0 and car.fuel < car.maxFuel * 0.08
  local fw = text(string.format('%.1f L', car.fuel), F.bold, 11, sx + sw - 12, sy + sh / 2, fuelLow and C.red or C.white, 1, 0.5)
  text('FUEL', F.label, 10, sx + sw - 18 - fw, sy + sh / 2, C.label, 1, 0.5)

  -- gear disc with the rpm ring (270 degrees, open at the bottom)
  circle(cx, cy, cr, C.bgDark, 48)
  local a0, a1 = math.pi * 0.75, math.pi * 2.25
  local ringColor = f >= 0.94 and C.red or f >= 0.85 and C.yellow or C.lime
  if atLimit then ringColor = blink(0.12) and C.blue or C.red end
  arc(cx, cy, cr - 9, a0, a1, C.track, 7, 60)
  arc(cx, cy, cr - 9, a0, a0 + (a1 - a0) * clamp(f, 0, 1), ringColor, 7, 60)
  local g = car.gear
  local gs = g < 0 and 'R' or g == 0 and 'N' or tostring(g)
  text(gs, F.black, 46, cx, cy - 2, g < 0 and C.amber or C.white, 0.5, 0.5)

  -- shift lights
  local lit = clamp((f - 0.72) / (0.97 - 0.72), 0, 1) * LEDS
  for k = 1, LEDS do
    local x = 130 + (k - 1) * 15.5
    local on = k <= lit + 0.001
    local c = k <= 5 and C.lime or k <= 10 and C.yellow or C.red
    if atLimit then c, on = C.blue, blink(0.12) end
    lamp(x, 32, 4.5, on and c or C.track, on)
  end

  -- speed and rpm
  text('KM/H', F.label, 10, 128, 52, C.label, 0, 0.5)
  text(string.format('%d', math.floor(car.speedKmh + 0.5)), F.bold, 28, 126, 78, C.white, 0, 0.5)
  text('RPM', F.label, 10, 236, 52, C.label, 0, 0.5)
  text(string.format('%d', math.floor(car.rpm)), F.bold, 28, 234, 78, C.white, 0, 0.5)

  -- pedals: clutch, brake, throttle
  local pedals = { { 1 - car.clutch, C.blue }, { car.brake, C.red }, { car.gas, C.green } }
  for k, p in ipairs(pedals) do
    local x, y, h = 362 + (k - 1) * 13, 30, 60
    rect(x, y, 8, h, C.track, 3)
    local hh = h * clamp(p[1], 0, 1)
    rect(x, y + h - hh, 8, hh, p[2], 3)
  end
end)

-- ------------------------------------------------------------------ lap timing and delta
local LAP_W = 440

local function sectorColor(k, cur, car, sim)
  local best = car.bestSplits[k] or 0
  local overall = nil
  for i = 0, sim.carsCount - 1 do
    local c = ac.getCar(i)
    if c and c.isConnected and not isSC(i) and #c.bestSplits > k then
      local b = c.bestSplits[k]
      if b and b > 0 and (not overall or b < overall) then overall = b end
    end
  end
  if overall and cur <= overall then return C.purple end
  if best <= 0 or cur <= best then return C.green end
  return C.yellow
end

element('lap', LAP_W, function()
  local car = ac.getCar(0)
  local sim = ac.getSim()
  if not car then return end

  -- delta bar
  local d = car.performanceMeter or 0
  local hasBest = car.bestLapTimeMs > 0
  pill(0, 0, LAP_W, 30, C.bgDark)
  local cx = LAP_W / 2
  if hasBest then
    local f = clamp(d / 1.5, -1, 1)
    local half = LAP_W / 2 - 50
    if f < 0 then hgrad(cx + half * f - 46, 5, -half * f, 20, C.green, alpha(C.green, 0.1))
    elseif f > 0 then hgrad(cx + 46, 5, half * f, 20, alpha(C.red, 0.1), C.red) end
    local c = d <= 0 and C.green or C.red
    pill(cx - 46, 3, 92, 24, c)
    text(signed(d, 2), F.black, 15, cx, 15, C.black, 0.5, 0.5)
  else
    text('NO REFERENCE LAP', F.bold, 11, cx, 15, C.dim, 0.5, 0.5)
  end

  -- main panel
  local y0 = 36
  rect(0, y0, LAP_W, 124, C.bg, 12)
  outline(0, y0, LAP_W, 124, C.edge, 12, 1)
  local flash = lapFlash and now < lapFlash.untilT
  if flash then
    local best = sessionBest(raceOrder(sim))
    local c = not lapFlash.valid and C.red or (best and lapFlash.ms <= best) and C.purple
      or (lapFlash.ms <= car.bestLapTimeMs) and C.green or C.yellow
    text('LAP ' .. lapFlash.lap, F.label, 10, 16, y0 + 14, C.label, 0, 0.5)
    text(lapTime(lapFlash.ms), F.bold, 32, 14, y0 + 38, c, 0, 0.5)
  else
    text(car.isLapValid and 'CURRENT' or 'INVALID', F.label, 10, 16, y0 + 14, car.isLapValid and C.label or C.red, 0, 0.5)
    text(lapTime(car.lapTimeMs), F.bold, 32, 14, y0 + 38, car.isLapValid and C.white or C.red, 0, 0.5)
  end

  -- position and laps
  local race = isRace(sim)
  rect(LAP_W - 82, y0 + 12, 68, 38, C.white, 7)
  text('P' .. place(car), F.black, 22, LAP_W - 48, y0 + 31, C.black, 0.5, 0.5)
  local session = ac.getSession(sim.currentSessionIndex)
  local info = ''
  if race and session and not session.isTimedRace and session.laps and session.laps > 0 then
    info = string.format('LAP %d/%d', math.min(car.lapCount + 1, session.laps), session.laps)
  elseif sim.sessionTimeLeft and sim.sessionTimeLeft > 0 then
    info = clockTime(sim.sessionTimeLeft / 1000)
  end
  if info ~= '' then text(info, F.bold, 11, LAP_W - 98, y0 + 31, C.label, 1, 0.5) end

  -- last, best, predicted
  local cols = {
    { 'LAST', lapTime(car.previousLapTimeMs), car.isLastLapValid and C.white or C.red },
    { 'BEST', lapTime(car.bestLapTimeMs), C.purple },
    { 'PRED', hasBest and lapTime(car.bestLapTimeMs + d * 1000) or '-:--.---', d <= 0 and C.green or C.white },
  }
  for k, c in ipairs(cols) do
    local x = 16 + (k - 1) * 140
    text(c[1], F.label, 9, x, y0 + 64, C.label, 0, 0.5)
    text(c[2], F.bold, 14, x, y0 + 80, c[3], 0, 0.5)
  end

  -- sectors: done ones coloured with their time, the current one fills with progress
  local n = math.max(1, #car.bestSplits, #sim.lapSplits)
  local gap = 6
  local w = (LAP_W - 28 - (n - 1) * gap) / n
  local sy = y0 + 96
  for k = 0, n - 1 do
    local x = 14 + k * (w + gap)
    local cur = car.currentSplits[k] or 0
    pill(x, sy, w, 18, C.track)
    if k < car.currentSector and cur > 0 then
      local c = sectorColor(k, cur, car, sim)
      pill(x, sy, w, 18, c)
      text(string.format('%.3f', cur / 1000), F.bold, 10, x + w / 2, sy + 9, C.black, 0.5, 0.5)
    else
      if k == car.currentSector and #sim.lapSplits > k then
        local s0 = sim.lapSplits[k]
        local s1 = (k + 1 < #sim.lapSplits) and sim.lapSplits[k + 1] or 1
        local p = clamp((car.splinePosition - s0) / math.max(1e-3, s1 - s0), 0, 1)
        if p > 0.02 then pill(x, sy, math.max(18, w * p), 18, rgbm(1, 1, 1, 0.3)) end
      end
      text('S' .. (k + 1), F.bold, 10, x + w / 2, sy + 9, C.dim, 0.5, 0.5)
    end
  end
end)

-- ------------------------------------------------------------------ tower rows (standings and relative)
local ROW_H, ROW_GAP = 25, 2

local function rowBase(y, w, mine, odd)
  if mine then
    hgrad(0, y, w, ROW_H, rgbm(0.88, 0.02, 0, 0.92), rgbm(0.6, 0.0, 0, 0.75))
  else
    rect(0, y, w, ROW_H, odd and C.bg or rgbm(0.02, 0.025, 0.035, 0.66), 4)
  end
end

local function posBox(y, pos, mine)
  rect(0, y, 30, ROW_H, mine and C.white or rgbm(1, 1, 1, 0.92), 4, ui.CornerFlags.Left)
  text(tostring(pos), F.black, 13, 15, y + ROW_H / 2, C.black, 0.5, 0.5)
end

local function towerHeader(w, left, mid, flagText, flagColor)
  rect(0, 0, w, 30, C.bgDark, 8)
  rect(0, 0, 4, 30, C.accent, 8, ui.CornerFlags.Left)
  local lw = text(left, F.black, 13, 14, 15, C.white, 0, 0.5)
  if mid and mid ~= '' then
    rect(22 + lw, 8, 1.5, 14, C.faint)
    text(mid, F.bold, 12, 30 + lw, 15, C.label, 0, 0.5)
  end
  if flagText then
    local fw = measure(flagText, F.black, 11) + 18
    rect(w - fw, 0, fw, 30, flagColor, 8, ui.CornerFlags.Right)
    text(flagText, F.black, 11, w - fw / 2, 15, C.black, 0.5, 0.5)
  end
end

-- flag shown on the tower: our neutralisations first, then the sim's flag
local function towerFlag(sim)
  if R and R.state.state ~= R.GREEN then
    local st = R.state
    if st.state == R.GREEN_FLASH then return 'GREEN', C.green end
    if R.SC and st.mode == R.SC then return 'SAFETY CAR', C.yellow end
    return (st.mode == R.VSC and 'VSC' or 'FCY'), C.yellow
  end
  local f = sim.raceFlagType
  if f == ac.FlagType.Caution then return 'YELLOW', C.yellow end
  if f == ac.FlagType.Finished then return 'FINISH', C.white end
  if f == ac.FlagType.OneLapLeft then return 'LAST LAP', C.white end
  if f == ac.FlagType.Stop then return 'BLACK', C.red end
  if f == ac.FlagType.FasterCar then return 'BLUE', C.cyan end
  if sim.isSessionStarted then return 'GREEN', C.green end
  return nil
end

local function sessionInfo(sim, cars)
  local session = ac.getSession(sim.currentSessionIndex)
  if isRace(sim) and session and not session.isTimedRace and session.laps and session.laps > 0 then
    local leader = cars[1]
    local lap = leader and math.min(leader.lapCount + 1, session.laps) or 1
    return string.format('LAP %d/%d', lap, session.laps)
  end
  if sim.sessionTimeLeft and sim.sessionTimeLeft > 0 then return clockTime(sim.sessionTimeLeft / 1000) end
  return ''
end

-- ------------------------------------------------------------------ standings tower
local ST_W = 320

element('standings', ST_W, function()
  local sim = ac.getSim()
  local cars = raceOrder(sim)
  local race = isRace(sim)
  local flagText, flagColor = towerFlag(sim)
  towerHeader(ST_W, sessionName(sim), sessionInfo(sim, cars), flagText, flagColor)

  local maxRows = math.max(5, math.floor((ui.windowSize().y / S - 34) / (ROW_H + ROW_GAP)))
  local me = 1
  for k, c in ipairs(cars) do if c.index == 0 then me = k end end
  local rows = {}
  if #cars <= maxRows then
    for k = 1, #cars do rows[#rows + 1] = k end
  else
    local top = 3
    for k = 1, top do rows[#rows + 1] = k end
    local from = math.max(top + 1, math.min(#cars - (maxRows - top) + 1, me - math.floor((maxRows - top) / 2)))
    for k = from, math.min(#cars, from + maxRows - top - 1) do rows[#rows + 1] = k end
  end
  local best = sessionBest(cars)

  for r, k in ipairs(rows) do
    local c = cars[k]
    local target = 34 + (r - 1) * (ROW_H + ROW_GAP)
    rowY[c.index] = approach(rowY[c.index], target, 12)
    local y = rowY[c.index]
    local mine = c.index == 0
    rowBase(y, ST_W, mine, r % 2 == 1)
    posBox(y, place(c), mine)
    rect(34, y + 5, 3, ROW_H - 10, teamColor(c.index), 1)
    local nameW = text(lastName(c.index):upper(), F.bold, 12, 44, y + ROW_H / 2, C.white, 0, 0.5)
    local x = 50 + nameW
    -- places gained or lost since the start
    local sp = startPos[c.index]
    if race and sp and sp ~= place(c) and x < ST_W - 120 then
      local diff = sp - place(c)
      local up = diff > 0
      local tc = up and C.green or C.red
      local my = y + ROW_H / 2
      if up then ui.drawTriangleFilled(v(x, my + 3), v(x + 8, my + 3), v(x + 4, my - 4), tc)
      else ui.drawTriangleFilled(v(x, my - 3), v(x + 8, my - 3), v(x + 4, my + 4), tc) end
      text(tostring(math.abs(diff)), F.bold, 10, x + 11, my, tc, 0, 0.5)
    end
    -- fastest lap marker
    if best and c.bestLapTimeMs == best then
      circle(ST_W - 92, y + ROW_H / 2, 4, C.purple, 12)
    end
    local right, rc = '', C.text
    if c.isInPitlane then
      pill(ST_W - 52, y + 5, 42, ROW_H - 10, C.yellow)
      text('PIT', F.black, 10, ST_W - 31, y + ROW_H / 2, C.black, 0.5, 0.5)
    else
      if race then
        if k == 1 then
          right = 'LEADER'
          rc = mine and C.white or C.label
        else
          local ahead = cars[k - 1]
          local lapsDown = cars[1].lapCount - c.lapCount - ((cars[1].splinePosition < c.splinePosition) and 1 or 0)
          if lapsDown >= 1 then
            right = '+' .. lapsDown .. ' LAP' .. (lapsDown > 1 and 'S' or '')
          else
            local g, ga = gapToLeader(c), gapToLeader(ahead)
            if g and ga then right = string.format('+%.1f', math.max(0, g - ga)) end
          end
        end
      elseif c.bestLapTimeMs > 0 then
        if best and c.bestLapTimeMs > best then right = string.format('+%.3f', (c.bestLapTimeMs - best) / 1000)
        else right, rc = lapTime(c.bestLapTimeMs), mine and C.white or C.purple end
      end
      text(right, F.bold, 12, ST_W - 10, y + ROW_H / 2, rc, 1, 0.5)
    end
    if rows[r + 1] and rows[r + 1] ~= k + 1 then
      rect(40, target + ROW_H + ROW_GAP / 2 - 0.5, ST_W - 80, 1, C.faint)
    end
  end
end)

-- ------------------------------------------------------------------ relative
local REL_W = 380

element('relative', REL_W, function()
  local sim = ac.getSim()
  local me = ac.getCar(0)
  if not me then return end
  local race = isRace(sim)
  local list = {}
  for i = 1, sim.carsCount - 1 do
    local c = ac.getCar(i)
    if c and c.isConnected and not c.isInPit and not isSC(i) then
      local ahead = (c.splinePosition - me.splinePosition) % 1
      local gap
      if R then
        if ahead < 0.5 then gap = R.gapSeconds(me, me.splinePosition, c.splinePosition)
        else gap = -R.gapSeconds(me, c.splinePosition, me.splinePosition) end
      else
        local lapS = (me.bestLapTimeMs > 0 and me.bestLapTimeMs or 120000) / 1000
        gap = (ahead < 0.5 and ahead or ahead - 1) * lapS
      end
      list[#list + 1] = { c = c, gap = gap }
    end
  end
  table.sort(list, function(a, b) return a.gap > b.gap end)
  local aheadRows, behindRows = {}, {}
  for _, e in ipairs(list) do
    if e.gap >= 0 then aheadRows[#aheadRows + 1] = e else behindRows[#behindRows + 1] = e end
  end
  local show = {}
  for k = math.max(1, #aheadRows - 2), #aheadRows do show[#show + 1] = aheadRows[k] end
  show[#show + 1] = { c = me, gap = 0, me = true }
  for k = 1, math.min(3, #behindRows) do show[#show + 1] = behindRows[k] end

  towerHeader(REL_W, 'RELATIVE', '', nil)
  for r, e in ipairs(show) do
    local y = 34 + (r - 1) * (ROW_H + ROW_GAP)
    local c = e.c
    local lapDiff = c.lapCount + c.splinePosition - (me.lapCount + me.splinePosition)
    local nc = C.white
    if not e.me and race then
      if lapDiff > 0.5 then nc = C.amber elseif lapDiff < -0.5 then nc = C.cyan end
    end
    rowBase(y, REL_W, e.me, r % 2 == 1)
    posBox(y, place(c), e.me)
    rect(34, y + 5, 3, ROW_H - 10, teamColor(c.index), 1)
    local nw = text(tla(c.index), F.black, 13, 44, y + ROW_H / 2, nc, 0, 0.5)
    ui.pushClipRect(v(54 + nw, y), v(REL_W - (c.isInPitlane and 106 or 70), y + ROW_H), true)
    text(ac.getCarName(c.index) or '', F.label, 10, 54 + nw, y + ROW_H / 2, e.me and C.white or C.dim, 0, 0.5)
    ui.popClipRect()
    if c.isInPitlane then
      pill(REL_W - 100, y + 5, 34, ROW_H - 10, C.yellow)
      text('PIT', F.black, 9, REL_W - 83, y + ROW_H / 2, C.black, 0.5, 0.5)
    end
    if not e.me then
      rect(REL_W - 62, y, 62, ROW_H, rgbm(0, 0, 0, 0.25), 4, ui.CornerFlags.Right)
      text(signed(-e.gap, 1), F.bold, 12, REL_W - 10, y + ROW_H / 2, nc, 1, 0.5)
    end
  end
end)

-- ------------------------------------------------------------------ tyres and brakes
local TY_W, TY_H = 280, 236

local function drawTyre(x, y, w, h, wh, leftSide)
  local opt = (wh.tyreOptimumTemperature and wh.tyreOptimumTemperature > 0) and wh.tyreOptimumTemperature or 85
  -- outside / middle / inside stripes, outside towards the edge of the car
  local o, m, i = wh.tyreOutsideTemperature, wh.tyreMiddleTemperature, wh.tyreInsideTemperature
  local stripes = leftSide and { o, m, i } or { i, m, o }
  local sw = w / 3
  for s = 1, 3 do
    local flags = s == 1 and ui.CornerFlags.Left or s == 3 and ui.CornerFlags.Right or ui.CornerFlags.None
    rect(x + (s - 1) * sw, y, sw + (s < 3 and 0.5 or 0), h, heat(stripes[s], opt), 8, flags)
  end
  -- tread: grooves and a soft shade so it reads as a tyre
  for g = 1, 2 do rect(x + g * sw - 0.75, y + 5, 1.5, h - 10, rgbm(0, 0, 0, 0.3)) end
  vgrad(x, y, w, h * 0.45, rgbm(1, 1, 1, 0.2), rgbm(1, 1, 1, 0))
  vgrad(x, y + h * 0.6, w, h * 0.4, rgbm(0, 0, 0, 0), rgbm(0, 0, 0, 0.25))
  outline(x, y, w, h, rgbm(0, 0, 0, 0.5), 8, 1.5)
  if wh.isBlown then
    rect(x, y, w, h, rgbm(0.6, 0, 0, 0.75), 8)
    text('!', F.black, 30, x + w / 2, y + h / 2, C.white, 0.5, 0.5)
  end
end

element('tyres', TY_W, function()
  local car = ac.getCar(0)
  if not car then return end
  rect(0, 0, TY_W, TY_H, C.bg, 12)
  outline(0, 0, TY_W, TY_H, C.edge, 12, 1)
  -- header: compound and laps on this set
  local okName, compound = pcall(ac.getTyresName, 0, car.compoundIndex)
  compound = (okName and compound and compound ~= '') and compound or 'TYRES'
  local cw = text(compound:upper(), F.black, 12, 14, 18, C.white, 0, 0.5)
  local laps = math.max(0, car.lapCount - stintStartLap)
  text(string.format('%d LAP%s', laps, laps == 1 and '' or 'S'), F.bold, 11, 24 + cw, 18, C.label, 0, 0.5)
  text('PSI', F.label, 9, TY_W - 14, 18, C.label, 1, 0.5)
  rect(12, 32, TY_W - 24, 1, C.edge)

  -- car body between the tyres
  rect(TY_W / 2 - 22, 52, 44, 160, rgbm(1, 1, 1, 0.05), 20)
  rect(TY_W / 2 - 18, 96, 36, 46, rgbm(1, 1, 1, 0.06), 10)

  local names = { 'FL', 'FR', 'RL', 'RR' }
  for i = 0, 3 do
    local wh = car.wheels[i]
    local right = i % 2 == 1
    local y = 44 + math.floor(i / 2) * 96
    local tw, th = 38, 80
    local tx = right and TY_W - 14 - tw or 14
    drawTyre(tx, y, tw, th, wh, not right)
    -- brake disc: thin bar on the inner side of the tyre
    local bt = wh.discTemperature or 0
    local bx = right and tx - 9 or tx + tw + 4
    local bc = bt > 850 and C.red or bt > 750 and C.amber or bt > 250 and C.green or C.cyan
    rect(bx, y + 10, 5, th - 20, C.track, 2)
    local bf = clamp(bt / 1000, 0, 1)
    rect(bx, y + 10 + (th - 20) * (1 - bf), 5, (th - 20) * bf, bc, 2)
    if bt > 750 then circle(bx + 2.5, y + th / 2, 9, alpha(bc, 0.18), 16) end

    -- numbers on the inner side
    local ax = right and 1 or 0
    local nx = right and bx - 8 or bx + 13
    local opt = (wh.tyreOptimumTemperature and wh.tyreOptimumTemperature > 0) and wh.tyreOptimumTemperature or 85
    text(names[i + 1], F.label, 9, nx, y + 8, C.label, ax, 0.5)
    text(string.format('%d°', math.floor(wh.tyreCoreTemperature + 0.5)), F.black, 18, nx, y + 26,
      heat(wh.tyreCoreTemperature, opt), ax, 0.5)
    text(string.format('%.1f', wh.tyrePressure), F.bold, 13, nx, y + 46, C.white, ax, 0.5)
    local wear = clamp((1 - (wh.tyreWear or 0)) * 100, 0, 100)
    local wc = wear > 96 and C.green or wear > 93 and C.yellow or C.red
    text(string.format('%d%%', math.floor(wear + 0.5)), F.bold, 10, nx, y + 63, wc, ax, 0.5)
    local bw = 34
    local barX = right and nx - bw or nx
    pill(barX, y + 72, bw, 4, C.track)
    local wf = clamp((wear - 85) / 15, 0, 1) -- 85% and below: empty bar
    if right then pill(barX + bw * (1 - wf), y + 72, bw * wf, 4, wc) else pill(barX, y + 72, bw * wf, 4, wc) end
  end
end)

-- ------------------------------------------------------------------ car: fuel, battery, electronics, damage
local CAR_W, CAR_H = 300, 222

local function damageLevel(x)
  x = x or 0
  if x >= 60 then return 3 elseif x >= 20 then return 2 elseif x >= 3 then return 1 end
  return 0
end

element('car', CAR_W, function()
  local car = ac.getCar(0)
  if not car then return end
  local ds = (R and R.connected()) and R.input or nil
  local showToEnd = ds and ds.lapsToGo and ds.lapsToGo > 0
  local panelH = CAR_H - (showToEnd and 0 or 18) - (car.kersPresent and 0 or 24)
  rect(0, 0, CAR_W, panelH, C.bg, 12)
  outline(0, 0, CAR_W, panelH, C.edge, 12, 1)

  -- fuel
  local perLap = car.fuelPerLap
  if ds and ds.fuelPerLap and ds.fuelPerLap > 0 then perLap = ds.fuelPerLap end
  local lapsLeft = (perLap and perLap > 0) and car.fuel / perLap or nil
  text('FUEL', F.label, 10, 14, 16, C.label, 0, 0.5)
  local fw = text(string.format('%.1f', car.fuel), F.black, 26, 14, 40, C.white, 0, 0.5)
  text('L', F.bold, 12, 18 + fw, 46, C.label, 0, 0.5)
  if lapsLeft then
    local lc = lapsLeft < 2 and C.red or lapsLeft < 4 and C.yellow or C.white
    text(string.format('%.1f', lapsLeft), F.black, 26, CAR_W - 52, 40, lc, 1, 0.5)
    text('LAPS', F.bold, 10, CAR_W - 46, 46, C.label, 0, 0.5)
    text(string.format('%.2f L/LAP', perLap), F.label, 10, CAR_W - 14, 16, C.label, 1, 0.5)
  end
  -- segmented gauge
  local segs, gx, gw = 20, 14, CAR_W - 28
  local fFrac = car.maxFuel > 0 and car.fuel / car.maxFuel or 0
  local fc = (lapsLeft and lapsLeft < 2) and C.red or (lapsLeft and lapsLeft < 4) and C.yellow or C.green
  for s = 0, segs - 1 do
    local on = (s + 0.5) / segs <= fFrac
    rect(gx + s * gw / segs, 60, gw / segs - 2, 8, on and fc or C.track, 2)
  end
  local y = 78
  if showToEnd then
    local diff = ds.fuelToEnd or 0
    text('TO THE END', F.label, 10, 14, y + 6, C.label, 0, 0.5)
    text(string.format('%+.1f L', diff), F.bold, 12, CAR_W - 14, y + 6, diff >= 0 and C.green or C.red, 1, 0.5)
    y = y + 18
  end

  -- hybrid battery
  if car.kersPresent then
    local kc = car.kersCharge or 0
    text('ERS', F.label, 10, 14, y + 10, C.label, 0, 0.5)
    local bx, bw, n = 50, CAR_W - 112, 10
    for s = 0, n - 1 do
      local on = (s + 0.5) / n <= kc
      local c = kc < 0.2 and C.red or (car.kersCharging and C.cyan or C.lime)
      rect(bx + s * bw / n, y + 4, bw / n - 2, 12, on and c or C.track, 2)
    end
    rect(bx + bw, y + 7, 3, 6, C.faint, 1)
    text(string.format('%d%%', math.floor(kc * 100 + 0.5)), F.bold, 12, CAR_W - 14, y + 10, C.white, 1, 0.5)
    if car.kersCharging then text('+', F.black, 12, CAR_W - 52, y + 10, C.cyan, 1, 0.5) end
    y = y + 24
  end

  -- electronics
  local items = {
    { 'BB', car.brakeBias > 0 and string.format('%.1f', car.brakeBias * 100) or '-' },
    { 'ABS', car.absModes > 0 and (car.absMode > 0 and tostring(car.absMode) or 'OFF') or '-' },
    { 'TC', car.tractionControlModes > 0 and (car.tractionControlMode > 0 and tostring(car.tractionControlMode) or 'OFF') or '-' },
    { 'EB', car.engineBrakeSettingsCount > 0 and tostring(car.currentEngineBrakeSetting + 1) or '-' },
    { 'MAP', tostring((car.fuelMap or 0) + 1) },
  }
  local iw = (CAR_W - 28) / #items
  y = y + 4
  for k, it in ipairs(items) do
    local x = 14 + (k - 1) * iw
    rect(x + 2, y, iw - 4, 46, C.bgDark, 6)
    text(it[1], F.label, 9, x + iw / 2, y + 12, C.label, 0.5, 0.5)
    text(it[2], F.black, 16, x + iw / 2, y + 31, C.white, 0.5, 0.5)
  end
  y = y + 56

  -- damage: a small car seen from above, zones lit by level
  local dmg = car.damage
  local zone = { dmg and dmg[0], dmg and dmg[1], dmg and dmg[2], dmg and dmg[3] }
  local lvlColor = { [0] = C.track, C.yellow, C.amber, C.red }
  local dx, dy = 22, y + 4
  rect(dx, dy + 6, 22, 40, rgbm(1, 1, 1, 0.08), 6)
  rect(dx + 2, dy, 18, 5, lvlColor[damageLevel(zone[1])], 2)          -- front
  rect(dx + 2, dy + 47, 18, 5, lvlColor[damageLevel(zone[2])], 2)     -- rear
  rect(dx - 6, dy + 10, 4, 32, lvlColor[damageLevel(zone[3])], 2)     -- left
  rect(dx + 24, dy + 10, 4, 32, lvlColor[damageLevel(zone[4])], 2)    -- right
  local worst = 0
  for k = 1, 4 do worst = math.max(worst, damageLevel(zone[k])) end
  text('DAMAGE', F.label, 9, 64, dy + 14, C.label, 0, 0.5)
  text(({ [0] = 'NONE', 'MINOR', 'MODERATE', 'SEVERE' })[worst], F.bold, 12, 64, dy + 32,
    worst == 0 and C.white or lvlColor[worst], 0, 0.5)
  text('WATER', F.label, 9, 190, dy + 14, C.label, 1, 0.5)
  text(string.format('%d°', math.floor((car.waterTemperature or 0) + 0.5)), F.bold, 12, 190, dy + 32, C.white, 1, 0.5)
  text('OIL', F.label, 9, CAR_W - 14, dy + 14, C.label, 1, 0.5)
  text(string.format('%d°', math.floor((car.oilTemperature or 0) + 0.5)), F.bold, 12, CAR_W - 14, dy + 32, C.white, 1, 0.5)
end)

-- ------------------------------------------------------------------ engineer: team radio, proposals, strategy
local EN_W = 440
local lastRadioSeq, radioSince, radioShown = -1, -100, ''

local function radioIcon(x, y, c)
  circle(x, y, 3, c, 12)
  for k = 1, 2 do
    arc(x, y, 4 + k * 4, -math.pi * 0.3, math.pi * 0.3, alpha(c, 1 - k * 0.3), 1.8, 12)
    arc(x, y, 4 + k * 4, math.pi * 0.7, math.pi * 1.3, alpha(c, 1 - k * 0.3), 1.8, 12)
  end
end

element('engineer', EN_W, function()
  local connected = R and R.connected()
  rect(0, 0, EN_W, 30, C.bgDark, 8)
  rect(0, 0, 4, 30, C.accent, 8, ui.CornerFlags.Left)
  radioIcon(26, 15, C.white)
  text('TEAM RADIO', F.black, 12, 44, 15, C.white, 0, 0.5)
  if not connected then
    lamp(EN_W - 76, 15, 3.5, C.dim, false)
    text('OFFLINE', F.bold, 10, EN_W - 12, 15, C.dim, 1, 0.5)
    return
  end
  local inp = R.input
  local status = R.text('engineerText')
  lamp(EN_W - 12 - measure(status ~= '' and status:upper() or 'ONLINE', F.bold, 10) - 10, 15, 3.5, C.green, true)
  text(status ~= '' and status:upper() or 'ONLINE', F.bold, 10, EN_W - 12, 15, C.green, 1, 0.5)
  local y = 34

  -- last radio message, for 20 s, sliding in
  if inp.radioSeq ~= lastRadioSeq then
    lastRadioSeq, radioSince, radioShown = inp.radioSeq, now, R.text('radioText')
  end
  local age = now - radioSince
  if radioShown ~= '' and age < 20 then
    local fade = age > 19 and (20 - age) or 1
    local off = (1 - ease(age / 0.25)) * 30
    ui.pushDWriteFont(F.bold)
    local th = ui.measureDWriteText(radioShown, 14 * S, (EN_W - 66) * S).y / S
    ui.popDWriteFont()
    local hgt = math.max(44, th + 20)
    rect(0, y, EN_W, hgt, alpha(C.bg, fade), 8)
    rect(0, y, 4, hgt, alpha(C.accent, fade), 8, ui.CornerFlags.Left)
    -- voice bars: lively while the message is new
    for b = 0, 3 do
      local amp = age < 6 and (0.35 + 0.65 * math.abs(math.sin(now * (7 + b * 2.3) + b))) or 0.3
      local bh = 18 * amp
      rect(16 + b * 7, y + hgt / 2 - bh / 2, 4, bh, alpha(C.accent, fade), 2)
    end
    paragraph(radioShown, F.bold, 14, 52 - off, y + 10, EN_W - 66, alpha(C.white, fade))
    y = y + hgt + 4
  end

  -- proposal to confirm
  if inp.proposalPending ~= 0 then
    local pulse = 0.55 + 0.45 * math.sin(now * 4)
    rect(0, y, EN_W, 60, rgbm(0.1, 0.085, 0, 0.85), 8)
    outline(1, y + 1, EN_W - 2, 58, alpha(C.yellow, pulse), 8, 2)
    text('PROPOSAL', F.black, 10, 14, y + 14, C.yellow, 0, 0.5)
    text(R.text('proposalText'), F.bold, 15, 14, y + 38, C.white, 0, 0.5)
    badge('CONFIRM', EN_W - 158, y + 7, 70, 16, C.green, true)
    badge('DISCARD', EN_W - 82, y + 7, 70, 16, C.red, true)
    y = y + 64
  end

  -- strategy chips
  local chips = {}
  if inp.lapsToGo and inp.lapsToGo > 0 then chips[#chips + 1] = { string.format('%d TO GO', inp.lapsToGo), C.white } end
  if inp.pitWindowOpen and inp.pitWindowOpen > 0 then
    chips[#chips + 1] = { string.format('PIT L%d-%d', inp.pitWindowOpen, math.max(inp.pitWindowOpen, inp.pitWindowClose)), C.cyan }
  end
  if inp.pitStopsLeft and inp.pitStopsLeft > 0 then
    chips[#chips + 1] = { string.format('%d STOP%s', inp.pitStopsLeft, inp.pitStopsLeft > 1 and 'S' or ''), C.white }
  end
  local strat = R.text('strategyText')
  if #chips > 0 or strat ~= '' then
    rect(0, y, EN_W, 30, C.bg, 8)
    local x = 10
    for _, ch in ipairs(chips) do
      local w = measure(ch[1], F.bold, 10) + 16
      pill(x, y + 6, w, 18, alpha(ch[2], 0.16))
      text(ch[1], F.bold, 10, x + w / 2, y + 15, ch[2], 0.5, 0.5)
      x = x + w + 6
    end
    if strat ~= '' then
      ui.pushClipRect(v(x, y), v(EN_W - 8, y + 30), true)
      text(strat, F.label, 11, x + 4, y + 15, C.text, 0, 0.5)
      ui.popClipRect()
    end
  end
end)

-- ------------------------------------------------------------------ track map
local MAP_W = 300
local mapPts, mapBox = nil, nil

local function buildMap()
  local pts = {}
  local minx, maxx, minz, maxz = 1e9, -1e9, 1e9, -1e9
  for k = 0, 359 do
    local p = ac.trackProgressToWorldCoordinate(k / 360)
    pts[#pts + 1] = p
    minx, maxx = math.min(minx, p.x), math.max(maxx, p.x)
    minz, maxz = math.min(minz, p.z), math.max(maxz, p.z)
  end
  if maxx - minx < 1 then return nil end
  mapPts, mapBox = pts, { minx = minx, maxx = maxx, minz = minz, maxz = maxz }
end
ac.onSessionStart(function() mapPts = nil end)

element('map', MAP_W, function()
  if not mapPts then pcall(buildMap) end
  if not mapPts then placeholder(MAP_W, MAP_W, 'MAP: no AI line'); return end
  local size = ui.windowSize()
  local w, h = size.x / S, size.y / S
  local pad = 18
  local b = mapBox
  local k = math.min((w - 2 * pad) / (b.maxx - b.minx), (h - 2 * pad) / (b.maxz - b.minz))
  local ox = pad + ((w - 2 * pad) - (b.maxx - b.minx) * k) / 2
  local oz = pad + ((h - 2 * pad) - (b.maxz - b.minz) * k) / 2
  local function mx(p) return ox + (p.x - b.minx) * k end
  local function mz(p) return oz + (p.z - b.minz) * k end
  local neutral = R and R.state.state ~= R.GREEN and R.state.state ~= R.GREEN_FLASH

  -- track: dark casing, light surface
  for _, p in ipairs(mapPts) do ui.pathLineTo(v(mx(p), mz(p))) end
  ui.pathStroke(rgbm(0, 0, 0, 0.78), true, 11 * S)
  for _, p in ipairs(mapPts) do ui.pathLineTo(v(mx(p), mz(p))) end
  ui.pathStroke(neutral and alpha(C.yellow, 0.95) or rgbm(0.92, 0.93, 0.95, 0.92), true, 4.5 * S)
  -- start / finish: a short chequered bar across the track
  local p0, p1 = mapPts[1], mapPts[2]
  local dx, dz = mx(p1) - mx(p0), mz(p1) - mz(p0)
  local len = math.sqrt(dx * dx + dz * dz)
  if len > 1e-3 then
    -- two rows of four squares, chequered, across the track
    local nx, nz = -dz / len, dx / len
    local tx, tz = dx / len, dz / len
    local q = 2.6
    for row = 0, 1 do
      for s = -2, 1 do
        local c = ((s + row) % 2 == 0) and C.white or C.black
        local ax = mx(p0) + nx * s * q + tx * (row - 1) * q
        local az = mz(p0) + nz * s * q + tz * (row - 1) * q
        ui.drawQuadFilled(v(ax, az), v(ax + nx * q, az + nz * q), v(ax + nx * q + tx * q, az + nz * q + tz * q),
          v(ax + tx * q, az + tz * q), c)
      end
    end
  end

  -- cars: numbered discs, the player on top with a pulse
  local sim = ac.getSim()
  local mine = nil
  local sc = scIndex()
  for i = sim.carsCount - 1, 0, -1 do
    local c = ac.getCar(i)
    if c and c.isConnected and not c.isInPit and i ~= sc then
      if i == 0 then mine = c
      else
        local x, y = mx(c.position), mz(c.position)
        local pos = place(c)
        local fill = c.isInPitlane and rgbm(0.6, 0.6, 0.6, 0.9) or (pos == 1 and C.yellow or C.white)
        circle(x, y, 8.5, rgbm(0, 0, 0, 0.75), 16)
        circle(x, y, 7, fill, 16)
        text(tostring(pos), F.black, 7.5, x, y, C.black, 0.5, 0.5)
      end
    end
  end
  -- the safety car while it is out (or coming in): amber rounded tag with a flashing halo
  local phase = R and R.state and R.state.scPhase
  if sc >= 0 and R.SC_OUT and (phase == R.SC_OUT or phase == R.SC_IN) then
    local c = ac.getCar(sc)
    if c and c.isConnected then
      local x, y = mx(c.position), mz(c.position)
      if phase == R.SC_OUT and blink(0.5) then circle(x, y, 15, alpha(C.amber, 0.3), 20) end
      rect(x - 12, y - 8, 24, 16, rgbm(0, 0, 0, 0.8), 6)
      rect(x - 10.5, y - 6.5, 21, 13, C.amber, 5)
      text('SC', F.black, 7.5, x, y, C.black, 0.5, 0.5)
    end
  end
  if mine then
    local x, y = mx(mine.position), mz(mine.position)
    local p = (now % 1.4) / 1.4
    ring(x, y, 9 + 10 * p, alpha(C.accent, 1 - p), 2, 24)
    circle(x, y, 10.5, C.white, 20)
    circle(x, y, 8.5, C.accent, 20)
    text(tostring(place(mine)), F.black, 8, x, y, C.white, 0.5, 0.5)
  end
end)

-- ------------------------------------------------------------------ radar
local RADAR_W = 220
local RADAR_RANGE = 16
local radarA = 0

element('radar', RADAR_W, function()
  local me = ac.getCar(0)
  if not me then return end
  local sim = ac.getSim()
  local fwd = vec3(me.look.x, 0, me.look.z):normalize()
  local side = vec3(fwd.z, 0, -fwd.x)
  local near = {}
  local leftWarn, rightWarn = 0, 0
  for i = 1, sim.carsCount - 1 do
    local c = ac.getCar(i)
    if c and c.isConnected and not c.isInPit then
      local d = c.position - me.position
      local lx, lz = d:dot(side), d:dot(fwd)
      if math.abs(lx) < RADAR_RANGE * 0.7 and math.abs(lz) < RADAR_RANGE then
        near[#near + 1] = { c = c, x = lx, z = lz }
        if math.abs(lz) < 5.5 and math.abs(lx) < 4.5 then
          local wv = 1 - clamp((math.abs(lx) - 2) / 2.5, 0, 1)
          if lx < 0 then leftWarn = math.max(leftWarn, wv) else rightWarn = math.max(rightWarn, wv) end
        end
      end
    end
  end
  radarA = approach(radarA, #near > 0 and 1 or 0, 8)
  if radarA < 0.02 then placeholder(RADAR_W, RADAR_W, 'RADAR'); return end
  local a = radarA
  local cx, cy = RADAR_W / 2, RADAR_W / 2
  local R0 = RADAR_W / 2 - 6
  local k = R0 / RADAR_RANGE
  circle(cx, cy, R0, alpha(rgbm(0.02, 0.025, 0.035, 0.55), a), 48)
  ring(cx, cy, R0, alpha(C.edge, a), 1, 48)
  ring(cx, cy, R0 * 0.5, alpha(C.edge, a), 1, 40)
  ui.drawLine(v(cx - R0, cy), v(cx + R0, cy), alpha(C.edge, a), 1 * S)
  ui.drawLine(v(cx, cy - R0), v(cx, cy + R0), alpha(C.edge, a), 1 * S)
  -- side warnings: a glow on the side where a car is alongside
  local function sideGlow(dir, amount)
    if amount <= 0 then return end
    local c = amount > 0.6 and C.red or C.amber
    local x0 = dir < 0 and cx - R0 or cx + R0 * 0.35
    if dir < 0 then hgrad(x0, cy - R0 * 0.45, R0 * 0.65, R0 * 0.9, alpha(c, 0.5 * amount * a), alpha(c, 0))
    else hgrad(x0, cy - R0 * 0.45, R0 * 0.65, R0 * 0.9, alpha(c, 0), alpha(c, 0.5 * amount * a)) end
  end
  sideGlow(-1, leftWarn)
  sideGlow(1, rightWarn)

  local function carShape(x, z, dir, c)
    local p = vec2((cx + x * k) * S, (cy - z * k) * S)
    local f = dir * (2.3 * k * S)
    local s = vec2(-dir.y, dir.x) * (0.95 * k * S)
    ui.drawQuadFilled(p - f - s, p - f + s, p + f + s, p + f - s, c)
  end
  for _, e in ipairs(near) do
    local l = vec3(e.c.look.x, 0, e.c.look.z)
    local lx, lz = l:dot(side), l:dot(fwd)
    local len = math.sqrt(lx * lx + lz * lz)
    if len < 1e-3 then lx, lz, len = 0, 1, 1 end
    local close = math.abs(e.x) < 2.6 and math.abs(e.z) < 5.5
    carShape(e.x, e.z, vec2(lx / len, -lz / len), alpha(close and C.red or C.yellow, a))
  end
  carShape(0, 0, vec2(0, -1), alpha(C.white, a))
end)

-- ------------------------------------------------------------------ per frame
function H.init(race) R = race end

function H.update(dt, sim)
  frameDt = clamp(dt or 0.016, 0, 0.25)
  if wallClock then syncClock() else now = now + frameDt end
  updateLive(frameDt, sim)
end

return H
