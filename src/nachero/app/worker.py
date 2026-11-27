"""Bucle principal: conecta con el cliente (o trabaja sin el), carga datos y sigue cada fase."""

import contextlib
import random
import re
import threading
import time
from pathlib import Path

from nachero import paths
from nachero.app.demo import Demo
from nachero.app.draft import Draft
from nachero.app.runes import RuneImporter
from nachero.app.state import APP, CTX, LOCK, OPTS, PHASE_ES, TASKS, Repeats, demo_must_stop, log, log_error, set_demo
from nachero.app.trace import Trace
from nachero.clients.cdragon import CDragon, latest_patch
from nachero.clients.lcu import LCU
from nachero.config import BUILD_TIERS, CFG, LEAGUE_NAMES
from nachero.domain import blind as BL
from nachero.domain import calibration
from nachero.domain import ingame as IG
from nachero.domain import pool as POOL
from nachero.domain import roles as R
from nachero.domain.common import ROLE_ES, ROLES
from nachero.domain.common import tier_name as TIER
from nachero.domain.engine import Engine
from nachero.domain.player import Player
from nachero.domain.pro import ProEngine
from nachero.domain.queues import classify, has_bans
from nachero.domain.stats import ChainStats, source_of
from nachero.jsonio import read_json, write_json
from nachero.sources.champions import Champs
from nachero.sources.golgg import GolGG
from nachero.sources.history import load_history, role_of, valid_games
from nachero.sources.items import Items
from nachero.sources.local_stats import LocalStats
from nachero.sources.lolalytics import Lolalytics
from nachero.sources.remote_stats import RemoteStats


def pool_row(engine, champs, cid, role):
    """Fila de Tu pool: tú con el campeón y su fuerza en el rol, con su rol y confianza. El
    estimado es el del motor a ciegas (sin draft, con el riesgo de counter si eliges primero, tus
    puntos extra y tu estilo): el mismo número que en la pantalla de espera y en la recomendación."""
    you = engine.player.components(cid, role)
    meta, tr = engine.meta(cid, role)
    est = engine.roles.estimate(cid, role)
    blind = engine.evaluate(cid, role)
    return {
        "id": cid,
        "name": champs.name(cid),
        "role": ROLE_ES.get(role, role),
        "role_key": role,
        "games": you["games"],
        "wr": round(100 * you["wins"] / you["games"]) if you["games"] else None,
        "exp": round(you["exp_games"]),
        "mastery": you["mastery"],
        "you": round(you["total"], 1),
        "meta": round(meta, 1),
        "tier": TIER(tr) if est["games"] else None,
        "meta_wr": tr["wr"] if tr and est["games"] else None,
        "meta_games": est["games"],
        "role_pct": round(est["pct"], 1),
        "role_cat": est["category"],
        "role_cat_es": est["category_es"],
        "confidence": est["confidence"],
        "confidence_es": est["confidence_es"],
        "roles_label": engine.roles.label(cid),
        "est": blind["est"],
        "risk": blind["parts"].get("risk", 0.0),
        "blind": engine.blind_summary(cid, role),  # seguro a ciegas o de counter (#75)
    }


def pool_rows(engine, champs):
    """Tus campeones por rol: lo jugado (2+ partidas, o 1 en tu rol principal) y, con maestría alta,
    los roles principal y flex del campeón aunque no sean el tuyo."""
    p, main = engine.player, engine.main_role()
    keys = {(c, r) for (c, r), gs in p.by_cr.items() if len(gs) >= 2 or r == main}
    for cid, m in p.mastery.items():
        if m.get("championPoints", 0) >= 80000:
            keys |= {(cid, r) for r in engine.roles.roles(cid, "flex")}
    rows = [pool_row(engine, champs, cid, role) for cid, role in keys]
    for r in rows:
        if r["blind"] is None:  # pide sus matchups en segundo plano (caché por parche)
            engine.lola.matchups(r["id"], r["role_key"])
    return sorted(rows, key=lambda r: -r["est"])


