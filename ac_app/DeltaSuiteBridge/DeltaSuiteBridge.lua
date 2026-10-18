-- Delta Suite Bridge (app Lua per Custom Shaders Patch)
--
-- Ponte tra Assetto Corsa e Delta Suite (programma esterno), tramite due file mappati in memoria:
--   DeltaSuite_Bridge_Out_v1  scritto qui: regolazioni attuali, setup, pit stop, avversari, tasti radio
--   DeltaSuite_Bridge_In_v1   scritto da Delta Suite: un comando alla volta, numerato da `seq`
--   DeltaSuite_Onboard_v6     video onboard: fino a 4 viste (auto, telecamera, qualità) rese con
--                             ac.GeometryShot, con esposizione e gamma (o il post-processing del gioco con
--                             YEBIS); i fotogrammi arrivano a Delta Suite come texture condivise, DDS grezzo
--                             nella mapping (solo la principale) o file JPG; in più posizioni delle auto
--                             (GPS) e telecamere F6 dell'auto
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
  float exposure;
  int tonemap;
  int transport;
  char folder[260];
  int viewEnabled[4];
  int viewCamera[4];
  int viewCar[4];
  int viewWidth[4];
  int viewHeight[4];
  int viewFps[4];
  float gameFps;
  int carCameras;
  float carCamData[96];
  float wheelData[12];
  int carCount;
  float carPosX[64];
  float carPosZ[64];
  int frame[4];
  int shotWidth[4];
  int shotHeight[4];
  int shotCar[4];
  float renderMs[4];
  unsigned int sharedHandleLo[4];
  unsigned int sharedHandleHi[4];
  char status[4][96];
  int dataSize[3];
  char data[3][3686656];
  int endMarker;
]]
local ONBOARD_VERSION, ONBOARD_END, ONBOARD_SLOTS, ONBOARD_DATA_MAX = 6, 0x44534F31, 3, 3686656 -- 'DSO1'
local ONBOARD_VIEWS, MAX_CAR_CAMERAS, MAX_CARS_POS = 4, 16, 64
local CAR_CAMERA_BASE = 8 -- da qui in poi le telecamere F6 dell'auto (cameras.ini): 8 = la prima
local TONEMAP_YEBIS, TRANSPORT_MEMORY, TRANSPORT_SHARED = 3, 1, 2

-- Variabili a livello di modulo: restano vive finché l'app è caricata.
local out = ac.writeMemoryMappedFile('DeltaSuite_Bridge_Out_v1', OUT_LAYOUT)
local inp = ac.writeMemoryMappedFile('DeltaSuite_Bridge_In_v1', IN_LAYOUT)
local onb = ac.writeMemoryMappedFile('DeltaSuite_Onboard_v6', ONBOARD_LAYOUT)

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

local shaderOk, encodeOk = true, true
local onbBeat, onbBeatChange = onb.hostBeat, -100
local onbActive = false
local camCountTimer, posTimer = 0, 0
local X, Y, Z = vec3(1, 0, 0), vec3(0, 1, 0), vec3(0, 0, 1)
local carNodes, wheelsLocal = {}, {} -- nodo carRoot e ruote nello spazio dell'auto, per indice d'auto
local fpsAvg = 0

-- una vista per riquadro di Delta Suite (0 = principale): shot, canvas e richiesta con cui sono stati creati
local views = {}
for k = 0, ONBOARD_VIEWS - 1 do views[k] = { timer = 0 } end

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

local function avg(a, b) return (a + b) * 0.5 end

-- campo che può mancare nelle versioni di CSP più vecchie (su una struct ffi leggerlo è un errore)
local function field(obj, name)
  local ok, v = pcall(function () return obj[name] end)
  if ok then return v end
  return nil
end

local function freeView(k)
  local v = views[k]
  if v.shot then v.shot:dispose() end
  if v.canvas then v.canvas:dispose() end
  views[k] = { timer = 0 }
  onb.sharedHandleLo[k], onb.sharedHandleHi[k] = 0, 0
end

local function freeAll()
  for k = 0, ONBOARD_VIEWS - 1 do freeView(k) end
  carNodes, wheelsLocal = {}, {} -- ripresi alla prossima ripresa (cambio di sessione o di auto)
end

