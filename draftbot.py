"""draftbot - asistente de cola y champion select para League of Legends.

Solo usa la API local del cliente (LCU): no toca el juego ni su memoria.
No lee nombres de jugadores en champ select (solo campeones).
Estadisticas Master+ de Lolalytics (cache local, pocas peticiones).

Uso:
  python draftbot.py              -> abre el panel en http://127.0.0.1:8765
  python draftbot.py --observe    -> arranca en modo Observar (no actua)
  python draftbot.py --demo       -> champ select simulado para ver el panel
  python draftbot.py --no-browser -> no abre el navegador al arrancar
  python draftbot.py --profile    -> informe de tu pool en consola y sale
  python draftbot.py --port 8766  -> usa otro puerto para el panel
"""
import json, mimetypes, os, random, re, sys, threading, time, urllib.parse, webbrowser
from collections import deque
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from lcu import LCU, CDragon
from data import Champs, Lolalytics
from model import TIER, Engine, Player, ROLE_ES, ROLE_SHORT, comp_notes, comp_summary, load_history
from pro import GolGG, ProEngine
import tags as T

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
UI = os.path.join(HERE, "ui")
CFG_PATH = os.path.join(HERE, "config.json")
CFG = json.load(open(CFG_PATH, encoding="utf-8"))
CACHE = os.path.join(HERE, "history_cache.json")
SPELL_IDS = {"Cleanse": 1, "Exhaust": 3, "Flash": 4, "Ghost": 6, "Heal": 7, "Smite": 11,
             "Teleport": 12, "Ignite": 14, "Barrier": 21}
PHASE_ES = {None: "Sin cliente", "None": "Menú principal", "Lobby": "En la sala", "Matchmaking": "Buscando partida",
            "ReadyCheck": "Partida encontrada", "ChampSelect": "Selección de campeón", "GameStart": "Cargando partida",
            "InProgress": "En partida", "WaitingForStats": "Esperando estadísticas", "PreEndOfGame": "Fin de partida",
            "EndOfGame": "Fin de partida", "Reconnect": "Reconectar"}
TIMER_ES = {"PLANNING": "Planificación", "BAN_PICK": "Bans y picks", "FINALIZATION": "Finalización", "GAME_STARTING": "Empezando"}
TOGGLES = ["auto_accept", "auto_ban", "auto_hover_pick", "auto_lock_pick", "auto_spells", "open_coachless_on_lock"]
DEMO = "--demo" in sys.argv

LOCK = threading.RLock()
APP = {"mode": "observe" if ("--observe" in sys.argv or DEMO) else CFG.get("start_mode", "observe"),
       "connected": False, "offline": False, "loading": True, "phase": None, "draft": None, "idle": None, "rank": None,
       "pool": [], "log": deque(maxlen=200), "demo": DEMO, "data": {}}


def log(msg, kind="info"):
    with LOCK:
        APP["log"].appendleft({"t": time.strftime("%H:%M:%S"), "msg": msg, "kind": kind})
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def save_cfg():
    with open(CFG_PATH, "w", encoding="utf-8") as f:
        json.dump(CFG, f, indent=2, ensure_ascii=False)


