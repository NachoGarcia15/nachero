"use strict";

const $ = (s) => document.querySelector(s);
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const img = (kind, id) => `/api/img/${kind}/${id}`;
const nf1 = new Intl.NumberFormat("es-ES", { minimumFractionDigits: 1, maximumFractionDigits: 1 });
const nf0 = new Intl.NumberFormat("es-ES");
const f1 = (v) => nf1.format(v);
const signed = (v) => (v > 0 ? "+" : v < 0 ? "−" : "±") + nf1.format(Math.abs(v));
const tone = (v, eps = 0.25) => (v > eps ? "pos" : v < -eps ? "neg" : "muted");
const memo = {};
const once = (key, val, fn) => { const j = JSON.stringify(val); if (memo[key] !== j) { memo[key] = j; fn(val); } };

let STATE = null;
let VIEW = "draft";
let POOL_ROLE = "all";
let POOL_SORT = { key: "est", dir: -1 };

/* ------------------------------------------------------------------ red */
async function post(url, body) {
  try {
    await fetch(url, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body || {}) });
  } catch (_) { /* el siguiente sondeo mostrara el estado real */ }
  poll();
}

/* ------------------------------------------------------------------ cabecera */
document.querySelectorAll("#modes button").forEach((b) => (b.onclick = () => post("/api/mode", { mode: b.dataset.mode })));
document.querySelectorAll("#tabs button").forEach((b) => (b.onclick = () => setView(b.dataset.view)));

function setView(v) {
  VIEW = v;
  document.querySelectorAll("#tabs button").forEach((b) => b.classList.toggle("on", b.dataset.view === v));
  ["draft", "pool", "pro", "log"].forEach((k) => ($("#view-" + k).hidden = k !== v));
  if (v === "pro" && typeof proInit === "function") proInit();
  try { localStorage.setItem("nachero.view", v); } catch (_) {}
}
window.addEventListener("DOMContentLoaded", () => {
  try { const v = (localStorage.getItem("nachero.view") || localStorage.getItem("draftbot.view")); if (v) setView(v); } catch (_) {}
});

/* Qué falta para mostrar algo (códigos de `app/status.py: empty_states`). */
const EMPTY = {
  platform: (s) => ["Nachero necesita Windows",
    `Estás en ${esc((s.platform || {}).name || "otro sistema")}: Nachero solo puede leer el cliente de LoL en Windows. Descarga nachero.exe y ábrelo en Windows con el cliente abierto.`],
  no_champions: () => ["Sin datos de campeones",
    "No encuentro el cliente de LoL ni puedo descargar los datos de CommunityDragon. Abre el cliente o comprueba la conexión a internet: reintento solo."],
  loading: () => ["Cargando", "Leyendo tu historial y las estadísticas Master+…"],
  no_client: () => ["Abre el cliente de League of Legends",
    "Sin el cliente no puedo leer tus partidas y no hay ninguna guardada. Cuando lo abras me conecto solo."],
  no_games: () => ["Sin partidas en tu historial",
    "El cliente no tiene partidas tuyas de soloq, flex o normales en la Grieta. Juega alguna y tu pool aparecerá aquí."],
  no_patch: () => ["No sé cuál es el parche actual",
    "Sin el cliente ni internet no puedo saberlo, así que no hay estadísticas Master+. Abre el cliente o comprueba la conexión."],
  no_data: (s) => ["Sin estadísticas Master+",
    `No he podido descargar las estadísticas de Lolalytics del parche ${esc(s.patch || "")}. Comprueba la conexión a internet y pulsa «Actualizar ahora» en Ajustes.`],
};
function emptyState(code, s) {
  const [title, text] = (EMPTY[code] || EMPTY.loading)(s || {});
  return `<div class="empty-state"><h2>${title}</h2><p>${text}</p></div>`;
}

/* ------------------------------------------------------------------ tareas (#46) */
// Lo que está haciendo la app, del registro de tareas del servidor (`domain/tasks.py`).
const taskOf = (s, id) => ((s && s.tasks) || []).find((t) => t.id === id);
const searching = (s) => !s.connected && !s.offline;
const TASK_GLYPH = {
  done: `<svg viewBox="0 0 16 16" width="14" height="14"><path d="M3.5 8.5l3 3 6-7" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/></svg>`,
  error: `<svg viewBox="0 0 16 16" width="14" height="14"><path d="M8 4.2v4.6" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"/><circle cx="8" cy="11.6" r="1.1" fill="currentColor"/></svg>`,
  skipped: `<svg viewBox="0 0 16 16" width="14" height="14"><path d="M4.5 8h7" stroke="currentColor" stroke-width="1.6" stroke-linecap="round"/></svg>`,
  running: `<i></i>`,
  pending: `<i></i>`,
};
const secs = (n) => (n >= 60 ? `${Math.floor(n / 60)} min ${String(Math.round(n % 60)).padStart(2, "0")} s` : `${Math.round(n)} s`);

// Lo que se ve a la derecha de cada paso: n/m, el resultado o el error con su reintento.
function taskDetail(t) {
  if (t.state === "error") return esc(t.error) + (t.retry_in ? ` · reintento en ${secs(t.retry_in)}` : "");
  if (t.state === "running" && t.total) return `${t.detail ? esc(t.detail) + " · " : ""}<span class="num">${t.done}/${t.total}</span>`;
  if (t.state === "running" && t.elapsed >= 3) return `${esc(t.detail || "")} <span class="num">${Math.round(t.elapsed)} s</span>`;
  return esc(t.detail || "");
}

// Lista de pasos con su estado. Se actualiza por id (sin repintar) para que las barras y los
// cambios de estado se animen en vez de saltar.
function updateSteps(ol, tasks) {
  const seen = new Set();
  tasks.forEach((t, i) => {
    seen.add(t.id);
    let li = ol.querySelector(`[data-id="${t.id}"]`);
    if (!li) {
      li = document.createElement("li");
      li.dataset.id = t.id;
      li.innerHTML = `<span class="glyph" aria-hidden="true"></span><span class="name"></span><span class="det"></span><span class="track"><i></i></span>`;
    }
    if (ol.children[i] !== li) ol.insertBefore(li, ol.children[i] || null);
    if (li.dataset.state !== t.state) {
      li.dataset.state = t.state;
      li.className = "step " + t.state;
      li.querySelector(".glyph").innerHTML = TASK_GLYPH[t.state] || "";
    }
    li.querySelector(".name").textContent = t.text;
    const det = taskDetail(t);
    if (li.querySelector(".det").innerHTML !== det) li.querySelector(".det").innerHTML = det;
    const track = li.querySelector(".track");
    const known = t.state === "running" && t.total;
    track.classList.toggle("indet", t.state === "running" && !t.total);
    track.firstChild.style.width = known ? `${Math.round((100 * t.done) / t.total)}%` : t.state === "done" ? "100%" : "0%";
  });
  [...ol.children].forEach((li) => { if (!seen.has(li.dataset.id)) li.remove(); });
}

// Consejos de draft durante la carga (textos de Nachero), como en la pantalla de carga de LoL.
const TIPS = [
  "Banea lo que te counterea, no lo que está roto.",
  "Si eliges pronto, elige algo difícil de counterear.",
  "Un pick flex esconde tu rol hasta el final del draft.",
  "Antes de elegir, mira qué le falta a tu equipo: daño mágico, frontline o control.",
  "Tu mejor campeón suele rendir más que el más fuerte del parche.",
  "Un buen matchup de línea vale poco si tu equipo se queda sin daño.",
  "Con el último pick del equipo puedes ir a por el counter sin miedo.",
  "Si tu rival de línea aún no ha elegido, cuenta con que puede counterearte.",
  "Contra mucho control, valora un campeón con escudos o con Limpiar.",
  "Pocas partidas con un campeón pesan menos que muchas: la confianza importa.",
  "En jungla, piensa qué líneas pueden ganar y empieza por ese lado.",
  "Marcar tu pick pronto ayuda a tu equipo a completar la composición.",
];
let TIP_I = Math.floor(Math.random() * TIPS.length);
let TIP_TIMER = null;
function rotateTips(on) {
  if (!on) { clearInterval(TIP_TIMER); TIP_TIMER = null; return; }
  if (TIP_TIMER) return;
  TIP_TIMER = setInterval(() => {
    const p = $(".boot .tip-text");
    if (!p) return rotateTips(false);
    p.classList.add("out");
    setTimeout(() => { TIP_I = (TIP_I + 1) % TIPS.length; p.textContent = TIPS[TIP_I]; p.classList.remove("out"); }, 260);
  }, 7000);
}

const MARK = `<svg class="mark" viewBox="0 0 32 32" width="44" height="44" aria-hidden="true">
  <rect width="32" height="32" rx="7" fill="#18181c"/>
  <path class="n1" d="M8 23.5V10.5l13 13" fill="none" stroke="#6ea8ff" stroke-width="5" stroke-linecap="round" stroke-linejoin="round" pathLength="1"/>
  <path class="n2" d="M21 23.5V13" fill="none" stroke="#ff7a7f" stroke-width="5" stroke-linecap="round" pathLength="1"/>
  <path class="n3" d="M21 6l5 7H16z" fill="#ff7a7f" stroke="#ff7a7f" stroke-width="1" stroke-linejoin="round"/></svg>`;