def pool_plans(engine, champs, rows) -> dict:
    """Plan de Tu pool (#75) en tu rol principal y en el secundario: seguros a ciegas, de counter,
    tamaño de tu pool (regla del 80 %) y, si no tienes ningún pick seguro, candidatos del parche."""
    p = engine.player
    roles = [engine.main_role()]
    second = engine.cfg.get("secondary_role")
    if second in ROLES and second not in roles:
        roles.append(second)
    never = {champs.id(n) for n in engine.cfg.get("never_pick", [])}
    th = engine.bl
    out = {}
    for role in roles:
        mine = [r for r in rows if r["role_key"] == role]
        have = {r["id"] for r in mine}
        games = [len(gs) for (c, r), gs in p.by_cr.items() if r == role]
        # maestría de los campeones que se juegan en este rol (la regla del 80 % es por rol)
        mastery = [
            m.get("championPoints", 0)
            for cid, m in p.mastery.items()
            if R.at_least(engine.roles.category(cid, role), "flex")
        ]
        plan = POOL.plan(mine, role, th, mastery, games)
        if "safe" in plan["missing"]:
            sugg = []
            for cid in engine.strong(role, 12):
                if cid in have or cid in never:
                    continue
                b = engine.blind_summary(cid, role)
                if b is None:
                    engine.lola.matchups(cid, role)  # en segundo plano: estará en la próxima vuelta
                elif b["label"] == "safe":
                    sugg.append({"id": cid, "name": champs.name(cid), "p_pool": b["p_pool"],
                                 "meta": round(engine.meta(cid, role)[0], 1)})  # fmt: skip
            plan = POOL.plan(mine, role, th, mastery, games, sugg)
        out[role] = plan
    return out


def evaluate(engine, champs, cid, role, view="draft", draft_ctx=None):
    """Buscador «Evaluar cualquier campeón»: su estimación en ese rol, con su confianza.

    En Tu pool, como una fila más (a ciegas). En Draft, con el draft actual si estás en la champ
    select (`draft_ctx` de `Draft.context`) o a ciegas si no."""
    if view == "pool":
        row = pool_row(engine, champs, cid, role)
        row["split"] = engine.roles.describe(cid)
        return row
    ctx = draft_ctx or {}
    return engine.evaluate(
        cid,
        role,
        allies=ctx.get("allies", ()),
        enemy_ids=ctx.get("enemy_ids", ()),
        enemy_left_after=ctx.get("enemy_left_after", 5),
        unavailable=ctx.get("unavailable", ()),
        ally_roles=ctx.get("ally_roles"),
    )


STALE_HOURS = 24  # tier lists más viejas que esto: el panel avisa


def source_warnings(*sources) -> list[dict]:
    """Avisos de las fuentes cuyo lector ya no encuentra datos (ver sources/health.py)."""
    out = []
    for s in sources:
        for p in getattr(s, "providers", [s]):
            h = getattr(p, "health", None)
            if h is not None:
                out += h.warnings()
    return out


def save_record(rec: dict, patch=None) -> None:
    """Guarda un pick confirmado para la calibración (en el perfil de la cuenta)."""
    recs = read_json(paths.predictions_file(), [])
    recs = recs if isinstance(recs, list) else []
    recs.append({**rec, "patch": rec.get("patch") or patch})
    write_json(paths.predictions_file(), recs[-2000:])


def resolve_records(games) -> int:
    """Apunta el resultado de los picks guardados que ya están en el historial."""
    recs = read_json(paths.predictions_file(), [])
    if not isinstance(recs, list) or not recs:
        return 0
    recs, done = calibration.resolve(recs, games, time.time() * 1000)
    write_json(paths.predictions_file(), recs)
    return done


def game_players(detail) -> list[dict]:
    """Campeón, equipo y posición de cada jugador del detalle de una partida del cliente
    (`/lol-match-history/v1/games/{id}`). Sin nombres: solo lo público al acabar la partida."""
    out = []
    for p in (detail or {}).get("participants") or []:
        if isinstance(p, dict) and p.get("championId"):
            out.append({"team": p.get("teamId"), "champ": p["championId"], "role": role_of(p)})
    return out


def lane_d2(engine):
    """`d2` posterior de tu campeón contra tu rival de línea (caché de matchups; None sin datos)."""

    def fn(cid, role, opp):
        lanes = engine.lola.matchups(cid, role, fetch=False) or {}
        row = lanes.get(role, {}).get(str(opp))
        if not row:
            return None
        return BL.posterior(row["d2"], row["n"], engine.sigma(cid, role, role, lanes), row.get("wr"))[0]

    return fn


def enrich_records(lcu, engine, limit=5) -> int:
    """Posición real de los rivales en las partidas ya resueltas (#71): con eso se sabe quién era tu
    rival de línea, si eligió después de ti y si te counteó. Como mucho `limit` por vez."""
    recs = read_json(paths.predictions_file(), [])
    if not isinstance(recs, list):
        return 0
    todo = [i for i, r in enumerate(recs) if r.get("gameId") and "enemy_roles" not in r][-limit:]
    th = engine.bl
    for i in todo:
        detail = lcu.get(f"/lol-match-history/v1/games/{recs[i]['gameId']}", timeout=20)
        players = game_players(detail)
        if players:
            recs[i] = calibration.enrich(recs[i], players, lane_d2(engine), th["threshold"])
    if todo:
        write_json(paths.predictions_file(), recs)
    return len(todo)


def enrich_quiet(lcu, engine) -> None:
    """`enrich_records` en segundo plano al arrancar: un fallo no importa (se reintenta al acabar
    la próxima partida)."""
    try:
        enrich_records(lcu, engine)
    except Exception as e:
        log(f"Calibración: no pude leer el detalle de una partida ({e.__class__.__name__})", "warn")