# ---------------------------------------------------------------- champ select
class Draft:
    def __init__(self, lcu, champs, engine):
        self.lcu, self.champs, self.engine = lcu, champs, engine
        self.reset()

    def reset(self):
        self.done_ban = self.spells_set = self.coachless_opened = False
        self.seen, self.last_best = set(), None

    def note(self, msg, kind="action"):
        if msg not in self.seen:
            self.seen.add(msg)
            log(msg, kind)

    def tick(self, s, acting, pickable=None, bannable=None):
        ch, eng = self.champs, self.engine
        me = s["localPlayerCellId"]
        my = next((m for m in s["myTeam"] if m["cellId"] == me), {})
        role = my.get("assignedPosition") or eng.player.main_role
        acts = [a for grp in s["actions"] for a in grp]
        bans_ally = [a["championId"] for a in acts if a["type"] == "ban" and a["completed"] and a.get("isAllyAction") and a["championId"]]
        bans_enemy = [a["championId"] for a in acts if a["type"] == "ban" and a["completed"] and not a.get("isAllyAction") and a["championId"]]
        bans_ally = list(dict.fromkeys(bans_ally + [c for c in s.get("bans", {}).get("myTeamBans", []) if c]))
        bans_enemy = list(dict.fromkeys(bans_enemy + [c for c in s.get("bans", {}).get("theirTeamBans", []) if c]))
        banned = set(bans_ally) | set(bans_enemy)
        ally_ids = [m["championId"] for m in s["myTeam"] if m["cellId"] != me and m["championId"]]
        ally_intent = {m["championPickIntent"] for m in s["myTeam"] if m["cellId"] != me and m.get("championPickIntent")}
        enemy_ids = [m["championId"] for m in s["theirTeam"] if m["championId"]]
        if pickable is None:
            pickable = set(self.lcu.get("/lol-champ-select/v1/pickable-champion-ids") or [])
        my_ban = next((a for a in acts if a["actorCellId"] == me and a["type"] == "ban" and not a["completed"]), None)
        my_pick = next((a for a in acts if a["actorCellId"] == me and a["type"] == "pick"), None)
        timer = s.get("timer", {})
        left = max(0, timer.get("adjustedTimeLeftInPhase", 0) / 1000)

        unavailable = banned | set(ally_ids) | set(enemy_ids) | ally_intent
        locked = my_pick["championId"] if my_pick and my_pick["completed"] and my_pick["championId"] else None
        # aliados: elegidos pesan 1; los que solo marcan, 0,5
        allies = [(m["championId"], 1.0) if m["championId"] else (m.get("championPickIntent") or 0, 0.5)
                  for m in s["myTeam"] if m["cellId"] != me]
        allies = [(c, w) for c, w in allies if c]
        # picks rivales que quedan despues de tu turno (para el riesgo de counter)
        enemy_left_after = 5 - len(enemy_ids)
        if my_pick:
            my_group = next((gi for gi, grp in enumerate(s["actions"]) if any(a is my_pick or a.get("id") == my_pick.get("id") for a in grp)), None)
            if my_group is not None:
                enemy_left_after = 0 if my_pick["completed"] else sum(
                    1 for gi, grp in enumerate(s["actions"]) if gi > my_group
                    for a in grp if a["type"] == "pick" and not a.get("isAllyAction") and not a["completed"])
        picks, ctx = eng.picks(role, unavailable, pickable, allies, enemy_ids,
                               enemy_left_after=enemy_left_after, include=[locked])
        enemy_roles = ctx["enemy_roles"]
        ally, enemy = comp_summary(ally_ids, ch), comp_summary(enemy_ids, ch)
        ally_ident = T.identity(allies, ch)
        enemy_ident = T.identity([(e, 1.0) for e in enemy_ids], ch)
        ally["identity"], enemy["identity"] = T.IDENTITY_ES[ally_ident[0]], T.IDENTITY_ES[enemy_ident[0]]
        ally["engage"], enemy["engage"] = round(ally_ident[2]["E"], 1), round(enemy_ident[2]["E"], 1)
        mine = next((p for p in picks if p["id"] == locked), None)
        picks = [p for p in picks if p["id"] != locked]
        best = picks[0] if picks else None
        blocked = banned | set(ally_ids) | set(enemy_ids) | ally_intent | {p["id"] for p in picks[:2]} | {locked}
        bans = []
        if my_ban:   # solo mientras tu ban este pendiente
            if bannable is None:
                bannable = set(self.lcu.get("/lol-champ-select/v1/bannable-champion-ids") or [])
            bans = [b for b in eng.bans(role, picks, blocked) if not bannable or b["id"] in bannable][:5]
        status = []

        # hechizos
        sp = [SPELL_IDS[x] for x in CFG["spells_by_role"].get(role, []) if x in SPELL_IDS]
        if CFG["auto_spells"] and not self.spells_set and len(sp) == 2:
            names = " + ".join(CFG["spells_by_role"][role])
            if acting:
                self.lcu.req("PATCH", "/lol-champ-select/v1/session/my-selection", {"spell1Id": sp[0], "spell2Id": sp[1]})
                self.spells_set = True
                self.note(f"Hechizos puestos: {names}")
            else:
                status.append(("info", f"Pondría {names}"))

        # ban
        ban_target = bans[0] if bans else None
        if my_ban and my_ban["isInProgress"] and ban_target and not self.done_ban:
            if acting and CFG["auto_ban"]:
                time.sleep(random.uniform(1.5, 3))
                self.lcu.req("PATCH", f"/lol-champ-select/v1/session/actions/{my_ban['id']}",
                             {"championId": ban_target["id"], "completed": True})
                self.done_ban = True
                self.note(f"Baneado {ban_target['name']}")
            else:
                status.append(("turn", f"Te toca banear: {ban_target['name']}"))

        # pick
        if my_pick and not my_pick["completed"] and best:
            if CFG["auto_hover_pick"] and acting and my_pick["championId"] != best["id"]:
                self.lcu.req("PATCH", f"/lol-champ-select/v1/session/actions/{my_pick['id']}", {"championId": best["id"]})
            if my_pick["isInProgress"]:
                if acting and CFG["auto_lock_pick"] and left <= CFG["lock_when_seconds_left"]:
                    self.lcu.req("PATCH", f"/lol-champ-select/v1/session/actions/{my_pick['id']}",
                                 {"championId": best["id"], "completed": True})
                    self.note(f"Confirmado {best['name']}")
                else:
                    status.append(("turn", f"Te toca elegir: {best['name']}"))
            elif not acting and CFG["auto_hover_pick"]:
                status.append(("info", f"Marcaría {best['name']}"))
        self.last_best = best["id"] if best else None

        # coachless
        coach = None
        if my_pick and my_pick["completed"] and my_pick["championId"]:
            coach = f"https://coachless.gg/builds/{ch.slug(my_pick['championId'])}?role={role}"
            if acting and CFG["open_coachless_on_lock"] and not self.coachless_opened:
                self.coachless_opened = True
                webbrowser.open(coach)
                self.note(f"Abierta la build de {ch.name(my_pick['championId'])} en Coachless")

        for kind, msg in status:
            self.note(("Observando · " if not acting else "") + msg, "hint")

        in_progress = {a["actorCellId"]: a["type"] for a in acts if a.get("isInProgress") and not a["completed"]}
        my_team = []
        for m in sorted(s["myTeam"], key=lambda m: m["cellId"]):
            cid = m["championId"] or 0
            intent = m.get("championPickIntent") or 0
            state = "picked" if cid else ("hover" if intent else "empty")
            if m["cellId"] == me and not cid:
                intent = (my_pick or {}).get("championId") or intent
                state = "hover" if intent else ("suggest" if best else "empty")
                intent = intent or (best["id"] if best else 0)
            r = m.get("assignedPosition", "")
            my_team.append({"me": m["cellId"] == me, "role": ROLE_SHORT.get(r, ""), "role_es": ROLE_ES.get(r, ""),
                            "champ": ch.brief(cid or intent), "state": state,
                            "active": in_progress.get(m["cellId"])})
        enemy_team = []
        for m in sorted(s["theirTeam"], key=lambda m: m["cellId"]):
            cid = m["championId"] or 0
            r = enemy_roles.get(cid, "")
            enemy_team.append({"role": ROLE_SHORT.get(r, ""), "role_es": ROLE_ES.get(r, ""), "champ": ch.brief(cid),
                               "state": "picked" if cid else "empty", "active": in_progress.get(m["cellId"]),
                               "lane_opp": bool(cid) and r == role})
        my_turn = None
        if my_ban and my_ban["isInProgress"]:
            my_turn = "ban"
        elif my_pick and my_pick["isInProgress"] and not my_pick["completed"]:
            my_turn = "pick"
        return {"role": role, "role_es": ROLE_ES.get(role, role), "timer_left": round(left),
                "timer_phase": TIMER_ES.get(timer.get("phase", ""), timer.get("phase", "")), "my_turn": my_turn,
                "my_team": my_team, "enemy_team": enemy_team,
                "bans": {"ally": [ch.brief(c) for c in bans_ally], "enemy": [ch.brief(c) for c in bans_enemy]},
                "ally_comp": ally, "enemy_comp": enemy,
                "notes": comp_notes(ally, enemy) + (["Tu equipo aún no tiene engage: un pick que inicie peleas vale más."]
                                                    if len(allies) >= 2 and ally["engage"] < 0.5 else []),
                "picks": picks[:8], "hero": mine or best, "locked": bool(mine), "ban_suggestions": bans, "status": [{"kind": k, "msg": m} for k, m in status],
                "coachless": coach, "mode": ctx["mode"], "lane_known": ctx["lane_known"],
                "enemy_left_after": enemy_left_after,
                "my_pick": ({**ch.brief(my_pick["championId"]), "completed": my_pick["completed"]}
                            if my_pick and my_pick["championId"] else None)}


