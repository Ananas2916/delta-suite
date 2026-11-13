// Delta Suite remote pit wall. Plain JS, no libraries: it has to run smoothly on an old dual-core laptop.
// - /api/state is polled twice a second (every 2 s with the page in the background);
// - setup and strategy are fetched only while their tab is open; the track line only when it changes;
// - the onboard video is requested one JPEG at a time and only while a video is on screen: when the requests
//   stop (other tab, page hidden, browser closed) Delta Suite stops rendering it in AC.
"use strict";

const $ = (id) => document.getElementById(id);
const store = {
  get(k, d = null) { try { const v = localStorage.getItem("deltasuite." + k); return v === null ? d : v; } catch (e) { return d; } },
  set(k, v) { try { v === null ? localStorage.removeItem("deltasuite." + k) : localStorage.setItem("deltasuite." + k, v); } catch (e) {} },
};
let token = store.get("token");
let since = 0, lapsKnown = -1, timer = null, failures = 0, composeKind = "say";
let tab = store.get("tab", "wall");
let last = null;                 // last /api/state
let track = { rev: -1, line: [], pit: [] };
let unread = 0;

function esc(s) {
  return String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}
function fmtMs(ms) {
  if (!ms || ms <= 0) return "–";
  const m = Math.floor(ms / 60000), s = (ms % 60000) / 1000;
  return m ? m + ":" + s.toFixed(3).padStart(6, "0") : s.toFixed(3);
}
function fmtGap(v) { return v == null ? "" : "+" + Number(v).toFixed(1); }
function headers() {
  const h = { "Content-Type": "application/json" };
  if (token) h.Authorization = "Bearer " + token;
  return h;
}
function api(path, opts = {}) { return fetch(path, { ...opts, headers: headers(), cache: "no-store" }); }
async function getJSON(path) {
  const r = await api(path);
  if (r.status === 401) { unpaired(); throw new Error("not paired"); }
  return r.ok ? r.json() : null;
}
async function action(body) {
  try {
    const r = await api("/api/action", { method: "POST", body: JSON.stringify(body) });
    const res = await r.json().catch(() => ({}));
    if (!res.ok) toast(res.error || "Action failed");
    return res;
  } catch (e) { toast("Delta Suite not reachable"); return {}; }
}
let toastTimer = null;
function toast(text) {
  const t = $("toast");
  t.textContent = text; t.classList.remove("hidden");
  clearTimeout(toastTimer); toastTimer = setTimeout(() => t.classList.add("hidden"), 3500);
}
function setText(id, v) { const el = $(id); if (el && el.textContent !== String(v)) el.textContent = v; }
function setHTML(el, html) { if (el._html !== html) { el.innerHTML = html; el._html = html; } }
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

// ---------------------------------------------------------------- pairing
function unpaired() { token = null; store.set("token", null); showPair("This device is not paired (or was revoked)."); }
function showPair(msg) {
  stopPolling(); video.stop();
  $("app").classList.add("hidden");
  $("pair").classList.remove("hidden");
  $("pairmsg").textContent = msg || "";
  if (!$("devname").value) {
    const ua = navigator.userAgent;
    $("devname").value = /iPad|Tablet/.test(ua) ? "Tablet" : /iPhone|Android.*Mobile/.test(ua) ? "Phone" : "Pit wall PC";
  }
  $("code").focus();
}
$("pairform").addEventListener("submit", async (e) => {
  e.preventDefault();
  const code = $("code").value.replace(/\D/g, "");
  if (code.length !== 6) { $("pairmsg").textContent = "The code has 6 digits"; return; }
  $("pairbtn").disabled = true;
  try {
    const r = await api("/api/pair", { method: "POST", body: JSON.stringify({ code, name: $("devname").value }) });
    const data = await r.json();
    if (!r.ok) {
      $("pairmsg").textContent = data.retry_after ? `${data.error} (retry in ${data.retry_after} s)` : data.error;
      $("code").value = "";
      return;
    }
    token = data.token; store.set("token", token);
    $("code").value = "";
    showApp();
  } catch (err) {
    $("pairmsg").textContent = "Delta Suite not reachable";
  } finally {
    $("pairbtn").disabled = false;
  }
});
$("code").addEventListener("input", () => {
  const v = $("code").value.replace(/\D/g, "").slice(0, 6);
  $("code").value = v;
  if (v.length === 6) $("pairform").requestSubmit();
});
$("logout").addEventListener("click", async () => {
  try { await api("/api/logout", { method: "POST", body: "{}" }); } catch (e) {}
  token = null; store.set("token", null); showPair("Disconnected.");
});