-- Canvas con texture condivisa: Delta Suite la apre con OpenSharedResource e la copia sulla propria
-- GPU, così in AC non c'è nessuna lettura dalla GPU (encode o save costano 9-12 ms a 1280×720).
local function makeSharedCanvas(k, w, h)
  if not (render.TextureFlags and render.TextureFlags.Shared) then return nil, 'TextureFlags.Shared assente' end
  local fmt = render.TextureFormat and render.TextureFormat.R8G8B8A8 and render.TextureFormat.R8G8B8A8.UNorm
  local aa = render.AntialiasingMode and render.AntialiasingMode.None
  local ok, c = pcall(ui.ExtraCanvas, vec2(w, h), 1, aa, fmt, render.TextureFlags.Shared)
  if not ok or not c then return nil, tostring(c) end
  local fn = field(c, 'sharedHandle')
  local hok, hnd = false, nil
  -- crossProcess = true: handle D3D11 "legacy" apribile da un altro processo con OpenSharedResource
  -- (con false è un identificativo valido solo per gli script dentro AC: E_INVALIDARG fuori)
  if fn then hok, hnd = pcall(fn, c, true) end
  hnd = hok and tonumber(hnd) or nil
  if not hnd or hnd == 0 then
    c:dispose()
    return nil, 'sharedHandle: ' .. tostring(hnd)
  end
  onb.sharedHandleLo[k], onb.sharedHandleHi[k] = hnd % 4294967296, math.floor(hnd / 4294967296)
  return c
end

local function makeShot(k, w, h, yebis, shared, key)
  local timer = views[k].timer
  freeView(k)
  local v = views[k]
  v.timer = timer
  local root = ac.findNodes('sceneRoot:yes')
  local ok, s = false, nil
  if yebis and render.AntialiasingMode and render.AntialiasingMode.YEBIS then
    -- antialiasing e conversione HDR→LDR con le impostazioni di post-processing del gioco
    ok, s = pcall(ac.GeometryShot, root, vec2(w, h), 1, true, render.AntialiasingMode.YEBIS)
    v.yebis = ok and s ~= nil
  end
  if not v.yebis then
    -- texture HDR se disponibile: l'esposizione poi non schiaccia le ombre su pochi livelli
    local fmt = render.TextureFormat and render.TextureFormat.R16G16B16A16 and render.TextureFormat.R16G16B16A16.Float
    if fmt then ok, s = pcall(ac.GeometryShot, root, vec2(w, h), 1, true, nil, fmt) end
    v.hdr = ok and s ~= nil
  end
  v.shot = (v.yebis or v.hdr) and s or ac.GeometryShot(root, vec2(w, h), 1, true)
  if v.shot.setBestSceneShotQuality then pcall(v.shot.setBestSceneShotQuality, v.shot)
  elseif render.ShadersType then pcall(v.shot.setShadersType, v.shot, render.ShadersType.Main) end
  pcall(v.shot.setClippingPlanes, v.shot, 0.05, 4000)
  if shared then
    local err
    v.canvas, err = makeSharedCanvas(k, w, h)
    v.shared = v.canvas ~= nil
    if err then ac.log('DeltaSuite onboard: texture condivisa non disponibile: ' .. err) end
  end
  v.canvas = v.canvas or ui.ExtraCanvas(vec2(w, h))
  v.w, v.h, v.key = w, h, key
end

-- Le telecamere si calcolano nello spazio dell'auto e si portano nel mondo con la trasformazione con cui
-- l'auto viene disegnata (nodo carRoot): così sono solidali con la carrozzeria inquadrata. Prima si partiva
-- dal centro delle ruote, che si muove con le sospensioni, e dallo stato fisico, che non coincide con quello
-- disegnato nello stesso fotogramma: l'immagine tremava molto.

-- ripiego se il nodo dell'auto non si trova: base dallo stato dell'auto (meno precisa)
local function basisOf(car)
  local side = field(car, 'side') or car.look:clone():cross(car.up)
  return {
    transformPoint = function (_, p) return car.position + side * p.x + car.up * p.y + car.look * p.z end,
    transformVector = function (_, v) return side * v.x + car.up * v.y + car.look * v.z end,
    inverse = function ()
      return { transformPoint = function (_, p)
        local d = p - car.position
        return vec3(d:dot(side), d:dot(car.up), d:dot(car.look))
      end }
    end,
  }
end

local function carTransform(idx, car)
  local node = carNodes[idx]
  if node == nil then
    node = ac.findNodes('carRoot:' .. idx)
    carNodes[idx] = node
  end
  return node:getWorldTransformationRaw() or basisOf(car)
