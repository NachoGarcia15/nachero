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
from nachero.app.state import APP, CTX, LOCK, OPTS, PHASE_ES, TASKS, demo_must_stop, log, set_demo
from nachero.clients.cdragon import CDragon, latest_patch
from nachero.clients.lcu import LCU
from nachero.config import CFG
from nachero.domain import calibration
from nachero.domain.common import ROLE_ES, ROLES
from nachero.domain.common import tier_name as TIER
from nachero.domain.engine import Engine
from nachero.domain.player import Player
from nachero.domain.pro import ProEngine
from nachero.domain.queues import classify
from nachero.domain.stats import ChainStats, source_of
from nachero.jsonio import read_json, write_json
from nachero.sources.champions import Champs
from nachero.sources.golgg import GolGG
from nachero.sources.history import load_history
from nachero.sources.local_stats import LocalStats
from nachero.sources.lolalytics import Lolalytics


def pool_row(engine, champs, cid, role):
    """Fila de Tu pool: tú con el campeón + su fuerza en el rol, a ciegas, con su rol y confianza."""
    you = engine.player.components(cid, role)
    meta, tr = engine.meta(cid, role)
    est = engine.roles.estimate(cid, role)
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
        "est": round(50 + you["total"] * engine.w("pool") + meta * engine.w("meta"), 1),
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
    return sorted(rows, key=lambda r: -r["est"])


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
        "tier": "Master+",
        "source": source_of(lola),
        "stale": stale,
        "warnings": source_warnings(lola, gol_src),
        "pro": gol_src.updated() if gol_src is not None else None,
    }


SOURCES = ("lolalytics", "local")


def stats_file() -> Path:
    custom = CFG.get("stats_file") or ""
    return Path(custom) if custom else paths.user_dir() / "stats" / "nachero-stats.json"


def build_stats(champs):
    """Fuentes de estadísticas según `stats_sources` (ver domain/stats.py). Sin ninguna válida,
    Lolalytics, como siempre."""
    names = [s for s in CFG.get("stats_sources") or [] if s in SOURCES] or ["lolalytics"]
    providers = []
    for name in dict.fromkeys(names):
        if name == "lolalytics":
            lola = Lolalytics(str(paths.cache_dir()), log)
            lola.slug_fallback = champs.slug
            providers.append(lola)
        else:
            providers.append(LocalStats(stats_file(), log))
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


def worker():
    while True:
        try:
            run_session()
        except Restart as e:
            log(str(e), "ok")
        except Exception as e:
            log(f"Reiniciando tras un error ({e.__class__.__name__}: {e})", "warn")
            time.sleep(3)


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
    try:
        pcache = read_json(paths.player_file(), {})
    except Exception:
        pcache = {}
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
        try:
            games = read_json(paths.history_file(), [])
        except Exception:
            games = []
        mastery, rank = pcache.get("mastery", []), pcache.get("rank")
        TASKS.finish("history", f"{len(games)} partidas guardadas" if games else "Sin partidas guardadas")
        TASKS.finish("mastery", "Guardada" if mastery else "Sin datos guardados")
    src = lcu if online else CDragon()
    TASKS.start("champions", detail="Del cliente" if online else "De CommunityDragon")
    champs = Champs(src)
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

    draft = Draft(lcu, champs, engine, RuneImporter(src))
    CTX["draft"] = draft  # el buscador del panel evalúa con el draft actual
    demo = None  # se crea al abrir la demo (por --demo o desde el panel)
    last_phase, accepted_at, last_idle, last_demo_step, last_probe = "-", 0, 0, -1, time.time()
    fails = 0  # fallos seguidos al leer la fase: el cliente a veces tarda mas de 5 s
    queue, queue_tries = None, 0  # tipo de cola de la champ select actual
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
                queue, queue_tries = None, 0
            if phase in ("EndOfGame", "PreEndOfGame"):
                TASKS.start("history", detail="Partida nueva: actualizando…")
                games = load_history(
                    lcu, str(paths.history_file()), CFG["history_queues"], log, str(paths.history_import_file())
                )
                TASKS.finish("history", f"{len(games)} partidas de la Grieta")
                with contextlib.suppress(Exception):
                    if resolve_records(games):
                        log("Partida apuntada en «¿Acierta Nachero?»", "ok")
                engine.player = player = Player(
                    games, lcu.get("/lol-champion-mastery/v1/local-player/champion-mastery", timeout=20) or []
                )
                with LOCK:
                    APP["history"] = player.history_summary(APP.get("rank"))
                    APP["games"] = len(player.games)
            if phase != "ChampSelect":
                with LOCK:
                    APP["draft"] = None
            last_phase = phase
        with LOCK:
            APP["phase"] = phase
            APP["data"] = data_status(lola, patch, gol())
        TASKS.queue("matchups", "Matchups y runas", len(lola.pending))
        if patch and TASKS.retry_due("tiers"):
            threading.Thread(target=refresh_tiers, args=(lola, patch), daemon=True).start()

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
        if not APP["pool"]:
            with LOCK:
                APP["pool"] = pool_rows(engine, champs)

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
                            s, False, pickable=set(), bannable=set(), queue={"kind": "draft", "name": "Demo"}
                        )
                    else:
                        if queue is None:
                            # tres intentos; si el cliente no la da, se recomienda como en la Grieta
                            queue_tries += 1
                            queue = read_queue(lcu) or (classify(None) if queue_tries >= 3 else None)
                            if queue:
                                msg, kind = QUEUE_LOG[queue["kind"]]
                                log(msg.format(name=queue["name"]), kind)
                        d = None
                        if queue:
                            s = lcu.get("/lol-champ-select/v1/session")
                            d = champ_select_view(draft, s, acting, queue)
                            rec = draft.pop_record()
                            if rec:
                                save_record(rec, patch)
                    with LOCK:
                        APP["draft"] = d
            except Exception as e:
                log(f"Fallo puntual ({e.__class__.__name__}: {e}); reintento.", "warn")
        time.sleep(1)