// ---------------------------------------------------------------- tabs
function showTab(name) {
  tab = name; store.set("tab", name);
  document.querySelectorAll(".nav").forEach((b) => b.classList.toggle("on", b.dataset.tab === name));
  document.querySelectorAll("main.tab").forEach((m) => m.classList.toggle("hidden", m.id !== "tab-" + name));
  if (name === "engineer") { unread = 0; $("unread").classList.add("hidden"); const l = $("log"); l.scrollTop = l.scrollHeight; }
  if (name === "pit") loadSetup();
  if (name === "strategy") loadStrategy();
  if (last) render(last);
  video.update();
}
document.querySelectorAll(".nav").forEach((b) => b.addEventListener("click", () => showTab(b.dataset.tab)));

// ---------------------------------------------------------------- polling
function showApp() {
  $("pair").classList.add("hidden");
  $("app").classList.remove("hidden");
  since = 0; lapsKnown = -1; $("log").innerHTML = ""; $("walllog").innerHTML = "";
  audio.start = Infinity;      // no backlog: only messages spoken from now on
  showTab(tab);
  poll();
}
function stopPolling() { if (timer) clearTimeout(timer); timer = null; }
async function poll() {
  stopPolling();
  try {
    const r = await api(`/api/state?since=${since}&laps=${lapsKnown}`);
    if (r.status === 401) { unpaired(); return; }
    if (r.ok) { last = await r.json(); render(last); failures = 0; $("offline").classList.add("hidden"); }
  } catch (e) {
    if (++failures >= 3) { $("offline").classList.remove("hidden"); $("live").classList.remove("on"); }
  }
  timer = setTimeout(poll, document.hidden ? 2000 : 500);
}
document.addEventListener("visibilitychange", () => { video.update(); if (!document.hidden && token) poll(); });

// ---------------------------------------------------------------- render
function tempColor(t) {
  if (!t) return "var(--dim)";
  if (t < 70) return "var(--blue)";
  if (t < 80) return "#7cc7ff";
  if (t <= 100) return "var(--good)";
  if (t <= 110) return "var(--warn)";
  return "var(--bad)";
}
function flagClass(flag) {
  return /yellow/i.test(flag) ? "yellow" : /red|black|penalty/i.test(flag) ? "red" : /blue/i.test(flag) ? "blue"
    : /green|clear/i.test(flag) ? "green" : "";
}

function render(d) {
  const L = d.live || {};
  $("live").classList.toggle("on", !!(d.running && L.on_track));
  setText("session", L.on_track ? [L.session, L.car, L.track].filter(Boolean).join(" · ") : (d.running ? "Waiting for AC…" : "Acquisition stopped"));
  const flag = L.flag || (L.on_track ? "Green" : "—");
  setText("flag", flag);
  $("flag").className = "pill " + flagClass(flag);
  if (d.track_rev != null && d.track_rev !== track.rev) loadTrack(d.track_rev);
  renderRadio(d);
  renderProposals(d.proposals || []);
  if (d.laps) { lapsKnown = d.laps_n; renderLaps(d); }
  if (tab === "wall") renderWall(d, L);
  if (tab === "onboard") renderOnboard(d, L);
  video.meta(d.video || {}, d);
}