def data_status(lola, patch, gol_src=None, now=None):
    """Estado de los datos para el panel: fuente, frescura y avisos."""
    now = time.time() if now is None else now
    st = lola.stats()
    updated = lola.updated_at()
    data_patch = getattr(lola, "patch", None)
    stale = bool(updated and now - updated > STALE_HOURS * 3600) or bool(patch and data_patch and data_patch != patch)
    return {
        "patch": patch,
        "updated": updated,
        "games": st.get("games", 0),
        "counters": st.get("builds", 0),
        "pending": len(lola.pending),
        "tier": stats_league_name(lola),
        "source": source_of(lola),
        "stale": stale,
        "warnings": source_warnings(lola, gol_src),
        "pro": gol_src.updated() if gol_src is not None else None,
        "fallback": fallback_note(lola, patch),
    }


def stats_league_name(lola) -> str:
    """Liga de las tier lists que se usan (para el panel): la de los datos propios si mandan ellos;
    Lolalytics da la fuerza en el parche en Master+."""
    for p in getattr(lola, "providers", None) or [lola]:
        tier = getattr(p, "tier", None)
        if tier and any(tier(r) for r in ROLES):
            league = p.data.get("league") if isinstance(p, LocalStats) else None
            return LEAGUE_NAMES.get(league or "", "Master+")
    return "Master+"


def fallback_note(lola, patch) -> str | None:
    """Si hay datos propios configurados pero no del parche, qué se usa en su lugar (para el panel)."""
    providers = getattr(lola, "providers", None)
    if not providers or not patch:
        return None
    own = providers[0]
    if own.name == "Lolalytics" or own.roles_ready(patch) >= 5:
        return None
    return f"Sin datos propios del parche {patch}: uso {source_of(lola)}"


SOURCES = ("lolalytics", "local", "remote")
DEFAULT_SOURCES = ["lolalytics"]


def source_names() -> list[str]:
    """Fuentes en orden según `stats_mode` (automática, propia o Lolalytics). Si `stats_sources`
    se ha cambiado a mano (avanzado), manda eso."""
    custom = [s for s in CFG.get("stats_sources") or [] if s in SOURCES]
    if custom and custom != DEFAULT_SOURCES:
        return custom
    mode = CFG.get("stats_mode", "auto")
    own = ["remote"] if CFG.get("stats_url") else (["local"] if stats_file().exists() else [])
    if mode == "lolalytics":
        return ["lolalytics"]
    if mode == "own":
        return own or ["local"]
    return own + ["lolalytics"]


def stats_file() -> Path:
    custom = CFG.get("stats_file") or ""
    return Path(custom) if custom else paths.user_dir() / "stats" / "nachero-stats.json"


def own_league() -> str:
    """Liga de los datos propios: `build_tier`, la misma que la de las páginas de build de Lolalytics."""
    tier = CFG.get("build_tier")
    return tier if tier in BUILD_TIERS else "emerald_plus"


def build_stats(champs):
    """Fuentes de estadísticas según `stats_sources` (ver domain/stats.py). Sin ninguna válida,
    Lolalytics, como siempre."""
    names = source_names()
    providers = []
    # la liga de los datos propios es la de los matchups (`build_tier`, Esmeralda+ por defecto): la
    # muestra con volumen para matchups y sinergias (#86)
    region, league = CFG.get("stats_region", "euw1"), own_league()
    for name in dict.fromkeys(names):
        if name == "lolalytics":
            lola = Lolalytics(str(paths.cache_dir()), log, build_tier=CFG.get("build_tier"))
            lola.slug_fallback = champs.slug
            providers.append(lola)
        elif name == "remote":
            providers.append(RemoteStats(CFG.get("stats_url", ""), paths.cache_dir() / "stats", log, region, league))
        else:
            providers.append(LocalStats(stats_file(), log, region, league))
    if len(providers) == 1:
        return providers[0]
    log("Estadísticas: " + " → ".join(p.name for p in providers), "info")
    return ChainStats(providers)


def fallback_patch():
    """Parche actual sin cliente: Data Dragon o CommunityDragon, con caché."""
    return latest_patch(paths.cache_dir() / "patch.json")


def current_patch(lcu, games, fallback=fallback_patch):
    """Parche del cliente; si no lo da, el de tu última partida y, si no hay, el de internet."""
    try:
        v = lcu.get("/lol-patch/v1/game-version")
    except Exception:
        v = None
    if isinstance(v, str) and re.match(r"\d+\.\d+", v):
        return ".".join(v.split(".")[:2])
    return games[0]["patch"] if games else fallback()


def offline_patch(games, fallback=fallback_patch):
    """Sin cliente: el parche de internet (tu última partida puede ser de un parche viejo)."""
    return fallback() or (games[0]["patch"] if games else None)