# ---------------------------------------------------------------- demo
class Demo:
    """Simula un draft ranked completo 5v5. Tu eres el segundo pick azul (jungla)."""
    STEP_SECONDS = 4

    def __init__(self, champs):
        self.c, self.t0, self.locked = champs, time.time(), None

    def session(self, my_best):
        i = lambda n: self.c.id(n) or 0
        step = int((time.time() - self.t0) / self.STEP_SECONDS) % 7
        if step < 5:
            self.locked = None
        elif self.locked is None:
            self.locked = my_best
        my_best = self.locked or my_best
        roles = ["top", "jungle", "middle", "bottom", "utility"]
        ally_final = [i("Darius"), 0, i("Zed"), i("Jinx"), i("Nautilus")]
        enemy_final = [i("Aatrox"), i("Viego"), i("Talon"), i("Kai'Sa"), i("Leona")]
        ally_bans = [i("Yone"), 0, i("Kayn"), i("Draven"), i("Pyke")]
        enemy_bans = [i("Graves"), i("Qiyana"), i("Akali"), i("Ezreal"), i("Blitzcrank")]
        pick_order = [[0], [5, 6], [1, 2], [7, 8], [3, 4], [9]]   # celdas que eligen en cada turno
        done_turns = {0: 0, 1: 0, 2: 0, 3: 1, 4: 2, 5: 4, 6: 6}[step]
        bans_done = step >= 2
        my_locked = step >= 5
        me_champ = my_best if my_locked else 0
        picked = {c for t in pick_order[:done_turns] for c in t}
        active = set(pick_order[done_turns]) if (bans_done and done_turns < 6) else set()

        my_team = []
        for k in range(5):
            cid = (me_champ if k == 1 else ally_final[k]) if k in picked or (k == 1 and my_locked) else 0
            intent = ally_final[k] if (k != 1 and k not in picked) else 0
            my_team.append({"cellId": k, "assignedPosition": roles[k], "championId": cid, "championPickIntent": intent})
        their = [{"cellId": 5 + k, "championId": enemy_final[k] if 5 + k in picked else 0} for k in range(5)]
        acts, aid = [], 0
        bans = []
        for k in range(10):
            aid += 1
            ally = k < 5
            champ = (ally_bans[k] if ally else enemy_bans[k - 5]) if bans_done else 0
            bans.append({"id": aid, "actorCellId": k, "type": "ban", "isAllyAction": ally,
                         "completed": bans_done, "isInProgress": (step == 1), "championId": champ})
        acts.append(bans)
        for turn in pick_order:
            grp = []
            for cell in turn:
                aid += 1
                done = cell in picked or (cell == 1 and my_locked)
                champ = (me_champ if cell == 1 else (ally_final[cell] if cell < 5 else enemy_final[cell - 5])) if done else 0
                grp.append({"id": aid, "actorCellId": cell, "type": "pick", "isAllyAction": cell < 5,
                            "completed": done, "isInProgress": cell in active and not done, "championId": champ})
            acts.append(grp)
        phase = "PLANNING" if step == 0 else ("FINALIZATION" if step == 6 else "BAN_PICK")
        left = [28, 25, 27, 22, 18, 26, 40][step]
        return {"localPlayerCellId": 1, "myTeam": my_team, "theirTeam": their, "actions": acts,
                "bans": {"myTeamBans": [], "theirTeamBans": []},
                "timer": {"phase": phase, "adjustedTimeLeftInPhase": left * 1000}}, step