function renderWall(d, L) {
  setText("pos", L.position ? "P" + L.position : "–");
  const race = L.race || {};
  setText("lapinfo", L.current_lap ? `Lap ${L.current_lap}${race.total_laps ? " / " + race.total_laps : ""}` : "");
  setText("cur", L.current_lap_ms ? fmtMs(L.current_lap_ms).replace(/(\.\d)\d\d$/, "$1") : "–");
  const dl = $("delta");
  if (L.delta_s == null) dl.textContent = "";
  else { dl.textContent = (L.delta_s > 0 ? "+" : "") + L.delta_s.toFixed(2); dl.className = "delta " + (L.delta_s <= 0 ? "good" : "bad"); }
  setText("last", L.last_lap || "–"); setText("best", L.best_lap || "–");
  setText("speed", L.speed_kmh != null ? L.speed_kmh + " km/h" : "–");
  setText("gear", gearText(L.gear));
  $("pbrake").style.setProperty("--v", L.brake || 0);
  $("pgas").style.setProperty("--v", L.gas || 0);
  setText("fuel", L.fuel_l != null ? L.fuel_l.toFixed(1) + " L" : "–");
  setText("fuellaps", L.laps_of_fuel ?? "–");
  setText("fuelend", L.fuel_at_finish_l != null ? L.fuel_at_finish_l + " L" : "–");
  setText("togo", race.laps_to_go != null ? race.laps_to_go + (race.laps_to_go_estimated ? " (est.)" : "") :
          race.time_left_s != null ? Math.max(0, Math.round(race.time_left_s / 60)) + " min" : "–");
  const hy = (L.car_status || {}).hybrid;
  $("hybrid").classList.toggle("hidden", !hy);
  if (hy) { setText("batt", Math.round(hy.battery_pct) + "% · " + (hy.state || "")); $("battbar").style.width = hy.battery_pct + "%"; }

  setText("compound", L.tyre_compound || "");
  const names = ["FL", "FR", "RL", "RR"];
  const t = L.tyre_temp_c || [], p = L.tyre_press_psi || [], w = L.tyre_wear_pct || [], b = L.brake_temp_c || [];
  setHTML($("tyres"), names.map((n, i) => `<div class="tyre" style="border-left-color:${tempColor(t[i])}">
      <div class="t" style="color:${tempColor(t[i])}">${t[i] != null ? Math.round(t[i]) + "°" : "–"}</div>
      <div class="s">${n} · ${p[i] != null ? p[i].toFixed(1) + " psi" : "–"}</div>
      <div class="s">wear ${w[i] != null ? w[i].toFixed(1) + "%" : "–"} · brake ${b[i] != null ? b[i] + "°" : "–"}</div></div>`).join(""));

  setText("bias", L.brake_bias_pct != null ? L.brake_bias_pct + "%" : "–");
  setText("abs", L.abs != null ? `${L.abs}/${L.abs_levels}` : "–");
  setText("tc", L.tc != null ? `${L.tc}/${L.tc_levels}` : "–");
  setText("eb", L.engine_brake ?? "–");
  setText("temps", L.air_c != null ? `${Math.round(L.air_c)}° / ${Math.round(L.track_c)}°` : "–");
  const alerts = ((L.car_status || {}).alerts || []).filter((a) => a.level !== "ok");
  setHTML($("alerts"), alerts.map((a) => `<div class="alert ${a.level}">${esc(a.text)}</div>`).join(""));

  const st = d.standings || [];
  setText("stcount", st.length ? st.length + " cars" : "");
  if (st.length) {
    setHTML($("standings"), st.map((r) => `<tr class="${r.is_you ? "me" : ""} ${r.in_pit ? "pit" : ""}">
      <td>${r.pos}</td><td class="name">${esc(r.driver)}${r.in_pit ? " · PIT" : ""}</td>
      <td>${r.laps_down ? "+" + r.laps_down + "L" : fmtGap(r.gap_s)}</td><td>${fmtGap(r.interval_s)}</td>
      <td>${fmtMs(r.last_ms)}</td><td>${fmtMs(r.best_ms)}</td></tr>`).join(""));
  }
  drawGPS($("gps"), d.gps);
  setText("gpsnote", track.line.length ? "" : "line learned while driving");
  setText("busy", d.engineer_busy ? "engineer is thinking…" : "");
}

function gearText(g) { return g == null ? "–" : g === -1 ? "R" : g === 0 ? "N" : String(g); }

function renderOnboard(d, L) {
  $("hud").classList.toggle("hidden", !L.on_track);
  setText("hspeed", L.speed_kmh ?? "–");
  setText("hgear", gearText(L.gear));
  $("hbrake").style.setProperty("--v", L.brake || 0);
  $("hgas").style.setProperty("--v", L.gas || 0);
  drawGPS($("gps2"), d.gps);
}

