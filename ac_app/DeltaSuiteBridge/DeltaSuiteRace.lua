-- Delta Suite race control (loaded by DeltaSuiteBridge.lua with a protected require).
--
-- Neutralisations run by the app itself, offline: FCY (countdown, then a fixed speed limit) and VSC (a delta
-- time to stay positive on), with the AI cars capped through the physics API and the race flag overridden.
-- Delta Suite (or the driver, with the CSP buttons) asks for them; the HUD shows them.
--
-- Two mappings, same rules as the bridge (only 4-byte int/float and char arrays):
--   DeltaSuite_Race_Out_v1  written here: neutralisation state, VSC delta, speed check
--   DeltaSuite_Race_In_v1   written by Delta Suite: commands, settings, data for the HUD (radio, strategy...)
-- Layouts identical to hub_core/ac/race_link.py.

local M = {}

local VERSION = 1
local END_MARKER = 0x44535231 -- 'DSR1'

local RACE_OUT_LAYOUT = [[
  int version;
  int frame;
  int available;
  int state;
  int mode;
  float stateTime;
  float countdown;
  float delta;
  float limitKmh;
  float playerKmh;
  int overLimit;
  float infractionS;
  int ackSeq;
  int requestSeq;
  int requestCmd;
  int scCar;
  int scPhase;
  float scGapM;
  int endMarker;
]]

local RACE_IN_LAYOUT = [[
  int version;
  int hostBeat;
  int seq;
  int cmd;
  float vscFactor;
  float vscAiKmh;
  float fcyKmh;
  float countdownS;
  float endingS;
  float scKmh;
  char scCarId[64];
  float pitExitSpline;
  int scWaveLaps;
  float pitLaneX;
  float pitLaneZ;
  float pitLaneDirX;
  float pitLaneDirZ;
  int pitLaneKnown;
  int lapsToGo;
  float fuelLapsLeft;
  float fuelToEnd;
  float fuelPerLap;
  int pitWindowOpen;
  int pitWindowClose;
  int pitStopsLeft;
  int radioSeq;
  char radioText[256];
  int proposalPending;
  char proposalText[160];
  char engineerText[96];
  char strategyText[96];
  int endMarker;
]]

-- states and modes (same numbers in race_link.py)
M.GREEN, M.PENDING, M.ACTIVE, M.ENDING, M.GREEN_FLASH = 0, 1, 2, 3, 4
M.NONE, M.FCY, M.VSC, M.SC = 0, 1, 2, 3
-- safety car phases: no SC car in the session, parked in its box, on track leading, going in, missing, called
-- and waiting at the pit exit for the leader
M.SC_NONE, M.SC_PARKED, M.SC_OUT, M.SC_IN, M.SC_MISSING, M.SC_WAITING = 0, 1, 2, 3, 4, 5
local CMD_FCY, CMD_VSC, CMD_END, CMD_CANCEL, CMD_SC = 1, 2, 3, 4, 5

local DEFAULTS = { vscFactor = 1.4, vscAiKmh = 0, fcyKmh = 80, countdownS = 10, endingS = 12, scKmh = 120,
  scWaveLaps = 1 }
-- vscAiKmh 0 = auto
local GREEN_FLASH_S = 6
local MAX_BANK_S = 10.0         -- VSC: time banked by going slower than the reference is capped here. The
                                -- reference is the best lap slowed in proportion (fast on the straights, slow in
                                -- the corners): with a tight cap a steady speed only ever drifts negative
local DELTA_TOLERANCE_S = 0.2   -- below -0.2 s the driver is too fast
local FCY_GRACE_S = 2           -- after the countdown: the driver had the countdown to slow down
local FCY_AI_BRAKE_S = 3        -- AI cars race on during the countdown, capped only in its last seconds to brake
local VSC_AI_MARGIN = 0.97      -- auto VSC cap: just under the reference's average speed
local VSC_GRACE_S = 8           -- VSC: the delta starts after a few seconds, the time it takes to brake
local FCY_TOLERANCE_KMH = 3
local BINS = 200                -- reference lap profile: time at each 1/200 of the lap
local AI_CAUTION = 3
-- safety car
local SC_RELEASE_MAX_M = 300    -- the SC leaves the pit exit when the leader is this far from it...
local SC_RELEASE_MIN_M = 120    -- ... but not closer than this
local SC_JOIN_MIN_M = 400       -- the SC joins just past the pit exit with the leader this far from it...
local SC_JOIN_MAX_M = 800       -- ... up to this: early, so the player's car (often the leader) is far, and the SC
                                -- waits for the leader at SC_WAIT_KMH
local SC_LANE_KMH = 60          -- in the pit lane: gentle (full gas there made it hit the walls)
local SC_LANE_GAS = 0.45
local SC_UNSEEN_M = 250         -- the SC is moved only with the player's car this far from its box and the spot
local FLASH_PERIOD_S = 0.5      -- every car's high beams flash during a neutralisation
local SC_WAIT_TIMEOUT_S = 180   -- the leader never came by (in the pits, stopped): out anyway
local SC_EXIT_AHEAD_M = 30      -- placed just past the pit exit, on the track
local SC_CLEAR_M = 40           -- ... in a spot with no car this close
local SC_WAIT_KMH = 80          -- until the leader is behind it, the SC goes slowly
local SC_PICKUP_M = 80          -- leader this close behind: picked up, SC at its normal speed
local SC_FIELD_KMH = 90         -- field held at this speed while the SC gets up to speed
local SC_LAUNCH_S = 40          -- ... at most this long (normally until it reaches SC_ROLLING_KMH)
local SC_ROLLING_KMH = 40
local QUEUE_GAP_M = 22          -- gap kept to the car ahead in the queue
local QUEUE_K = 0.6             -- km/h of extra cap per metre of extra gap
local QUEUE_CATCH_KMH = 40      -- far behind: up to SC speed + this to close up
local WAVE_KMH = 60             -- lapped cars waved by: SC speed + this to get past the queue and the SC
local SC_IN_TIMEOUT_S = 240     -- going in: if the SC is not in the pit lane by then, it is put there
local OVERTAKE_WARN_S = 4       -- an overtake under SC keeps the warning on this long
local SC_KICK_S = 30            -- after being placed on track the AI does not throttle up by itself: help it
local SC_KICK_KMH = 80          -- ... up to this speed (once)
local SC_GOVERNOR_KMH = 6       -- with its controls overridden the AI ignores its top speed: brake above cap + this