end

-- ruote nello spazio dell'auto, prese una volta sola: la carrozzeria non segue le sospensioni
local function wheelsOf(idx, car, m)
  local w = wheelsLocal[idx]
  if w then return w end
  local inv = m:inverse()
  w = {}
  for i = 0, 3 do w[i + 1] = inv:transformPoint(car.wheels[i].position) end
  wheelsLocal[idx] = w
  return w
end

local function countCarCameras(car)
  local n = field(car, 'carCamerasCount')
  if n then return math.min(n, MAX_CAR_CAMERAS) end
  if not ac.accessCarCamera then return 0 end
  n = 0
  while n < MAX_CAR_CAMERAS do
    local ok, c = pcall(ac.accessCarCamera, n)
    if not ok or not c then break end
    n = n + 1
  end
  return n
end

-- telecamere F6 e ruote dell'auto del giocatore, nello spazio dell'auto: Delta Suite ne ricava i nomi
local function publishCarCameras()
  local player = ac.getCar(0)
  local n = player and countCarCameras(player) or 0
  for i = 0, n - 1 do
    local ok, cc = pcall(ac.accessCarCamera, i)
    if ok and cc then
      local t = cc.transform
      local p, d = t.position, t.look * -1 -- .look della telecamera guarda all'indietro
      onb.carCamData[i * 6], onb.carCamData[i * 6 + 1], onb.carCamData[i * 6 + 2] = p.x, p.y, p.z
      onb.carCamData[i * 6 + 3], onb.carCamData[i * 6 + 4], onb.carCamData[i * 6 + 5] = d.x, d.y, d.z
    end
  end
  onb.carCameras = n
  if player then
    local w = wheelsOf(0, player, carTransform(0, player))
    for i = 1, 4 do
      onb.wheelData[(i - 1) * 3], onb.wheelData[(i - 1) * 3 + 1], onb.wheelData[(i - 1) * 3 + 2] = w[i].x, w[i].y, w[i].z
    end
  end
end

-- posizione (x, z) di ogni auto per la mappa GPS di Delta Suite
local function publishPositions(sim)
  local n = math.min(sim.carsCount, MAX_CARS_POS)
  for i = 0, n - 1 do
    local c = ac.getCar(i)
    if c then onb.carPosX[i], onb.carPosZ[i] = c.position.x, c.position.z end
  end
  onb.carCount = n
end

-- telecamera in coordinate dell'auto: posizione, direzione, alto, fov (stesso ordine di CAMERAS in onboard_feed.py)
local function localCamera(car, w, kind)
  local front, rear = avg(w[1], w[2]), avg(w[3], w[4])
  local centre = avg(front, rear)
  if kind == 1 then -- cofano: dagli occhi del pilota, ma l'abitacolo in una seconda vista non viene reso
    return field(car, 'driverEyesPosition') or (centre + Y * 0.62 - Z * 0.15), Z, Y, 72
  elseif kind == 2 then -- posteriore: sopra la coda, dietro il tetto (più in basso alettone e coda coprono metà)
    return rear + Y * 1.15 - Z * 0.3, (Z * -1 - Y * 0.1):normalize(), Y, 60
  elseif kind >= 3 and kind <= 6 then -- ruote
    local wp = w[kind - 2]
    local out = X * (wp.x >= centre.x and 1 or -1)
    if kind <= 4 then -- anteriori: più in fuori e più in basso, sennò il parafango copre la gomma
      local pos = wp + out * 0.36 + Y * 0.16 - Z * 0.9
      return pos, (Z * 1.5 + (wp - pos):normalize()):normalize(), Y, 68
    end
    local pos = wp + out * 0.28 + Y * 0.22 + Z * 0.95 -- posteriori: guardano indietro
    return pos, (Z * -2 + (wp - pos):normalize()):normalize(), Y, 68
  elseif kind == 7 then -- inseguimento
    return centre - Z * 5.5 + Y * 1.7, (Z - Y * 0.14):normalize(), Y, 55
  end
  -- T-cam: sopra il tetto e un po' avanti, sennò il tetto copre metà inquadratura
  return centre + Y * 1.18 + Z * 0.15, (Z - Y * 0.07):normalize(), Y, 62
end