// ---------------------------------------------------------------- GPS (canvas, redrawn at the poll rate)
const ZONE = { yellow: "#f5c518", red: "#ff3b3b", blue: "#3d9bff" };
let trail = [];
async function loadTrack(rev) {
  track.rev = rev;           // also on failure: no retry storm
  try { const t = await getJSON("/api/data/track"); if (t) track = t; } catch (e) {}
}
function pointAt(pos) {
  const n = track.line.length;
  const f = ((pos % 1) + 1) % 1 * n, i = Math.floor(f) % n, j = (i + 1) % n, k = f - Math.floor(f);
  const a = track.line[i], b = track.line[j];
  return [a[0] + (b[0] - a[0]) * k, a[1] + (b[1] - a[1]) * k];
}
function drawGPS(cv, gps) {
  if (!cv || !cv.offsetWidth) return;
  const dpr = Math.min(window.devicePixelRatio || 1, 2);
  const W = cv.offsetWidth, H = cv.offsetHeight;
  if (cv.width !== Math.round(W * dpr)) { cv.width = Math.round(W * dpr); cv.height = Math.round(H * dpr); }
  const g = cv.getContext("2d");
  g.setTransform(dpr, 0, 0, dpr, 0, 0);
  g.clearRect(0, 0, W, H);
  const cars = (gps && gps.cars) || [];
  const hasLine = track.line.length > 10;
  const me = cars.find((c) => c.me);
  if (!hasLine && me && me.x != null) {
    trail.push([me.x, me.z]);
    if (trail.length > 4000) trail.shift();
  }
  const pts = hasLine ? track.line.concat(track.pit || []) : trail.concat(cars.filter((c) => c.x != null).map((c) => [c.x, c.z]));
  if (!pts.length) { g.fillStyle = "#8a93a3"; g.font = "13px sans-serif"; g.fillText("No track data yet", 12, 24); return; }
  let x0 = Infinity, x1 = -Infinity, z0 = Infinity, z1 = -Infinity;
  for (const [x, z] of pts) { x0 = Math.min(x0, x); x1 = Math.max(x1, x); z0 = Math.min(z0, z); z1 = Math.max(z1, z); }
  const pad = 14, w = Math.max(x1 - x0, 50), h = Math.max(z1 - z0, 50);
  const k = Math.min((W - 2 * pad) / w, (H - 2 * pad) / h), cx = (x0 + x1) / 2, cz = (z0 + z1) / 2;
  const px = (x, z) => [W / 2 + (x - cx) * k, H / 2 + (z - cz) * k];
  const path = (list, closed) => {
    g.beginPath();
    list.forEach(([x, z], i) => { const [a, b] = px(x, z); i ? g.lineTo(a, b) : g.moveTo(a, b); });
    if (closed) g.closePath();
  };
  g.lineJoin = g.lineCap = "round";
  if (hasLine) {
    if (track.pit && track.pit.length > 1) { path(track.pit, false); g.strokeStyle = "#2a303b"; g.lineWidth = 3; g.stroke(); }
    path(track.line, true); g.strokeStyle = "#3a4250"; g.lineWidth = 7; g.stroke();
    g.strokeStyle = "#cfd5df"; g.lineWidth = 2.5; g.stroke();
    for (const zn of (gps && gps.zones) || []) {
      const n = Math.max(2, Math.ceil((zn.end - zn.start) * track.line.length) + 1);
      const seg = []; for (let i = 0; i < n; i++) seg.push(pointAt(zn.start + (zn.end - zn.start) * i / (n - 1)));
      path(seg, false); g.strokeStyle = ZONE[zn.kind] || "#fff"; g.lineWidth = 5; g.stroke();
    }
    const [sx, sz] = px(...track.line[0]); g.fillStyle = "#fff"; g.fillRect(sx - 2, sz - 6, 4, 12);
  } else if (trail.length > 1) {
    path(trail, false); g.strokeStyle = "#3a4250"; g.lineWidth = 3; g.stroke();
  }
  const r = Math.max(6, Math.min(10, W / 50));
  const sorted = cars.slice().sort((a, b) => (a.me ? 1 : 0) - (b.me ? 1 : 0));    // yours on top
  for (const c of sorted) {
    const xy = hasLine && c.pos != null ? pointAt(c.pos) : c.x != null ? [c.x, c.z] : null;
    if (!xy) continue;
    const [a, b] = px(...xy);
    g.beginPath(); g.arc(a, b, c.me ? r * 1.15 : r, 0, 2 * Math.PI);
    g.fillStyle = c.pit ? "#1b2029" : c.me ? "#e10600" : c.leader ? "#b26cff" : "#e8ebf0";
    g.fill(); g.lineWidth = 1.5; g.strokeStyle = c.pit ? "#8a93a3" : "#0b0d10"; g.stroke();
    if (c.num) {
      g.fillStyle = c.pit ? "#8a93a3" : c.me || c.leader ? "#fff" : "#111";
      g.font = `800 ${Math.round(r * (c.num.length > 1 ? 0.95 : 1.1))}px sans-serif`;
      g.textAlign = "center"; g.textBaseline = "middle"; g.fillText(c.num, a, b + 0.5);
    }
  }
}
window.addEventListener("resize", () => { if (last) { drawGPS($("gps"), last.gps); drawGPS($("gps2"), last.gps); } });