local out = ac.writeMemoryMappedFile('DeltaSuite_Race_Out_v1', RACE_OUT_LAYOUT)
local inp = ac.writeMemoryMappedFile('DeltaSuite_Race_In_v1', RACE_IN_LAYOUT)
M.input = inp

local btnFcy = ac.ControlButton('DeltaSuite/Race control: FCY')
local btnVsc = ac.ControlButton('DeltaSuite/Race control: VSC')
local btnEnd = ac.ControlButton('DeltaSuite/Race control: end neutralisation')
local btnSc = ac.ControlButton('DeltaSuite/Race control: safety car')
M.buttons = { fcy = btnFcy, vsc = btnVsc, ending = btnEnd, sc = btnSc }

local lastSeq = inp.seq
local lastBeat, lastBeatChange = inp.hostBeat, -100
local clock = 0

-- public state, read by the HUD
local S = {
  available = false, reason = '', state = M.GREEN, mode = M.NONE, since = 0, countdown = 0,
  delta = 0, limitKmh = 0, playerKmh = 0, overLimit = false, infraction = 0, connected = false,
  scCar = -1, scPhase = 0, scGapM = 0,   -- safety car index, phase (M.SC_*), player's gap to the car ahead (m)
}
M.state = S

local function settingText(name)
  if inp.version == VERSION then return ffi.string(inp[name]) end
  return ''
end

local function setting(name)
  if inp.version == VERSION then
    local v = inp[name]
    if v and v > 0 then return v end
  end
  return DEFAULTS[name]
end
M.setting = setting

-- ------------------------------------------------------------ reference lap
-- Time into the lap at each bin, from the driver's best valid lap; uniform profile until one exists.
local ref = { times = nil, lapS = nil }
-- Timed with our own clock from the spline's zero, not with AC's lap timer: the timing line and the spline's zero
-- are not at the same spot, and a profile cut at the timing line jumps by a whole lap where the spline wraps
-- (seen live: a VSC delta of -133 s just after crossing the line).
local cur = { times = {}, t0 = nil, last = nil, pitted = false }
local REF_MAX_FACTOR = 1.25     -- a spline lap slower than the best lap time × this is not a reference

local function recordLap(car, now)
  local p = car.splinePosition
  local bin = math.min(BINS - 1, math.floor(p * BINS))
  if cur.last and cur.last > 0.9 and p < 0.1 then
    -- spline lap completed: keep it if complete, out of the pits and the fastest so far
    if cur.t0 then
      local n = 0
      for _ in pairs(cur.times) do n = n + 1 end
      local lapS = now - cur.t0
      local best = car.bestLapTimeMs > 0 and car.bestLapTimeMs / 1000 or nil
      local plausible = not best or lapS <= best * REF_MAX_FACTOR
      if n > BINS * 0.8 and not cur.pitted and plausible and (not ref.lapS or lapS < ref.lapS) then
        local t, last = {}, 0
        for i = 0, BINS - 1 do
          if cur.times[i] then last = cur.times[i] end
          t[i] = last
        end
        ref.times, ref.lapS = t, lapS
      end
    end
    cur.times, cur.t0, cur.pitted = {}, now, false
  elseif cur.last and math.abs(p - cur.last) > 0.2 then
    cur.times, cur.t0 = {}, nil           -- jump (teleport, back to the pits): this lap does not count
  end
  if car.isInPitlane then cur.pitted = true end
  cur.last = p
  if cur.t0 and cur.times[bin] == nil then cur.times[bin] = now - cur.t0 end
end

local function refLapS(car)
  if ref.lapS then return ref.lapS end
  if car.bestLapTimeMs > 0 then return car.bestLapTimeMs / 1000 end
  if car.estimatedLapTimeMs > 0 then return car.estimatedLapTimeMs / 1000 end
  return math.max(60, ac.getSim().trackLengthM / (150 / 3.6))
end

-- time into the reference lap at lap position p (0..1)
local function refAt(car, p)
  local lapS = refLapS(car)
  if not ref.times then return p * lapS end
  local f = p * BINS
  local i = math.floor(f) % BINS
  local a = ref.times[i]
  local b = (i + 1 < BINS) and ref.times[i + 1] or ref.lapS
  return a + (b - a) * (f - math.floor(f))
end

-- reference time to go from total position `from` to `to` (laps + spline)
local function refElapsed(car, from, to)
  local lapS = refLapS(car)
  local lf, lt = math.floor(from), math.floor(to)
  return (lt - lf) * lapS + refAt(car, to - lt) - refAt(car, from - lf)
end
M.refElapsed = refElapsed

-- VSC speed cap for the AI: the setting, or (0 = auto) the average speed of the VSC reference lap, so the AI runs
-- at the VSC pace on any track and car (a cap is reached on the straights only: the average stays below it)
local function vscAiKmh()
  local v = setting('vscAiKmh')
  if v and v > 0 then return v end
  local car = ac.getCar(0)
  local len = ac.getSim().trackLengthM
  if not car or not len or len <= 0 then return 110 end
  return math.max(50, VSC_AI_MARGIN * len / (refLapS(car) * setting('vscFactor')) * 3.6)