-- posizione, direzione, alto, fov nel mondo; l'ultimo valore è una nota per lo stato
local function cameraFor(idx, car, kind)
  local m = carTransform(idx, car)
  local note = nil
  if kind >= CAR_CAMERA_BASE then
    -- telecamere F6 dell'auto: ac.accessCarCamera vale per l'auto del giocatore; la matrice è relativa
    -- al modello e la sua .look guarda all'indietro
    local ok, cc = false, nil
    if idx == 0 and ac.accessCarCamera then ok, cc = pcall(ac.accessCarCamera, kind - CAR_CAMERA_BASE) end
    if ok and cc then
      local t = cc.transform
      return m:transformPoint(t.position), m:transformVector(t.look * -1):normalize(),
        m:transformVector(t.up):normalize(), cc.fov > 1 and cc.fov or 60, nil
    end
    kind, note = 0, 'F6 solo per la tua auto'
  end
  local p, l, u, fov = localCamera(car, wheelsOf(idx, car, m), kind)
  return m:transformPoint(p), m:transformVector(l):normalize(), m:transformVector(u):normalize(), fov, note
end

-- esposizione e gamma sul fotogramma reso; se lo shader non compila, solo un moltiplicatore
local function developShot(v)
  local size = vec2(v.w, v.h)
  local exposure = onb.exposure > 0 and onb.exposure or 1
  local mode = onb.tonemap
  if v.yebis then
    if exposure ~= 1 and v.shot.setExposure then pcall(v.shot.setExposure, v.shot, exposure) end
    exposure, mode = 1, 0
  end
  v.canvas:update(function ()
    if shaderOk then
      local ok, err = pcall(ui.renderShader, {
        p1 = vec2(), p2 = size, blendMode = render.BlendMode and render.BlendMode.Opaque or nil,
        textures = { txIn = v.shot }, values = { gExposure = exposure, gMode = mode }, shader = TONEMAP_SHADER,
      })
      if ok then return end
      shaderOk = false
      ac.log('DeltaSuite onboard shader: ' .. tostring(err))
    end
    local k = math.min(exposure, 4)
    ui.drawImage(v.shot, vec2(), size, rgbm(k, k, k, 1))
  end)
end