QUEUE_LOG = {
    "draft": ("Cola: {name}", "info"),
    "blind": ("Cola: {name} · sin bans, recomiendo para tu rol principal", "info"),
    "other": ("{name}: Nachero solo recomienda en la Grieta del Invocador; no toco nada", "hint"),
    "unknown": ("No he podido leer el tipo de cola: recomiendo como en la Grieta", "warn"),
}


SLOW_TICK = 3.0  # s: un análisis de la champ select más lento que esto se apunta en el registro


def queue_message(queue: dict, session: dict | None) -> tuple[str, str]:
    """Mensaje del registro para la cola: una personalizada con bans se trata como un draft."""
    if queue["kind"] == "blind" and has_bans(session or {}):
        return f"Cola: {queue['name']} · con bans, recomiendo como en un draft", "info"
    msg, kind = QUEUE_LOG[queue["kind"]]
    return msg.format(name=queue["name"]), kind


def read_queue(lcu):
    """Tipo de cola de la partida actual (`domain.queues.classify`), o None si el cliente no responde."""
    try:
        flow = lcu.get("/lol-gameflow/v1/session", timeout=10)
    except Exception:
        return None
    return classify(flow) if isinstance(flow, dict) else None


def champ_select_view(draft, s, acting, queue):
    """Lo que muestra el panel en la champ select: fuera de la Grieta, solo el aviso (sin actuar).
    En ARAM, además, las runas de ARAM del campeón que te toque."""
    if queue["kind"] == "other":
        out = {"unsupported": True, "queue": queue["name"]}
        if queue.get("aram") and s:
            out["aram"] = draft.aram_tick(s, acting)
        return out
    return draft.tick(s, acting, queue=queue) if s else None


def turn_notice(d: dict | None, seen: set) -> tuple[str, str] | None:
    """Aviso de la bandeja (`tray_notify`) en la champ select: al empezar, con la recomendación, y al
    llegar tu turno de ban o de pick. Uno de cada por selección (`seen` lo recuerda)."""
    if not d or d.get("unsupported") or not d.get("hero") or d.get("locked"):
        return None
    hero = d["hero"]
    rec = f"{hero['name']} · {hero['est']:.1f} % WR estimado".replace(".", ",")
    turn = d.get("my_turn")
    if turn == "ban" and "ban" not in seen and d.get("ban_suggestions"):
        seen.update({"start", "ban"})
        return "Te toca banear", f"Nachero recomienda banear {d['ban_suggestions'][0]['name']}"
    if turn == "pick" and "pick" not in seen:
        seen.update({"start", "pick"})
        return "Te toca elegir", f"Nachero recomienda {rec}"
    if "start" not in seen:
        seen.add("start")
        return "Selección de campeón", f"Nachero recomienda {rec}"
    return None


IN_GAME = ("GameStart", "InProgress", "Reconnect")  # pantalla de carga y partida en curso
GAME_REFRESH = 5  # s entre recálculos de la vista «En partida» mientras faltan matchups o la build


def game_view(engine, champs, items, flow, champ_select=None, puuid=None, role=None) -> dict | None:
    """Vista «En partida» (#88): drafts, puntuación de cada campeón y equipo, y tu build.

    `flow`: `/lol-gameflow/v1/session`; `champ_select`: la última sesión de champ select (de esta
    partida); `role`: el tuyo si la champ select no lo dio (a ciegas). Fuera de la Grieta, None."""
    queue = classify(flow) if isinstance(flow, dict) else classify(None)
    if queue["kind"] == "other":
        return None
    game = IG.parse_game(flow, puuid, champ_select)
    if not game or not game["ally"]:
        return None
    rep = IG.report(engine, champs, game, role or engine.main_role())
    me, my_role = rep["me"], rep["my_role"]
    build, coach = None, None
    if me:
        fn = getattr(engine.lola, "build", None)
        raw = fn(me["id"], my_role) if callable(fn) else None
        build = IG.build_view(raw, items, CFG.get("runes_source", "pick"))
        if build:
            build["spells"] = [items.brief(s, "spell") for s in build["spells"]]
        rep["build_pending"] = raw is None and callable(fn)
        # Coachless: solo el enlace (sus condiciones no permiten leer sus datos)
        coach = f"https://coachless.gg/builds/{champs.slug(me['id'])}?role={my_role}"
    for team in (rep["ally"], rep["enemy"]):
        for p in team:
            p["spells"] = [items.brief(s, "spell") for s in p["spells"]]
    # sin el catálogo todavía, los nombres son números: se vuelve a calcular en unos segundos
    names = items.ready() if hasattr(items, "ready") else True
    # sin la ficha de algún campeón (Nachero abierto a mitad de partida), la composición sale con la
    # neutra (daño mixto): igual
    ids = [p["id"] for p in game["ally"] + game["enemy"]]
    cards = champs.ready(ids) if hasattr(champs, "ready") else True
    return {
        **rep,
        "build": build,
        "coachless": coach,
        "queue": queue.get("name", ""),
        "names_ready": names,
        "cards_ready": cards,
    }