end
M.vscAiKmh = vscAiKmh

-- ------------------------------------------------------------ AI cars
local origAggr = {}
local capped = false

local function forEachAI(fn)
  local sim = ac.getSim()
  for i = 0, sim.carsCount - 1 do
    local c = ac.getCar(i)
    if c and c.isAIControlled and not c.isRemote and i ~= S.scCar then fn(i, c) end
  end
end

-- the original aggression also goes to ac.store: if the app is reloaded mid-neutralisation (Delta Suite updating
-- it, a script error) the new instance can still give it back
local function capAI(kmh)
  forEachAI(function(i, c)
    if origAggr[i] == nil then
      origAggr[i] = c.aiAggression
      ac.store('.DeltaSuite.aggr.' .. i, c.aiAggression)
    end
    pcall(physics.setAITopSpeed, i, kmh)
    pcall(physics.setAICaution, i, AI_CAUTION)
    pcall(physics.setAIAggression, i, 0)
  end)
  capped = true
  ac.store('.DeltaSuite.capped', 1)
end

local function releaseAI()
  if not capped then return end
  forEachAI(function(i)
    pcall(physics.setAITopSpeed, i, 1e9)
    pcall(physics.setAICaution, i, 1)
    if origAggr[i] ~= nil then pcall(physics.setAIAggression, i, origAggr[i]) end
    ac.store('.DeltaSuite.aggr.' .. i, nil)
  end)
  capped = false
  ac.store('.DeltaSuite.capped', nil)
end

-- loaded while a previous instance had the AI capped: free them and clear the flag
if ac.load('.DeltaSuite.capped') then
  local sim = ac.getSim()
  for i = 0, sim.carsCount - 1 do
    local a = tonumber(ac.load('.DeltaSuite.aggr.' .. i) or '')
    if a then origAggr[i] = a end
  end
  capped = true
  releaseAI()
  pcall(physics.overrideRacingFlag, ac.FlagType.None)
  ac.log('DeltaSuite race control: reloaded mid-neutralisation, AI released')
end

local tweaks = nil
pcall(function() tweaks = ac.configureSceneTweaks() end)
local flashing = false
local function flashLights(on)
  if not tweaks then return end
  pcall(function()
    tweaks.forceHighBeams = on and ac.SceneTweakFlag.ForceOn or ac.SceneTweakFlag.Default
    tweaks.forceHeadlights = on and ac.SceneTweakFlag.ForceOn or ac.SceneTweakFlag.Default
  end)
end
flashLights(false)

local function setFlag(yellow)
  pcall(physics.overrideRacingFlag, yellow and ac.FlagType.Caution or ac.FlagType.None)
end

-- ------------------------------------------------------------ safety car
-- A real car of the session (the one named in the settings, or the first whose name or id says "safety"),
-- parked in its pit box from the start. A parked AI does not drive out of its box on request, so it is put
-- straight on track ahead of the leader (physics.setAICarPosition), where no car is close; the field is held slow
-- while it gets up to speed, then queues behind it car by car: each AI's speed cap follows the car ahead and the
-- gap to it. Going in: pit request, the queue holds until the SC is in the pit lane, green when the leader
-- crosses the line.
local SCX = {
  light = nil, yellow = nil, red = nil, deployedAt = 0, inAt = 0, leaderSpline = nil, kick = nil,
  kicking = false, rolling = false, calledAt = 0, pickedUp = false, laps = 0, lastSpline = nil,
  waveDone = false, wave = {}, pitExit = nil, pitSeen = {}, capNow = 120,
  queue = {}, playerAheadOf = nil, overtakeAt = -100,
}

local function trackLen() return math.max(500, ac.getSim().trackLengthM or 4000) end

local function findSC()
  local sim = ac.getSim()
  local wanted = settingText('scCarId'):lower()
  for i = 1, sim.carsCount - 1 do
    local id = (ac.getCarID(i) or ''):lower()
    local name = (ac.getCarName(i) or ''):lower()
    if wanted ~= '' then
      if id == wanted then return i end
    elseif id:find('safety', 1, true) or name:find('safety', 1, true) then
      return i
    end
  end
  return -1
end

local function scLights(on)
  local i = S.scCar
  if i < 0 then return end
  if not SCX.yellow then
    pcall(function()
      local root = ac.findNodes('carRoot:' .. i)
      SCX.yellow = root:findMeshes('{ g_safety_yellow, ManufacturerPlate_Geo_lodA }')
      SCX.red = root:findMeshes('{ g_safety_red, Light_Geo_lodA00278, Light_Geo_lodA002 }')
      SCX.yellow:ensureUniqueMaterials()
      SCX.red:ensureUniqueMaterials()
    end)
  end
  if on and not SCX.light then
    pcall(function()
      SCX.light = ac.LightSource(ac.LightType.Regular)
      SCX.light.range, SCX.light.fadeAt, SCX.light.fadeSmooth = 14, 600, 60
    end)
  elseif not on and SCX.light then
    pcall(function() SCX.light:dispose() end)
    SCX.light = nil
  end
  if not on then
    pcall(function()
      SCX.yellow:setMaterialProperty('ksEmissive', vec3(0, 0, 0))
      SCX.red:setMaterialProperty('ksEmissive', vec3(0, 0, 0))
    end)
  end
end

local function scLightsFrame()
  local i = S.scCar
  if i < 0 or not SCX.light then return end
  local car = ac.getCar(i)
  local on = (clock % 0.5) < 0.25
  pcall(function()
    SCX.yellow:setMaterialProperty('ksEmissive', on and vec3(80, 40, 0) or vec3(0, 0, 0))
    SCX.red:setMaterialProperty('ksEmissive', on and vec3(0, 0, 0) or vec3(80, 40, 0))
  end)
  pcall(function()
    SCX.light.position = car.position + car.up * 1.6
    SCX.light.color = on and rgb(30, 14, 0) or rgb(8, 4, 0)
  end)
