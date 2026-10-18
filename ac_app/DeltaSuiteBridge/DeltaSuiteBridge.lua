-- Delta Suite Bridge (app Lua per Custom Shaders Patch)
--
-- Ponte tra Assetto Corsa e Delta Suite (programma esterno), tramite due file mappati in memoria:
--   DeltaSuite_Bridge_Out_v1  scritto qui: regolazioni attuali, setup, pit stop, avversari, tasti radio
--   DeltaSuite_Bridge_In_v1   scritto da Delta Suite: un comando alla volta, numerato da `seq`
--   DeltaSuite_Onboard_v4     video onboard: Delta Suite chiede telecamera/auto/qualità, qui si rende
--                             una seconda vista (ac.GeometryShot), le si dà esposizione e gamma (o il
--                             post-processing del gioco con YEBIS) e il fotogramma arriva a Delta Suite
--                             come texture condivisa, DDS grezzo nella mapping o file JPG
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
  int transport;
  char folder[260];
  int frame;
  int shotWidth;
  int shotHeight;
  int shotCar;
  float renderMs;
  float gameFps;
  unsigned int sharedHandleLo;
  unsigned int sharedHandleHi;
  char status[96];
  int dataSize[3];
  char data[3][3686656];
  int endMarker;
]]
local ONBOARD_VERSION, ONBOARD_END, ONBOARD_SLOTS, ONBOARD_DATA_MAX = 4, 0x44534F31, 3, 3686656 -- 'DSO1'
local TONEMAP_YEBIS, TRANSPORT_MEMORY, TRANSPORT_SHARED = 3, 1, 2

-- Variabili a livello di modulo: restano vive finché l'app è caricata.
local out = ac.writeMemoryMappedFile('DeltaSuite_Bridge_Out_v1', OUT_LAYOUT)
local inp = ac.writeMemoryMappedFile('DeltaSuite_Bridge_In_v1', IN_LAYOUT)
local onb = ac.writeMemoryMappedFile('DeltaSuite_Onboard_v4', ONBOARD_LAYOUT)

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

local shot, shotCanvas, shotW, shotH, shotYebis, shotShared = nil, nil, 0, 0, false, false
local shotKey = nil -- richiesta con cui è stata creata la shot: si ricrea solo se cambia
local shotHdr, shaderOk, encodeOk = false, true, true
local onbTimer, onbBeat, onbBeatChange = 0, onb.hostBeat, -100
local onbActive = false
local fpsAvg = 0

-- La GeometryShot non passa dal post-processing del gioco: senza esposizione e gamma esce scura
-- (provato con CSP 0.2.11). gMode: 0 niente, 1 solo gamma, 2 curva filmica (ACES) + gamma; con YEBIS
-- (tonemap 3) il post-processing lo fa la GeometryShot stessa e qui si copia e basta.
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
  shot, shotCanvas, shotW, shotH, shotYebis, shotShared, shotKey = nil, nil, 0, 0, false, false, nil
  onb.sharedHandleLo, onb.sharedHandleHi = 0, 0
end

-- Canvas con texture condivisa: Delta Suite la apre con OpenSharedResource e la copia sulla propria
-- GPU, così in AC non c'è nessuna lettura dalla GPU (encode o save costano 9-12 ms a 1280×720).
local function makeSharedCanvas(w, h)
  if not (render.TextureFlags and render.TextureFlags.Shared) then return nil, 'TextureFlags.Shared assente' end
  local fmt = render.TextureFormat and render.TextureFormat.R8G8B8A8 and render.TextureFormat.R8G8B8A8.UNorm
  local aa = render.AntialiasingMode and render.AntialiasingMode.None
  local ok, c = pcall(ui.ExtraCanvas, vec2(w, h), 1, aa, fmt, render.TextureFlags.Shared)
  if not ok or not c then return nil, tostring(c) end
  local fn = field(c, 'sharedHandle')
  local hok, hnd = false, nil
  if fn then
    hok, hnd = pcall(fn, c, false) -- handle "legacy": si apre da un altro processo senza duplicarlo
    if not hok then hok, hnd = pcall(fn, c) end
  end
  hnd = hok and tonumber(hnd) or nil
  if not hnd or hnd == 0 then
    c:dispose()
    return nil, 'sharedHandle: ' .. tostring(hnd)
  end
  onb.sharedHandleLo, onb.sharedHandleHi = hnd % 4294967296, math.floor(hnd / 4294967296)
  return c
end

local sharedError = nil