# ---------------------------------------------------------------- bucle principal
_GOL = None


def gol():
    """Fuente de gol.gg compartida (no depende de la sesion con el cliente)."""
    global _GOL
    if _GOL is None:
        _GOL = GolGG(str(paths.cache_dir()), log)
    return _GOL


class Restart(Exception):
    """Reinicia la sesion (p. ej. al abrirse o cerrarse el cliente)."""


class NoPhase(Exception):
    """El cliente responde sin fase (error o respuesta vacía): cuenta como un fallo de lectura. Si
    pasara a «Sin cliente», al volver a la champ select se borraría lo que lleva marcado Nachero y
    su propia marca parecería del jugador."""


def worker():
    while True:
        try:
            run_session()
        except Restart as e:
            log(str(e), "ok")
        except Exception as e:
            log_error(f"Reiniciando tras un error ({e.__class__.__name__}: {e})", e)
            time.sleep(3)


HISTORY_BUSY = threading.Lock()  # una sola lectura del historial a la vez


def refresh_history(lcu, engine) -> bool:
    """Al acabar una partida: historial, «¿Acierta Nachero?» y tu modelo personal. Va en segundo
    plano: el historial puede tardar más de un minuto y, si el cliente falla, antes se reiniciaba
    toda la sesión. Si ya se está leyendo, no hace nada (False)."""
    if not HISTORY_BUSY.acquire(blocking=False):
        return False
    try:
        TASKS.start("history", detail="Partida nueva: actualizando…")
        games = load_history(
            lcu, str(paths.history_file()), CFG["history_queues"], log, str(paths.history_import_file())
        )
        TASKS.finish("history", f"{len(games)} partidas de la Grieta")
        with contextlib.suppress(Exception):
            if resolve_records(games):
                log("Partida apuntada en «¿Acierta Nachero?»", "ok")
            enrich_records(lcu, engine)
        mastery = lcu.get("/lol-champion-mastery/v1/local-player/champion-mastery", timeout=20)
        if not isinstance(mastery, list):  # sin respuesta: la que ya tenía
            mastery = list(engine.player.mastery.values())
        engine.player = player = Player(games, mastery)
        with LOCK:
            APP["history"] = player.history_summary(APP.get("rank"))
            APP["games"] = len(player.games)
            APP["refresh_idle"] = True  # Tu pool, con la partida nueva
        return True
    except Exception as e:
        TASKS.fail("history", f"No he podido leer el historial ({e.__class__.__name__})")
        log_error(f"No he podido actualizar el historial ({e.__class__.__name__}: {e})", e)
        return False
    finally:
        HISTORY_BUSY.release()


def client_ready(lcu):
    return lcu.connect() and isinstance(lcu.get("/lol-gameflow/v1/gameflow-phase"), str)


def find_client(lcu, tries=3):
    """Busca el cliente varias veces (tarda en responder al abrirse); lo cuenta en la tarea `client`."""
    TASKS.start("client", detail="Buscando…")
    for i in range(tries):
        if i:
            TASKS.step("client", 0, detail=f"Buscando… (intento {i + 1} de {tries})")
        try:
            if client_ready(lcu):
                return True
        except Exception:
            pass
        if i < tries - 1:
            time.sleep(2)
    return False


def refresh_tiers(lola, patch, force=False):
    """Tier lists de la fuente de estadísticas (n/5 roles) con su tarea; si falta alguna, se reintenta sola."""
    TASKS.start("tiers", total=5, detail=f"Parche {patch}")
    ready = lola.refresh_tiers(patch, force=force, progress=lambda n, total: TASKS.step("tiers", n, total))
    if ready >= 5:
        TASKS.finish("tiers", f"Parche {patch} · 5 roles")
        if force:
            log("Estadísticas Master+ actualizadas", "ok")
    else:
        TASKS.fail(
            "tiers", f"{source_of(lola)} no responde: {ready} de 5 roles. Reintento en 2 min", retry_in=TIERS_RETRY
        )
    return ready


TIERS_RETRY = 120


def load_tournament(name):
    """Torneo de gol.gg para el simulador pro (n/6 páginas), con su tarea."""
    TASKS.start("golgg", f"Torneo pro · {name}", total=6)
    gol().load(name, progress=lambda n, total: TASKS.step("golgg", n, total))
    if gol().dataset(name):
        TASKS.finish("golgg", f"{gol().dataset(name).get('games', 0)} partidas")
    else:
        TASKS.fail("golgg", f"gol.gg no responde ({name}): pruébalo otra vez en un rato")