end

-- parked: braked with the stop counter only (a throttle limit, even released later, leaves the AI off the gas)
local function kickOff()
  if SCX.kick then pcall(function() SCX.kick.gas, SCX.kick.brake = 0, 0 end) end
  SCX.kicking = false
end

-- The track's pit_lane.ai, read here (Delta Suite is not needed): 4 int32 header (version, count, lap time,
-- samples), then per point x, y, z, length (float32) and id (int32). The file often runs on the track before the pit
-- entry and after the exit: the pit lane proper is its longest stretch away from the lap line (PIT_OFF_LINE_M).
local PIT_OFF_LINE_M = 8
local PIT_START_BEFORE_M = 150  -- the SC starts this far before the end of the pit lane, heading for the exit
local pitFile = nil             -- { exit = spline, pos = vec3, dir = vec3 } or false if unusable

local function loadPitLane()
  local data
  for _, folder in ipairs({ ac.FolderID.CurrentTrackLayout, ac.FolderID.CurrentTrack }) do
    local ok, d = pcall(io.load, ac.getFolder(folder) .. '/ai/pit_lane.ai')
    if ok and d and #d >= 16 then data = d; break end
  end
  if not data then return false end
  local base = ffi.cast('const char*', data)
  local count = ffi.cast('const int32_t*', base)[1]
  if count < 10 or count > 200000 or 16 + count * 20 > #data then return false end
  local pts, off = {}, {}
  for i = 0, count - 1 do
    local f = ffi.cast('const float*', base + 16 + i * 20)
    local p = vec3(f[0], f[1], f[2])
    pts[i + 1] = p
    local q = ac.trackProgressToWorldCoordinate(ac.worldCoordinateToTrackProgress(p))
    off[i + 1] = math.sqrt((q.x - p.x) ^ 2 + (q.z - p.z) ^ 2) > PIT_OFF_LINE_M
  end
  local best, runStart, bestEnd = 0, nil, nil
  for k = 1, count + 1 do
    local o = off[k] or false
    if o and not runStart then runStart = k
    elseif not o and runStart then
      if k - runStart > best then best, bestEnd = k - runStart, k end
      runStart = nil
    end
  end
  if not bestEnd or best < 10 then return false end
  local e = math.min(bestEnd, count)
  local k, travelled = e, 0
  while k > 2 and travelled < PIT_START_BEFORE_M do
    travelled = travelled + (pts[k] - pts[k - 1]):length()
    k = k - 1
  end
  local dir = pts[math.min(k + 3, count)] - pts[k]
  dir.y = 0
  return { exit = ac.worldCoordinateToTrackProgress(pts[e]), pos = pts[k] + vec3(0, 0.3, 0), dir = dir:normalize() }
end

-- pit exit: from the track's pit_lane.ai, else Delta Suite, else learned from cars leaving the pit lane, else near
-- the SC's box
local function learnPitExit()
  local sim = ac.getSim()
  for i = 0, sim.carsCount - 1 do
    local c = ac.getCar(i)
    if c and i ~= S.scCar then
      local was = SCX.pitSeen[i]
      SCX.pitSeen[i] = c.isInPitlane
      if was and not c.isInPitlane and c.speedKmh > 30 then SCX.pitExit = c.splinePosition end
    end
  end
end

local function pitExit()
  if pitFile == nil then
    local ok, r = pcall(loadPitLane)
    pitFile = ok and r or false
    if not ok then ac.log('DeltaSuite SC: pit_lane.ai: ' .. tostring(r)) end
    if pitFile then
      ac.log(string.format('DeltaSuite SC: pit exit at %.3f, SC starts at (%.0f, %.0f, %.0f)', pitFile.exit,
        pitFile.pos.x, pitFile.pos.y, pitFile.pos.z))
    end
  end
  if pitFile then return pitFile.exit end
  if inp.version == VERSION and S.connected and inp.pitExitSpline >= 0 and inp.pitExitSpline <= 1 then
    return inp.pitExitSpline
  end
  if SCX.pitExit then return SCX.pitExit end
  local ok, p = pcall(function()
    return ac.worldCoordinateToTrackProgress(ac.getCar(S.scCar).pitTransform.position)
  end)
  if ok and p and p >= 0 then return (p + 200 / trackLen()) % 1 end
  return nil
end

local function waveLaps()
  if inp.version == VERSION and inp.scWaveLaps < 0 then return 0 end   -- "never"
  return setting('scWaveLaps')
end

local function holdSC()
  kickOff()
  pcall(physics.setAIStopCounter, S.scCar, 10)
  pcall(physics.setAIPitStopRequest, S.scCar, false)
end

local function parkSC()
  if S.scCar < 0 then return end
  pcall(physics.teleportCarTo, S.scCar, ac.SpawnSet.Pits)
  holdSC()
  scLights(false)
  S.scPhase = M.SC_PARKED
end

