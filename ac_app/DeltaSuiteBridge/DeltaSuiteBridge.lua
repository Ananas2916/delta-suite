-- Delta Suite Bridge (Lua app for Custom Shaders Patch)
--
-- Bridge between Assetto Corsa and Delta Suite (external program), through two memory-mapped files:
--   DeltaSuite_Bridge_Out_v1  written here: current adjustments, setup, pit stop, rivals, radio buttons
--   DeltaSuite_Bridge_In_v1   written by Delta Suite: one command at a time, numbered by `seq`
-- The onboard video lives in DeltaSuiteOnboard.lua, loaded with a protected require: if it fails, the
-- bridge still works.
-- The layouts must stay identical to those in hub_core/ac/csp_bridge.py (only 4-byte int/float and
-- char arrays, so the alignment is the same in LuaJIT and in ctypes).

local VERSION = 1
local END_MARKER = 0x44535431 -- 'DST1': Delta Suite checks it reads it at the expected offset

local MAX_SETUP, MAX_PIT, MAX_CARS = 96, 16, 64

local OUT_LAYOUT = [[
  int version;
  int frame;
  int ackSeq;
  int ackOk;
  char ackMsg[64];
  int focusedCar;
  int carsCount;
  int setupEditable;
  int pttDown;
  int confirmCount;
  int cancelCount;
  float brakeBias;
  float brakeBiasStep;
  float brakeBiasMin;
  float brakeBiasMax;
  int absMode;
  int absModes;
  int tcMode;
  int tcModes;
  int engineBrakeCount;
  int setupCount;
  int pitCount;
  int pitPreset;
  char setupName[96][32];
  char setupLabel[96][48];
  char setupUnits[96][12];
  int setupValue[96];
  int setupMin[96];
  int setupMax[96];
  int setupStep[96];
  float setupMult[96];
  int setupReadOnly[96];
  char pitName[16][32];
  char pitType[16][12];
  int pitValue[16];
  int pitMin[16];
  int pitMax[16];
  int pitReadOnly[16];
  int carIndex[64];
  int carConnected[64];
  int carRacePos[64];
  int carLapCount[64];
  float carSpline[64];
  int carLapTimeMs[64];
  int carLastLapMs[64];
  int carBestLapMs[64];
  int carInPitlane[64];
  int carInPit[64];
  float carSpeed[64];
  int carLastLapValid[64];
  char carDriver[64][32];
  char carModel[64][32];
  int endMarker;
]]

local IN_LAYOUT = [[
  int version;
  int hostBeat;
  int seq;
  int cmd;
  float value;
  char name[32];
  char text[512];
  int endMarker;
]]

-- Module-level variables: they stay alive while the app is loaded.
local out = ac.writeMemoryMappedFile('DeltaSuite_Bridge_Out_v1', OUT_LAYOUT)
local inp = ac.writeMemoryMappedFile('DeltaSuite_Bridge_In_v1', IN_LAYOUT)

local btnRadio = ac.ControlButton('DeltaSuite/Engineer radio (hold)')
local btnOk = ac.ControlButton('DeltaSuite/Confirm proposal')
local btnNo = ac.ControlButton('DeltaSuite/Discard proposal')
btnOk:setAlwaysActive(true)
btnNo:setAlwaysActive(true)

local CMD_BRAKE_BIAS, CMD_ABS, CMD_TC, CMD_ENGINE_BRAKE = 1, 2, 3, 4
local CMD_SETUP, CMD_PIT, CMD_LOAD_SETUP, CMD_SAVE_SETUP = 5, 6, 7, 8

local lastSeq = inp.seq -- commands left over from a previous session: ignored
local lastBeat, lastBeatChange = inp.hostBeat, -100
local clock = 0
local setupTimer, namesTimer = 0, 0
local lastAck = ''

local function setStr(dst, size, s)
  ffi.fill(dst, size)
  s = tostring(s or '')
  if #s > size - 1 then s = s:sub(1, size - 1) end
  if #s > 0 then ffi.copy(dst, s, #s) end
end

local function round(v) return math.floor(v + 0.5) end

