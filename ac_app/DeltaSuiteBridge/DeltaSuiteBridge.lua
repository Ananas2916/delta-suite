-- Delta Suite Bridge (app Lua per Custom Shaders Patch)
--
-- Ponte tra Assetto Corsa e Delta Suite (programma esterno), tramite due file mappati in memoria:
--   DeltaSuite_Bridge_Out_v1  scritto qui: regolazioni attuali, setup, pit stop, avversari, tasti radio
--   DeltaSuite_Bridge_In_v1   scritto da Delta Suite: un comando alla volta, numerato da `seq`
-- I layout devono restare identici a quelli in hub_core/csp_bridge.py (solo int/float a 4 byte e
-- array di char, così l'allineamento è lo stesso in LuaJIT e in ctypes).

local VERSION = 1
local END_MARKER = 0x44535431 -- 'DST1': Delta Suite controlla di leggerlo alla posizione attesa

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

-- Variabili a livello di modulo: restano vive finché l'app è caricata.
local out = ac.writeMemoryMappedFile('DeltaSuite_Bridge_Out_v1', OUT_LAYOUT)
local inp = ac.writeMemoryMappedFile('DeltaSuite_Bridge_In_v1', IN_LAYOUT)

local btnRadio = ac.ControlButton('DeltaSuite/Radio ingegnere (tieni premuto)')
local btnOk = ac.ControlButton('DeltaSuite/Conferma proposta')
local btnNo = ac.ControlButton('DeltaSuite/Scarta proposta')
btnOk:setAlwaysActive(true)
btnNo:setAlwaysActive(true)

local CMD_BRAKE_BIAS, CMD_ABS, CMD_TC, CMD_ENGINE_BRAKE = 1, 2, 3, 4
local CMD_SETUP, CMD_PIT, CMD_LOAD_SETUP, CMD_SAVE_SETUP = 5, 6, 7, 8

local lastSeq = inp.seq -- comandi rimasti da una sessione precedente: ignorati
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
    return true, 'freno motore ' .. round(value)
  elseif cmd == CMD_SETUP then
    if not ac.isSetupAvailableToEdit() then return false, 'setup modificabile solo ai box' end
    local ok = ac.setSetupSpinnerValue(name, round(value))
    return ok, ok and (name .. ' = ' .. round(value)) or ('valore non accettato: ' .. name)
  elseif cmd == CMD_PIT then
    if not ac.setPitstopSpinnerValue then return false, 'CSP troppo vecchio per il pit stop' end
    local ok = ac.setPitstopSpinnerValue(name, value)
    return ok, ok and ('pit ' .. name) or ('pit non modificabile: ' .. name)
  elseif cmd == CMD_LOAD_SETUP then
    local ok = ac.loadSetup(text)
    return ok, ok and 'setup caricato' or 'setup caricabile solo dal menu setup ai box'
  elseif cmd == CMD_SAVE_SETUP then
    local ok = ac.saveCurrentSetup(text)
    return ok, ok and ('setup salvato: ' .. text) or 'salvataggio non riuscito'
  end
  return false, 'comando sconosciuto ' .. tostring(cmd)
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
end

function script.windowMain(dt)
  local connected = clock - lastBeatChange < 2
  ui.text(connected and 'Delta Suite: collegato' or 'Delta Suite: non collegato (avvia l\'acquisizione)')
  if lastAck ~= '' then ui.text('Ultimo comando: ' .. lastAck) end
  ui.text(' ')
  ui.text('Radio ingegnere (tieni premuto):')
  btnRadio:control(vec2(0, 0))
  ui.text('Conferma proposta dell\'ingegnere:')
  btnOk:control(vec2(0, 0))
  ui.text('Scarta proposta:')
  btnNo:control(vec2(0, 0))
end
