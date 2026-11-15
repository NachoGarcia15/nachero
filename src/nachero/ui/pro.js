"use strict";
/* Simulador de drafts competitivos. Usa los helpers globales de app.js ($, esc, img, f1, signed, tone). */

const PRO_ORDER = [
  ["blue", "ban"], ["red", "ban"], ["blue", "ban"], ["red", "ban"], ["blue", "ban"], ["red", "ban"],
  ["blue", "pick"], ["red", "pick"], ["red", "pick"], ["blue", "pick"], ["blue", "pick"], ["red", "pick"],
  ["red", "ban"], ["blue", "ban"], ["red", "ban"], ["blue", "ban"],
  ["red", "pick"], ["blue", "pick"], ["blue", "pick"], ["red", "pick"],
];
const PRO_PARTS = {
  prio: "Prioridad", flex: "Flex", comp: "Cohesión", counter: "Contra su comp", matchup: "Matchup",
  risk: "Riesgo de counter", deny: "Denegar", their_comp: "Encaja al rival", role_need: "Rol que le falta",
};
const SIDE_ES = { blue: "Azul", red: "Rojo" };
const ROLE_FILTERS = [["all", "Todos"], ["top", "Top"], ["jungle", "Jungla"], ["middle", "Mid"], ["bottom", "ADC"], ["utility", "Support"]];

let PRO = { tournament: "", blue: { bans: [], picks: [] }, red: { bans: [], picks: [] }, fearless: [], history: [] };
let PRO_UI = { tournaments: null, champs: [], res: null, filter: "all", q: "", fearlessMode: false, inited: false, timer: null };
try { const s = JSON.parse(localStorage.getItem("nachero.pro") || localStorage.getItem("draftbot.pro") || "null"); if (s && s.blue) PRO = { ...PRO, ...s }; } catch (_) {}

function proSave() { try { localStorage.setItem("nachero.pro", JSON.stringify(PRO)); } catch (_) {} }
const proName = (id) => (PRO_UI.champs.find((c) => c.id === id) || {}).name || "";

function proStepInfo(step) {
  if (step >= PRO_ORDER.length) return { label: "Draft completo", side: null, kind: null };
  const [side, kind] = PRO_ORDER[step];
  const n = PRO_ORDER.slice(0, step + 1).filter(([s, k]) => s === side && k === kind).length;
  const label = kind === "ban" ? `Ban ${n} · ${SIDE_ES[side]}` : `Pick ${side === "blue" ? "B" : "R"}${n} · ${SIDE_ES[side]}`;
  return { label, side, kind };
}

async function proInit() {
  if (PRO_UI.inited) return;
  PRO_UI.inited = true;
  renderPro();
  try {
    const r = await fetch("/api/pro/tournaments");
    const t = await r.json();
    if (!r.ok) throw new Error(t.error || "gol.gg");
    PRO_UI.tournaments = t;
    if (!PRO.tournament || !t.all.includes(PRO.tournament)) PRO.tournament = t.majors[0] || t.all[0] || "";
  } catch (e) {
    PRO_UI.tournaments = { error: String(e.message || e) };
  }
  await proLoadChamps();
  proSuggest();
}

async function proLoadChamps() {
  try {
    const r = await fetch("/api/pro/champions?t=" + encodeURIComponent(PRO.tournament || ""));
    if (r.ok) PRO_UI.champs = await r.json();
  } catch (_) {}
}

async function proSuggest() {
  proSave();
  try {
    const r = await fetch("/api/pro/suggest", { method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ tournament: PRO.tournament, blue: PRO.blue, red: PRO.red, fearless: PRO.fearless }) });
    PRO_UI.res = await r.json();
  } catch (e) {
    PRO_UI.res = { error: "Nachero no responde" };
  }
  renderPro();
  // mientras se descargan datos (gol.gg o matchups), vuelve a pedir en unos segundos
  clearTimeout(PRO_UI.timer);
  const res = PRO_UI.res || {};
  const waiting = (res.data && !res.data.loaded && PRO.tournament) || (res.suggestions || []).some((s) => s.loaded === false);
  if (waiting) PRO_UI.timer = setTimeout(async () => { if (res.data && !res.data.loaded) await proLoadChamps(); proSuggest(); }, 3500);
}