-- cars in the race, in track order behind the SC (nearest first); pit lane and retired cars left out
local function queueOrder()
  local sim, sc = ac.getSim(), ac.getCar(S.scCar)
  local list = {}
  for i = 0, sim.carsCount - 1 do
    local c = ac.getCar(i)
    if i ~= S.scCar and c and c.isConnected and not c.isInPitlane and not c.isRetired then
      list[#list + 1] = { i = i, c = c, behind = (sc.splinePosition - c.splinePosition) % 1 }
    end
  end
  table.sort(list, function(a, b) return a.behind < b.behind end)
  return list
end

local function leaderIndex()
  local sim = ac.getSim()
  local best, bestPos = nil, 1e9
  for i = 0, sim.carsCount - 1 do
    local c = ac.getCar(i)
    if i ~= S.scCar and c and c.isConnected and not c.isInPit and c.racePosition > 0 and c.racePosition < bestPos then
      best, bestPos = i, c.racePosition
    end
  end
  return best
end

-- the first spot from p on with no car within SC_CLEAR_M, or nil
local function freeSpot(p)
  local L = trackLen()
  local sim = ac.getSim()
  for _ = 1, 10 do
    local clear = true
    for i = 0, sim.carsCount - 1 do
      local c = ac.getCar(i)
      if i ~= S.scCar and c and c.isConnected and not c.isInPitlane then
        local d = math.abs(((c.splinePosition - p + 0.5) % 1) - 0.5) * L
        if d < SC_CLEAR_M then clear = false; break end
      end
    end
    if clear then return p end
    p = (p + 20 / L) % 1
  end
  return nil
end

-- the point in the pit lane, before the exit, where the SC starts so it is seen driving out (from Delta Suite)
local function pitLanePoint()
  if pitFile == nil then pitExit() end
  if pitFile then return pitFile.pos, pitFile.dir end
  if inp.version ~= VERSION or not S.connected or inp.pitLaneKnown ~= 1 then return nil end
  local sc = ac.getCar(S.scCar)
  local y = sc and sc.position.y or 0
  local pos = vec3(inp.pitLaneX, y + 30, inp.pitLaneZ)
  local hit = physics.raycastTrack(pos, vec3(0, -1, 0), 80)
  if hit and hit >= 0 then pos.y = pos.y - hit + 0.3 else pos.y = y + 0.3 end
  return pos, vec3(inp.pitLaneDirX, 0, inp.pitLaneDirZ):normalize()
end

-- the player's car is far enough from pos not to see the SC being moved there (the car, not the camera: an orbit
-- camera on the SC would otherwise keep it in the pits for ever)
local function unseen(pos)
  local me = ac.getCar(0)
  return me ~= nil and (me.position - pos):length() > SC_UNSEEN_M
end

local function deploySC(p, lanePos, laneDir)
  local pos, dir
  if lanePos then
    pos, dir = lanePos, laneDir
  else
    pos = ac.trackProgressToWorldCoordinate(p)
    dir = (ac.trackProgressToWorldCoordinate((p + 2 / trackLen()) % 1) - pos):normalize()
  end
  local ok = pcall(physics.setAICarPosition, S.scCar, pos, dir)
  if not ok then return false end
  pcall(physics.setAIThrottleLimit, S.scCar, 1)
  pcall(physics.setAIStopCounter, S.scCar, 0)
  pcall(physics.setAIPitStopRequest, S.scCar, false)
  pcall(physics.setAITopSpeed, S.scCar, SC_WAIT_KMH)
  pcall(physics.setAIAggression, S.scCar, 0)
  pcall(physics.awakeCar, S.scCar)
  SCX.kick = SCX.kick or ac.overrideCarControls(S.scCar)
  SCX.kicking, SCX.rolling = true, false
  scLights(true)
  S.scPhase, SCX.deployedAt = M.SC_OUT, clock
  SCX.playerAheadOf, SCX.leaderSpline = nil, nil
  SCX.pickedUp, SCX.laps, SCX.lastSpline, SCX.waveDone, SCX.wave = false, 0, nil, false, {}
  return true
end

-- every frame while the SC is out: speed caps along the queue
local function driveQueue()
  local sc = ac.getCar(S.scCar)
  local L = trackLen()
  local launch = not SCX.rolling and clock - SCX.deployedAt < SC_LAUNCH_S and S.scPhase == M.SC_OUT
  local scKmh = setting('scKmh')
  local q = queueOrder()
  SCX.queue = q
  local aheadSpline, aheadSpeed = sc.splinePosition, sc.speedKmh
  for _, e in ipairs(q) do
    local c = e.c
    local w = SCX.wave[e.i]
    if w then
      -- waved by: free to pass the queue and the SC; once just ahead of the SC it is at the back of the queue
      if w.last and w.last < 0.1 and e.behind > 0.9 then SCX.wave[e.i] = nil; w = nil end
      if w then w.last = e.behind end
    end
    if w then
      if c.isAIControlled and not c.isRemote then
        pcall(physics.setAITopSpeed, e.i, scKmh + WAVE_KMH)
        pcall(physics.setAICaution, e.i, 0)
        pcall(physics.setAIAggression, e.i, 1)
      end
      goto continue
    end
    local gap = ((aheadSpline - c.splinePosition) % 1) * L
    if c.isAIControlled and not c.isRemote then
      if origAggr[e.i] == nil then
        origAggr[e.i] = c.aiAggression
        ac.store('.DeltaSuite.aggr.' .. e.i, c.aiAggression)
      end
      local cap
      if launch then
        cap = SC_FIELD_KMH
      elseif gap > 400 then
        cap = scKmh + QUEUE_CATCH_KMH
      else
        cap = math.max(30, math.min(scKmh + QUEUE_CATCH_KMH, aheadSpeed + QUEUE_K * (gap - QUEUE_GAP_M)))
      end
      pcall(physics.setAITopSpeed, e.i, cap)
      pcall(physics.setAICaution, e.i, AI_CAUTION)
      pcall(physics.setAIAggression, e.i, 0)
    end
    if e.i == 0 then S.scGapM = gap end
    aheadSpline, aheadSpeed = c.splinePosition, c.speedKmh
    ::continue::
  end
  capped = true
  ac.store('.DeltaSuite.capped', 1)
end