// ---------------------------------------------------------------- proposals
function renderProposals(list) {
  const props = list.slice().reverse();
  const html = props.length ? props.map((p) => {
    const open = ["pending", "in pits", "error"].includes(p.status);
    return `<div class="prop"><div class="what"><b>${esc(p.description)}</b><span>${esc(p.reason)}</span>
      <span> · ${esc(p.status)}${p.outcome ? " — " + esc(p.outcome) : ""}</span></div>
      ${open ? `<button class="btn ok" data-act="confirm" data-id="${p.id}">Confirm</button>
               <button class="btn no" data-act="discard" data-id="${p.id}">Discard</button>` : ""}</div>`;
  }).join("") : '<div class="empty">No proposals</div>';
  for (const id of ["wallprops", "pitprops", "engprops"]) setHTML($(id), html);
}
document.querySelectorAll(".proposals").forEach((el) => el.addEventListener("click", async (e) => {
  const btn = e.target.closest("button[data-act]");
  if (!btn) return;
  btn.disabled = true;
  await action({ kind: btn.dataset.act, id: Number(btn.dataset.id) });
}));

// ---------------------------------------------------------------- radio log and audio
const audio = {
  on: store.get("audio") === "1", start: Infinity, queue: [], playing: false,
  push(seq) { if (this.on && seq >= this.start) { this.queue.push(seq); this.next(); } },
  async next() {
    if (this.playing || !this.queue.length) return;
    this.playing = true;
    const seq = this.queue.shift();
    try { await this.play(seq); } catch (e) {}
    this.playing = false;
    this.next();
  },
  async play(seq) {
    const r = await api(`/api/audio?seq=${seq}`);
    if (!r.ok) return;
    const url = URL.createObjectURL(await r.blob());
    const a = new Audio(url);
    await new Promise((res) => { a.onended = a.onerror = res; a.play().catch(res); });
    URL.revokeObjectURL(url);
  },
};
$("audio").checked = audio.on;
$("audio").addEventListener("change", () => {
  audio.on = $("audio").checked; store.set("audio", audio.on ? "1" : "0");
  audio.queue = [];
  audio.start = since + 1;                   // from the next message on
});

function msgEl(e) {
  const el = document.createElement("div");
  el.className = "msg " + e.who;
  const time = new Date(e.t * 1000).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
  el.innerHTML = `<div class="who">${esc(e.who)} · ${time}${e.audio ? ` <button class="play" data-seq="${e.seq}" title="Play">▶</button>` : ""}</div>${esc(e.text)}`;
  return el;
}
function renderRadio(d) {
  const entries = d.radio || [];
  if (!entries.length) { setText("busy2", d.engineer_busy ? "engineer is thinking…" : ""); return; }
  for (const box of [$("log"), $("walllog")]) {
    const atBottom = box.scrollHeight - box.scrollTop - box.clientHeight < 40;
    for (const e of entries) box.appendChild(msgEl(e));
    const max = box.id === "walllog" ? 40 : 300;
    while (box.children.length > max) box.removeChild(box.firstChild);
    if (atBottom) box.scrollTop = box.scrollHeight;
  }
  const backlog = since === 0;            // first load: old messages are neither played nor counted as new
  for (const e of entries) {
    if (e.audio) audio.push(e.seq);       // only from audio.start on
    if (!backlog && tab !== "engineer" && e.who !== "system") unread++;
    since = Math.max(since, e.seq);
  }
  if (audio.start === Infinity) audio.start = since + 1;
  if (unread && tab !== "engineer") { $("unread").textContent = unread; $("unread").classList.remove("hidden"); }
  setText("busy2", d.engineer_busy ? "engineer is thinking…" : "");
}
document.addEventListener("click", (e) => {
  const b = e.target.closest("button.play");
  if (b) audio.play(Number(b.dataset.seq)).catch(() => toast("Audio no longer available"));
});

