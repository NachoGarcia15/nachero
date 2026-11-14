"""Bucle principal: conecta con el cliente (o trabaja sin el), carga datos y sigue cada fase."""

import random
import re
import time

from draftbot import paths
from draftbot.app.demo import Demo
from draftbot.app.draft import Draft
from draftbot.app.runes import RuneImporter
from draftbot.app.state import APP, CTX, LOCK, OPTS, PHASE_ES, log
from draftbot.clients.cdragon import CDragon
from draftbot.clients.lcu import LCU
from draftbot.config import CFG
from draftbot.domain.common import ROLE_ES, ROLES
from draftbot.domain.common import tier_name as TIER
from draftbot.domain.engine import Engine
from draftbot.domain.player import Player
from draftbot.domain.pro import ProEngine
from draftbot.jsonio import read_json, write_json
from draftbot.sources.champions import Champs
from draftbot.sources.golgg import GolGG
from draftbot.sources.history import load_history
from draftbot.sources.lolalytics import Lolalytics


def pool_rows(engine, champs):
    p, main = engine.player, engine.main_role()
    keys = {(c, r) for (c, r), gs in p.by_cr.items() if len(gs) >= 2 or r == main}
    t_main = engine.lola.tier(main)
    for cid, m in p.mastery.items():
        if (
            m.get("championPoints", 0) >= 80000
            and t_main
            and str(cid) in t_main["champs"]
            and t_main["champs"][str(cid)]["games"] >= 1500
        ):
            keys.add((cid, main))
    rows = []
    for cid, role in keys:
        you = p.components(cid, role)
        meta, tr = engine.meta(cid, role)
        rows.append(
            {
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
                "tier": TIER(tr),
                "meta_wr": tr["wr"] if tr else None,
                "est": round(50 + you["total"] * engine.w("pool") + meta * engine.w("meta"), 1),
            }
        )
    return sorted(rows, key=lambda r: -r["est"])


def data_status(lola, patch):
    t = lola.cache.get("tiers", {})
    return {
        "patch": patch,
        "updated": lola.updated_at(),
        "games": sum(v.get("games", 0) for v in t.values()),
        "counters": len(lola.cache.get("builds", {})),
        "pending": len(lola.pending),
        "tier": "Master+",
    }


def current_patch(lcu, games):
    v = lcu.get("/lol-patch/v1/game-version")
    if isinstance(v, str) and re.match(r"\d+\.\d+", v):
        return ".".join(v.split(".")[:2])
    return games[0]["patch"] if games else "30"


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


def run_session():
    lcu = LCU()
    online = False
    for _ in range(3):
        try:
            online = client_ready(lcu)
        except Exception:
            online = False
        if online:
            break
        time.sleep(2)
    src = lcu if online else CDragon()
    champs = Champs(src)
    if not champs.by_id:
        raise Restart("Sin datos de campeones; reintento…")
    try:
        pcache = read_json(paths.player_file(), {})
    except Exception:
        pcache = {}
    if online:
        games = load_history(lcu, str(paths.history_file()), CFG["history_queues"], log)
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
        patch = current_patch(lcu, games)
        log("Conectado al cliente de LoL" + (" · modo demo" if OPTS["demo"] else ""), "ok")
    else:
        try:
            games = read_json(paths.history_file(), [])
        except Exception:
            games = []
        mastery, rank = pcache.get("mastery", []), pcache.get("rank")
        patch = games[0]["patch"] if games else "30"
        log(
            "Cliente de LoL cerrado: uso datos guardados y CommunityDragon" + (" · modo demo" if OPTS["demo"] else ""),
            "warn",
        )
    player = Player(games, mastery)
    lola = Lolalytics(str(paths.cache_dir()), log)
    lola.slug_fallback = champs.slug
    log(f"Leyendo estadísticas Master+ del parche {patch}…")
    lola.refresh_tiers(patch)
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
    main = engine.main_role()
    for r in engine.picks(main, set(), set(), [], [])[0][:10]:
        lola.request(r["id"], main, champs.slug(r["id"]))
    with LOCK:
        APP["connected"], APP["offline"], APP["rank"], APP["loading"] = online, not online, rank, False
        APP["pool"], APP["refresh_idle"] = [], True
    roles = ", ".join(f"{ROLE_ES[r]} {n}" for r, n in sorted(player.role_games.items(), key=lambda x: -x[1]))
    log(f"Listo · rol principal {ROLE_ES[main]} · {len(player.games)} partidas analizadas ({roles or 'ninguna'})", "ok")

    draft = Draft(lcu, champs, engine, RuneImporter(src))
    demo = Demo(champs) if OPTS["demo"] else None
    last_phase, accepted_at, last_idle, last_demo_step, last_probe = "-", 0, 0, -1, time.time()
    fails = 0  # fallos seguidos al leer la fase: el cliente a veces tarda mas de 5 s
    while True:
        mode = APP["mode"]
        if not online:
            if time.time() - last_probe > 10:
                last_probe = time.time()
                if client_ready(LCU()):
                    raise Restart("Cliente de LoL detectado: me conecto")
            phase = "ChampSelect" if OPTS["demo"] else None
        else:
            try:
                phase = "ChampSelect" if OPTS["demo"] else lcu.get("/lol-gameflow/v1/gameflow-phase", timeout=10)
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
            if phase in ("EndOfGame", "PreEndOfGame"):
                games = load_history(lcu, str(paths.history_file()), CFG["history_queues"], log)
                engine.player = player = Player(
                    games, lcu.get("/lol-champion-mastery/v1/local-player/champion-mastery", timeout=20) or []
                )
            if phase != "ChampSelect":
                with LOCK:
                    APP["draft"] = None
            last_phase = phase
        with LOCK:
            APP["phase"] = phase
            APP["data"] = data_status(lola, patch)

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

        if mode != "paused":
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
                        s, step = demo.session(draft.last_best or champs.id("Taliyah"))
                        if step < last_demo_step:
                            draft.reset()
                        last_demo_step = step
                        d = draft.tick(s, False, pickable=set(), bannable=set())
                    else:
                        s = lcu.get("/lol-champ-select/v1/session")
                        d = draft.tick(s, acting) if s else None
                    with LOCK:
                        APP["draft"] = d
            except Exception as e:
                log(f"Fallo puntual ({e.__class__.__name__}: {e}); reintento.", "warn")
        time.sleep(1)