-- the player passing the car that was ahead in the queue (or the SC): warning and infraction time
local function checkOvertake(car)
  local q = SCX.queue
  local ahead = S.scCar
  for k, e in ipairs(q) do
    if e.i == 0 then
      ahead = k > 1 and q[k - 1].i or S.scCar
      break
    end
  end
  if SCX.playerAheadOf ~= nil and ahead ~= SCX.playerAheadOf then
    -- the car that was ahead is now behind us: overtaken (a car that went into the pits does not count)
    local prev = ac.getCar(SCX.playerAheadOf)
    if prev and not prev.isInPitlane and ((car.splinePosition - prev.splinePosition) % 1) < 0.5 then
      SCX.overtakeAt = clock
    end
  end
  SCX.playerAheadOf = ahead
  return clock - SCX.overtakeAt < OVERTAKE_WARN_S
end

-- ------------------------------------------------------------ state machine
local base = nil   -- VSC delta start: { t = clock, pos = laps + spline }

-- laps + lap position, counted from the spline itself: lapCount and splinePosition do not change on the same frame
-- at the finish line, and a one-frame jump of a whole lap would wreck the delta
local track = { laps = 0, last = nil }
local function totalPos(car)
  local p = car.splinePosition
  if track.last then
    if track.last > 0.9 and p < 0.1 then track.laps = track.laps + 1
    elseif track.last < 0.1 and p > 0.9 then track.laps = track.laps - 1 end
  end
  track.last = p
  return track.laps + p
end

local function enter(state, mode)
  S.state, S.since = state, clock
  if mode then S.mode = mode end
  if state == M.PENDING then
    S.countdown = setting('countdownS')
    setFlag(true)
  elseif state == M.ACTIVE then
    S.infraction, S.overLimit = 0, false
    if S.mode == M.SC then
      S.limitKmh = setting('scKmh')
      SCX.overtakeAt = -100
    elseif S.mode == M.VSC then
      capAI(vscAiKmh())
      local car = ac.getCar(0)
      base = { t = clock, pos = S.pos or car.splinePosition }
      S.delta = 0
    else
      capAI(setting('fcyKmh'))
    end
    setFlag(true)
  elseif state == M.ENDING then
    S.countdown = setting('endingS')
    if S.mode == M.SC then
      -- "safety car in this lap": lights off, into the pits at the end of the lap; green when the leader crosses
      -- the line after the SC is in the pit lane
      S.countdown, SCX.inAt, SCX.leaderSpline = 0, clock, nil
      scLights(false)
      pcall(physics.setAIPitStopRequest, S.scCar, true)
      S.scPhase = M.SC_IN
    end
  elseif state == M.GREEN_FLASH then
    releaseAI()
    setFlag(false)
    base, S.delta, S.overLimit = nil, 0, false
  elseif state == M.GREEN then
    releaseAI()
    setFlag(false)
    if S.mode == M.SC and (S.scPhase == M.SC_OUT or S.scPhase == M.SC_WAITING) then parkSC() end
    S.mode, base = M.NONE, nil
    S.overLimit, S.delta, S.limitKmh = false, 0, 0
  end
end

local function request(cmd)
  if not S.available then return false, S.reason end
  if cmd == CMD_FCY or cmd == CMD_VSC then
    if S.state ~= M.GREEN and S.state ~= M.GREEN_FLASH then return false, 'neutralisation already running' end
    if cmd == CMD_FCY then enter(M.PENDING, M.FCY) else enter(M.ACTIVE, M.VSC) end
    return true, cmd == CMD_FCY and 'FCY' or 'VSC'
  elseif cmd == CMD_SC then
    if S.state ~= M.GREEN and S.state ~= M.GREEN_FLASH then return false, 'neutralisation already running' end
    if S.scCar < 0 then return false, 'no safety car in this session' end
    if S.scPhase ~= M.SC_PARKED then return false, 'safety car not ready' end
    enter(M.ACTIVE, M.SC)
    S.scPhase, SCX.calledAt = M.SC_WAITING, clock
    capAI(vscAiKmh())                     -- everyone slows down until they reach the SC queue
    return true, 'SC'
  elseif cmd == CMD_END then
    if S.state == M.PENDING then enter(M.GREEN); return true, 'cancelled' end
    if S.state ~= M.ACTIVE then return false, 'nothing to end' end
    enter(M.ENDING)
    return true, 'ending'
  elseif cmd == CMD_CANCEL then
    enter(M.GREEN)
    return true, 'green'
  end
  return false, 'unknown command'
end
M.request = function(kind)
  return request(({ fcy = CMD_FCY, vsc = CMD_VSC, sc = CMD_SC, ending = CMD_END, cancel = CMD_CANCEL })[kind] or 0)
end

ac.onSessionStart(function()
  enter(M.GREEN)
  S.scCar, S.scPhase, SCX.yellow, SCX.red = findSC(), M.SC_NONE, nil, nil
  pitFile = nil
  if S.scCar >= 0 then parkSC() end
  origAggr = {}
  ref.times, ref.lapS, cur.times, cur.t0, cur.last = nil, nil, {}, nil, nil
end)

local function updateChecks(car, dt)
  S.playerKmh = car.speedKmh
  S.limitKmh = 0
  local checking = S.state == M.ACTIVE or S.state == M.ENDING
  if not checking or car.isInPitlane then S.overLimit = false; return end
  if S.mode == M.VSC and base then
    local pos = S.pos
    if S.state == M.ACTIVE and clock - S.since < VSC_GRACE_S then
      base.t, base.pos, S.delta, S.overLimit = clock, pos, 0, false
      return
    end
    local d = (clock - base.t) - setting('vscFactor') * refElapsed(car, base.pos, pos)
    if d < -30 or d > 30 then
      -- impossible value (reference changed under us, teleport): start the delta again rather than show it
      base.t, base.pos, d = clock, pos, 0
    end
    if d > MAX_BANK_S then
      base.t = base.t + (d - MAX_BANK_S)
      d = MAX_BANK_S
    end
    S.delta = d
    S.overLimit = d < -DELTA_TOLERANCE_S
  elseif S.mode == M.SC then
    S.limitKmh = setting('scKmh')
    S.overLimit = checkOvertake(car)
  elseif S.mode == M.FCY then
    S.limitKmh = setting('fcyKmh')
    S.overLimit = clock - S.since > FCY_GRACE_S and car.speedKmh > S.limitKmh + FCY_TOLERANCE_KMH
  end
  if car.isAIControlled then S.overLimit = false end -- the AI is driving: nothing to warn about
  if S.overLimit then S.infraction = S.infraction + dt end