// Pantalla de arranque: qué está haciendo la app, paso a paso, con un consejo mientras tanto.
function renderBoot(el, s) {
  let boot = el.querySelector(".boot");
  if (!boot) {
    el.innerHTML = `<div class="boot">
      ${MARK}
      <h1 class="boot-title"></h1>
      <p class="boot-sub" aria-live="polite"></p>
      <ol class="steps"></ol>
      <p class="tip"><span>Consejo</span><span class="tip-text">${esc(TIPS[TIP_I])}</span></p>
    </div>`;
    boot = el.querySelector(".boot");
    rotateTips(true);
  }
  const tasks = (s.tasks || []).filter((t) => t.boot);
  const pg = s.progress || {};
  const cur = tasks.find((t) => t.id === pg.current);
  boot.querySelector(".boot-title").textContent = searching(s) ? "Buscando el cliente de LoL"
    : s.offline ? "Preparando tu draft sin el cliente" : "Preparando tu draft";
  boot.querySelector(".boot-sub").textContent = searching(s)
    ? "Si no está abierto, sigo con tus datos guardados en unos segundos."
    : cur ? `Paso ${pg.step} de ${pg.steps} · ${cur.text}` : "Casi listo";
  updateSteps(boot.querySelector(".steps"), tasks);
}

// Barra superior: estado del cliente y, aparte, el trabajo en segundo plano con su detalle.
function renderWork(s) {
  const w = $("#work");
  const pg = s.progress || {};
  const errs = (s.tasks || []).filter((t) => t.state === "error");
  const show = pg.busy || errs.length;
  w.hidden = !show;
  if (!show) return;
  w.classList.toggle("err", !pg.busy);
  w.querySelector("span").textContent = pg.busy ? `Actualizando · ${pg.label}` : `${errs[0].text}: falló, reintento solo`;
  const mark = { done: "✓", running: "…", error: "!", skipped: "–", pending: "·" };
  w.title = (s.tasks || []).map((t) => `${mark[t.state] || ""} ${t.text}${t.total && t.state === "running" ? ` ${t.done}/${t.total}` : ""}${t.state === "error" ? `: ${t.error}` : t.detail ? `: ${t.detail}` : ""}`).join("\n");
}

function renderHeader(s) {
  const conn = $("#conn");
  const noWin = s.platform && !s.platform.supported;
  conn.classList.toggle("ok", !!s.connected);
  conn.classList.toggle("off", !!s.offline);
  conn.classList.toggle("seek", searching(s) && !noWin);
  conn.querySelector("span").textContent = noWin && !s.connected ? "Necesita Windows" : s.offline ? "Cliente cerrado" : searching(s) ? "Buscando el cliente" : s.loading ? "Conectado" : s.phase_es || "Conectado";
  renderWork(s);
  $("#platform").hidden = !noWin;
  if (noWin) $("#platform").textContent = `Nachero necesita Windows con el cliente de LoL abierto y estás en ${s.platform.name}: descarga nachero.exe y ábrelo en Windows.`;
  $("#rank").innerHTML = s.rank ? `<b>${esc(s.rank.tier)}</b> · ${s.rank.lp} LP · ${s.rank.w}V ${s.rank.l}D` : "";
  $("#demo").hidden = !s.demo;
  once("update", s.update || null, renderUpdate);
  $("#demo-exit").hidden = !s.demo_ui;
  const modes = s.modes || {};
  document.querySelectorAll("#modes button").forEach((b) => {
    b.classList.toggle("on", b.dataset.mode === s.mode);
    b.setAttribute("aria-checked", b.dataset.mode === s.mode);
    const m = modes[b.dataset.mode];
    if (m) b.title = b.dataset.mode === "active" ? `${m.text} ${m.summary}` : m.text;
  });
  // qué hace el modo actual: al pasar el ratón por el selector (antes, una línea fija bajo la barra)
  const cur = modes[s.mode];
  $("#modes").title = cur ? `${cur.label}: ${s.mode === "active" && !s.demo ? cur.text + " " + cur.summary : cur.text}` : "";
  once("modes", modes, () => renderModes(modes));
}

// Aviso de nueva versión (si `update_url` apunta a un latest.json): enlace a la descarga.
function renderUpdate(u) {
  const el = $("#update");
  el.hidden = !u;
  if (!u) return;
  el.innerHTML = `<span>Hay una versión nueva de Nachero: <b>${esc(u.version)}</b>${u.notes ? ` · ${esc(u.notes)}` : ""}</span><a class="btn" href="${esc(u.url)}" target="_blank" rel="noopener">Descargar</a>`;
}

function renderModes(modes) {
  $("#modes-help").innerHTML = ["paused", "observe", "active"].filter((k) => modes[k]).map((k) => {
    const m = modes[k];
    const touches = k !== "active" ? "No toca el cliente."
      : m.touches.length ? `En el cliente: ${m.touches.map(esc).join(" · ")}.` : "Con tus ajustes no toca el cliente.";
    return `<div class="opt"><div class="tx"><b>${esc(m.label)}</b><small>${esc(m.text)}<br>${touches}</small></div></div>`;
  }).join("");
}

/* ------------------------------------------------------------------ draft */
function slot(p, side) {
  const cls = ["slot", p.state, p.me ? "me" : "", p.active === "pick" ? "active" : "", p.lane_opp ? "opp" : ""].join(" ");
  const tile = p.champ ? `<img class="tile" src="${img("tile", p.champ.id)}" alt="">` : `<div class="tile"></div>`;
  let name = p.champ ? esc(p.champ.name) : p.active === "ban" ? "Baneando…" : p.active === "pick" ? "Eligiendo…" : "—";
  let sub = "";
  if (p.me) sub = p.state === "picked" ? "Tú · confirmado" : p.state === "hover" ? "Tú · marcado" : p.state === "suggest" ? "Tú · sugerido" : "Tú";
  else if (p.state === "hover") sub = "Marcando";
  else if (side === "enemy" && p.lane_opp) sub = "Tu rival de línea";
  return `<div class="${cls}">${tile}<div class="nm">${name}${sub ? `<span class="sub">${sub}</span>` : ""}</div><span class="role">${esc(p.role)}</span></div>`;
}

function comp(c) {
  return `${c.identity ? `<div class="ident">${esc(c.identity)}</div>` : ""}<div class="comp">
    <div><b>${c.ad}</b><small>AD</small></div>
    <div><b>${c.ap}</b><small>AP</small></div>
    <div><b>${c.front}</b><small>Frontline</small></div>
    <div><b>${c.cc}</b><small>Control</small></div></div>`;
}

const PART_LABELS = [
  ["you", "Tú con él"], ["meta", "Fuerza en el parche"], ["lane", "Rival de línea"], ["enemies", "Resto del rival"],
  ["allies", "Encaje con tu equipo"], ["vs_comp", "Contra su composición"], ["risk", "Riesgo de counter"],
  ["ease", "Fácil de jugar"],
];
const MU_PARTS = ["lane", "enemies", "risk"];

function parts(p, d) {
  const show = PART_LABELS.filter(([k]) => {
    if (k === "you") return d.mode === "pool";
    if (k === "risk") return !d.lane_known && d.enemy_left_after > 0;
    if (k === "vs_comp") return Math.abs(p.parts.vs_comp) >= 0.05;
    if (k === "ease") return p.parts.ease !== undefined; // solo en autofill
    return true;
  });
  return `<div class="parts">${show.map(([k, label]) => {
    const pending = MU_PARTS.includes(k) && !p.matchups_loaded;
    const v = p.parts[k] || 0;
    const w = pending ? 0 : Math.min(50, (Math.abs(v) / 4) * 50);
    return `<div class="part"><span>${label}</span><div class="track"><i class="${v >= 0 ? "p" : "n"}" style="width:${w}%"></i></div><span class="v ${pending ? "muted" : tone(v)}">${pending ? "…" : signed(v)}</span></div>`;
  }).join("")}</div>`;
}

const ROLE_TAG = { top: "TOP", jungle: "JG", middle: "MID", bottom: "ADC", utility: "SUP" };
const ROLE_NAME = { top: "Top", jungle: "Jungla", middle: "Mid", bottom: "ADC", utility: "Support" };
const CONF_HELP = {
  high: "Muchas partidas en este rol en Master+: la estimación es fiable.",
  medium: "Bastantes partidas en este rol en Master+.",
  low: "Pocas partidas en este rol en Master+: la fuerza se acerca a la de su rol principal y penaliza.",
  none: "Casi sin partidas en este rol en Master+: estimación a partir de su rol principal.",
};

/* Rol del campeón (si no es su principal) y confianza de la estimación, en chips. */
function roleChips(p) {
  if (!p.confidence) return "";
  const n = p.meta_games ? `${nf0.format(p.meta_games)} partidas` : "sin partidas";
  const cat = p.role_cat && p.role_cat !== "main"
    ? `<span class="chip cat" title="${esc(p.roles_label ? "Sus roles: " + p.roles_label : "")}">${esc(ROLE_NAME[p.role] || "")} ${esc(p.role_cat_es)}</span>` : "";
  return `${cat}<span class="chip conf-${esc(p.confidence)}" title="${esc(CONF_HELP[p.confidence] || "")} ${n}${p.role_pct ? ` (${f1(p.role_pct)} % de sus partidas)` : ""}.">Confianza ${esc((p.confidence_es || "").toLowerCase())}</span>`;
}

