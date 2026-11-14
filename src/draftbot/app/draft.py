"""Logica de la seleccion de campeon en soloq: lee la sesion del cliente, recomienda y (en modo activo) actua."""

import random
import time
import webbrowser

from draftbot.app.state import SPELL_IDS, TIMER_ES, log
from draftbot.config import CFG
from draftbot.domain import runes as R
from draftbot.domain import tags as T
from draftbot.domain.common import ROLE_ES, ROLE_SHORT
from draftbot.domain.engine import comp_notes, comp_summary


class Draft:
    def __init__(self, lcu, champs, engine, runes=None):
        self.lcu, self.champs, self.engine, self.runes = lcu, champs, engine, runes
        self.reset()

    def reset(self):
        self.done_ban = self.spells_set = self.coachless_opened = self.runes_done = False
        self.runes_state = "pending"
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
        bans_ally = [
            a["championId"]
            for a in acts
            if a["type"] == "ban" and a["completed"] and a.get("isAllyAction") and a["championId"]
        ]
        bans_enemy = [
            a["championId"]
            for a in acts
            if a["type"] == "ban" and a["completed"] and not a.get("isAllyAction") and a["championId"]
        ]
        bans_ally = list(dict.fromkeys(bans_ally + [c for c in s.get("bans", {}).get("myTeamBans", []) if c]))
        bans_enemy = list(dict.fromkeys(bans_enemy + [c for c in s.get("bans", {}).get("theirTeamBans", []) if c]))
        banned = set(bans_ally) | set(bans_enemy)
        ally_ids = [m["championId"] for m in s["myTeam"] if m["cellId"] != me and m["championId"]]
        ally_intent = {
            m["championPickIntent"] for m in s["myTeam"] if m["cellId"] != me and m.get("championPickIntent")
        }
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
        allies = [
            (m["championId"], 1.0) if m["championId"] else (m.get("championPickIntent") or 0, 0.5)
            for m in s["myTeam"]
            if m["cellId"] != me
        ]
        allies = [(c, w) for c, w in allies if c]
        # picks rivales que quedan despues de tu turno (para el riesgo de counter)
        enemy_left_after = 5 - len(enemy_ids)
        if my_pick:
            my_group = next(
                (
                    gi
                    for gi, grp in enumerate(s["actions"])
                    if any(a is my_pick or a.get("id") == my_pick.get("id") for a in grp)
                ),
                None,
            )
            if my_group is not None:
                enemy_left_after = (
                    0
                    if my_pick["completed"]
                    else sum(
                        1
                        for gi, grp in enumerate(s["actions"])
                        if gi > my_group
                        for a in grp
                        if a["type"] == "pick" and not a.get("isAllyAction") and not a["completed"]
                    )
                )
        picks, ctx = eng.picks(
            role, unavailable, pickable, allies, enemy_ids, enemy_left_after=enemy_left_after, include=[locked]
        )
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
        if my_ban:  # solo mientras tu ban este pendiente
            if bannable is None:
                bannable = set(self.lcu.get("/lol-champ-select/v1/bannable-champion-ids") or [])
            bans = [b for b in eng.bans(role, picks, blocked) if not bannable or b["id"] in bannable][:5]
        status = []

        # hechizos
        sp = [SPELL_IDS[x] for x in CFG["spells_by_role"].get(role, []) if x in SPELL_IDS]
        if CFG["auto_spells"] and not self.spells_set and len(sp) == 2:
            names = " + ".join(CFG["spells_by_role"][role])
            if acting:
                self.lcu.req(
                    "PATCH", "/lol-champ-select/v1/session/my-selection", {"spell1Id": sp[0], "spell2Id": sp[1]}
                )
                self.spells_set = True
                self.note(f"Hechizos puestos: {names}")
            else:
                status.append(("info", f"Pondría {names}"))

        # ban
        ban_target = bans[0] if bans else None
        if my_ban and my_ban["isInProgress"] and ban_target and not self.done_ban:
            if acting and CFG["auto_ban"]:
                time.sleep(random.uniform(1.5, 3))
                self.lcu.req(
                    "PATCH",
                    f"/lol-champ-select/v1/session/actions/{my_ban['id']}",
                    {"championId": ban_target["id"], "completed": True},
                )
                self.done_ban = True
                self.note(f"Baneado {ban_target['name']}")
            else:
                status.append(("turn", f"Te toca banear: {ban_target['name']}"))

        # pick
        if my_pick and not my_pick["completed"] and best:
            if CFG["auto_hover_pick"] and acting and my_pick["championId"] != best["id"]:
                self.lcu.req(
                    "PATCH", f"/lol-champ-select/v1/session/actions/{my_pick['id']}", {"championId": best["id"]}
                )
            if my_pick["isInProgress"]:
                if acting and CFG["auto_lock_pick"] and left <= CFG["lock_when_seconds_left"]:
                    self.lcu.req(
                        "PATCH",
                        f"/lol-champ-select/v1/session/actions/{my_pick['id']}",
                        {"championId": best["id"], "completed": True},
                    )
                    self.note(f"Confirmado {best['name']}")
                else:
                    status.append(("turn", f"Te toca elegir: {best['name']}"))
            elif not acting and CFG["auto_hover_pick"]:
                status.append(("info", f"Marcaría {best['name']}"))
        self.last_best = best["id"] if best else None

        # runas: la recomendada para el campeon confirmado (o vista previa del recomendado)
        runes_info = self.handle_runes(locked or (best["id"] if best else None), role, bool(locked), acting, status)

        # coachless
        coach = None
        if my_pick and my_pick["completed"] and my_pick["championId"]:
            coach = f"https://coachless.gg/builds/{ch.slug(my_pick['championId'])}?role={role}"
            if acting and CFG["open_coachless_on_lock"] and not self.coachless_opened:
                self.coachless_opened = True
                webbrowser.open(coach)
                self.note(f"Abierta la build de {ch.name(my_pick['championId'])} en Coachless")

        for _kind, msg in status:
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
            my_team.append(
                {
                    "me": m["cellId"] == me,
                    "role": ROLE_SHORT.get(r, ""),
                    "role_es": ROLE_ES.get(r, ""),
                    "champ": ch.brief(cid or intent),
                    "state": state,
                    "active": in_progress.get(m["cellId"]),
                }
            )
        enemy_team = []
        for m in sorted(s["theirTeam"], key=lambda m: m["cellId"]):
            cid = m["championId"] or 0
            r = enemy_roles.get(cid, "")
            enemy_team.append(
                {
                    "role": ROLE_SHORT.get(r, ""),
                    "role_es": ROLE_ES.get(r, ""),
                    "champ": ch.brief(cid),
                    "state": "picked" if cid else "empty",
                    "active": in_progress.get(m["cellId"]),
                    "lane_opp": bool(cid) and r == role,
                }
            )
        my_turn = None
        if my_ban and my_ban["isInProgress"]:
            my_turn = "ban"
        elif my_pick and my_pick["isInProgress"] and not my_pick["completed"]:
            my_turn = "pick"
        return {
            "role": role,
            "role_es": ROLE_ES.get(role, role),
            "timer_left": round(left),
            "timer_phase": TIMER_ES.get(timer.get("phase", ""), timer.get("phase", "")),
            "my_turn": my_turn,
            "my_team": my_team,
            "enemy_team": enemy_team,
            "bans": {"ally": [ch.brief(c) for c in bans_ally], "enemy": [ch.brief(c) for c in bans_enemy]},
            "ally_comp": ally,
            "enemy_comp": enemy,
            "notes": comp_notes(ally, enemy)
            + (
                ["Tu equipo aún no tiene engage: un pick que inicie peleas vale más."]
                if len(allies) >= 2 and ally["engage"] < 0.5
                else []
            ),
            "picks": picks[:8],
            "hero": mine or best,
            "locked": bool(mine),
            "ban_suggestions": bans,
            "status": [{"kind": k, "msg": m} for k, m in status],
            "coachless": coach,
            "runes": runes_info,
            "mode": ctx["mode"],
            "lane_known": ctx["lane_known"],
            "enemy_left_after": enemy_left_after,
            "my_pick": (
                {**ch.brief(my_pick["championId"]), "completed": my_pick["completed"]}
                if my_pick and my_pick["championId"]
                else None
            ),
        }

    def handle_runes(self, cid, role, locked, acting, status):
        """Importa (o describe) la pagina de runas de Lolalytics para `cid` en `role`.
        Devuelve el resumen para el panel, o None si no hay nada que mostrar."""
        if not cid or not self.runes or not CFG.get("import_runes", True):
            return None
        sets = self.engine.lola.runes(cid, role)
        name = self.champs.name(cid)
        if sets is None:
            return {"state": "loading"}
        source = CFG.get("runes_source", "pick")
        rune_set = sets.get(source) or sets.get("pick") or sets.get("win")
        if not rune_set:
            if locked and not self.runes_done:
                self.runes_done = True
                self.note(f"Sin runas recomendadas para {name} en este rol: no importo nada", "hint")
            return {"state": "none"}
        info = self.runes.describe(rune_set) or {}
        info["source"] = R.SOURCE_ES.get(source if sets.get(source) else "pick", "")
        if not locked:
            return {**info, "state": "preview"}
        if self.runes_done:
            return {**info, "state": self.runes_state}
        if not acting:
            status.append(("info", f"Importaría runas: {info.get('keystone', '')}"))
            return {**info, "state": "would"}
        self.runes_done = True
        ok, msg = self.runes.apply(self.lcu, name, ROLE_SHORT.get(role, ""), rune_set)
        self.runes_state = "imported" if ok else "failed"
        self.note(msg, "action" if ok else "warn")
        return {**info, "state": self.runes_state}