/* Paso actual calculado desde el estado local (no depende de la ultima respuesta del servidor) */
function proLocalStep() {
  const seen = { blue: { ban: 0, pick: 0 }, red: { ban: 0, pick: 0 } };
  for (let i = 0; i < PRO_ORDER.length; i++) {
    const [s, k] = PRO_ORDER[i];
    if (seen[s][k] < PRO[s][k === "ban" ? "bans" : "picks"].length) seen[s][k]++;
    else return i;
  }
  return PRO_ORDER.length;
}

function proApply(id) {
  const taken = new Set([...PRO.blue.bans, ...PRO.blue.picks, ...PRO.red.bans, ...PRO.red.picks, ...PRO.fearless]);
  if (taken.has(id)) return Promise.resolve();
  if (PRO_UI.fearlessMode) {
    PRO.fearless.push(id);
    PRO.history.push({ fearless: id });
    return proSuggest();
  }
  const step = proLocalStep();
  if (step >= PRO_ORDER.length) return Promise.resolve();
  const [side, kind] = PRO_ORDER[step];
  const key = kind === "ban" ? "bans" : "picks";
  PRO[side][key].push(id);
  PRO.history.push({ side, key, id });
  return proSuggest();
}

function proUndo() {
  const h = PRO.history.pop();
  if (!h) return;
  if (h.fearless) PRO.fearless = PRO.fearless.filter((x) => x !== h.fearless);
  else PRO[h.side][h.key] = PRO[h.side][h.key].filter((x, i, a) => !(x === h.id && i === a.lastIndexOf(h.id)));
  proSuggest();
}

function proReset(keepFearless) {
  PRO.blue = { bans: [], picks: [] };
  PRO.red = { bans: [], picks: [] };
  if (!keepFearless) PRO.fearless = [];
  PRO.history = [];
  proSuggest();
}

/* Siguiente partida de una serie fearless: los picks de esta pasan a bloqueados */
function proNextGame() {
  const used = [...PRO.blue.picks, ...PRO.red.picks].filter((x) => !PRO.fearless.includes(x));
  PRO.fearless.push(...used);
  proReset(true);
}

/* ------------------------------------------------------------------ pintado */
function proTeam(side, res) {
  const t = (res.teams || {})[side] || { picks: [], notes: [], identity_es: "", lanes: [] };
  const bans = PRO[side].bans;
  const cur = res.side === side;
  const banSlots = Array.from({ length: 5 }, (_, i) => bans[i]
    ? `<img src="${img("tile", bans[i])}" title="${esc(proName(bans[i]))}" alt="${esc(proName(bans[i]))}">`
    : `<span class="pslot ${cur && res.kind === "ban" && i === bans.length ? "now" : ""}"></span>`).join("");
  const picks = Array.from({ length: 5 }, (_, i) => {
    const p = t.picks[i];
    const now = cur && res.kind === "pick" && i === PRO[side].picks.length;
    return p
      ? `<div class="ppick"><img src="${img("tile", p.id)}" alt=""><span class="nm">${esc(p.name)}</span><span class="role">${esc(p.role_short)}</span></div>`
      : `<div class="ppick empty ${now ? "now" : ""}"><span class="tile"></span><span class="nm">${now ? "Eligiendo…" : "—"}</span></div>`;
  }).join("");
  return `<div class="pteam ${side}">
    <div class="pteam-head"><h2>${SIDE_ES[side]}</h2><span>${esc(t.identity_es || "")}</span></div>
    <div class="pbans">${banSlots}</div>
    <div class="ppicks">${picks}</div>
    ${t.notes.length ? `<div class="pnotes">${t.notes.map((n) => `<p>${esc(n)}</p>`).join("")}</div>` : ""}
    ${t.lanes.length ? `<div class="planess">${t.lanes.map((l) => `<div><span class="role">${esc(l.role)}</span> ${esc(l.me)} <span class="muted">vs</span> ${esc(l.vs)} <span class="num ${l.d2 == null ? "muted" : tone(l.d2, 0.9)}">${l.d2 == null ? "…" : signed(l.d2)}</span></div>`).join("")}</div>` : ""}
  </div>`;
}