function matchupLine(p) {
  if (!p.matchups_loaded) {
    const t = taskOf(STATE, "matchups");
    const n = t && t.state === "running" && t.total ? ` (${t.done}/${t.total})` : "";
    return `<div class="mus"><span class="loading-dot">Calculando matchups${n}…</span></div>`;
  }
  if (p.matchups.length) {
    const other = p.matchups_other_role ? `<span class="muted other-note" title="Sin matchups de este rol: se usan los de su rol principal, con la mitad de peso.">* datos de otro rol</span>` : "";
    return `<div class="mus">${p.matchups.slice(0, 5).map((m) => `<span class="${m.lane ? "lane" : ""}${m.other_role ? " other" : ""}">${esc(m.name)} <i>${ROLE_TAG[m.role] || ""}</i> <span class="num ${tone(m.d2, 0.9)}">${signed(m.d2)}</span>${m.other_role ? "*" : ""}</span>`).join("")}${other}</div>`;
  }
  if (p.risk_items && p.risk_items.length) {
    return `<div class="mus"><span class="muted">Le pueden counterear:</span>${p.risk_items.map((m) => `<span>${esc(m.name)} <span class="num ${tone(m.d2, 0.9)}">${signed(m.d2)}</span></span>`).join("")}</div>`;
  }
  return "";
}

const RUNES_STATE = {
  preview: "Runas recomendadas",
  would: "Importaría estas runas",
  imported: "Runas importadas",
  failed: "No se pudieron importar las runas",
  pending: "Runas",
};

function runesLine(r, locked) {
  if (!r) return "";
  if (r.state === "loading") return `<div class="runes muted">Cargando runas…</div>`;
  if (r.state === "none") {
    return `<div class="runes muted">Sin runas recomendadas para este campeón en este rol${locked ? ": no se importa nada" : ""}.</div>`;
  }
  return `<div class="runes ${r.state}">
    <span class="lbl">${RUNES_STATE[r.state] || "Runas"}</span>
    <b>${esc(r.keystone)}</b> <span class="muted">· ${esc(r.primary)} + ${esc(r.secondary)}</span>
    <small>${esc((r.runes || []).join(" · "))}${r.source ? ` — ${esc(r.source)}` : ""}</small>
  </div>`;
}

function whyList(p) {
  if (!p.why || !p.why.length) return "";
  return `<ul class="why">${p.why.slice(0, 4).map((w) => `<li class="${w.sign === "+" ? "pos" : "neg"}"><span>${esc(w.text)}</span></li>`).join("")}</ul>`;
}

function modeSwitch(mode) {
  return `<div class="seg seg-sm pickmode" role="radiogroup" aria-label="Base de la recomendación">
    <button data-pm="pool" class="${mode === "pool" ? "on" : ""}" role="radio" aria-checked="${mode === "pool"}">Con tu pool</button>
    <button data-pm="meta" class="${mode === "meta" ? "on" : ""}" role="radio" aria-checked="${mode === "meta"}">Solo meta y draft</button></div>`;
}

function bindModeSwitch(root) {
  root.querySelectorAll(".pickmode button").forEach((b) => (b.onclick = () => post("/api/settings", { pick_mode: b.dataset.pm })));
}

function draftContext(d) {
  if (d.blind) return "A ciegas: el rival no ve tu pick ni tú el suyo";
  const opp = d.enemy_team.find((e) => e.lane_opp && e.champ);
  if (opp) return `Rival de línea: <b>${esc(opp.champ.name)}</b>`;
  if (d.enemy_left_after > 0) return `Tu rival de línea aún no ha elegido · ${d.enemy_left_after} pick${d.enemy_left_after > 1 ? "s" : ""} rival${d.enemy_left_after > 1 ? "es" : ""} después de ti`;
  return "Tu rival de línea aún no ha elegido";
}

function subline(p) {
  const bits = [];
  if (p.role_cat && p.role_cat !== "main") bits.push(`${ROLE_NAME[p.role] || ""} ${p.role_cat_es}`);
  if (p.confidence && p.confidence !== "high") bits.push(`confianza ${(p.confidence_es || "").toLowerCase()}`);
  if (p.recent30 >= 2) bits.push(`${p.recent30} este mes`);
  if (p.games) bits.push(`${p.games} partidas · ${p.wr}%`);
  else if (p.exp >= 5) bits.push(`~${p.exp} partidas de maestría`);
  else bits.push("sin experiencia");
  if (p.tier) bits.push(`tier ${p.tier}`);
  return bits.join(" · ");
}

// Fundido suave al pasar de la carga (o de los skeletons) al contenido.
function appear(el) {
  el.classList.remove("appear");
  void el.offsetWidth;
  el.classList.add("appear");
}

function renderDraft([d, idle, s]) {
  const el = $("#draft-main");
  if (s.empty && s.empty !== "loading") { rotateTips(false); el.innerHTML = emptyState(s.empty, s); return; }
  // Cuatro estados: buscando el cliente, conectado y cargando (los dos con la pantalla de carga),
  // cliente cerrado (datos guardados, o el aviso de `no_client` si no hay) y listo.
  if (s.loading) return renderBoot(el, s);
  rotateTips(false);
  if (el.querySelector(".boot")) appear(el);
  if (!d) return renderIdle(el, idle, s);
  if (d.unsupported) return renderUnsupported(el, d);

  const best = d.hero;
  const alts = d.locked ? d.picks.slice(0, 6) : d.picks.slice(1, 7);
  const turn = d.status.find((x) => x.kind.startsWith("turn"));
  const infos = d.status.filter((x) => !x.kind.startsWith("turn"));
  const low = d.timer_left <= 8 && d.my_turn;

  el.innerHTML = `<div class="cs">
    <div class="team ally">
      <div class="team-head"><h2>Tu equipo</h2><span>${esc(d.role_es)}</span></div>
      <div class="slots">${d.my_team.map((p) => slot(p, "ally")).join("")}</div>
      ${comp(d.ally_comp)}
    </div>

    <div class="center">
      <div class="phase-line"><span class="ph"><b>${esc(d.timer_phase)}</b>${d.queue ? " · " + esc(d.queue) : ""} · ${draftContext(d)}</span><span class="timer ${low ? "low" : ""}">${d.timer_left}</span></div>
      ${turn ? `<div class="turn"><span>${esc(turn.msg)}</span><small>${turn.kind === "turn_auto" ? "Nachero confirma lo que esté marcado: cámbialo en el cliente o aquí" : "hazlo tú"}</small></div>` : ""}
      ${chooser(d.choose)}
      ${roleFitLine(d)}
      ${infos.length ? `<p class="info-line">${infos.map((x) => esc(x.msg)).join(" · ")}${s.mode !== "active" ? " (modo observar)" : ""}</p>` : ""}
      ${best ? `
      <article class="hero">
        <div class="hero-art" style="background-image:url('${img("splash", best.id)}')"></div>
        <div class="hero-body">
          <div class="eyebrow">${d.locked ? "Tu pick confirmado" : "Mejor pick para " + esc(d.role_es)}${d.mode === "meta" ? " · sin tu pool" : ""}</div>
          <h1>${esc(best.name)}</h1>
          <div class="chips">${roleChips(best)}</div>
          <div class="est"><span class="num">${f1(best.est)}%</span><small>WR estimado</small></div>
          ${parts(best, d)}
          ${matchupLine(best)}
          ${whyList(best)}
          ${runesLine(d.runes, d.locked)}
          ${d.coachless ? `<a class="coach" href="${esc(d.coachless)}" target="_blank" rel="noopener">Ver build en Coachless</a>` : ""}
        </div>
      </article>` : `<div class="hero"><div class="hero-body"><h1>Sin candidatos</h1><p class="muted">No hay campeones disponibles en tu pool para este rol.</p></div></div>`}

      <div class="block">
        <div class="block-head"><h3>${d.locked ? "Otras opciones que tenías" : "Alternativas"}</h3>${modeSwitch(d.mode)}</div>
        <div class="rows ${d.mode}">
          <div class="row head"><span></span><span></span><span style="text-align:left">Campeón</span>${d.mode === "pool" ? "<span>Tú</span>" : ""}<span>Parche</span><span>Rival</span><span>Equipo</span><span>Estimado</span></div>
          ${alts.map((p, i) => {
            const rival = p.parts.lane + p.parts.enemies + p.parts.risk + p.parts.vs_comp;
            return `
          <div class="row">
            <span class="i">${i + (d.locked ? 1 : 2)}</span><img src="${img("tile", p.id)}" alt="">
            <div class="nm">${esc(p.name)}<small>${esc(subline(p))}</small></div>
            ${d.mode === "pool" ? `<span class="c ${tone(p.parts.you)}">${signed(p.parts.you)}</span>` : ""}
            <span class="c ${tone(p.parts.meta)}">${signed(p.parts.meta)}</span>
            <span class="c ${p.matchups_loaded ? tone(rival) : "muted"}">${p.matchups_loaded ? signed(rival) : "…"}</span>
            <span class="c ${tone(p.parts.allies)}">${signed(p.parts.allies)}</span>
            <span class="c est">${f1(p.est)}%</span>
          </div>`; }).join("")}
        </div>
        <p class="foot">WR estimado = 50 + suma de partes. Rival = línea + resto del rival + composición + riesgo de counter. Fuera de su rol principal, la confianza baja con las partidas que tiene en tu rol.</p>
      </div>

      <div class="block ${d.ban_suggestions.length ? "split" : ""}">
        ${d.ban_suggestions.length ? `<div>
          <div class="block-head"><h3>Bans</h3><span>según tu pool</span></div>
          <div class="bans-list">${d.ban_suggestions.slice(0, 4).map((b, i) => `
            <div class="ban ${i === 0 ? "top" : ""}"><img src="${img("tile", b.id)}" alt=""><div><span class="nm">${esc(b.name)}</span><small>${esc(b.reasons.join(" · "))}</small></div></div>`).join("")}
          </div>
        </div>` : ""}
        <div>
          <div class="block-head"><h3>Composición</h3></div>
          <div class="notes">${d.notes.length ? d.notes.map((n) => `<p>${esc(n)}</p>`).join("") : `<p class="empty">Nada que destacar por ahora.</p>`}</div>
        </div>
      </div>

      <div class="banbar">
        <div><span>Bans aliados</span>${d.bans.ally.map((b) => `<img src="${img("tile", b.id)}" title="${esc(b.name)}" alt="${esc(b.name)}">`).join("") || '<span>—</span>'}</div>
        <div><span>Bans rivales</span>${d.bans.enemy.map((b) => `<img src="${img("tile", b.id)}" title="${esc(b.name)}" alt="${esc(b.name)}">`).join("") || '<span>—</span>'}</div>
      </div>
    </div>

    <div class="team enemy">
      <div class="team-head"><h2>Rival</h2><span>${d.blind ? "oculto a ciegas" : "roles estimados"}</span></div>
      <div class="slots">${d.enemy_team.map((p) => slot(p, "enemy")).join("")}</div>
      ${comp(d.enemy_comp)}
    </div>
  </div>`;
  bindModeSwitch(el);
  el.querySelectorAll(".choose button").forEach((b) => (b.onclick = () => choose(d.choose.kind, Number(b.dataset.id))));
}