local function applyCommand(cmd, value, name, text)
  if cmd == CMD_BRAKE_BIAS then
    ac.setBrakeBias(value)
    return true, string.format('bias %.1f%%', value * 100)
  elseif cmd == CMD_ABS then
    ac.setABS(round(value))
    return true, 'ABS ' .. round(value)
  elseif cmd == CMD_TC then
    ac.setTC(round(value))
    return true, 'TC ' .. round(value)
  elseif cmd == CMD_ENGINE_BRAKE then
    ac.setEngineBrakeSetting(round(value))
    return true, 'engine brake ' .. round(value)
  elseif cmd == CMD_SETUP then
    if not ac.isSetupAvailableToEdit() then return false, 'setup can only be changed in the pits' end
    local ok = ac.setSetupSpinnerValue(name, round(value))
    return ok, ok and (name .. ' = ' .. round(value)) or ('value not accepted: ' .. name)
  elseif cmd == CMD_PIT then
    if not ac.setPitstopSpinnerValue then return false, 'CSP too old for pit stops' end
    local ok = ac.setPitstopSpinnerValue(name, value)
    return ok, ok and ('pit ' .. name) or ('pit item not editable: ' .. name)
  elseif cmd == CMD_LOAD_SETUP then
    local ok = ac.loadSetup(text)
    return ok, ok and 'setup loaded' or 'setups can only be loaded from the setup menu in the pits'
  elseif cmd == CMD_SAVE_SETUP then
    local ok = ac.saveCurrentSetup(text)
    return ok, ok and ('setup saved: ' .. text) or 'saving failed'
  end
  return false, 'unknown command ' .. tostring(cmd)
end