document.querySelectorAll(".chip").forEach((chip) => chip.addEventListener("click", () => {
  composeKind = chip.dataset.kind;
  document.querySelectorAll(".chip").forEach((t) => t.classList.toggle("on", t === chip));
  $("msg").placeholder = composeKind === "say" ? "Read out on the driver's radio…" : "Question for the AI engineer (answer in the log)…";
  $("msg").focus();
}));
$("composer").addEventListener("submit", async (e) => {
  e.preventDefault();
  const text = $("msg").value.trim();
  if (!text) return;
  const res = await action({ kind: composeKind, text });
  if (res.ok) $("msg").value = "";
});

// ---------------------------------------------------------------- laps and strategy
function renderLaps(d) {
  setText("ideal", [d.best_lap ? "best " + d.best_lap : "", d.theoretical_best ? "ideal " + d.theoretical_best : ""].filter(Boolean).join(" · "));
  const laps = (d.laps || []).slice().reverse();
  const valid = (d.laps || []).filter((l) => l.valid).map((l) => l.time_ms);
  const bestMs = valid.length ? Math.min(...valid) : -1;
  const bs = d.best_sectors_ms || [];
  setHTML($("laps"), laps.length ? laps.map((l) => {
    const s = l.sectors_ms || [];
    const cls = !l.valid ? "invalid" : l.time_ms === bestMs ? "best" : "";
    const wear = (l.tyre_wear_end_pct || []).map((v) => v.toFixed(0)).join(" ");
    return `<tr><td>${l.lap}</td><td class="${cls}">${esc(l.time)}</td>
      ${[0, 1, 2].map((i) => `<td class="${s[i] && s[i] === bs[i] ? "best" : ""}">${s[i] ? (s[i] / 1000).toFixed(3) : "–"}</td>`).join("")}
      <td>${l.fuel_used_l ?? "–"}</td><td>${(l.avg_tyre_temp_c || []).map((v) => Math.round(v)).join(" ")}</td>
      <td>${wear}</td><td>${l.vmax_kmh != null ? Math.round(l.vmax_kmh) : "–"}</td></tr>`;
  }).join("") : '<tr><td colspan="9" class="empty">No laps yet</td></tr>');
}
const kv = (pairs) => pairs.map(([k, v]) => `<div><span>${esc(k)}</span><b>${esc(v ?? "–")}</b></div>`).join("");
let strategyTimer = null;
async function loadStrategy() {
  clearTimeout(strategyTimer);
  if (tab !== "strategy") return;
  strategyTimer = setTimeout(loadStrategy, document.hidden ? 10000 : 3000);
  try {
    const s = await getJSON("/api/data/strategy");
    if (!s) return;
    const p = s.plan;
    setHTML($("fuelplan"), kv([
      ["Fuel", s.fuel_l != null ? s.fuel_l + " L" : null],
      ["Per lap", s.fuel_per_lap_l != null ? s.fuel_per_lap_l.toFixed(2) + " L" : null],
      ["Laps to go", s.laps_to_go != null ? s.laps_to_go + (s.laps_to_go_estimated ? " (est.)" : "") : null],
      ["Laps on fuel", p ? p.laps_on_fuel : null],
      ["Needed", p ? p.fuel_needed_l + " L" : null],
      ["To add", p ? p.fuel_to_add_l + " L" : null],
      ["Stops", p ? p.stops : null],
      ["Pit window", p && p.pit_window ? `lap ${p.pit_window[0]}–${p.pit_window[1]}` : p ? "no stop" : null],
    ]));
    const dg = s.degradation;
    const w = s.tyre_wear_pct || [];
    setHTML($("degr"), kv([
      ["Stint laps", s.stint_laps],
      ["Loss / lap", dg ? (dg.s_per_lap >= 0 ? "+" : "") + dg.s_per_lap.toFixed(3) + " s" : null],
      ["Drop-off", dg && dg.drop_off_at_stint_lap ? "stint lap " + dg.drop_off_at_stint_lap : dg ? "not in sight" : null],
      ["Best stop", s.optimal_pit_stint_lap ? "stint lap " + s.optimal_pit_stint_lap : dg && s.laps_to_go ? "no stop needed" : null],
      ["Wear FL/FR", w.length ? `${w[0]} / ${w[1]} %` : null],
      ["Wear RL/RR", w.length ? `${w[2]} / ${w[3]} %` : null],
    ]));
    setText("forecast", dg ? "Next laps: " + dg.forecast.join(" · ") : "Degradation forecast after 3 clean laps in the stint.");
    const bs = s.best_sectors_ms || [];
    setHTML($("pace"), kv([
      ["Ideal lap", s.ideal_lap],
      ["Best S1", bs[0] ? (bs[0] / 1000).toFixed(3) : null],
      ["Best S2", bs[1] ? (bs[1] / 1000).toFixed(3) : null],
      ["Best S3", bs[2] ? (bs[2] / 1000).toFixed(3) : null],
      ["Time left", s.time_left_s != null ? Math.round(s.time_left_s / 60) + " min" : null],
    ]));
  } catch (e) {}
}