/* Autofill o rol secundario: por qué la recomendación cambia. */
function roleFitLine(d) {
  const f = d.role_fit;
  if (!f || d.blind) return "";
  if (f.kind === "autofill") {
    return `<p class="rolefit autofill"><b>Autofill</b> · vas de ${esc(d.role_es)} y apenas lo juegas (${f.games} partida${f.games === 1 ? "" : "s"}). Priorizo campeones fáciles, fuertes en el parche y con poco riesgo de counter.</p>`;
  }
  if (f.kind === "secondary") return `<p class="rolefit">${esc(d.role_es)} es tu rol secundario.</p>`;
  return "";
}

/* Mejores opciones de tu turno: un clic las marca en el cliente y cuenta como elección tuya. */
let CHOOSE_MSG = null; // {text, err, until}
function chooser(c) {
  if (!c || !c.options || !c.options.length) return "";
  const ban = c.kind === "ban";
  const tip = c.enabled ? (ban ? "Marcar este ban en el cliente" : "Marcar este campeón en el cliente") : "Pasa a modo Activo para marcar desde aquí";
  const msg = CHOOSE_MSG && CHOOSE_MSG.until > Date.now() ? CHOOSE_MSG : null;
  const who = msg ? `<span class="who ${msg.err ? "err" : ""}">${esc(msg.text)}</span>`
    : c.by === "player" ? `<span class="who">Elegido por ti</span>` : c.by === "nachero" ? `<span class="who">Marcado por Nachero</span>` : "";
  return `<div class="choose" role="group" aria-label="${ban ? "Elegir ban" : "Elegir pick"}">
    <span class="lbl">${ban ? "Banear" : "Elegir"}</span>
    ${c.options.map((o) => `<button data-id="${o.id}" class="${o.id === c.marked ? "on" : ""}" ${c.enabled ? "" : "disabled"} title="${esc(tip)}" aria-pressed="${o.id === c.marked}"><img src="${img("tile", o.id)}" alt="">${esc(o.name)}</button>`).join("")}
    ${who}
  </div>`;
}

async function choose(kind, id) {
  let text = "", err = false;
  try {
    const r = await fetch("/api/draft/choose", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ kind, id }) });
    const out = await r.json();
    err = !r.ok;
    text = r.ok ? `Has elegido ${out.name}` : out.error || "No se ha podido marcar";
  } catch (_) {
    err = true;
    text = "Nachero no responde";
  }
  CHOOSE_MSG = { text, err, until: Date.now() + 4000 };
  delete memo.draft; // repinta ya con el mensaje
  poll();
}

const ARAM_RUNES = {
  loading: "Buscando las runas de ARAM…",
  none: "Sin runas de ARAM para este campeón: no importo nada.",
  preview: "Runas de ARAM: las importo en cuanto dejes de cambiar de campeón",
  would: "Importaría estas runas de ARAM (modo Observar)",
  imported: "Runas de ARAM importadas",
  failed: "No se pudieron importar las runas de ARAM",
};

function renderUnsupported(el, d) {
  const a = d.aram;
  if (a) {
    const r = a.runes;
    el.innerHTML = `<div class="idle">
      <h1>${esc(d.queue || "ARAM")}${a.champ ? ` · ${esc(a.champ.name)}` : ""}</h1>
      <p class="lead">En ARAM Nachero solo prepara las runas de ARAM del campeón que te toque (Lolalytics), y las cambia si cambias de campeón. Ni picks, ni bans, ni hechizos.</p>
      ${!a.champ ? `<p class="muted">Esperando a que tengas campeón…</p>`
        : !r ? `<p class="muted">Importar runas está desactivado en Ajustes.</p>`
        : r.keystone ? `<div class="runes ${esc(r.state)}"><span class="lbl">${ARAM_RUNES[r.state] || "Runas de ARAM"}${r.state === "imported" ? ` para ${esc(a.champ.name)}` : ""}</span>
            <b>${esc(r.keystone)}</b> <span class="muted">· ${esc(r.primary)} + ${esc(r.secondary)}</span>
            <small>${esc((r.runes || []).join(" · "))}</small></div>`
        : `<p class="muted">${ARAM_RUNES[r.state] || ""}</p>`}
    </div>`;
    return;
  }
  el.innerHTML = `<div class="idle">
    <h1>${esc(d.queue || "Este modo")}: sin recomendaciones</h1>
    <p class="lead">Nachero solo recomienda en la Grieta del Invocador (draft, a ciegas, personalizadas y herramienta de práctica). En este modo no toca el cliente: ni bans, ni picks, ni hechizos, ni runas.</p>
  </div>`;
}

function renderIdle(el, idle, s) {
  const paused = s.mode === "paused";
  const picks = (idle && idle.picks) || [];
  el.innerHTML = `<div class="idle">
    <h1>${paused ? "Nachero está en pausa" : "Esperando a la selección de campeón"}${s.booting ? `<span class="stale" title="Se ven tus datos guardados mientras se cargan los nuevos">Actualizando…</span>` : ""}</h1>
    ${s.offline ? `<p class="note-off">Abre League of Legends y me conecto solo. Mientras, ${s.games ? `uso tus ${nf0.format(s.games)} partidas guardadas` : "no tengo tus partidas y recomiendo solo por el meta"}.</p>` : ""}
    <p class="lead">${esc(s.phase_es || "")}${paused ? "" : s.mode === "active" ? " · modo Activo. " + esc(s.active_summary || "Actuará según tus ajustes.") : " · modo Observar: solo recomienda, no acepta la partida ni toca el cliente"}</p>
    ${cover()}
    ${idle ? `<div class="idle-role"><span>Tu rol</span>${roleSwitch(idle, s.main_role)}
      <small>${idle.auto ? "Automático: el que más juegas." : "Fijado por ti."} En la selección de campeón manda el rol que te asigne el cliente.</small></div>` : ""}
    ${picks.length ? `
      <div class="block-head"><h3>Si entras ahora de ${esc(idle.role_es)}, a ciegas</h3>${modeSwitch(s.pick_mode)}</div>
      <div class="idle-grid">${picks.map((p) => `
        <div class="card"><img src="${img("tile", p.id)}" alt="">
          <div><b>${esc(p.name)}</b><span class="num">${f1(p.est)}%</span><small>${esc(subline(p))}</small></div></div>`).join("")}
      </div>` : ""}
    <p class="idle-foot">${s.pick_mode === "meta"
      ? "Modo solo meta y draft: ignora tu pool y recomienda por la fuerza del campeón en Master+ este parche, sus matchups y lo que encaje con tu equipo."
      : "Con tu pool: suma tu experiencia, forma y resultados con cada campeón a su fuerza en Master+ este parche."}</p>
  </div>`;
  bindModeSwitch(el);
  el.querySelectorAll(".roleswitch button").forEach((b) => (b.onclick = () => post("/api/settings", { main_role: b.dataset.role })));
  el.querySelectorAll("[data-cover-demo]").forEach((b) => (b.onclick = startDemo));
}

