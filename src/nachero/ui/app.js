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

function renderHeader(s) {
  const conn = $("#conn");
  const noWin = s.platform && !s.platform.supported;
  conn.classList.toggle("ok", !!s.connected);
  conn.classList.toggle("off", !!s.offline);
  conn.querySelector("span").textContent = noWin && !s.connected ? "Necesita Windows" : s.loading ? "Cargando datos" : s.offline ? "Cliente cerrado" : !s.connected ? "Esperando al cliente" : s.phase_es || "Conectado";
  $("#platform").hidden = !noWin;
  if (noWin) $("#platform").textContent = `Nachero necesita Windows con el cliente de LoL abierto y estás en ${s.platform.name}: descarga nachero.exe y ábrelo en Windows.`;
  $("#rank").innerHTML = s.rank ? `<b>${esc(s.rank.tier)}</b> · ${s.rank.lp} LP · ${s.rank.w}V ${s.rank.l}D` : "";
  $("#demo").hidden = !s.demo;
  const modes = s.modes || {};
  document.querySelectorAll("#modes button").forEach((b) => {
    b.classList.toggle("on", b.dataset.mode === s.mode);
    b.setAttribute("aria-checked", b.dataset.mode === s.mode);
    const m = modes[b.dataset.mode];
    if (m) b.title = b.dataset.mode === "active" ? `${m.text} ${m.summary}` : m.text;
  });
  const cur = modes[s.mode];
  $("#mode-hint").innerHTML = cur ? `<b>${esc(cur.label)}</b> · ${esc(s.mode === "active" && !s.demo ? cur.text + " " + cur.summary : cur.text)}` : "";
  once("modes", modes, () => renderModes(modes));
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
];
const MU_PARTS = ["lane", "enemies", "risk"];