def open_profile(lcu):
    """Usa los datos de la cuenta conectada (o, sin cliente, los de la última). Sin datos
    personales en el registro: ni nombre ni puuid."""
    me = lcu.get("/lol-summoner/v1/current-summoner", timeout=10) if lcu else None
    me = me if isinstance(me, dict) else {}
    pid = me.get("puuid")
    moved = paths.use_profile(pid or paths.last_profile())
    if moved:
        log("Tu historial y tu maestría pasan al perfil de esta cuenta", "ok")
    name, tag = me.get("gameName") or me.get("displayName"), me.get("tagLine")
    with LOCK:
        if pid:
            APP["profile"] = {"name": f"{name}#{tag}" if name and tag else name or "", "saved": False}
        elif paths.profile_id():
            APP["profile"] = {"name": "", "saved": True}  # sin cliente: la última cuenta
        else:
            APP["profile"] = None
    return paths.profile_id()


def run_session():
    TASKS.plan()
    lcu = LCU()
    online = find_client(lcu)
    with LOCK:  # el panel deja de decir «Abre el cliente» en cuanto lo encuentra
        APP["connected"], APP["offline"] = online, not online
    if online:
        TASKS.finish("client", "Conectado")
    else:
        TASKS.skip("client", "Cerrado: sigo sin él")
    open_profile(lcu if online else None)
    pcache = read_json(paths.player_file(), {})
    pcache = pcache if isinstance(pcache, dict) else {}  # roto: se vuelve a escribir al conectar
    if online:
        TASKS.start("history", detail="Leyendo tus últimas 200 partidas…")
        games = load_history(
            lcu, str(paths.history_file()), CFG["history_queues"], log, str(paths.history_import_file())
        )
        TASKS.finish("history", f"{len(games)} partidas de la Grieta")
        TASKS.start("mastery", detail="Leyendo…")
        mastery = lcu.get("/lol-champion-mastery/v1/local-player/champion-mastery", timeout=20) or pcache.get(
            "mastery", []
        )
        qs = (lcu.get("/lol-ranked/v1/current-ranked-stats") or {}).get("queues", [])
        rk = next((q for q in qs if q.get("queueType") == "RANKED_SOLO_5x5"), {})
        rank = None
        if rk.get("tier") and rk["tier"] != "NONE":
            div = "" if rk["tier"] in ("MASTER", "GRANDMASTER", "CHALLENGER") else " " + rk.get("division", "")
            rank = {
                "tier": rk["tier"].title() + div,
                "lp": rk.get("leaguePoints", 0),
                "w": rk.get("wins", 0),
                "l": rk.get("losses", 0),
            }
        write_json(paths.player_file(), {"mastery": mastery, "rank": rank, "t": time.time()})
        TASKS.finish("mastery", f"{len(mastery)} campeones" + (f" · {rank['tier']}" if rank else ""))
        with LOCK:
            APP["rank"] = rank
    else:
        games = valid_games(read_json(paths.history_file(), []))
        mastery, rank = pcache.get("mastery", []), pcache.get("rank")
        mastery = mastery if isinstance(mastery, list) else []
        rank = rank if isinstance(rank, dict) else None
        TASKS.finish("history", f"{len(games)} partidas guardadas" if games else "Sin partidas guardadas")
        TASKS.finish("mastery", "Guardada" if mastery else "Sin datos guardados")
    src = lcu if online else CDragon()
    TASKS.start("champions", detail="Del cliente" if online else "De CommunityDragon")
    champs = Champs(src)
    champs.preload()  # fichas en segundo plano: el bucle no espera al cliente por ellas
    if not champs.by_id:
        with LOCK:
            APP["issue"] = "no_champions"
        TASKS.fail("champions", "Sin cliente ni CommunityDragon. Reintento en 10 s", retry_in=10)
        time.sleep(10)
        raise Restart("Sin datos de campeones (ni cliente ni CommunityDragon); reintento…")
    with LOCK:
        APP["issue"] = None
    patch = current_patch(lcu, games) if online else offline_patch(games)
    TASKS.finish("champions", f"{len(champs.by_id)} campeones" + (f" · parche {patch}" if patch else ""))
    if online:
        log("Conectado al cliente de LoL" + (" · modo demo" if OPTS["demo"] else ""), "ok")
    else:
        log(
            "Cliente de LoL cerrado: uso datos guardados y CommunityDragon" + (" · modo demo" if OPTS["demo"] else ""),
            "warn",
        )
    with contextlib.suppress(Exception):
        resolve_records(games)
    player = Player(games, mastery)
    lola = build_stats(champs)
    if patch:
        log(f"Leyendo estadísticas Master+ del parche {patch}…")
        refresh_tiers(lola, patch)
    else:
        TASKS.fail("tiers", "No sé cuál es el parche actual (sin cliente ni internet)")
        log("No sé cuál es el parche actual (sin cliente ni internet): sin estadísticas Master+", "warn")
    engine = Engine(champs, lola, player, CFG)
    CTX.update(
        lcu=lcu,
        src=src,
        champs=champs,
        lola=lola,
        engine=engine,
        patch=patch,
        pro=ProEngine(champs, lola, engine, gol()),
    )
    if online:  # posición real de los rivales en las partidas resueltas que aún no la tienen (#71)
        threading.Thread(target=enrich_quiet, args=(lcu, engine), daemon=True).start()
    TASKS.start("picks", detail="Calculando tu pool y tus mejores picks…")
    main = engine.main_role()
    for r in engine.picks(main, set(), set(), [], [])[0][:10]:
        lola.request(r["id"], main, champs.slug(r["id"]))
    TASKS.finish("picks", f"Rol principal {ROLE_ES[main]}")
    with LOCK:
        APP["connected"], APP["offline"], APP["rank"], APP["loading"] = online, not online, rank, False
        APP["pool"], APP["refresh_idle"] = [], True
        APP["history"] = player.history_summary(rank)
        APP["games"], APP["patch"] = len(player.games), patch
    roles = ", ".join(f"{ROLE_ES[r]} {n}" for r, n in sorted(player.role_games.items(), key=lambda x: -x[1]))
    log(f"Listo · rol principal {ROLE_ES[main]} · {len(player.games)} partidas analizadas ({roles or 'ninguna'})", "ok")

    runes = RuneImporter(src)
    runes.preload()  # catálogo de runas en segundo plano: el bucle no lo espera
    draft = Draft(lcu, champs, engine, runes)
    draft.trace = Trace(paths.log_dir() / "selecciones")  # diagnóstico de cada selección real
    CTX["draft"] = draft  # el buscador del panel evalúa con el draft actual
    items = CTX["items"] = Items(src)  # objetos y hechizos de la vista «En partida»
    items.preload()
    last_cs, last_game = None, 0.0  # última champ select real (para «En partida») y su último cálculo
    demo = None  # se crea al abrir la demo (por --demo o desde el panel)
    last_phase, accepted_at, last_idle, last_demo_step, last_probe = "-", 0, 0, -1, time.time()
    last_tiers = time.time()
    fails = 0  # fallos seguidos al leer la fase: el cliente a veces tarda mas de 5 s
    queue, queue_tries, queue_logged = None, 0, False  # tipo de cola de la champ select actual
    failures = Repeats()  # un fallo que se repite cada segundo se apunta una vez
    notified: set = set()  # avisos de la bandeja ya dados en esta champ select
    last_slow = 0.0  # último aviso de «Selección lenta» (uno cada 30 s como mucho)
    while True:
        mode = APP["mode"]
        if not online:
            if time.time() - last_probe > 10:
                last_probe = time.time()
                if client_ready(LCU()):
                    raise Restart("Cliente de LoL detectado: me conecto")
                if not patch and fallback_patch():
                    raise Restart("Parche actual encontrado: cargo las estadísticas")
            phase = "ChampSelect" if OPTS["demo"] else None
        else:
            try:
                real = lcu.get("/lol-gameflow/v1/gameflow-phase", timeout=10)
                if not isinstance(real, str):
                    raise NoPhase("sin fase")
                if demo_must_stop(real):
                    set_demo(False)
                    log("Demo cerrada: empieza tu partida de verdad", "ok")
                phase = "ChampSelect" if OPTS["demo"] else real
                fails = 0
            except Exception as e:
                fails += 1
                if fails < 4:
                    log(f"El cliente no responde ({e.__class__.__name__}); reintento…", "warn")
                    time.sleep(1)
                    continue
                with LOCK:
                    APP["connected"], APP["phase"] = False, None
                raise Restart("Cliente desconectado") from None
        if phase != last_phase:
            log(f"Fase: {PHASE_ES.get(phase, phase)}")
            if phase == "ChampSelect":
                draft.reset()
                notified = set()
                queue, queue_tries, queue_logged = None, 0, False
                last_cs = None
            if phase in ("EndOfGame", "PreEndOfGame") and online and not OPTS["demo"]:
                threading.Thread(target=refresh_history, args=(lcu, engine), daemon=True).start()
            if phase != "ChampSelect":
                with LOCK:
                    APP["draft"] = None
            if phase not in IN_GAME:
                with LOCK:
                    APP["game"] = None
            last_game = 0.0
            last_phase = phase
        with LOCK:
            APP["phase"] = phase
            APP["data"] = data_status(lola, patch, gol())
        TASKS.queue("matchups", "Matchups y runas", len(lola.pending))
        if patch and (TASKS.retry_due("tiers") or time.time() - last_tiers > 3600):
            last_tiers = time.time()  # cada hora: datos propios nuevos (ETag) o tier lists caducadas
            threading.Thread(target=refresh_tiers, args=(lola, patch), daemon=True).start()
        if APP.pop("restart_session", False):
            raise Restart("Fuente de estadísticas cambiada: vuelvo a cargar los datos")

        if (time.time() - last_idle > 20 or APP.get("refresh_idle")) and phase != "ChampSelect":
            last_idle = time.time()
            APP["refresh_idle"] = False
            main = engine.main_role()
            picks = engine.picks(main, set(), set(), [], [])[0][:5]
            for p in picks:
                lola.matchups(p["id"], main)  # deja listos sus matchups y runas
            with LOCK:
                APP["idle"] = {
                    "role": main,
                    "role_es": ROLE_ES[main],
                    "auto": CFG.get("main_role", "auto") not in ROLES,
                    "picks": picks,
                }
                APP["pool"] = pool_rows(engine, champs)
                APP["pool_plans"] = draft.pool_plans = pool_plans(engine, champs, APP["pool"])
        if not APP["pool"]:
            with LOCK:
                APP["pool"] = pool_rows(engine, champs)
                APP["pool_plans"] = draft.pool_plans = pool_plans(engine, champs, APP["pool"])

        if mode != "paused" or OPTS["demo"]:  # la demo no toca el cliente: se ve también en pausa
            acting = mode == "active" and not OPTS["demo"]
            try:
                if phase == "ReadyCheck" and CFG["auto_accept"] and time.time() - accepted_at > 10:
                    rc = lcu.get("/lol-matchmaking/v1/ready-check") or {}
                    if rc.get("playerResponse") == "None":
                        if acting:
                            time.sleep(random.uniform(*CFG["accept_delay_seconds"]))
                            lcu.req("POST", "/lol-matchmaking/v1/ready-check/accept")
                            log("Partida aceptada", "action")
                        else:
                            log("Observando · Aceptaría la partida: acéptala tú", "hint")
                        accepted_at = time.time()
                elif phase == "ChampSelect":
                    if OPTS["demo"]:
                        if demo is None or demo.t0 < OPTS["demo_since"]:  # demo nueva: desde el principio
                            demo, last_demo_step = Demo(champs), -1
                            draft.reset()
                        s, step = demo.session(draft.last_best or champs.id("Taliyah"))
                        if step < last_demo_step:
                            draft.reset()
                        last_demo_step = step
                        d = draft.tick(
                            s, False, pickable=set(), bannable=set(),
                            queue={"kind": "draft", "name": "Demo", "demo": True},
                        )  # fmt: skip
                    else:
                        if queue is None:
                            # tres intentos; si el cliente no la da, se recomienda como en la Grieta
                            queue_tries += 1
                            queue = read_queue(lcu) or (classify(None) if queue_tries >= 3 else None)
                        d = None
                        if queue:
                            s = lcu.get("/lol-champ-select/v1/session")
                            if isinstance(s, dict) and s.get("myTeam"):
                                last_cs = s
                            if not queue_logged and isinstance(s, dict):
                                # con la sesión, para saber si la personalizada tiene bans
                                queue_logged = True
                                log(*queue_message(queue, s))
                            t0 = time.time()
                            d = champ_select_view(draft, s, acting, queue)
                            slow = time.time() - t0
                            if slow > SLOW_TICK and time.time() - last_slow > 30:  # esperas en el cliente real
                                last_slow = time.time()
                                parts = " · ".join(f"{k} {v:.1f} s" for k, v in draft.timings.items() if v >= 0.5)
                                log(f"Selección lenta: {slow:.1f} s en analizar ({parts or 'sin detalle'})", "warn")
                            rec = draft.pop_record()
                            if rec:
                                save_record(rec, patch)
                            notice, notify = turn_notice(d, notified), OPTS.get("notify")
                            if notice and notify and CFG.get("tray_notify", True):
                                with contextlib.suppress(Exception):  # un aviso no para la champ select
                                    notify(*notice)
                    with LOCK:
                        APP["draft"] = d
                elif phase in IN_GAME and online and not OPTS["demo"]:
                    g = APP.get("game")
                    pending = (
                        not g
                        or not g.get("loaded")
                        or g.get("build_pending")
                        or not g.get("names_ready")
                        or not g.get("cards_ready", True)
                    )
                    if time.time() - last_game > (GAME_REFRESH if pending else 60):
                        last_game = time.time()
                        flow = lcu.get("/lol-gameflow/v1/session", timeout=10)
                        me = lcu.get("/lol-summoner/v1/current-summoner", timeout=10) or {}
                        role = draft.context["role"] if draft.context else None
                        g = game_view(engine, champs, items, flow, last_cs, me.get("puuid"), role)
                        with LOCK:
                            APP["game"] = g
            except Exception as e:
                failures.report("Fallo puntual", e)
        time.sleep(1)
