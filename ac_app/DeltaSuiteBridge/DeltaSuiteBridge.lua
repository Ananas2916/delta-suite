-- Delta Suite Bridge (app Lua per Custom Shaders Patch)
--
-- Ponte tra Assetto Corsa e Delta Suite (programma esterno), tramite due file mappati in memoria:
--   DeltaSuite_Bridge_Out_v1  scritto qui: regolazioni attuali, setup, pit stop, avversari, tasti radio
--   DeltaSuite_Bridge_In_v1   scritto da Delta Suite: un comando alla volta, numerato da `seq`
--   DeltaSuite_Onboard_v2     video onboard: Delta Suite chiede telecamera/auto/qualità, qui si rende
--                             una seconda vista (ac.GeometryShot), le si dà esposizione e gamma e il
--                             JPG va nella mapping (o in un file, se questa CSP non sa codificarlo)
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

local ONBOARD_LAYOUT = [[
  int version;
  int hostBeat;
  int enabled;
  int camera;
  int carIndex;
  int width;
  int height;
  int fps;
  float exposure;
  int tonemap;
  char folder[260];
  int frame;
  int shotWidth;
  int shotHeight;
  int shotCar;
  float renderMs;
  float gameFps;
  char status[96];
  int jpegSize[3];
  char jpeg[3][393216];
  int endMarker;
]]
local ONBOARD_VERSION, ONBOARD_END, ONBOARD_SLOTS, ONBOARD_JPEG_MAX = 2, 0x44534F31, 3, 393216 -- 'DSO1'

-- Variabili a livello di modulo: restano vive finché l'app è caricata.
local out = ac.writeMemoryMappedFile('DeltaSuite_Bridge_Out_v1', OUT_LAYOUT)
local inp = ac.writeMemoryMappedFile('DeltaSuite_Bridge_In_v1', IN_LAYOUT)
local onb = ac.writeMemoryMappedFile('DeltaSuite_Onboard_v2', ONBOARD_LAYOUT)

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

-- ------------------------------------------------------------------ onboard

local shot, shotCanvas, shotW, shotH = nil, nil, 0, 0
local shotHdr, shaderOk = false, true
local onbTimer, onbBeat, onbBeatChange = 0, onb.hostBeat, -100
local onbActive = false
local fpsAvg = 0

-- La GeometryShot non passa dal post-processing del gioco: senza esposizione e gamma esce scura
-- (provato con CSP 0.2.11). gMode: 0 niente, 1 solo gamma, 2 curva filmica (ACES) + gamma.
local TONEMAP_SHADER = [[
float4 main(PS_IN pin) {
  float3 c = txIn.Sample(samLinear, pin.Tex).rgb * gExposure;
  if (gMode > 1.5) c = saturate(c * (2.51 * c + 0.03) / (c * (2.43 * c + 0.59) + 0.14));
  if (gMode > 0.5) c = pow(saturate(c), 1.0 / 2.2);
  return float4(saturate(c), 1);
}]]

local function freeShot()
  if shot then shot:dispose() end
  if shotCanvas then shotCanvas:dispose() end
  shot, shotCanvas, shotW, shotH = nil, nil, 0, 0
end

local function makeShot(w, h)
  freeShot()
  local root = ac.findNodes('sceneRoot:yes')
  -- texture HDR se disponibile: l'esposizione poi non schiaccia le ombre su pochi livelli
  local fmt = render.TextureFormat and render.TextureFormat.R16G16B16A16 and render.TextureFormat.R16G16B16A16.Float
  local ok, s = false, nil
  if fmt then ok, s = pcall(ac.GeometryShot, root, vec2(w, h), 1, true, nil, fmt) end
  shotHdr = ok and s ~= nil
  shot = shotHdr and s or ac.GeometryShot(root, vec2(w, h), 1, true)
  if shot.setBestSceneShotQuality then pcall(shot.setBestSceneShotQuality, shot)
  elseif render.ShadersType then pcall(shot.setShadersType, shot, render.ShadersType.Main) end
  pcall(shot.setClippingPlanes, shot, 0.05, 4000)
  shotCanvas = ui.ExtraCanvas(vec2(w, h))
  shotW, shotH = w, h
end

local function avg(a, b) return (a + b) * 0.5 end

-- campo che può mancare nelle versioni di CSP più vecchie (su una struct ffi leggerlo è un errore)
local function field(obj, name)
  local ok, v = pcall(function () return obj[name] end)
  if ok then return v end
  return nil
end

-- telecamera montata sull'auto: posizione, direzione, alto, fov (stesso ordine di CAMERAS in onboard_feed.py)
local function cameraFor(car, kind)
  local fwd, up = car.look, car.up
  local side = field(car, 'side') or fwd:clone():cross(up)
  local w = { car.wheels[0].position, car.wheels[1].position, car.wheels[2].position, car.wheels[3].position }
  local front, rear = avg(w[1], w[2]), avg(w[3], w[4])
  local centre = avg(front, rear)
  if kind == 1 then -- cofano: dagli occhi del pilota, ma l'abitacolo in una seconda vista non viene reso
    local eyes, tr = field(car, 'driverEyesPosition'), field(car, 'transform')
    local pos = (eyes and tr) and tr:transformPoint(eyes) or (centre + up * 0.62 - fwd * 0.15)
    return pos, fwd, up, 72
  elseif kind == 2 then -- posteriore
    return centre + up * 0.95 - fwd * 0.6, (fwd * -1 - up * 0.08):normalize(), up, 60
  elseif kind >= 3 and kind <= 6 then -- ruote
    local wp = w[kind - 2]
    local out = side * ((wp - centre):dot(side) >= 0 and 1 or -1)
    if kind <= 4 then -- anteriori: più in fuori e più in basso, sennò il parafango copre la gomma
      local pos = wp + out * 0.36 + up * 0.16 - fwd * 0.9
      return pos, (fwd * 1.5 + (wp - pos):normalize()):normalize(), up, 68
    end
    local pos = wp + out * 0.28 + up * 0.22 + fwd * 0.95 -- posteriori: guardano indietro
    return pos, (fwd * -2 + (wp - pos):normalize()):normalize(), up, 68
  elseif kind == 7 then -- inseguimento
    return centre - fwd * 5.5 + up * 1.7, (fwd - up * 0.14):normalize(), up, 55
  end
  -- T-cam: sopra il tetto e un po' avanti, sennò il tetto copre metà inquadratura
  return centre + up * 1.18 + fwd * 0.15, (fwd - up * 0.07):normalize(), up, 62