end

-- safety car, every frame: find it, keep it parked, drive the queue, bring it in, green at the line
local scFindT = -10
local function updateSC(dt)
  if pitFile == nil and clock > 2 and S.scCar >= 0 then pitExit() end   -- read the pit lane once, early
  if clock - scFindT > 2 and (S.scPhase == M.SC_NONE or S.scPhase == M.SC_MISSING) then
    scFindT = clock
    local i = findSC()
    if i >= 0 and S.state == M.GREEN then
      S.scCar = i
      parkSC()
    elseif i < 0 then
      S.scCar, S.scPhase = -1, M.SC_NONE
    end
  end
  if S.scCar < 0 then return end
  local sc = ac.getCar(S.scCar)
  if not sc then S.scPhase = M.SC_MISSING; return end

  learnPitExit()
  if S.scPhase == M.SC_PARKED or S.scPhase == M.SC_WAITING then
    if math.floor(clock) ~= math.floor(clock - dt) then holdSC() end
  elseif S.scPhase == M.SC_IN and sc.isInPit then
    holdSC()
    S.scPhase = M.SC_PARKED
  end
  if S.mode ~= M.SC then return end

  if S.scPhase == M.SC_OUT or S.scPhase == M.SC_IN then
    if sc.speedKmh >= SC_ROLLING_KMH then SCX.rolling = true end
    if SCX.kick then
      local lane = sc.isInPitlane and S.scPhase == M.SC_OUT
      local cap = lane and math.min(SCX.capNow, SC_LANE_KMH) or SCX.capNow
      pcall(physics.setAITopSpeed, S.scCar, cap)
      local kickTo = lane and SC_LANE_KMH / 2 or SC_KICK_KMH
      if SCX.kicking and (sc.speedKmh >= kickTo or clock - SCX.deployedAt > SC_KICK_S) then
        SCX.kicking = false
      end
      if lane and sc.speedKmh < 10 and clock - SCX.deployedAt < SC_KICK_S then SCX.kicking = true end
      local over = sc.speedKmh - (cap + SC_GOVERNOR_KMH)
      local braking = not SCX.kicking and over > 0 and (lane or not sc.isInPitlane)
      pcall(function()
        SCX.kick.gas = SCX.kicking and (lane and SC_LANE_GAS or 1) or 0
        SCX.kick.brake = braking and math.min(0.7, over / 30) or 0
      end)
    end
  end
  if S.state == M.ACTIVE and S.scPhase == M.SC_WAITING then
    -- joins just past the pit exit with the leader 400-800 m from it, unseen by the player
    if math.floor(clock) ~= math.floor(clock - dt) then capAI(vscAiKmh()) end
    local e, leader = pitExit(), leaderIndex()
    if e and leader then
      local d = ((e - ac.getCar(leader).splinePosition) % 1) * trackLen()
      local timeout = clock - SCX.calledAt > SC_WAIT_TIMEOUT_S
      -- AC sends any AI in the pit lane without a stop back to its box (tested: placed in the pit lane it was put
      -- back and spun its wheels there): the SC joins on the track just past the pit exit, unseen by the player
      local spotPos = ac.trackProgressToWorldCoordinate((e + SC_EXIT_AHEAD_M / trackLen()) % 1)
      local inWindow = d <= SC_JOIN_MAX_M and d >= SC_JOIN_MIN_M
      if not timeout and not (unseen(spotPos) and unseen(ac.getCar(S.scCar).position)) then inWindow = false end
      if S.scPhase == M.SC_WAITING and (inWindow or timeout) then
        local spot = freeSpot((e + SC_EXIT_AHEAD_M / trackLen()) % 1)
        if spot then
          SCX.capNow = SC_WAIT_KMH
          deploySC(spot)
        end
      end
    end
  elseif S.state == M.ACTIVE then
    -- slow until the leader is right behind; then laps behind the SC count towards waving the lapped cars by
    local leader = leaderIndex()
    if leader and not SCX.pickedUp then
      local gap = ((sc.splinePosition - ac.getCar(leader).splinePosition) % 1) * trackLen()
      if gap < SC_PICKUP_M then SCX.pickedUp = true end
    end
    SCX.capNow = SCX.pickedUp and setting('scKmh') or SC_WAIT_KMH
    if SCX.pickedUp and SCX.lastSpline and SCX.lastSpline > 0.9 and sc.splinePosition < 0.1 then
      SCX.laps = SCX.laps + 1
    end
    SCX.lastSpline = sc.splinePosition
    local n = waveLaps()
    if leader and not SCX.waveDone and n > 0 and SCX.laps >= n then
      SCX.waveDone = true
      local L = ac.getCar(leader)
      local lead = L.lapCount + L.splinePosition
      local count = 0
      for _, e in ipairs(queueOrder()) do
        local c = e.c
        if e.i ~= leader and lead - (c.lapCount + c.splinePosition) > 0.6 then
          SCX.wave[e.i] = { last = nil }
          count = count + 1
        end
      end
      S.waving = count
      ac.log('DeltaSuite SC: lapped cars waved by: ' .. count)
    end
    driveQueue()
    scLightsFrame()
  elseif S.state == M.ENDING then
    local inLane = sc.isInPitlane or sc.isInPit
    if not inLane and clock - SCX.inAt > SC_IN_TIMEOUT_S then
      parkSC()
      S.scPhase, inLane = M.SC_IN, true
    end
    if not inLane then
      driveQueue()                        -- the SC still leads until the pit entry
    else
      -- SC in: the leader sets the pace (SC speed) and the queue holds until the leader crosses the line
      local leader = leaderIndex()
      if leader then
        local L = ac.getCar(leader)
        pcall(physics.setAITopSpeed, leader, setting('scKmh'))
        local q = queueOrder()
        local aheadSpline, aheadSpeed = L.splinePosition, L.speedKmh
        local trackL = trackLen()
        -- queue behind the leader: order by distance behind it
        table.sort(q, function(a, b)
          return (L.splinePosition - a.c.splinePosition) % 1 < (L.splinePosition - b.c.splinePosition) % 1
        end)
        for _, e in ipairs(q) do
          if e.i ~= leader then
            local gap = ((aheadSpline - e.c.splinePosition) % 1) * trackL
            if e.c.isAIControlled and not e.c.isRemote then
              local cap = math.max(30, math.min(setting('scKmh') + QUEUE_CATCH_KMH,
                aheadSpeed + QUEUE_K * (gap - QUEUE_GAP_M)))
              pcall(physics.setAITopSpeed, e.i, cap)
            end
            aheadSpline, aheadSpeed = e.c.splinePosition, e.c.speedKmh
          end
        end
        if SCX.leaderSpline and SCX.leaderSpline > 0.9 and L.splinePosition < 0.1 then
          enter(M.GREEN_FLASH)
        end
        SCX.leaderSpline = L.splinePosition
      end
    end
  end