local function updateSetup()
  out.setupEditable = ac.isSetupAvailableToEdit() and 1 or 0
  local spinners = ac.getSetupSpinners() or {}
  local n = math.min(#spinners, MAX_SETUP)
  for i = 1, n do
    local s, k = spinners[i], i - 1
    setStr(out.setupName[k], 32, s.name)
    setStr(out.setupLabel[k], 48, s.label)
    setStr(out.setupUnits[k], 12, s.units)
    out.setupValue[k] = s.value or 0
    out.setupMin[k] = s.min or 0
    out.setupMax[k] = s.max or 0
    out.setupStep[k] = s.step or 1
    out.setupMult[k] = s.displayMultiplier or 1
    out.setupReadOnly[k] = s.readOnly and 1 or 0
  end
  out.setupCount = n

  if ac.getPitstopSpinners then
    local pit = ac.getPitstopSpinners() or {}
    local m = math.min(#pit, MAX_PIT)
    for i = 1, m do
      local p, k = pit[i], i - 1
      setStr(out.pitName[k], 32, p.name)
      setStr(out.pitType[k], 12, p.type)
      out.pitValue[k] = p.value or 0
      out.pitMin[k] = p.min or 0
      out.pitMax[k] = p.max or 0
      out.pitReadOnly[k] = p.readOnly and 1 or 0
    end
    out.pitCount = m
    out.pitPreset = ac.getSim().currentQuickPitPreset or 0
  end
end

local function updateCars(sim, withNames)
  local n = math.min(sim.carsCount, MAX_CARS)
  out.carsCount = n
  for i = 0, n - 1 do
    local c = ac.getCar(i)
    if c then
      out.carIndex[i] = c.index
      out.carConnected[i] = c.isConnected and 1 or 0
      out.carRacePos[i] = c.racePosition
      out.carLapCount[i] = c.lapCount
      out.carSpline[i] = c.splinePosition
      out.carLapTimeMs[i] = c.lapTimeMs
      out.carLastLapMs[i] = c.previousLapTimeMs
      out.carBestLapMs[i] = c.bestLapTimeMs
      out.carInPitlane[i] = c.isInPitlane and 1 or 0
      out.carInPit[i] = c.isInPit and 1 or 0
      out.carSpeed[i] = c.speedKmh
      out.carLastLapValid[i] = c.isLastLapValid and 1 or 0
      if withNames then
        setStr(out.carDriver[i], 32, ac.getDriverName(i))
        setStr(out.carModel[i], 32, ac.getCarName(i))
      end
    end
  end
end

-- onboard video in a separate module, in the same folder as the app
local onboard, onboardError = nil, nil
do
  if __dirname then package.path = package.path .. ';' .. __dirname .. '/?.lua' end
  local ok, mod = pcall(require, 'DeltaSuiteOnboard')
  if ok and type(mod) == 'table' then
    onboard = mod
  else
    onboardError = tostring(mod)
    ac.log('DeltaSuite onboard not loaded: ' .. onboardError)
  end
end

function script.update(dt)
  clock = clock + dt
  out.version = VERSION
  out.endMarker = END_MARKER
  out.frame = out.frame + 1

  local sim = ac.getSim()
  out.focusedCar = sim.focusedCar
  out.pttDown = btnRadio:down() and 1 or 0
  if btnOk:pressed() then out.confirmCount = out.confirmCount + 1 end
  if btnNo:pressed() then out.cancelCount = out.cancelCount + 1 end

  local car = ac.getCar(0)
  if car then
    out.brakeBias = car.brakeBias
    out.brakeBiasStep = car.brakesBiasStep
    out.brakeBiasMin = car.brakesBiasLimitDown
    out.brakeBiasMax = car.brakesBiasLimitUp
    out.absMode = car.absMode
    out.absModes = car.absModes
    out.tcMode = car.tractionControlMode
    out.tcModes = car.tractionControlModes
    out.engineBrakeCount = car.engineBrakeSettingsCount
  end

  namesTimer = namesTimer - dt
  updateCars(sim, namesTimer <= 0)
  if namesTimer <= 0 then namesTimer = 2 end

  setupTimer = setupTimer - dt
  if setupTimer <= 0 then
    setupTimer = 0.5
    local ok, err = pcall(updateSetup)
    if not ok then ac.log('DeltaSuite setup: ' .. tostring(err)) end
  end

  if inp.hostBeat ~= lastBeat then
    lastBeat, lastBeatChange = inp.hostBeat, clock
  end

  if inp.seq ~= lastSeq then
    lastSeq = inp.seq
    local called, ok, msg = pcall(applyCommand, inp.cmd, inp.value, ffi.string(inp.name), ffi.string(inp.text))
    if not called then ok, msg = false, tostring(ok) end
    lastAck = tostring(msg or '')
    out.ackOk = ok and 1 or 0
    setStr(out.ackMsg, 64, lastAck)
    out.ackSeq = lastSeq
  end

  if onboard then onboard.update(dt, sim) end
end

-- ------------------------------------------------------------------ window
-- Styled window: header with the connection state, cards for the radio buttons and the onboard video. Cards get
-- their background from the height measured on the previous frame (ImGui draws in order: the background must
-- come before the content). If anything in the styled version fails (older CSP), the plain one is used.

local C = {
  accent = rgbm(0.88, 0.02, 0, 1), good = rgbm(0.18, 0.82, 0.48, 1), bad = rgbm(1, 0.3, 0.3, 1),
  warn = rgbm(1, 0.76, 0.24, 1), text = rgbm(0.91, 0.92, 0.94, 1), dim = rgbm(0.55, 0.58, 0.64, 1),
  card = rgbm(0.08, 0.09, 0.12, 0.72), line = rgbm(1, 1, 1, 0.07),
}
local PAD, GAP = 10, 8
local cardH = {}
local styledFailed = false

local function plainWindow()
  local connected = clock - lastBeatChange < 2
  ui.text(connected and 'Delta Suite: connected' or 'Delta Suite: not connected (start the acquisition)')
  if lastAck ~= '' then ui.text('Last command: ' .. lastAck) end
  if onboard then
    onboard.window()
  else
    ui.text('Onboard not loaded: ' .. tostring(onboardError))
  end
  ui.text(' ')
  ui.text('Engineer radio (hold):')
  btnRadio:control(vec2(0, 0))
  ui.text("Confirm the engineer's proposal:")
  btnOk:control(vec2(0, 0))
  ui.text('Discard proposal:')
  btnNo:control(vec2(0, 0))
end

local function pill(text, color, right)
  ui.pushFont(ui.Font.Small)
  local size = ui.measureText(text)
  local w, h = size.x + 22, size.y + 6
  local p = vec2(right - w, ui.getCursorY())
  ui.drawRectFilled(p, p + vec2(w, h), rgbm(color.r, color.g, color.b, 0.16), h / 2)
  ui.drawCircleFilled(p + vec2(9, h / 2), 3.5, color, 12)
  ui.setCursor(p + vec2(16, 3))
  ui.textColored(text, color)
  ui.popFont()
end

local function card(id, title, width, content)
  local p = ui.getCursor()
  local h = cardH[id] or 60
  ui.drawRectFilled(p, p + vec2(width, h), C.card, 6)
  ui.drawRectFilled(p, p + vec2(3, h), C.accent, 1)
  ui.setCursor(p + vec2(PAD + 2, PAD - 2))
  ui.beginGroup()
  ui.pushFont(ui.Font.Small)
  ui.textColored(title, C.dim)
  ui.popFont()
  ui.offsetCursorY(2)
  content(width - 2 * PAD - 2)
  ui.endGroup()
  cardH[id] = ui.getCursorY() - p.y + PAD - 4
  ui.setCursor(vec2(p.x, p.y + cardH[id] + GAP))
end

local function binding(label, button, width, hint)
  ui.textColored(label, C.text)
  if hint then
    ui.sameLine(0, 6)
    ui.pushFont(ui.Font.Small)
    ui.textColored(hint, C.dim)
    ui.popFont()
  end
  button:control(vec2(width, 0))
  ui.offsetCursorY(4)
end

local function styledWindow()
  local connected = clock - lastBeatChange < 2
  local win = ui.windowSize()
  local x0 = ui.getCursorX()
  local width = win.x - 2 * x0

  -- header: logo and connection state
  local top = ui.getCursorY()
  ui.pushFont(ui.Font.Title)
  local th = ui.measureText('DELTA SUITE').y
  ui.drawRectFilled(vec2(x0, top + th * 0.2), vec2(x0 + th * 0.6, top + th * 0.8), C.accent, 2)
  ui.setCursor(vec2(x0 + th * 0.6 + 8, top))
  ui.textColored('DELTA SUITE', C.text)
  ui.popFont()
  local after = ui.getCursorY()
  ui.setCursorY(top + 4)
  pill(connected and 'CONNECTED' or 'OFFLINE', connected and C.good or C.bad, x0 + width)
  ui.setCursor(vec2(x0, after))
  ui.pushFont(ui.Font.Small)
  if not connected then
    ui.textColored('Start the acquisition in Delta Suite on this PC.', C.dim)
  elseif lastAck ~= '' then
    ui.textColored('Last command: ' .. lastAck, out.ackOk == 1 and C.good or C.warn)
  else
    ui.textColored('Telemetry, rivals and setup are being shared.', C.dim)
  end
  ui.popFont()
  ui.offsetCursorY(GAP)

  card('radio', 'ENGINEER RADIO', width, function(w)
    local tx = btnRadio:down()
    ui.textColored('Push to talk', C.text)
    if tx then
      ui.sameLine(0, 16)
      local c = ui.getCursor()
      ui.drawCircleFilled(c + vec2(-6, ui.measureText('T').y / 2), 4, C.bad, 12)
      ui.textColored('TRANSMITTING', C.bad)
    end
    btnRadio:control(vec2(w, 0))
    ui.offsetCursorY(2)
  end)

  card('proposals', "ENGINEER'S PROPOSALS", width, function(w)
    binding('Confirm', btnOk, w, 'applies the proposed change')
    binding('Discard', btnNo, w, nil)
  end)

  card('onboard', 'ONBOARD VIDEO', width, function(w)
    if onboard then
      local y = ui.getCursorY()
      onboard.window()
      if ui.getCursorY() == y then
        ui.textColored('Idle: opens with the Onboard page in Delta Suite.', C.dim)
      end
    else
      ui.textColored('Not loaded: ' .. tostring(onboardError), C.warn)
    end
  end)
end

function script.windowMain(dt)
  if not styledFailed then
    local ok, err = pcall(styledWindow)
    if ok then return end
    styledFailed = true
    ac.log('DeltaSuite styled window failed, plain window from now on: ' .. tostring(err))
  end
  plainWindow()
end