const ROLE_BTNS = [["top", "Top"], ["jungle", "Jungla"], ["middle", "Mid"], ["bottom", "ADC"], ["utility", "Support"]];
function roleSwitch(idle, chosen) {
  const auto = !chosen || chosen === "auto";
  return `<div class="seg seg-sm roleswitch" role="radiogroup" aria-label="Tu rol">
    <button data-role="auto" class="${auto ? "on" : ""}">Auto${auto ? " · " + esc(idle.role_es) : ""}</button>
    ${ROLE_BTNS.map(([r, t]) => `<button data-role="${r}" class="${!auto && chosen === r ? "on" : ""}">${t}</button>`).join("")}</div>`;
}

/* ------------------------------------------------------------------ pool */
const POOL_COLS = [
  ["name", "Campeón"], ["role", "Rol"], ["games", "Partidas"], ["wr", "WR"], ["exp", "Experiencia"],
  ["you", "Tú"], ["tier", "Tier"], ["meta", "Meta"], ["meta_games", "Confianza"], ["est", "Estimado"],
];

// El cliente solo da tus ultimas 200 partidas de cualquier cola: explica por que el pool
// puede sumar menos partidas que las victorias y derrotas de la cabecera.
function historyNote(h) {
  if (!h || !h.games) return "";
  const since = h.since ? new Date(h.since).toLocaleDateString("es-ES", { day: "numeric", month: "short", year: "numeric" }) : "";
  let txt = `${nf0.format(h.games)} partidas de soloq, flex y normales${since ? ` desde el ${esc(since)}` : ""}.`;
  if (h.missing > 0) {
    txt += ` Tu ranked de la temporada tiene ${nf0.format(h.season)}: el cliente solo guarda tus últimas ${h.client_limit} partidas de cualquier modo y las anteriores no se pueden leer. Desde ahora Nachero guarda todas las que juegues.`;
  }
  return `<p class="pool-note">${txt}</p>`;
}

function renderPool(rows) {
  const el = $("#pool-main");
  if (!rows || !rows.length) {
    const why = STATE && STATE.empty && STATE.empty.pool;
    el.innerHTML = why && why !== "loading" ? emptyState(why, STATE) : poolSkeleton(STATE || {});
    return;
  }
  if (el.querySelector(".skel")) appear(el);
  const count = (k) => rows.filter((r) => r.role_key === k).length;
  if (POOL_ROLE !== "all" && !ROLE_NAME[POOL_ROLE]) POOL_ROLE = "all";  // filtro guardado de una versión anterior
  const list = rows.filter((r) => POOL_ROLE === "all" || r.role_key === POOL_ROLE).slice();
  const k = POOL_SORT.key;
  list.sort((a, b) => {
    const va = a[k] ?? -1e9, vb = b[k] ?? -1e9;
    return (typeof va === "string" ? va.localeCompare(vb) : va - vb) * POOL_SORT.dir;
  });
  el.innerHTML = `
    <div class="pool-head">
      <div><h1>Tu pool</h1><p>WR estimado a ciegas por campeón y rol: tu experiencia y resultados con él, más su fuerza en Master+ este parche. Con maestría alta, cada campeón sale también en sus roles principal y flex.</p>${historyNote(STATE.history)}</div>
      <div class="filters"><button data-r="all" class="${POOL_ROLE === "all" ? "on" : ""}">Todos <small>${rows.length}</small></button>${ROLE_BTNS.map(([r, t]) => `<button data-r="${r}" class="${POOL_ROLE === r ? "on" : ""}" ${count(r) ? "" : "disabled"}>${t} <small>${count(r)}</small></button>`).join("")}</div>
    </div>
    <div class="tablewrap"><table>
      <thead><tr>${POOL_COLS.map(([key, label]) => `<th data-k="${key}" class="${key === k ? "sorted" : ""}">${label}${key === k ? (POOL_SORT.dir < 0 ? " ↓" : " ↑") : ""}</th>`).join("")}</tr></thead>
      <tbody>${list.map((r) => `<tr>
        <td class="ch"><div><img src="${img("tile", r.id)}" alt=""><span>${esc(r.name)}${r.roles_label ? `<small>${esc(r.roles_label)}</small>` : ""}</span></div></td>
        <td class="rl">${esc(r.role)}${r.role_cat && r.role_cat !== "main" ? ` <span class="chip cat">${esc(r.role_cat_es)}</span>` : ""}</td>
        <td>${r.games || "—"}</td>
        <td class="${r.wr == null ? "muted" : r.wr >= 55 ? "pos" : r.wr < 45 ? "neg" : ""}">${r.wr == null ? "—" : r.wr + "%"}</td>
        <td><span class="exp"><i><b style="width:${Math.min(100, (r.exp / 150) * 100)}%"></b></i>${nf0.format(r.exp)}</span></td>
        <td class="${tone(r.you)}">${signed(r.you)}</td>
        <td><span class="tier">${esc(r.tier || "—")}</span></td>
        <td class="${tone(r.meta)}">${signed(r.meta)}</td>
        <td><span class="chip conf-${esc(r.confidence)}" title="${nf0.format(r.meta_games || 0)} partidas en este rol en Master+">${esc(r.confidence_es || "—")}</span></td>
        <td><b>${f1(r.est)}%</b></td></tr>`).join("")}</tbody>
    </table></div>`;
  el.querySelectorAll(".filters button").forEach((b) => (b.onclick = () => { POOL_ROLE = b.dataset.r; memo.pool = null; renderPool(STATE.pool); evalDefaults("pool"); }));
  el.querySelectorAll("th").forEach((th) => (th.onclick = () => {
    const key = th.dataset.k;
    POOL_SORT = { key, dir: POOL_SORT.key === key ? -POOL_SORT.dir : (key === "name" || key === "role" ? 1 : -1) };
    renderPool(STATE.pool);
  }));
}

// Silueta de la tabla de Tu pool mientras llegan los datos, con el paso real en curso.
function poolSkeleton(s) {
  const pg = s.progress || {};
  const cur = taskOf(s, pg.current);
  const line = cur ? `${cur.text}${cur.total && cur.state === "running" ? ` ${cur.done}/${cur.total}` : ""}…` : "Calculando tu pool…";
  const row = (i) => `<tr>${POOL_COLS.map(([k]) => `<td>${k === "name" ? `<div><i class="sk sq"></i><i class="sk" style="width:${70 + ((i * 37) % 50)}px"></i></div>` : `<i class="sk" style="width:${k === "est" ? 44 : 28}px"></i>`}</td>`).join("")}</tr>`;
  return `<div class="skel" aria-busy="true">
    <div class="pool-head"><div><h1>Tu pool</h1><p class="loading-dot">${esc(line)}</p></div></div>
    <div class="tablewrap"><table><thead><tr>${POOL_COLS.map(([, label]) => `<th>${label}</th>`).join("")}</tr></thead>
    <tbody>${Array.from({ length: 8 }, (_, i) => row(i)).join("")}</tbody></table></div></div>`;
}

/* ------------------------------------------------------------------ evaluar cualquier campeón */
// Buscador de Draft y Tu pool: cualquier campeón en cualquier rol, con su confianza.
// El formulario se pinta una vez; solo se repinta el resultado (el draft se repinta cada segundo).
const EVAL = { draft: { id: null, role: null, res: null, t: 0, auto: true }, pool: { id: null, role: null, res: null, t: 0, auto: true } };
let CHAMPS = [];

async function loadChampList() {
  if (CHAMPS.length) return;
  try {
    const r = await fetch("/api/champions");
    if (!r.ok) return;
    CHAMPS = await r.json();
    $("#champ-list").innerHTML = CHAMPS.map((c) => `<option value="${esc(c.name)}"></option>`).join("");
  } catch (_) {}
}

// Rol por defecto: el de tu champ select (Draft), el filtro de Tu pool o tu rol principal.
function evalDefaultRole(where) {
  const s = STATE || {};
  if (where === "pool" && ROLE_NAME[POOL_ROLE]) return POOL_ROLE;
  if (where === "draft" && s.draft && s.draft.role && ROLE_NAME[s.draft.role]) return s.draft.role;
  return (s.idle && s.idle.role) || "jungle";
}

function evalDefaults(where) {
  const e = EVAL[where];
  if (!e.auto) return;
  const role = evalDefaultRole(where);
  if (role !== e.role) { e.role = role; renderEvalForm(where); if (e.id) evalFetch(where); }
}

function renderEvalForm(where) {
  const box = $("#eval-" + where);
  const e = EVAL[where];
  if (!box.dataset.ready) {
    box.dataset.ready = "1";
    box.innerHTML = `<div class="block-head"><h3>Evaluar cualquier campeón</h3><span>${where === "draft" ? "en el rol que elijas, con el draft actual si estás en la selección" : "en el rol que elijas, a ciegas, como una fila más de tu pool"}</span></div>
      <div class="eval-form">
        <input type="search" list="champ-list" placeholder="Escribe un campeón…" aria-label="Campeón a evaluar" autocomplete="off">
        <div class="seg seg-sm evalroles" role="radiogroup" aria-label="Rol"></div>
      </div>
      <div class="eval-out"></div>`;
    const input = box.querySelector("input");
    const pick = () => {
      const c = CHAMPS.find((x) => x.name.toLowerCase() === input.value.trim().toLowerCase());
      if (c && c.id !== e.id) { e.id = c.id; e.res = null; evalFetch(where); }
      if (!input.value.trim()) { e.id = null; e.res = null; renderEvalOut(where); }
    };
    input.addEventListener("input", pick);
    input.addEventListener("change", pick);
    input.addEventListener("focus", loadChampList);
    box.addEventListener("click", (ev) => {
      const b = ev.target.closest("[data-erole]");
      if (!b) return;
      e.role = b.dataset.erole;
      e.auto = false;
      renderEvalForm(where);
      if (e.id) evalFetch(where);
    });
  }
  box.querySelector(".evalroles").innerHTML = ROLE_BTNS.map(([r, t]) => `<button data-erole="${r}" class="${e.role === r ? "on" : ""}" role="radio" aria-checked="${e.role === r}">${t}</button>`).join("");
}