function proSuggestions(res) {
  if (res.done) {
    const v = res.verdict || {};
    const lean = v.lean ? `Ventaja de draft para <b>${SIDE_ES[v.lean]}</b>` : "Drafts equilibrados";
    return `<div class="pverdict"><h3>${lean}</h3>
      <p>Puntuación de composición (identidad, avisos y matchups de línea): Azul <span class="num">${signed(v.blue || 0)}</span> · Rojo <span class="num">${signed(v.red || 0)}</span></p>
      <div class="pactions"><button class="btn" id="pro-next">Siguiente partida (fearless)</button><button class="btn" id="pro-reset2">Nuevo draft</button></div></div>`;
  }
  const list = res.suggestions || [];
  if (!list.length) return `<p class="muted">Sin sugerencias para este paso.</p>`;
  return `<div class="psugs">${list.map((s, i) => `
    <button class="psug ${i === 0 ? "top" : ""}" data-id="${s.id}">
      <img src="${img("tile", s.id)}" alt="">
      <div class="body">
        <div class="l1"><b>${esc(s.name)}</b><span class="role">${esc(s.role_short)}</span>${s.pro ? `<span class="muted">${f1(s.pro.prio)}% prio · ${s.pro.picks}P ${s.pro.bans}B</span>` : `<span class="muted">sin datos pro</span>`}</div>
        <div class="l2">${Object.entries(s.parts).filter(([, v]) => Math.abs(v) >= 0.05).map(([k, v]) => `<span>${PRO_PARTS[k] || k} <i class="${tone(v, 0.05)}">${signed(v)}</i></span>`).join("")}</div>
        ${s.why && s.why.length ? `<div class="l3">${s.why.map((w) => `<span class="${w.sign === "+" ? "pos" : "neg"}">${w.sign === "+" ? "+" : "−"} ${esc(w.text)}</span>`).join("")}</div>` : ""}
      </div>
      <span class="sc num">${f1(s.score)}</span>
    </button>`).join("")}</div>`;
}

function proGrid(res) {
  const used = new Set([...PRO.blue.bans, ...PRO.blue.picks, ...PRO.red.bans, ...PRO.red.picks]);
  const fear = new Set(PRO.fearless);
  const q = PRO_UI.q.trim().toLowerCase();
  const list = PRO_UI.champs
    .filter((c) => !q || c.name.toLowerCase().includes(q))
    .filter((c) => PRO_UI.filter === "all" || c.roles.includes(PRO_UI.filter))
    .sort((a, b) => b.presence - a.presence || a.name.localeCompare(b.name));
  return list.map((c) => {
    const off = used.has(c.id) || fear.has(c.id);
    return `<button class="gch ${off ? "off" : ""} ${fear.has(c.id) ? "fear" : ""}" data-id="${c.id}" ${off ? "disabled" : ""} title="${esc(c.name)}">
      <img src="${img("tile", c.id)}" alt="" loading="lazy"><span>${esc(c.name)}</span>${c.presence ? `<i>${c.presence}%</i>` : ""}</button>`;
  }).join("");
}