end

function M.update(dt, sim)
  clock = clock + dt
  S.available = (not sim.isOnlineRace) and physics.allowed()
  S.reason = sim.isOnlineRace and 'offline only' or (physics.allowed() and '' or 'physics API not available')

  if inp.hostBeat ~= lastBeat then lastBeat, lastBeatChange = inp.hostBeat, clock end
  S.connected = clock - lastBeatChange < 2

  if inp.seq ~= lastSeq then
    lastSeq = inp.seq
    local called, ok = pcall(request, inp.cmd)
    out.ackSeq = lastSeq
    if not called then ac.log('DeltaSuite race control: ' .. tostring(ok)) end
  end
  for kind, btn in pairs(M.buttons) do
    if btn:pressed() then
      local cmd = kind == 'fcy' and CMD_FCY or kind == 'vsc' and CMD_VSC or kind == 'sc' and CMD_SC or CMD_END
      local ok = request(cmd)
      if ok then out.requestSeq, out.requestCmd = out.requestSeq + 1, cmd end
    end
  end

  local car = ac.getCar(0)
  if car then recordLap(car, clock); S.pos = totalPos(car) end -- every frame: the lap count follows the spline
  updateSC(dt)

  if S.state == M.PENDING then
    S.countdown = math.max(0, setting('countdownS') - (clock - S.since))
    if S.countdown <= FCY_AI_BRAKE_S and not capped then capAI(setting('fcyKmh')) end
    if S.countdown <= 0 then enter(M.ACTIVE) end
  elseif S.state == M.ACTIVE and capped and S.mode ~= M.SC then
    -- AI joining later (back from the pits, player handing over to the AI): cap them too, every second
    if math.floor(clock) ~= math.floor(clock - dt) then
      capAI(S.mode == M.VSC and vscAiKmh() or setting('fcyKmh'))
    end
  elseif S.state == M.ENDING and S.mode ~= M.SC then
    S.countdown = math.max(0, setting('endingS') - (clock - S.since))
    if S.countdown <= 0 then enter(M.GREEN_FLASH) end
  elseif S.state == M.GREEN_FLASH and clock - S.since > GREEN_FLASH_S then
    enter(M.GREEN)
  end
  if car then updateChecks(car, dt) end
  local neutral = S.state == M.PENDING or S.state == M.ACTIVE or S.state == M.ENDING
  if neutral then
    local on = (clock % FLASH_PERIOD_S) < FLASH_PERIOD_S / 2
    if on ~= flashing then flashing = on; flashLights(on) end
  elseif flashing then
    flashing = false
    flashLights(false)
  end
  -- the overridden flag does not always stick (seen at an SC deployment): asserted again every second
  if (S.state == M.PENDING or S.state == M.ACTIVE or S.state == M.ENDING) and math.floor(clock) ~= math.floor(clock - dt) then
    setFlag(true)
  end

  out.version = VERSION
  out.endMarker = END_MARKER
  out.frame = out.frame + 1
  out.available = S.available and 1 or 0
  out.state = S.state
  out.mode = S.mode
  out.stateTime = clock - S.since
  out.countdown = S.countdown
  out.delta = S.delta
  out.limitKmh = S.limitKmh
  out.playerKmh = S.playerKmh
  out.overLimit = S.overLimit and 1 or 0
  out.infractionS = S.infraction
  out.scCar = S.scCar
  out.scPhase = S.scPhase
  out.scGapM = S.scGapM
end

-- strings from Delta Suite for the HUD (empty when it is not connected)
function M.text(field)
  if inp.version ~= VERSION or not S.connected then return '' end
  return ffi.string(inp[field])
end

function M.connected() return S.connected and inp.version == VERSION end

-- reference time between two lap positions, for the relative gaps of the HUD
function M.gapSeconds(car, fromSpline, toSpline)
  return refElapsed(car, fromSpline, fromSpline + (toSpline - fromSpline) % 1)
end

function M.refLap(car) return refLapS(car) end

return M