async function evalFetch(where) {
  const e = EVAL[where];
  if (!e.id || !e.role) return;
  e.t = Date.now();
  const want = `${e.id}:${e.role}`;
  try {
    const r = await fetch(`/api/evaluate?id=${e.id}&role=${e.role}&view=${where}`);
    const res = await r.json();
    if (`${e.id}:${e.role}` !== want) return;  // ha cambiado mientras llegaba
    e.res = r.ok ? res : { error: res.error || "No se puede evaluar ahora" };
  } catch (_) {
    e.res = { error: "Nachero no responde" };
  }
  renderEvalOut(where);
}

function splitLine(res, where) {
  return `<div class="esplit">${(res.split || []).filter((x) => x.games > 0 || x.role === res.role_key || x.role === res.role).map((x) => {
    const on = x.role === (res.role_key || res.role);
    return `<button data-erole="${x.role}" class="${on ? "on" : ""}" title="${nf0.format(x.games)} partidas en Master+">${esc(x.role_es)} <b class="num">${f1(x.pct)} %</b>${x.category !== "main" ? ` <small>${esc({ flex: "flex", occasional: "ocasional", off: "fuera de rol" }[x.category] || "")}</small>` : ""}</button>`;
  }).join("")}</div>`;
}

function renderEvalOut(where) {
  const out = $(`#eval-${where} .eval-out`);
  const e = EVAL[where];
  if (!out) return;
  if (!e.id) { out.innerHTML = `<p class="muted">Por ejemplo Teemo en jungla o Katarina en ADC: sale su estimación aunque casi no se juegue ahí, con la confianza que dan sus partidas en ese rol.</p>`; return; }
  const res = e.res;
  if (!res) { out.innerHTML = `<p class="muted">Calculando…</p>`; return; }
  if (res.error) { out.innerHTML = `<p class="neg">${esc(res.error)}</p>`; return; }
  const p = { ...res, role: res.role_key || res.role };
  const head = `<div class="eval-head"><img src="${img("tile", res.id)}" alt=""><div><b>${esc(res.name)}</b> <span class="muted">en ${esc(ROLE_NAME[p.role] || "")}</span><div class="chips">${roleChips(p)}</div></div>
    <div class="est"><span class="num">${f1(res.est)}%</span><small>${where === "pool" ? "WR estimado a ciegas" : res.in_draft ? "WR estimado en este draft" : "WR estimado a ciegas"}</small></div></div>`;
  if (where === "pool") {
    out.innerHTML = `${head}
      <div class="parts">${[["you", "Tú con él", res.you], ["meta", "Fuerza en el parche", res.meta]].map(([, label, v]) => `<div class="part"><span>${label}</span><div class="track"><i class="${v >= 0 ? "p" : "n"}" style="width:${Math.min(50, (Math.abs(v) / 4) * 50)}%"></i></div><span class="v ${tone(v)}">${signed(v)}</span></div>`).join("")}</div>
      <p class="muted esub">${esc(subline({ ...p, recent30: 0 }))}</p>
      ${splitLine(res, where)}`;
  } else {
    out.innerHTML = `${head}${parts(res, res.ctx || {})}${matchupLine(res)}${whyList(res)}${splitLine(res, where)}`;
  }
}

// Mientras se ve el buscador, refresca el resultado (matchups que llegan, picks nuevos del draft).
function evalTick() {
  const s = STATE || {};
  const blocked = !STATE || s.loading || (!s.connected && !s.offline) || ["platform", "no_champions"].includes((s.empty || {}).draft);
  for (const where of ["draft", "pool"]) {
    $("#eval-" + where).hidden = !!blocked;
    if (VIEW !== where || blocked) continue;
    loadChampList();
    renderEvalForm(where);
    evalDefaults(where);
    const e = EVAL[where];
    if (e.id && Date.now() - e.t > (e.res && e.res.matchups_loaded === false ? 2000 : 4000)) evalFetch(where);
    if (!e.id && !$(`#eval-${where} .eval-out`).innerHTML) renderEvalOut(where);
  }
}

/* ------------------------------------------------------------------ actividad */
function renderLog(items) {
  $("#view-log").innerHTML = `<div class="log"><div class="log-head"><h1>Actividad</h1>
    <div><small id="diag-msg" role="status"></small><button class="btn" id="diag">Copiar diagnóstico</button></div></div>${items.map((l) => `<div class="log-item ${esc(l.kind)}"><time>${esc(l.t)}</time><span>${esc(l.msg)}</span></div>`).join("")}</div>`;
}

// Versión, sistema, fase, conexión, parche y log reciente, sin datos personales (lo limpia el servidor)
async function copyDiagnostics() {
  const msg = $("#diag-msg");
  try {
    const text = await (await fetch("/api/diagnostics")).text();
    try {
      await navigator.clipboard.writeText(text);
    } catch (_) {
      const ta = document.createElement("textarea");
      ta.value = text;
      document.body.appendChild(ta);
      ta.select();
      document.execCommand("copy");
      ta.remove();
    }
    msg.textContent = "Copiado: pégalo en tu mensaje";
  } catch (_) {
    msg.textContent = "No he podido copiarlo";
  }
  setTimeout(() => { if ($("#diag-msg")) $("#diag-msg").textContent = ""; }, 4000);
}
$("#view-log").addEventListener("click", (e) => { if (e.target.id === "diag") copyDiagnostics(); });

/* ------------------------------------------------------------------ ajustes */
const TOGGLES = [
  ["auto_accept", "Aceptar partida", "Con 1–3 s de retraso aleatorio."],
  ["auto_ban", "Banear", "Marca el primer ban sugerido (sin pisar los picks marcados por aliados) y confirma lo que esté marcado al final del turno. Si marcas otro, se banea el tuyo."],
  ["auto_hover_pick", "Marcar pick", "Marca tu mejor campeón y lo actualiza con el draft. Si marcas otro (en el cliente o aquí), deja de cambiarlo."],
  ["auto_lock_pick", "Confirmar pick", "Confirma lo que esté marcado al final de tu turno: tu elección o, si no tocas nada, la de Nachero."],
  ["auto_spells", "Hechizos", "Los de tu rol, al entrar en la selección."],
  ["import_runes", "Importar runas", "Al confirmar, crea la página «Nachero» con las runas de Lolalytics Master+. Nunca toca tus páginas."],
  ["open_coachless_on_lock", "Abrir Coachless", "La build del campeón confirmado, en tu navegador."],
];
const APP_TOGGLES = [
  ["close_to_tray", "Cerrar deja Nachero en la bandeja", "Sigue aceptando partidas y leyendo la selección. Para salir, clic derecho en su icono → Salir."],
  ["start_with_windows", "Abrir al iniciar Windows", "Arranca en la bandeja al iniciar sesión, sin abrir la ventana."],
];
const WEIGHTS = [
  ["pool", "Tu pool", "Experiencia, forma y resultados con cada campeón."],
  ["meta", "Fuerza en el parche", "Winrate del campeón en tu rol en Master+."],
  ["matchup", "Matchups", "Contra tu rival de línea, el resto del rival y riesgo de counter."],
  ["comp", "Composición", "Lo que le falta a tu equipo y la respuesta a la composición rival."],
];