# ---------------------------------------------------------------- estado auxiliar
def pool_rows(engine, champs):
    p = engine.player
    keys = {(c, r) for (c, r), gs in p.by_cr.items() if len(gs) >= 2 or r == p.main_role}
    t_main = engine.lola.tier(p.main_role)
    for cid, m in p.mastery.items():
        if m.get("championPoints", 0) >= 80000 and t_main and str(cid) in t_main["champs"] \
                and t_main["champs"][str(cid)]["games"] >= 1500:
            keys.add((cid, p.main_role))
    rows = []
    for cid, role in keys:
        you = p.components(cid, role)
        meta, tr = engine.meta(cid, role)
        rows.append({"id": cid, "name": champs.name(cid), "role": ROLE_ES.get(role, role), "role_key": role,
                     "games": you["games"], "wr": round(100 * you["wins"] / you["games"]) if you["games"] else None,
                     "exp": round(you["exp_games"]), "mastery": you["mastery"],
                     "you": round(you["total"], 1), "meta": round(meta, 1),
                     "tier": TIER(tr), "meta_wr": tr["wr"] if tr else None,
                     "est": round(50 + you["total"] * engine.w("pool") + meta * engine.w("meta"), 1)})
    return sorted(rows, key=lambda r: -r["est"])


def data_status(lola, patch):
    t = lola.cache.get("tiers", {})
    return {"patch": patch, "updated": lola.updated_at(),
            "games": sum(v.get("games", 0) for v in t.values()),
            "counters": len(lola.cache.get("builds", {})), "pending": len(lola.pending), "tier": "Master+"}