function renderPro() {
  const el = $("#view-pro");
  if (!el) return;
  const res = PRO_UI.res || {};
  const t = PRO_UI.tournaments;
  const info = proStepInfo(res.step || 0);
  const data = res.data || {};
  const dataLine = !PRO.tournament ? "" : data.loaded
    ? `${nf0.format(data.games)} partidas de ${esc(PRO.tournament)} (gol.gg) · matchups Master+ (Lolalytics)`
    : `Descargando ${esc(PRO.tournament)} de gol.gg…`;
  const progress = PRO_ORDER.map(([s, k], i) => `<i class="${s} ${k} ${i < (res.step || 0) ? "done" : ""} ${i === res.step ? "cur" : ""}"></i>`).join("");
  el.innerHTML = `<div class="pro">
    <div class="pro-head">
      <div><h1>Simulador de draft pro</h1><p class="muted">${t && t.error ? "No puedo leer gol.gg: " + esc(t.error) : dataLine}</p></div>
      <div class="pro-controls">
        <select id="pro-tour" aria-label="Torneo">${t && t.all ? [...new Set([...(t.majors || []), ...t.all])].map((n) => `<option ${n === PRO.tournament ? "selected" : ""}>${esc(n)}</option>`).join("") : `<option>${esc(PRO.tournament || "Cargando…")}</option>`}</select>
        <button class="btn" id="pro-undo" ${PRO.history.length ? "" : "disabled"}>Deshacer</button>
        <button class="btn" id="pro-reset">Reiniciar</button>
      </div>
    </div>
    <div class="pro-progress">${progress}</div>
    <div class="pro-board">
      ${proTeam("blue", res)}
      <div class="pro-center">
        <div class="pstep"><b>${esc(info.label)}</b><span class="muted">${res.done ? "" : `Paso ${(res.step || 0) + 1} de 20 · ${res.kind === "ban" ? "toca un campeón para banearlo" : "toca un campeón para elegirlo"}`}</span></div>
        ${res.error ? `<p class="neg">${esc(res.error)}</p>` : proSuggestions(res)}
      </div>
      ${proTeam("red", res)}
    </div>
    <div class="pro-gridhead">
      <input id="pro-q" type="search" placeholder="Buscar campeón" value="${esc(PRO_UI.q)}" aria-label="Buscar campeón">
      <div class="filters">${ROLE_FILTERS.map(([k, l]) => `<button data-f="${k}" class="${PRO_UI.filter === k ? "on" : ""}">${l}</button>`).join("")}</div>
      <label class="fearless"><input type="checkbox" id="pro-fear" ${PRO_UI.fearlessMode ? "checked" : ""}> Marcar como usados (fearless)</label>
      ${PRO.fearless.length ? `<span class="muted">${PRO.fearless.length} bloqueados</span><button class="btn" id="pro-clearfear">Quitar bloqueos</button>` : ""}
    </div>
    <div class="pro-grid">${proGrid(res)}</div>
  </div>`;

  // eventos
  el.querySelectorAll(".psug").forEach((b) => (b.onclick = () => proApply(Number(b.dataset.id))));
  el.querySelectorAll(".gch").forEach((b) => (b.onclick = () => proApply(Number(b.dataset.id))));
  const tour = $("#pro-tour");
  if (tour) tour.onchange = async () => { PRO.tournament = tour.value; await proLoadChamps(); proSuggest(); };
  $("#pro-undo").onclick = proUndo;
  $("#pro-reset").onclick = () => proReset(false);
  const r2 = $("#pro-reset2"); if (r2) r2.onclick = () => proReset(false);
  const nx = $("#pro-next"); if (nx) nx.onclick = proNextGame;
  const cf = $("#pro-clearfear"); if (cf) cf.onclick = () => { PRO.fearless = []; proSuggest(); };
  $("#pro-fear").onchange = (e) => { PRO_UI.fearlessMode = e.target.checked; };
  el.querySelectorAll(".pro-gridhead .filters button").forEach((b) => (b.onclick = () => { PRO_UI.filter = b.dataset.f; renderPro(); }));
  const q = $("#pro-q");
  q.oninput = () => {
    PRO_UI.q = q.value;
    const pos = q.selectionStart;
    $(".pro-grid").innerHTML = proGrid(res);
    el.querySelectorAll(".gch").forEach((b) => (b.onclick = () => proApply(Number(b.dataset.id))));
    q.focus(); q.setSelectionRange(pos, pos);
  };
}