function renderSettings(st) {
  $("#pickmode-settings").innerHTML = `
    <div class="opt"><div class="tx"><b>Base de la recomendación</b><small>${st.pick_mode === "meta"
      ? "Ignora tu pool: fuerza en el parche y encaje en el draft."
      : "Tu pool pesa junto a la fuerza en el parche y el draft (recomendado)."}</small>${modeSwitch(st.pick_mode)}</div></div>`;
  bindModeSwitch($("#pickmode-settings"));
  $("#toggles").innerHTML = TOGGLES.map(([k, t, d]) => `
    <div class="opt"><div class="tx"><b>${t}</b><small>${d}</small>
      ${k === "auto_lock_pick" ? `<div class="secs">Pick y ban, cuando queden <input id="secs" type="number" min="1" max="30" value="${st.lock_when_seconds_left}"> s</div>` : ""}</div>
      <label class="sw"><input type="checkbox" data-k="${k}" ${st[k] ? "checked" : ""} aria-label="${t}"><span></span></label></div>`).join("");
  $("#toggles").insertAdjacentHTML("beforeend", `
    <div class="opt"><div class="tx"><b>Página de runas</b><small>Cuál importar de Lolalytics Master+.</small>
      <div class="seg seg-sm runesrc" role="radiogroup" aria-label="Página de runas">
        <button data-src="pick" class="${st.runes_source !== "win" ? "on" : ""}">Más popular</button>
        <button data-src="win" class="${st.runes_source === "win" ? "on" : ""}">Mayor WR</button></div></div></div>`);
  document.querySelectorAll(".runesrc button").forEach((b) => (b.onclick = () => post("/api/settings", { runes_source: b.dataset.src })));
  document.querySelectorAll("#toggles input[type=checkbox]").forEach((i) => (i.onchange = () => post("/api/settings", { [i.dataset.k]: i.checked })));
  const secs = $("#secs");
  if (secs) secs.onchange = () => post("/api/settings", { lock_when_seconds_left: Number(secs.value) });

  $("#app-settings").innerHTML = APP_TOGGLES.map(([k, title, d]) => `
    <div class="opt"><div class="tx"><b>${title}</b><small>${d}</small></div>
      <label class="sw"><input type="checkbox" data-app="${k}" ${st[k] ? "checked" : ""} aria-label="${title}"><span></span></label></div>`).join("")
    + `<p class="drawer-note" id="app-msg" role="status"></p>`;
  document.querySelectorAll("#app-settings input").forEach((i) => (i.onchange = async () => {
    const r = await fetch("/api/settings", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ [i.dataset.app]: i.checked }) }).catch(() => null);
    if (!r || !r.ok) { i.checked = !i.checked; $("#app-msg").textContent = r ? (await r.json()).error || "No se ha podido cambiar" : "Nachero no responde"; }
    poll();
  }));

  const w = st.weights || {};
  $("#weights").innerHTML = WEIGHTS.map(([k, t, d]) => `
    <div class="weight"><label for="w-${k}">${t}<span class="num" id="wv-${k}">${f1(w[k] ?? 1)}×</span></label><small>${d}</small>
      <input type="range" id="w-${k}" min="0" max="2" step="0.1" value="${w[k] ?? 1}"></div>`).join("");
  WEIGHTS.forEach(([k]) => {
    const r = $("#w-" + k);
    r.oninput = () => ($("#wv-" + k).textContent = f1(Number(r.value)) + "×");
    r.onchange = () => post("/api/settings", { weights: { [k]: Number(r.value) } });
  });
}

function ago(ts) {
  if (!ts) return "nunca";
  const m = Math.round((Date.now() / 1000 - ts) / 60);
  return m < 1 ? "ahora mismo" : m < 60 ? `hace ${m} min` : `hace ${Math.round(m / 60)} h`;
}

function renderData(dt, why) {
  if (why && why !== "no_data") { $("#datainfo").innerHTML = emptyState(why, STATE).replace("empty-state", "empty-state small"); return; }
  if (!dt || !dt.patch) { $("#datainfo").textContent = "Cargando…"; return; }
  $("#datainfo").innerHTML = `${why ? `<p class="warn-line">${EMPTY.no_data(STATE)[1]}</p>` : ""}
    ${esc(dt.source || "Lolalytics")} · ${esc(dt.tier)} · parche ${esc(dt.patch)}<br>
    ${nf0.format(dt.games)} partidas analizadas por rol<br>
    Matchups en caché: ${dt.counters}${dt.pending ? ` · descargando ${dt.pending}` : ""}<br>
    Actualizado ${ago(dt.updated)}
    <div><button class="btn" id="refresh">Actualizar ahora</button></div>`;
  $("#refresh").onclick = () => post("/api/refresh");
}

function openDrawer(open) {
  $("#drawer").classList.toggle("open", open);
  $("#drawer").setAttribute("aria-hidden", !open);
  $("#scrim").hidden = !open;
}
$("#open-settings").onclick = () => openDrawer(true);
$("#close-settings").onclick = () => openDrawer(false);
$("#scrim").onclick = () => openDrawer(false);
document.addEventListener("keydown", (e) => { if (e.key === "Escape") openDrawer(false); });

/* ------------------------------------------------------------------ bienvenida y acerca de */
// Pasos: «Qué hace», «Cómo decide», «Qué toca y qué no» y «Y además» (en index.html).
const WELCOME = { step: 0, shown: false };
const wlSteps = () => [...document.querySelectorAll("#welcome .wl-step")];

function showStep(i) {
  const steps = wlSteps();
  WELCOME.step = Math.max(0, Math.min(steps.length - 1, i));
  steps.forEach((s, k) => (s.hidden = k !== WELCOME.step));
  $("#wl-title") && $("#wl-title").removeAttribute("id");
  steps[WELCOME.step].querySelector("h2").id = "wl-title";
  $("#wl-dots").innerHTML = steps.map((s, k) => `<button class="${k === WELCOME.step ? "on" : ""}" data-k="${k}" aria-label="Paso ${k + 1}: ${esc(s.dataset.title)}" aria-current="${k === WELCOME.step ? "step" : "false"}"></button>`).join("");
  $("#wl-dots").querySelectorAll("button").forEach((b) => (b.onclick = () => showStep(Number(b.dataset.k))));
  $("#wl-prev").disabled = WELCOME.step === 0;
  const last = WELCOME.step === steps.length - 1;
  $("#wl-next").textContent = last ? "Empezar" : "Siguiente";
}

function openWelcome() {
  WELCOME.shown = true;
  closeAbout();
  openDrawer(false);
  $("#welcome").hidden = false;
  showStep(0);
  $("#welcome .wl-card").focus();
}

// «Empezar» y «Saltar» la dan por vista. «Empezar» llevará a la configuración guiada (#4).
function closeWelcome() {
  if ($("#welcome").hidden) return;
  $("#welcome").hidden = true;
  if (STATE && STATE.settings && !STATE.settings.welcome_seen) post("/api/welcome", { seen: true });
}

function openAbout() {
  $("#about-version").textContent = (STATE && STATE.version) || "";
  $("#about-legal").textContent = $("#legal").textContent;
  $("#about").hidden = false;
  $("#about .about-card").focus();
}
function closeAbout() { $("#about").hidden = true; }

function startDemo() {
  closeWelcome();
  closeAbout();
  setView("draft");
  post("/api/demo", { on: true });
}

$("#wl-next").onclick = () => {
  if (WELCOME.step < wlSteps().length - 1) return showStep(WELCOME.step + 1);
  closeWelcome();
  openSetup(); // «Empezar» lleva a la configuración guiada
};
$("#wl-prev").onclick = () => showStep(WELCOME.step - 1);
$("#wl-skip").onclick = closeWelcome;
$("#open-about").onclick = openAbout;
$("#close-about").onclick = closeAbout;
$("#about-welcome").onclick = openWelcome;
$("#demo-exit").onclick = () => post("/api/demo", { on: false });
document.querySelectorAll("[data-demo]").forEach((b) => (b.onclick = startDemo));
$("#about").addEventListener("click", (e) => { if (e.target.id === "about") closeAbout(); });
document.addEventListener("keydown", (e) => {
  if (!$("#welcome").hidden) {
    // la misma tecla no debe llegar a la configuración guiada que abre «Empezar»
    if (["ArrowRight", "ArrowLeft", "Escape"].includes(e.key)) e.stopImmediatePropagation();
    if (e.key === "ArrowRight") { e.preventDefault(); $("#wl-next").click(); }
    else if (e.key === "ArrowLeft") { e.preventDefault(); showStep(WELCOME.step - 1); }
    else if (e.key === "Escape") closeWelcome();
  } else if (!$("#about").hidden && e.key === "Escape") closeAbout();
});