def current_patch(lcu, games):
    v = lcu.get("/lol-patch/v1/game-version")
    if isinstance(v, str) and re.match(r"\d+\.\d+", v):
        return ".".join(v.split(".")[:2])
    return games[0]["patch"] if games else "30"


# ---------------------------------------------------------------- bucle principal
CTX = {}
PLAYER_CACHE = os.path.join(HERE, "player_cache.json")
GOL = GolGG(HERE, lambda m, k="info": log(m, k))


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
        pcache = json.load(open(PLAYER_CACHE, encoding="utf-8"))
    except Exception:
        pcache = {}
    if online:
        games = load_history(lcu, CACHE, CFG["history_queues"], log)
        mastery = lcu.get("/lol-champion-mastery/v1/local-player/champion-mastery", timeout=20) or pcache.get("mastery", [])
        qs = (lcu.get("/lol-ranked/v1/current-ranked-stats") or {}).get("queues", [])
        rk = next((q for q in qs if q.get("queueType") == "RANKED_SOLO_5x5"), {})
        rank = None
        if rk.get("tier") and rk["tier"] != "NONE":
            div = "" if rk["tier"] in ("MASTER", "GRANDMASTER", "CHALLENGER") else " " + rk.get("division", "")
            rank = {"tier": rk["tier"].title() + div, "lp": rk.get("leaguePoints", 0),
                    "w": rk.get("wins", 0), "l": rk.get("losses", 0)}
        json.dump({"mastery": mastery, "rank": rank, "t": time.time()}, open(PLAYER_CACHE, "w", encoding="utf-8"))
        patch = current_patch(lcu, games)
        log("Conectado al cliente de LoL" + (" · modo demo" if DEMO else ""), "ok")
    else:
        try:
            games = json.load(open(CACHE, encoding="utf-8"))
        except Exception:
            games = []
        mastery, rank = pcache.get("mastery", []), pcache.get("rank")
        patch = games[0]["patch"] if games else "30"
        log("Cliente de LoL cerrado: uso datos guardados y CommunityDragon" + (" · modo demo" if DEMO else ""), "warn")
    player = Player(games, mastery)
    lola = Lolalytics(HERE, log)
    lola.slug_fallback = champs.slug
    log(f"Leyendo estadísticas Master+ del parche {patch}…")
    lola.refresh_tiers(patch)
    engine = Engine(champs, lola, player, CFG)
    CTX.update(lcu=lcu, src=src, champs=champs, lola=lola, engine=engine, patch=patch,
               pro=ProEngine(champs, lola, engine, GOL))
    for r in engine.picks(player.main_role, set(), set(), [], [])[0][:10]:
        lola.request(r["id"], player.main_role, champs.slug(r["id"]))
    with LOCK:
        APP["connected"], APP["offline"], APP["rank"], APP["loading"] = online, not online, rank, False
        APP["pool"], APP["refresh_idle"] = [], True
    log(f"Listo · rol principal {ROLE_ES[player.main_role]} · {len(player.games)} partidas de soloq analizadas", "ok")

    draft, demo = Draft(lcu, champs, engine), (Demo(champs) if DEMO else None)
    last_phase, accepted_at, last_idle, last_demo_step, last_probe = "-", 0, 0, -1, time.time()
    while True:
        mode = APP["mode"]
        if not online:
            if time.time() - last_probe > 10:
                last_probe = time.time()
                if client_ready(LCU()):
                    raise Restart("Cliente de LoL detectado: me conecto")
            phase = "ChampSelect" if DEMO else None
        else:
            try:
                phase = "ChampSelect" if DEMO else lcu.get("/lol-gameflow/v1/gameflow-phase")
            except Exception:
                with LOCK:
                    APP["connected"], APP["phase"] = False, None
                raise Restart("Cliente desconectado")
        if phase != last_phase:
            log(f"Fase: {PHASE_ES.get(phase, phase)}")
            if phase == "ChampSelect":
                draft.reset()
            if phase in ("EndOfGame", "PreEndOfGame"):
                games = load_history(lcu, CACHE, CFG["history_queues"], log)
                engine.player = player = Player(games, lcu.get("/lol-champion-mastery/v1/local-player/champion-mastery", timeout=20) or [])
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
            picks = engine.picks(player.main_role, set(), set(), [], [])[0][:5]
            with LOCK:
                APP["idle"] = {"role_es": ROLE_ES[player.main_role], "picks": picks}
                APP["pool"] = pool_rows(engine, champs)
        if not APP["pool"]:
            with LOCK:
                APP["pool"] = pool_rows(engine, champs)

        if mode != "paused":
            acting = mode == "active" and not DEMO
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
                    if DEMO:
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