-- In memoria (solo la vista principale) va il DDS grezzo di ExtraCanvas:encode() (in CSP 0.2.11 non
-- prende il formato e non comprime); su file va un JPG: onboard_<posto>.jpg per la principale,
-- onboard_v<vista>_<posto>.jpg per le altre. Se encode non dà un risultato utilizzabile non lo si chiama più.
local function publishFrame(k, v, n, folder, transport)
  local slot = n % ONBOARD_SLOTS
  if k == 0 and transport == TRANSPORT_MEMORY and encodeOk then
    local encFn = field(v.canvas, 'encode')
    local ok, enc = false, nil
    if encFn then ok, enc = pcall(encFn, v.canvas) end
    if ok and type(enc) == 'string' and #enc > 128 and #enc <= ONBOARD_DATA_MAX then
      ffi.copy(onb.data[slot], enc, #enc)
      onb.dataSize[slot] = #enc
      return 'memoria'
    end
    encodeOk = false
    ac.log('DeltaSuite onboard: encode inutilizzabile (' .. type(enc) .. (type(enc) == 'string' and
      (', ' .. #enc .. ' byte') or '') .. '), si passa ai file')
  end
  if k == 0 then onb.dataSize[slot] = 0 end
  if folder == '' then error('cartella dei fotogrammi non indicata') end
  local name = k == 0 and string.format('onboard_%d.jpg', slot) or string.format('onboard_v%d_%d.jpg', k, slot)
  v.canvas:save(folder .. '\\' .. name, ac.ImageFormat.JPG)
  return transport == TRANSPORT_MEMORY and k == 0 and 'file (encode non va)' or 'file'
end

local function renderView(k, sim)
  local v = views[k]
  local idx = onb.viewCar[k] >= 0 and onb.viewCar[k] or sim.focusedCar
  local car = ac.getCar(idx)
  if not car then setStr(onb.status[k], 96, 'auto ' .. idx .. ' non trovata'); return end
  local cap = k == 0 and 1920 or 640 -- le viste secondarie sono piccole: al massimo 640×360
  local w = math.max(160, math.min(cap, onb.viewWidth[k]))
  local h = math.max(90, math.min(cap * 9 / 16, onb.viewHeight[k]))
  local yebis, shared = onb.tonemap == TONEMAP_YEBIS, onb.transport == TRANSPORT_SHARED
  local key = string.format('%dx%d %s %s', w, h, tostring(yebis), tostring(shared))
  if not v.shot or key ~= v.key then makeShot(k, w, h, yebis, shared, key); v = views[k] end

  local t0 = os.clock()
  local pos, look, up, fov, camNote = cameraFor(idx, car, onb.viewCamera[k])
  v.shot:update(pos, look, up, fov)
  developShot(v)
  local n = onb.frame[k] + 1
  local route
  if v.shared then
    if k == 0 then onb.dataSize[n % ONBOARD_SLOTS] = 0 end
    route = 'condivisa'
  else
    route = publishFrame(k, v, n, ffi.string(onb.folder), shared and TRANSPORT_MEMORY or onb.transport)
    if shared then route = route .. ' (condivisa non va)' end
  end
  onb.renderMs[k] = (os.clock() - t0) * 1000
  onb.shotWidth[k], onb.shotHeight[k], onb.shotCar[k] = w, h, idx
  onb.frame[k] = n -- per ultimo: Delta Suite legge il fotogramma n - 1
  setStr(onb.status[k], 96, string.format('in diretta · %s · %s%s%s', route,
    v.yebis and 'yebis' or v.hdr and 'hdr' or 'ldr', shaderOk and '' or ' · senza shader',
    camNote and (' · ' .. camNote) or ''))
end

local function updateOnboard(dt, sim)
  onb.version = ONBOARD_VERSION
  onb.endMarker = ONBOARD_END
  if dt > 0 then fpsAvg = fpsAvg + (1 / dt - fpsAvg) * 0.05 end
  onb.gameFps = fpsAvg
  camCountTimer = camCountTimer - dt
  if camCountTimer <= 0 then
    camCountTimer = 2
    publishCarCameras()
  end
  posTimer = posTimer - dt
  if posTimer <= 0 then
    posTimer = 0.05
    publishPositions(sim)
  end
  if onb.hostBeat ~= onbBeat then onbBeat, onbBeatChange = onb.hostBeat, clock end
  local alive = clock - onbBeatChange < 2
  if not alive and next(wheelsLocal) ~= nil then
    carNodes, wheelsLocal = {}, {} -- Delta Suite staccata: alla ripresa si rileggono (magari è cambiata auto)
  end
  onbActive = false
  -- al massimo una vista resa per fotogramma di AC: la più in ritardo, così il costo non fa picchi
  local due, dueTimer = nil, 0
  for k = 0, ONBOARD_VIEWS - 1 do
    local v = views[k]
    if alive and onb.viewEnabled[k] == 1 then
      onbActive = true
      v.timer = v.timer - dt
      if v.timer <= dueTimer then due, dueTimer = k, v.timer end
    elseif v.shot then
      freeView(k)
      setStr(onb.status[k], 96, 'in pausa')
    end
  end
  if due ~= nil then
    views[due].timer = 1 / math.max(1, math.min(30, onb.viewFps[due]))
    renderView(due, sim)
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

  local ok, err = pcall(updateOnboard, dt, sim)
  if not ok then
    freeAll()
    for k = 0, ONBOARD_VIEWS - 1 do
      views[k].timer = 2 -- si riprova fra un po' invece di ripetere l'errore a ogni frame
      setStr(onb.status[k], 96, 'errore: ' .. tostring(err))
    end
    ac.log('DeltaSuite onboard: ' .. tostring(err))
  end
end

function script.windowMain(dt)
  local connected = clock - lastBeatChange < 2
  ui.text(connected and 'Delta Suite: collegato' or 'Delta Suite: non collegato (avvia l\'acquisizione)')
  if lastAck ~= '' then ui.text('Ultimo comando: ' .. lastAck) end
  if onbActive then
    for k = 0, ONBOARD_VIEWS - 1 do
      if views[k].shot then
        ui.text(string.format('Onboard %d: %dx%d, %.1f ms', k + 1, views[k].w, views[k].h, onb.renderMs[k]))
      end
    end
  end
  ui.text(' ')
  ui.text('Radio ingegnere (tieni premuto):')
  btnRadio:control(vec2(0, 0))
  ui.text('Conferma proposta dell\'ingegnere:')
  btnOk:control(vec2(0, 0))
  ui.text('Scarta proposta:')
  btnNo:control(vec2(0, 0))
end