// Portada de la pantalla de espera: qué hace Nachero, en tres ideas.
const COVER = [
  ['<path d="M4 5h16v14H4z"/><path d="M9 5v14M15 5v14"/>', "Lee tu selección", "Tu rol, tu equipo y el rival, en directo."],
  ['<path d="M5 13l4 4L19 7"/>', "Recomienda picks y bans", "Con datos Master+ y tu historial."],
  ['<circle cx="12" cy="12" r="8"/><path d="M12 8v4l3 2"/>', "Prepara tus runas", "Las de Master+, al confirmar tu pick."],
];
function cover() {
  return `<div class="cover">${COVER.map(([d, b, s]) => `<div><svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round">${d}</svg><div><b>${b}</b><small>${s}</small></div></div>`).join("")}</div>
    <div class="cover-demo"><button class="btn" data-cover-demo>Probar con una partida de demo</button><span>Una selección de campeón simulada. No toca el cliente.</span></div>`;
}

/* ------------------------------------------------------------------ configuración guiada (#4) */
const SETUP_STEPS = [
  ["roles", "Tus roles", "Para recomendarte fuera de la selección y detectar cuándo vas de autofill."],
  ["practice", "Lo que practicas", "Suman puntos extra aunque aún los juegues poco."],
  ["never", "Lo que nunca juegas", "No te los recomendará en ningún rol."],
];
const SETUP = { step: 0, main: "auto", secondary: "none", practice: [], never: [], keep: {}, busy: false };

function openSetup() {
  const st = (STATE && STATE.settings) || {};
  const bonus = st.pool_bonus || {};
  SETUP.step = 0;
  SETUP.main = st.main_role || "auto";
  SETUP.secondary = st.secondary_role || "none";
  SETUP.practice = Object.keys(bonus).filter((n) => bonus[n] > 0);
  SETUP.keep = Object.fromEntries(Object.entries(bonus).filter(([, v]) => v <= 0)); // ajustes a mano: se respetan
  SETUP.never = [...(st.never_pick || [])];
  loadChampList();
  closeAbout();
  openDrawer(false);
  $("#setup").hidden = false;
  renderSetup();
  $("#setup .setup-card").focus();
}
function closeSetup() { $("#setup").hidden = true; }

function champPicker(list, key) {
  return `<div class="picker">
    <input type="search" list="champ-list" placeholder="Escribe un campeón y pulsa Intro…" aria-label="Añadir campeón" data-add="${key}" autocomplete="off">
    <div class="chips-list">${list.length ? list.map((n) => `<span class="champ-chip">${esc(n)}<button data-del="${key}" data-name="${esc(n)}" aria-label="Quitar ${esc(n)}">×</button></span>`).join("") : `<span class="muted">Ninguno</span>`}</div>
  </div>`;
}

// Sugerencias para «Lo que practicas»: tus campeones con más partidas.
function poolSuggestions() {
  const seen = new Set(SETUP.practice);
  const rows = [...((STATE && STATE.pool) || [])].filter((r) => r && r.name).sort((a, b) => (b.games || 0) - (a.games || 0));
  const out = [];
  for (const r of rows) { if (!seen.has(r.name)) { seen.add(r.name); out.push(r.name); } if (out.length >= 8) break; }
  return out;
}

function renderSetup() {
  const [key, title, sub] = SETUP_STEPS[SETUP.step];
  const auto = (STATE && STATE.idle && STATE.idle.role_es) || "";
  const prof = STATE && STATE.profile;
  let body = "";
  if (key === "roles") {
    body = `<div class="setup-field"><b>Rol principal</b>
      <div class="seg seg-sm" role="radiogroup" aria-label="Rol principal">
        <button data-main="auto" class="${SETUP.main === "auto" ? "on" : ""}">Auto${auto ? " · " + esc(auto) : ""}</button>
        ${ROLE_BTNS.map(([r, n]) => `<button data-main="${r}" class="${SETUP.main === r ? "on" : ""}">${n}</button>`).join("")}</div>
      <small>Auto: el que más juegas.</small></div>
      <div class="setup-field"><b>Rol secundario</b>
      <div class="seg seg-sm" role="radiogroup" aria-label="Rol secundario">
        <button data-sec="none" class="${SETUP.secondary === "none" ? "on" : ""}">Ninguno</button>
        ${ROLE_BTNS.filter(([r]) => r !== SETUP.main).map(([r, n]) => `<button data-sec="${r}" class="${SETUP.secondary === r ? "on" : ""}">${n}</button>`).join("")}</div></div>
      ${prof && prof.name ? `<p class="setup-note">Tu historial y tu maestría se guardan aparte para cada cuenta: ahora, <b>${esc(prof.name)}</b>.</p>` : ""}`;
  } else if (key === "practice") {
    const sug = poolSuggestions();
    body = champPicker(SETUP.practice, "practice")
      + (sug.length ? `<div class="setup-sug"><small>De tu historial:</small>${sug.map((n) => `<button class="chip-btn" data-sug="${esc(n)}">+ ${esc(n)}</button>`).join("")}</div>` : "")
      + `<p class="setup-note">Cada uno suma ${f1((STATE && STATE.settings.practice_bonus) || 1.5)} puntos a su WR estimado con tu pool.</p>`;
  } else {
    body = champPicker(SETUP.never, "never");
  }
  $("#setup-body").innerHTML = `<div class="setup-step"><h2 id="setup-title">${title}</h2><p class="setup-sub">${sub}</p>${body}</div>`;
  $("#setup-dots").innerHTML = SETUP_STEPS.map((s, k) => `<button class="${k === SETUP.step ? "on" : ""}" data-k="${k}" aria-label="Paso ${k + 1}: ${esc(s[1])}"></button>`).join("");
  $("#setup-dots").querySelectorAll("button").forEach((b) => (b.onclick = () => { SETUP.step = Number(b.dataset.k); renderSetup(); }));
  $("#setup-prev").disabled = SETUP.step === 0;
  $("#setup-next").textContent = SETUP.step === SETUP_STEPS.length - 1 ? "Guardar" : "Siguiente";
  const input = $("#setup-body input[data-add]");
  if (input) {
    const add = () => {
      if (SETUP.busy) return; // al repintar, el campo pierde el foco y vuelve a lanzar «change»
      const c = CHAMPS.find((x) => x.name.toLowerCase() === input.value.trim().toLowerCase());
      if (!c) return;
      const list = SETUP[input.dataset.add];
      if (!list.includes(c.name)) list.push(c.name);
      SETUP.busy = true;
      renderSetup();
      SETUP.busy = false;
      $("#setup-body input[data-add]").focus();
    };
    input.addEventListener("change", add);
    input.addEventListener("keydown", (e) => { if (e.key === "Enter") { e.preventDefault(); add(); } });
  }
}

$("#setup-body").addEventListener("click", (e) => {
  const b = e.target.closest("button");
  if (!b) return;
  if (b.dataset.main) { SETUP.main = b.dataset.main; if (SETUP.secondary === SETUP.main) SETUP.secondary = "none"; }
  else if (b.dataset.sec) SETUP.secondary = b.dataset.sec;
  else if (b.dataset.sug) SETUP.practice.push(b.dataset.sug);
  else if (b.dataset.del) SETUP[b.dataset.del] = SETUP[b.dataset.del].filter((n) => n !== b.dataset.name);
  else return;
  renderSetup();
});
$("#setup-prev").onclick = () => { SETUP.step = Math.max(0, SETUP.step - 1); renderSetup(); };
$("#setup-next").onclick = () => {
  if (SETUP.step < SETUP_STEPS.length - 1) { SETUP.step += 1; return renderSetup(); }
  const bonus = { ...SETUP.keep };
  const old = (STATE && STATE.settings.pool_bonus) || {};
  SETUP.practice.forEach((n) => (bonus[n] = old[n] > 0 ? old[n] : (STATE.settings.practice_bonus || 1.5)));
  closeSetup();
  post("/api/settings", { main_role: SETUP.main, secondary_role: SETUP.secondary, pool_bonus: bonus, never_pick: SETUP.never, setup_done: true });
};
$("#setup-skip").onclick = closeSetup;
document.addEventListener("keydown", (e) => {
  if ($("#setup").hidden || e.target.matches("input")) return;
  if (e.key === "Escape") closeSetup();
  else if (e.key === "ArrowRight") $("#setup-next").click();
  else if (e.key === "ArrowLeft") $("#setup-prev").click();
});

function renderProfile(st, prof) {
  const role = (r) => (ROLE_BTNS.find(([k]) => k === r) || [, "—"])[1];
  const practice = Object.keys(st.pool_bonus || {}).filter((n) => st.pool_bonus[n] > 0);
  $("#profile-settings").innerHTML = `<div class="opt"><div class="tx">
    <b>${prof && prof.name ? esc(prof.name) : prof && prof.saved ? "Última cuenta usada" : "Sin cuenta todavía"}</b>
    <small>Rol principal: ${st.main_role === "auto" || !st.main_role ? "automático" : role(st.main_role)} · secundario: ${st.secondary_role && st.secondary_role !== "none" ? role(st.secondary_role) : "ninguno"}<br>
    Practicando: ${practice.length ? practice.map(esc).join(", ") : "nadie"} · Nunca: ${(st.never_pick || []).length ? st.never_pick.map(esc).join(", ") : "nadie"}</small>
    <div><button class="btn" id="open-setup">${st.setup_done ? "Cambiar tu perfil" : "Configurar tu perfil"}</button></div></div></div>`;
  $("#open-setup").onclick = openSetup;
}

/* ------------------------------------------------------------------ bucle */
async function poll() {
  try {
    const s = await (await fetch("/api/state")).json();
    STATE = s;
    renderHeader(s);
    if (s.settings && s.settings.welcome_seen === false && !WELCOME.shown) openWelcome();
    const empty = s.empty || {};
    const pg = s.progress || {};
    once("draft", [s.draft, s.idle, { connected: s.connected, offline: s.offline, loading: s.loading, mode: s.mode,
      tasks: s.loading ? s.tasks : null, progress: s.loading ? pg : null, booting: pg.booting, active_summary: ((s.modes || {}).active || {}).summary, main_role: (s.settings || {}).main_role,
      games: s.games, phase_es: s.offline ? "Cliente cerrado" : s.phase_es, pick_mode: s.settings.pick_mode,
      empty: empty.draft, platform: s.platform }], renderDraft);
    once("pool", [s.pool, empty.pool, s.pool && s.pool.length ? null : [pg.current, taskOf(s, pg.current)]], () => renderPool(s.pool));
    once("log", s.log, renderLog);
    once("settings", s.settings, renderSettings);
    once("profile", [s.settings, s.profile], () => renderProfile(s.settings, s.profile));
    once("data", { ...s.data, updated: s.data && s.data.updated && Math.floor(s.data.updated / 60), why: empty.data }, () => renderData(s.data, empty.data));
    evalTick();
    if (VIEW === "pro" && typeof proTick === "function") proTick();
  } catch (_) {
    const conn = $("#conn");
    conn.classList.remove("ok", "seek");
    conn.querySelector("span").textContent = "Nachero no responde";
    $("#work").hidden = true;
  }
}
poll();
setInterval(poll, 1000);