// ---------------------------------------------------------------- pit & setup
let setupTimer = null;
async function loadSetup() {
  clearTimeout(setupTimer);
  if (tab !== "pit") return;
  try {
    const s = await getJSON("/api/data/setup");
    if (s) renderSetup(s);
  } catch (e) {}
  setupTimer = setTimeout(loadSetup, document.hidden ? 5000 : 2000);
}
function renderSetup(s) {
  const c = s.controls;
  const ctl = $("controls");
  if (!c) setHTML(ctl, '<div class="empty">Needs the CSP app connected (Pit &amp; Setup → install it in Delta Suite)</div>');
  else {
    const rows = [["brake_bias", "Brake bias", c.brake_bias, "%", c.brake_bias_step, c.brake_bias_min, c.brake_bias_max]];
    if (c.abs_levels) rows.push(["abs", "ABS", c.abs, "", 1, 0, c.abs_levels]);
    if (c.tc_levels) rows.push(["tc", "TC", c.tc, "", 1, 0, c.tc_levels]);
    if (c.engine_brake_levels) rows.push(["engine_brake", "Engine brake", c.engine_brake, "", 1, 0, c.engine_brake_levels]);
    // rebuilt only when the values change, so a value being typed is not wiped
    setHTML(ctl, rows.map(([what, name, v, unit, step, lo, hi]) => `<div class="row" data-what="${what}" data-step="${step}" data-lo="${lo}" data-hi="${hi}">
      <span>${name}</span><button class="btn small" data-d="-1">−</button><b>${v ?? "–"}${unit}</b>
      <button class="btn small" data-d="1">+</button><input type="number" step="${step}" min="${lo}" max="${hi}" value="${v ?? ""}"></div>`).join("")
      + '<div class="sub" style="margin-top:8px">− / + and Enter create a proposal: confirm it here, in Delta Suite or from the wheel.</div>');
  }
  setText("setupsrc", s.source ? s.source + (s.editable_now ? " · editable now" : " · changes apply in the pits") : (s.note || ""));
  const items = s.items || [];
  setHTML($("setup"), items.length ? items.map((it) => `<tr><td class="name">${esc(it.label || it.name)}</td>
      <td>${esc(it.display_value ?? "")} ${esc(it.units || "")}</td><td>${it.value ?? "–"}</td>
      <td>${it.min ?? ""}–${it.max ?? ""}</td>
      <td>${it.read_only || !c ? "" : `<input class="setup-in" type="number" data-name="${esc(it.name)}" min="${it.min}" max="${it.max}" step="${it.step || 1}" value="${it.value}">`}</td></tr>`).join("")
    : `<tr><td colspan="5" class="empty">${esc(s.note || "No setup available")}</td></tr>`);
}
$("controls").addEventListener("click", async (e) => {
  const b = e.target.closest("button[data-d]");
  if (!b) return;
  const row = b.closest(".row"), input = row.querySelector("input");
  const step = Number(row.dataset.step), lo = Number(row.dataset.lo), hi = Number(row.dataset.hi);
  const v = Math.min(hi, Math.max(lo, Math.round((Number(input.value) + Number(b.dataset.d) * step) * 100) / 100));
  input.value = v;
  propose(row.dataset.what, v);
});
$("controls").addEventListener("keydown", (e) => {
  if (e.key !== "Enter" || e.target.tagName !== "INPUT") return;
  propose(e.target.closest(".row").dataset.what, Number(e.target.value));
});
$("setup").addEventListener("keydown", (e) => {
  if (e.key !== "Enter" || !e.target.classList.contains("setup-in")) return;
  propose("setup", Number(e.target.value), e.target.dataset.name);
});
async function propose(what, value, name = "") {
  const res = await action({ kind: "adjust", what, value, name });
  if (res.ok) toast("Proposal: " + res.description + " — confirm it to apply");
}