function parts(p, d) {
  const show = PART_LABELS.filter(([k]) => {
    if (k === "you") return d.mode === "pool";
    if (k === "risk") return !d.lane_known && d.enemy_left_after > 0;
    if (k === "vs_comp") return Math.abs(p.parts.vs_comp) >= 0.05;
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

function matchupLine(p) {
  if (!p.matchups_loaded) return `<div class="mus"><span class="loading-dot">Cargando matchups…</span></div>`;
  if (p.matchups.length) {
    return `<div class="mus">${p.matchups.slice(0, 5).map((m) => `<span class="${m.lane ? "lane" : ""}">${esc(m.name)} <i>${ROLE_TAG[m.role] || ""}</i> <span class="num ${tone(m.d2, 0.9)}">${signed(m.d2)}</span></span>`).join("")}</div>`;
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
  if (p.recent30 >= 2) bits.push(`${p.recent30} este mes`);
  if (p.games) bits.push(`${p.games} partidas · ${p.wr}%`);
  else if (p.exp >= 5) bits.push(`~${p.exp} partidas de maestría`);
  else bits.push("sin experiencia");
  if (p.tier) bits.push(`tier ${p.tier}`);
  return bits.join(" · ");
}

function renderDraft([d, idle, s]) {
  const el = $("#view-draft");
  if (s.empty && s.empty !== "loading") { el.innerHTML = emptyState(s.empty, s); return; }
  if (!s.connected || s.loading) {
    el.innerHTML = `<div class="loading">${s.connected ? "Cargando tu historial y las estadísticas Master+…" : "Abre el cliente de League of Legends."}</div>`;
    return;
  }
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
      ${turn ? `<div class="turn"><span>${esc(turn.msg)}</span><small>${turn.kind === "turn_auto" ? "Nachero lo confirmará al final del turno" : "hazlo tú"}</small></div>` : ""}
      ${infos.length ? `<p class="info-line">${infos.map((x) => esc(x.msg)).join(" · ")}${s.mode !== "active" ? " (modo observar)" : ""}</p>` : ""}
      ${best ? `
      <article class="hero">
        <div class="hero-art" style="background-image:url('${img("splash", best.id)}')"></div>
        <div class="hero-body">
          <div class="eyebrow">${d.locked ? "Tu pick confirmado" : "Mejor pick para " + esc(d.role_es)}${d.mode === "meta" ? " · sin tu pool" : ""}</div>
          <h1>${esc(best.name)}</h1>
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
        <p class="foot">WR estimado = 50 + suma de partes. Rival = línea + resto del rival + composición + riesgo de counter.</p>
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
}

function renderUnsupported(el, d) {
  el.innerHTML = `<div class="idle">
    <h1>${esc(d.queue || "Este modo")}: sin recomendaciones</h1>
    <p class="lead">Nachero solo recomienda en la Grieta del Invocador (draft, a ciegas, personalizadas y herramienta de práctica). En este modo no toca el cliente: ni bans, ni picks, ni hechizos, ni runas.</p>
  </div>`;
}

function renderIdle(el, idle, s) {
  const paused = s.mode === "paused";
  const picks = (idle && idle.picks) || [];
  el.innerHTML = `<div class="idle">
    <h1>${paused ? "Nachero está en pausa" : "Esperando a la selección de campeón"}</h1>
    <p class="lead">${esc(s.phase_es || "")}${paused ? "" : s.mode === "active" ? " · modo Activo. " + esc(s.active_summary || "Actuará según tus ajustes.") : " · modo Observar: solo recomienda, no acepta la partida ni toca el cliente"}</p>
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
  ["you", "Tú"], ["tier", "Tier"], ["meta", "Meta"], ["est", "Estimado"],
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
  const el = $("#view-pool");
  if (!rows || !rows.length) {
    const why = STATE && STATE.empty && STATE.empty.pool;
    el.innerHTML = why ? emptyState(why, STATE) : `<div class="loading">Calculando tu pool…</div>`;
    return;
  }
  const roles = [...new Set(rows.map((r) => r.role))];
  const list = rows.filter((r) => POOL_ROLE === "all" || r.role === POOL_ROLE).slice();
  const k = POOL_SORT.key;
  list.sort((a, b) => {
    const va = a[k] ?? -1e9, vb = b[k] ?? -1e9;
    return (typeof va === "string" ? va.localeCompare(vb) : va - vb) * POOL_SORT.dir;
  });
  el.innerHTML = `
    <div class="pool-head">
      <div><h1>Tu pool</h1><p>WR estimado a ciegas por campeón y rol: tu experiencia y resultados con él, más su fuerza en Master+ este parche.</p>${historyNote(STATE.history)}</div>
      <div class="filters"><button data-r="all" class="${POOL_ROLE === "all" ? "on" : ""}">Todos</button>${roles.map((r) => `<button data-r="${esc(r)}" class="${POOL_ROLE === r ? "on" : ""}">${esc(r)}</button>`).join("")}</div>
    </div>
    <div class="tablewrap"><table>
      <thead><tr>${POOL_COLS.map(([key, label]) => `<th data-k="${key}" class="${key === k ? "sorted" : ""}">${label}${key === k ? (POOL_SORT.dir < 0 ? " ↓" : " ↑") : ""}</th>`).join("")}</tr></thead>
      <tbody>${list.map((r) => `<tr>
        <td class="ch"><div><img src="${img("tile", r.id)}" alt="">${esc(r.name)}</div></td>
        <td class="rl">${esc(r.role)}</td>
        <td>${r.games || "—"}</td>
        <td class="${r.wr == null ? "muted" : r.wr >= 55 ? "pos" : r.wr < 45 ? "neg" : ""}">${r.wr == null ? "—" : r.wr + "%"}</td>
        <td><span class="exp"><i><b style="width:${Math.min(100, (r.exp / 150) * 100)}%"></b></i>${nf0.format(r.exp)}</span></td>
        <td class="${tone(r.you)}">${signed(r.you)}</td>
        <td><span class="tier">${esc(r.tier || "—")}</span></td>
        <td class="${tone(r.meta)}">${signed(r.meta)}</td>
        <td><b>${f1(r.est)}%</b></td></tr>`).join("")}</tbody>
    </table></div>`;
  el.querySelectorAll(".filters button").forEach((b) => (b.onclick = () => { POOL_ROLE = b.dataset.r; memo.pool = null; renderPool(STATE.pool); }));
  el.querySelectorAll("th").forEach((th) => (th.onclick = () => {
    const key = th.dataset.k;
    POOL_SORT = { key, dir: POOL_SORT.key === key ? -POOL_SORT.dir : (key === "name" || key === "role" ? 1 : -1) };
    renderPool(STATE.pool);
  }));
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
  ["auto_ban", "Banear", "El primer ban sugerido, sin pisar los picks marcados por aliados. <em>Decide por ti.</em>"],
  ["auto_hover_pick", "Marcar pick", "Deja marcado tu mejor campeón y lo actualiza con el draft. <em>Decide por ti.</em>"],
  ["auto_lock_pick", "Confirmar pick", "Confirma al final de tu turno. <em>Decide por ti; mejor desactivado en ranked.</em>"],
  ["auto_spells", "Hechizos", "Los de tu rol, al entrar en la selección."],
  ["import_runes", "Importar runas", "Al confirmar, crea la página «Nachero» con las runas de Lolalytics Master+. Nunca toca tus páginas."],
  ["open_coachless_on_lock", "Abrir Coachless", "La build del campeón confirmado, en tu navegador."],
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
      ${k === "auto_lock_pick" ? `<div class="secs">Cuando queden <input id="secs" type="number" min="1" max="30" value="${st.lock_when_seconds_left}"> s</div>` : ""}</div>
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
    Lolalytics · ${esc(dt.tier)} · parche ${esc(dt.patch)}<br>
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

/* ------------------------------------------------------------------ bucle */
async function poll() {
  try {
    const s = await (await fetch("/api/state")).json();
    STATE = s;
    renderHeader(s);
    const empty = s.empty || {};
    once("draft", [s.draft, s.idle, { connected: s.connected || s.offline, offline: s.offline, loading: s.loading, mode: s.mode, active_summary: ((s.modes || {}).active || {}).summary, main_role: (s.settings || {}).main_role,
      phase_es: s.offline ? "Cliente cerrado · datos guardados" : s.phase_es, pick_mode: s.settings.pick_mode,
      empty: empty.draft, platform: s.platform }], renderDraft);
    once("pool", [s.pool, empty.pool], () => renderPool(s.pool));
    once("log", s.log, renderLog);
    once("settings", s.settings, renderSettings);
    once("data", { ...s.data, updated: s.data && s.data.updated && Math.floor(s.data.updated / 60), why: empty.data }, () => renderData(s.data, empty.data));
  } catch (_) {
    const conn = $("#conn");
    conn.classList.remove("ok");
    conn.querySelector("span").textContent = "Nachero no responde";
  }
}
poll();
setInterval(poll, 1000);