# ---------------------------------------------------------------- servidor del panel
class Handler(BaseHTTPRequestHandler):
    img_cache = {}

    def log_message(self, *a):
        pass

    def send(self, code, body, ctype="application/json", cache=False):
        if isinstance(body, (dict, list)):
            body = json.dumps(body, ensure_ascii=False).encode()
        elif isinstance(body, str):
            body = body.encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Cache-Control", "max-age=86400" if cache else "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        path = self.path.split("?")[0]
        if path in ("/", "/index.html", "/style.css", "/app.js", "/pro.js"):
            f = os.path.join(UI, "index.html" if path in ("/", "/index.html") else path.lstrip("/"))
            ctype = mimetypes.guess_type(f)[0] or "text/plain"
            return self.send(200, open(f, "rb").read(), ctype + "; charset=utf-8")
        if path == "/api/state":
            with LOCK:
                st = {k: (list(v) if isinstance(v, deque) else v) for k, v in APP.items()}
            st["phase_es"] = PHASE_ES.get(st["phase"], st["phase"])
            st["settings"] = {k: CFG[k] for k in TOGGLES} | {"lock_when_seconds_left": CFG["lock_when_seconds_left"],
                                                             "weights": CFG.get("weights", {}),
                                                             "pick_mode": CFG.get("pick_mode", "pool")}
            return self.send(200, st)
        if path == "/api/pro/tournaments":
            try:
                return self.send(200, GOL.tournaments())
            except Exception as e:
                return self.send(502, {"error": f"gol.gg no responde ({e.__class__.__name__})"})
        if path == "/api/pro/champions":
            champs, pe = CTX.get("champs"), CTX.get("pro")
            if not champs:
                return self.send(503, {"error": "cargando"})
            q = urllib.parse.parse_qs(self.path.split("?", 1)[1] if "?" in self.path else "")
            ds = GOL.dataset((q.get("t") or [""])[0])
            out = []
            for cid in sorted(champs.by_id, key=champs.name):
                p = pe.pro(ds, cid) if pe else None
                shares = {r: round(pe.role_share(ds, cid, r), 2) for r in ("top", "jungle", "middle", "bottom", "utility")} if pe else {}
                out.append({"id": cid, "name": champs.name(cid), "prio": p["prio"] if p else 0,
                            "presence": round(100 * (p["picks"] + p["bans"]) / max(1, ds["games"])) if p else 0,
                            "roles": [r for r, v in shares.items() if v >= 0.12]})
            return self.send(200, out)
        m = re.match(r"^/api/img/(tile|splash|icon)/(\d+)$", path)
        if m:
            kind, cid = m.group(1), int(m.group(2))
            key = (kind, cid)
            if key not in self.img_cache:
                champs, lcu = CTX.get("champs"), CTX.get("src")
                data = None
                if champs and lcu:
                    try:
                        p = champs.info(cid)["img"].get(kind)
                        data = lcu.raw("GET", p, timeout=20) if p else None
                    except Exception:
                        data = None
                if data is None:
                    return self.send(404, {"error": "no image"})
                self.img_cache[key] = data
            data = self.img_cache[key]
            return self.send(200, data, "image/png" if kind == "icon" else "image/jpeg", cache=True)
        self.send(404, {"error": "not found"})

    def do_POST(self):
        n = int(self.headers.get("Content-Length", 0) or 0)
        try:
            body = json.loads(self.rfile.read(n) or b"{}")
        except Exception:
            return self.send(400, {"error": "json"})
        if self.path == "/api/mode" and body.get("mode") in ("paused", "observe", "active"):
            with LOCK:
                APP["mode"] = body["mode"]
            log("Modo " + {"paused": "pausado", "observe": "observar", "active": "activo"}[body["mode"]], "ok")
            return self.send(200, {"ok": True})
        if self.path == "/api/settings":
            changed = []
            for k, v in body.items():
                if k in TOGGLES and isinstance(v, bool):
                    CFG[k] = v
                    changed.append(k)
                elif k == "lock_when_seconds_left" and isinstance(v, (int, float)) and 1 <= v <= 30:
                    CFG[k] = int(v)
                    changed.append(k)
                elif k == "pick_mode" and v in ("pool", "meta"):
                    CFG[k] = v
                    changed.append("modo " + ("tu pool" if v == "pool" else "solo meta y draft"))
                elif k == "weights" and isinstance(v, dict):
                    for wk, wv in v.items():
                        if wk in ("pool", "meta", "matchup", "comp") and isinstance(wv, (int, float)) and 0 <= wv <= 2:
                            CFG.setdefault("weights", {})[wk] = round(float(wv), 2)
                            changed.append(f"peso {wk}")
            if changed:
                save_cfg()
                with LOCK:
                    APP["pool"] = []
                    APP["refresh_idle"] = True
                log("Ajustes guardados: " + ", ".join(changed), "ok")
            return self.send(200, {"ok": True})
        if self.path == "/api/pro/suggest":
            pe = CTX.get("pro")
            if not pe:
                return self.send(503, {"error": "cargando"})
            tour = body.get("tournament")
            if tour and not GOL.dataset(tour) and tour not in GOL.loading:
                threading.Thread(target=GOL.load, args=(tour,), daemon=True).start()
            try:
                return self.send(200, pe.suggest(body))
            except Exception as e:
                log(f"Simulador: fallo ({e.__class__.__name__}: {e})", "warn")
                return self.send(500, {"error": str(e)})
        if self.path == "/api/refresh":
            lola, patch = CTX.get("lola"), CTX.get("patch")
            if lola:
                threading.Thread(target=lambda: (lola.refresh_tiers(patch, force=True),
                                                 log("Estadísticas Master+ actualizadas", "ok")), daemon=True).start()
            return self.send(200, {"ok": True})
        self.send(404, {"error": "not found"})