// ---------------------------------------------------------------- onboard video (on demand)
const QKEY = "quality";
const video = {
  running: false, seq: 0, ctrl: null, url: null, frames: 0, fpsT: performance.now(),
  cam: Number(store.get("cam", "0")), car: Number(store.get("car", "-1")), q: Number(store.get(QKEY, "1")),
  metaKey: "",
  wanted() {
    if (document.hidden || !token) return false;
    return tab === "onboard" || (tab === "wall" && $("wallvideo").checked);
  },
  target() { return tab === "onboard" ? [$("obimg"), $("obvstatus")] : [$("wallimg"), $("wallvstatus")]; },
  update() {
    if (!this.wanted()) {
      this.stop();
      setText("wallvstatus", $("wallvideo").checked ? "" : "Video off: AC renders nothing extra");
      return;
    }
    if (!this.running) this.loop();
  },
  stop() {
    this.running = false;
    if (this.ctrl) this.ctrl.abort();
    this.ctrl = null;
  },
  restart() { this.seq = 0; this.stop(); this.update(); },
  async loop() {
    this.running = true;
    while (this.running && this.wanted()) {
      const [img, status] = this.target();
      this.ctrl = new AbortController();
      const t = setTimeout(() => this.ctrl && this.ctrl.abort(), 5000);
      try {
        const r = await fetch(`/api/frame?cam=${this.cam}&car=${this.car}&q=${this.q}&after=${this.seq}`,
                              { headers: headers(), cache: "no-store", signal: this.ctrl.signal });
        clearTimeout(t);
        if (r.status === 401) { unpaired(); break; }
        if ((r.headers.get("Content-Type") || "").startsWith("image/")) {
          this.seq = Number(r.headers.get("X-Frame-Seq")) || this.seq + 1;
          const url = URL.createObjectURL(await r.blob());
          const old = this.url;
          this.url = url;
          img.src = url;
          if (old) setTimeout(() => URL.revokeObjectURL(old), 1000);
          status.textContent = "";
          this.count();
        } else {
          const j = await r.json().catch(() => ({}));
          status.textContent = j.status || "Waiting for the onboard…";
          await sleep(500);            // nothing to show: do not hammer the hub
        }
      } catch (e) {
        clearTimeout(t);
        if (!this.running) break;
        status.textContent = "Delta Suite not reachable";
        await sleep(1000);
      }
    }
    this.running = false;
  },
  count() {
    this.frames++;
    const now = performance.now();
    if (now - this.fpsT >= 1000) {
      setText("fps", Math.round(this.frames * 1000 / (now - this.fpsT)) + " fps");
      this.frames = 0; this.fpsT = now;
    }
  },
  meta(v, d) {
    const key = JSON.stringify([v.cameras, v.cars, v.qualities]);
    if (key === this.metaKey) return;
    this.metaKey = key;
    // [text, index]; index null = header of the next group (as in Delta Suite's camera list)
    let html = "", open = false;
    for (const [text, idx] of v.cameras || []) {
      if (idx == null) { html += (open ? "</optgroup>" : "") + `<optgroup label="${esc(text)}">`; open = true; }
      else html += `<option value="${idx}"${idx === this.cam ? " selected" : ""}>${esc(text)}</option>`;
    }
    $("cam").innerHTML = html + (open ? "</optgroup>" : "");
    $("car").innerHTML = (v.cars || []).map(([idx, name]) => `<option value="${idx}"${idx === this.car ? " selected" : ""}>${esc(name)}</option>`).join("");
    $("quality").innerHTML = (v.qualities || []).map((name, i) => `<option value="${i}"${i === this.q ? " selected" : ""}>${esc(name)}</option>`).join("");
  },
};
$("cam").addEventListener("change", () => { video.cam = Number($("cam").value); store.set("cam", video.cam); video.restart(); });
$("car").addEventListener("change", () => { video.car = Number($("car").value); store.set("car", video.car); video.restart(); });
$("quality").addEventListener("change", () => { video.q = Number($("quality").value); store.set(QKEY, video.q); video.restart(); });
$("wallvideo").checked = store.get("wallvideo") === "1";
$("wallvideo").addEventListener("change", () => { store.set("wallvideo", $("wallvideo").checked ? "1" : "0"); video.update(); });
window.addEventListener("pagehide", () => video.stop());

if (token) showApp(); else showPair();