end

-- esposizione e gamma sul fotogramma reso; se lo shader non compila, solo un moltiplicatore
local function developShot()
  local size = vec2(shotW, shotH)
  local exposure = onb.exposure > 0 and onb.exposure or 1
  local mode = onb.tonemap
  shotCanvas:update(function ()
    if shaderOk then
      local ok, err = pcall(ui.renderShader, {
        p1 = vec2(), p2 = size, blendMode = render.BlendMode and render.BlendMode.Opaque or nil,
        textures = { txIn = shot }, values = { gExposure = exposure, gMode = mode }, shader = TONEMAP_SHADER,
      })
      if ok then return end
      shaderOk = false
      ac.log('DeltaSuite onboard shader: ' .. tostring(err))
    end
    local k = math.min(exposure, 4)
    ui.drawImage(shot, vec2(), size, rgbm(k, k, k, 1))
  end)
end

-- JPG nella mapping se la CSP sa codificarlo in memoria (niente file né righe nel log a ogni fotogramma),
-- altrimenti su file; ritorna la via usata, che finisce nello stato
local function publishFrame(n, folder)
  local slot = n % ONBOARD_SLOTS
  local enc, encFn = nil, field(shotCanvas, 'encode')
  if encFn then
    local ok, r = pcall(encFn, shotCanvas, ac.ImageFormat.JPG)
    if ok then enc = r end
  end
  if type(enc) == 'string' and #enc > 0 and #enc <= ONBOARD_JPEG_MAX then
    ffi.copy(onb.jpeg[slot], enc, #enc)
    onb.jpegSize[slot] = #enc
    return 'memoria'
  end
  onb.jpegSize[slot] = 0
  if folder == '' then error('cartella dei fotogrammi non indicata') end
  shotCanvas:save(string.format('%s\\onboard_%d.jpg', folder, slot), ac.ImageFormat.JPG)
  return 'file, encode ' .. type(enc)
end

local function updateOnboard(dt, sim)
  onb.version = ONBOARD_VERSION
  onb.endMarker = ONBOARD_END
  if dt > 0 then fpsAvg = fpsAvg + (1 / dt - fpsAvg) * 0.05 end
  onb.gameFps = fpsAvg
  if onb.hostBeat ~= onbBeat then onbBeat, onbBeatChange = onb.hostBeat, clock end
  onbActive = onb.enabled == 1 and clock - onbBeatChange < 2
  if not onbActive then
    if shot then freeShot(); setStr(onb.status, 96, 'in pausa') end
    return
  end
  onbTimer = onbTimer - dt
  if onbTimer > 0 then return end
  onbTimer = 1 / math.max(1, math.min(30, onb.fps))

  local idx = onb.carIndex >= 0 and onb.carIndex or sim.focusedCar
  local car = ac.getCar(idx)
  if not car then setStr(onb.status, 96, 'auto ' .. idx .. ' non trovata'); return end
  local w = math.max(160, math.min(1920, onb.width))
  local h = math.max(90, math.min(1080, onb.height))
  if not shot or w ~= shotW or h ~= shotH then makeShot(w, h) end

  local t0 = os.clock()
  local pos, look, up, fov = cameraFor(car, onb.camera)
  shot:update(pos, look, up, fov)
  developShot()
  local n = onb.frame + 1
  local route = publishFrame(n, ffi.string(onb.folder))
  onb.renderMs = (os.clock() - t0) * 1000
  onb.shotWidth, onb.shotHeight, onb.shotCar = w, h, idx
  onb.frame = n -- per ultimo: Delta Suite legge il fotogramma n - 1
  setStr(onb.status, 96, string.format('in diretta · %s · %s%s', route, shotHdr and 'hdr' or 'ldr',
    shaderOk and '' or ' · senza shader'))
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

  local ok, err = pcall(updateOnboard, dt, sim)
  if not ok then
    freeShot()
    onbTimer = 2 -- si riprova fra un po' invece di ripetere l'errore a ogni frame
    setStr(onb.status, 96, 'errore: ' .. tostring(err))
    ac.log('DeltaSuite onboard: ' .. tostring(err))
  end
end

function script.windowMain(dt)
  local connected = clock - lastBeatChange < 2
  ui.text(connected and 'Delta Suite: collegato' or 'Delta Suite: non collegato (avvia l\'acquisizione)')
  if lastAck ~= '' then ui.text('Ultimo comando: ' .. lastAck) end
  if onbActive then ui.text(string.format('Onboard in diretta: %dx%d, %.1f ms', shotW, shotH, onb.renderMs)) end
  ui.text(' ')
  ui.text('Radio ingegnere (tieni premuto):')
  btnRadio:control(vec2(0, 0))
  ui.text('Conferma proposta dell\'ingegnere:')
  btnOk:control(vec2(0, 0))
  ui.text('Scarta proposta:')
  btnNo:control(vec2(0, 0))
end