def main():
    if "--profile" in sys.argv:
        lcu = LCU()
        if not lcu.connect():
            print("No encuentro el cliente de LoL abierto.")
            return
        champs = Champs(lcu)
        games = load_history(lcu, CACHE, CFG["history_queues"], log)
        player = Player(games, lcu.get("/lol-champion-mastery/v1/local-player/champion-mastery", timeout=20))
        lola = Lolalytics(HERE, log)
        lola.refresh_tiers(current_patch(lcu, games))
        eng = Engine(champs, lola, player, CFG)
        for r in pool_rows(eng, champs)[:25]:
            print(f"{r['name']:13s} {r['role']:8s} {r['games']:3d}p  WR {'-' if r['wr'] is None else r['wr']:>3}%  exp {r['exp']:4d}  "
                  f"tú {r['you']:+5.1f}  meta {r['meta']:+5.1f} ({r['tier'] or '-':2s})  est {r['est']:.1f}%")
        return
    port = CFG.get("ui_port", 8765)
    if "--port" in sys.argv:
        port = int(sys.argv[sys.argv.index("--port") + 1])
    url = f"http://127.0.0.1:{port}"
    # En Windows, SO_REUSEADDR deja que dos procesos escuchen en el mismo puerto: lo desactivamos
    # para que un segundo draftbot detecte al primero en vez de quedarse "en sombra".
    ThreadingHTTPServer.allow_reuse_address = False
    try:
        srv = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    except OSError:
        print(f"draftbot ya está abierto en {url}; abro el panel.")
        if "--no-browser" not in sys.argv:
            webbrowser.open(f"{url}/?v=2")
        return
    threading.Thread(target=worker, daemon=True).start()
    log(f"Panel en {url}", "ok")
    if "--no-browser" not in sys.argv:
        webbrowser.open(f"{url}/?v=2")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\nSaliendo.")


if __name__ == "__main__":
    main()