local function makeShot(w, h, yebis, shared, key)
  freeShot()
  local root = ac.findNodes('sceneRoot:yes')
  local ok, s = false, nil
  if yebis and render.AntialiasingMode and render.AntialiasingMode.YEBIS then
    -- antialiasing e conversione HDR→LDR con le impostazioni di post-processing del gioco
    ok, s = pcall(ac.GeometryShot, root, vec2(w, h), 1, true, render.AntialiasingMode.YEBIS)
    shotYebis, shotHdr = ok and s ~= nil, false
  end
  if not shotYebis then
    -- texture HDR se disponibile: l'esposizione poi non schiaccia le ombre su pochi livelli
    local fmt = render.TextureFormat and render.TextureFormat.R16G16B16A16 and render.TextureFormat.R16G16B16A16.Float
    if fmt then ok, s = pcall(ac.GeometryShot, root, vec2(w, h), 1, true, nil, fmt) end
    shotHdr = ok and s ~= nil
  end
  shot = (shotYebis or shotHdr) and s or ac.GeometryShot(root, vec2(w, h), 1, true)
  if shot.setBestSceneShotQuality then pcall(shot.setBestSceneShotQuality, shot)
  elseif render.ShadersType then pcall(shot.setShadersType, shot, render.ShadersType.Main) end
  pcall(shot.setClippingPlanes, shot, 0.05, 4000)
  if shared then
    shotCanvas, sharedError = makeSharedCanvas(w, h)
    shotShared = shotCanvas ~= nil
    if sharedError then ac.log('DeltaSuite onboard: texture condivisa non disponibile: ' .. sharedError) end
  end
  shotCanvas = shotCanvas or ui.ExtraCanvas(vec2(w, h))
  shotW, shotH, shotKey = w, h, key
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
  elseif kind == 2 then -- posteriore: sopra la coda, dietro il tetto (più in basso alettone e coda coprono metà)
    return rear + up * 1.15 - fwd * 0.3, (fwd * -1 - up * 0.1):normalize(), up, 60
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
  if shotYebis then
    if exposure ~= 1 and shot.setExposure then pcall(shot.setExposure, shot, exposure) end
    exposure, mode = 1, 0
  end
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

-- In memoria va il DDS grezzo di ExtraCanvas:encode() (in CSP 0.2.11 non prende il formato e non
-- comprime): niente file e niente riga di log a ogni fotogramma. Su file va un JPG. Una sola lettura
-- dalla GPU per fotogramma; se encode non dà un risultato utilizzabile non lo si chiama più.
local function publishFrame(n, folder, transport)
  local slot = n % ONBOARD_SLOTS
  if transport == TRANSPORT_MEMORY and encodeOk then
    local encFn = field(shotCanvas, 'encode')
    local ok, enc = false, nil
    if encFn then ok, enc = pcall(encFn, shotCanvas) end
    if ok and type(enc) == 'string' and #enc > 128 and #enc <= ONBOARD_DATA_MAX then
      ffi.copy(onb.data[slot], enc, #enc)
      onb.dataSize[slot] = #enc
      return 'memoria'
    end
    encodeOk = false
    ac.log('DeltaSuite onboard: encode inutilizzabile (' .. type(enc) .. (type(enc) == 'string' and
      (', ' .. #enc .. ' byte') or '') .. '), si passa ai file')
  end
  onb.dataSize[slot] = 0
  if folder == '' then error('cartella dei fotogrammi non indicata') end
  shotCanvas:save(string.format('%s\\onboard_%d.jpg', folder, slot), ac.ImageFormat.JPG)
  return transport == TRANSPORT_MEMORY and 'file (encode non va)' or 'file'
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
  local yebis, shared = onb.tonemap == TONEMAP_YEBIS, onb.transport == TRANSPORT_SHARED
  local key = string.format('%dx%d %s %s', w, h, tostring(yebis), tostring(shared))
  if not shot or key ~= shotKey then makeShot(w, h, yebis, shared, key) end

  local t0 = os.clock()
  local pos, look, up, fov = cameraFor(car, onb.camera)
  shot:update(pos, look, up, fov)
  developShot()
  local n = onb.frame + 1
  local route
  if shotShared then
    onb.dataSize[n % ONBOARD_SLOTS] = 0
    route = 'condivisa'
  else
    route = publishFrame(n, ffi.string(onb.folder), shared and TRANSPORT_MEMORY or onb.transport)
    if shared then route = route .. ' (condivisa non va)' end
  end
  onb.renderMs = (os.clock() - t0) * 1000
  onb.shotWidth, onb.shotHeight, onb.shotCar = w, h, idx
  onb.frame = n -- per ultimo: Delta Suite legge il fotogramma n - 1
  setStr(onb.status, 96, string.format('in diretta · %s · %s%s', route,
    shotYebis and 'yebis' or shotHdr and 'hdr' or 'ldr', shaderOk and '' or ' · senza shader'))
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
