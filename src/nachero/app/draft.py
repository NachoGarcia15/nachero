"""Logica de la seleccion de campeon en soloq: lee la sesion del cliente, recomienda y (en modo activo) actua."""

import webbrowser

from nachero.app.state import SPELL_IDS, TIMER_ES, log
from nachero.config import CFG
from nachero.domain import runes as R
from nachero.domain import tags as T
from nachero.domain.common import ROLE_ES, ROLE_SHORT
from nachero.domain.engine import comp_notes, comp_summary
from nachero.domain.queues import has_bans


class Draft:
    def __init__(self, lcu, champs, engine, runes=None):
        self.lcu, self.champs, self.engine, self.runes = lcu, champs, engine, runes
        self.reset()

    def reset(self) -> None:
        self.spells_set = self.coachless_opened = self.runes_done = False
        self.runes_state = "pending"
        self.seen: set[str] = set()
        self.last_best: int | None = None
        # por id de acción (ban o pick): lo último que marcó Nachero, lo que eligió el jugador
        # (en el cliente o en el panel) y las que ya confirmó Nachero
        self.hovered: dict[int, int] = {}
        self.choice: dict[int, int] = {}
        self.confirmed: set[int] = set()
        self.context = None  # rol, aliados y rivales del último tick (para «Evaluar cualquier campeón»)

    def note(self, msg, kind="action"):
        if msg not in self.seen:
            self.seen.add(msg)
            log(msg, kind)

    def tick(self, s, acting, pickable=None, bannable=None, queue=None):
        """Recomienda (y en modo activo actua) en la champ select `s`. `queue` es el tipo de cola
        de `domain.queues.classify`; si falta, se trata como un draft de la Grieta."""
        ch, eng = self.champs, self.engine
        queue = queue or {}
        # a ciegas (sin bans): nadie ve los picks del otro, asi que no hay riesgo de counter
        blind = queue.get("kind") == "blind" and not has_bans(s)
        me = s["localPlayerCellId"]
        my = next((m for m in s["myTeam"] if m["cellId"] == me), {})
        # el rol que te asigna el cliente; en colas sin roles (blind, practice tool), tu rol principal
        role = (None if blind else my.get("assignedPosition")) or eng.main_role()
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
        enemy_left_after = 0 if blind else 5 - len(enemy_ids)
        if my_pick and not blind:
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
        self.context = {"role": role, "allies": allies, "enemy_ids": enemy_ids, "enemy_left_after": enemy_left_after}
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

        # ban y pick: Nachero marca su recomendación y confirma lo que esté marcado al final del
        # turno; si el jugador marca otro campeón (en el cliente o en el panel), manda el jugador
        taken = banned | set(ally_ids) | set(enemy_ids)
        choose = None
        if my_ban and my_ban["isInProgress"]:
            auto = CFG.get("auto_ban", False)
            turn = self.turn("ban", my_ban, bans[0] if bans else None, taken, acting, auto, auto, left, status)
            choose = {"kind": "ban", "options": [ch.brief(b["id"]) for b in bans[:5]], **turn}
        if my_pick and not my_pick["completed"] and best:
            turn = self.turn(
                "pick",
                my_pick,
                best,
                taken,
                acting,
                CFG.get("auto_hover_pick", False),
                CFG.get("auto_lock_pick", False),
                left,
                status,
            )
            if choose is None:
                choose = {"kind": "pick", "options": [ch.brief(p["id"]) for p in picks[:5]], **turn}
        if choose:
            choose["enabled"] = acting
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
            "queue": queue.get("name", ""),
            "blind": blind,
            "lane_known": ctx["lane_known"],
            "enemy_left_after": enemy_left_after,
            "choose": choose,
            "my_pick": (
                {**ch.brief(my_pick["championId"]), "completed": my_pick["completed"]}
                if my_pick and my_pick["championId"]
                else None
            ),
        }

    def turn(self, kind, action, target, taken, acting, hover, lock, left, status):
        """Tu ban o tu pick (`kind`) en la acción pendiente `action`.

        Con `hover`, marca la recomendación `target`; con `lock`, confirma lo que esté marcado a
        falta de `lock_when_seconds_left` s. Si lo marcado no es lo que marcó Nachero, es la
        elección del jugador: no se vuelve a marcar en ese turno y se confirma eso.
        Devuelve qué hay marcado y quién lo marcó, para el panel."""
        name = self.champs.name
        aid, cur = action["id"], action.get("championId") or 0
        secs = CFG["lock_when_seconds_left"]
        ban = kind == "ban"
        if cur and cur != self.hovered.get(aid):  # lo ha marcado el jugador (el registro lo dice el estado)
            self.choice[aid] = cur
        choice = self.choice.get(aid)
        if choice and choice in taken:  # lo ha elegido o baneado otro: vuelve la recomendación
            self.choice.pop(aid)
            if acting:
                self.note(f"{name(choice)} ya no está disponible: vuelvo a la recomendación", "warn")
            choice = None
        marked = choice or (cur if cur not in taken else 0)
        # el pick se puede marcar antes de tu turno (intención); el ban, solo en tu turno
        can_hover = not choice and hover and acting and target and (not ban or action["isInProgress"])
        if can_hover and cur != target["id"] and self.patch(aid, {"championId": target["id"]}):
            self.hovered[aid] = marked = target["id"]
        by = "player" if choice else ("nachero" if marked and marked == self.hovered.get(aid) else None)
        if action["isInProgress"]:
            final = marked or (target["id"] if target else 0)
            what = f"{'banear ' if ban else ''}{name(final)}" if final else ""
            if acting and lock and final and 0 < left <= secs:  # sin reloj (0) no se confirma a ciegas
                if aid not in self.confirmed and self.patch(aid, {"championId": final, "completed": True}):
                    self.confirmed.add(aid)
                    self.note(("Baneado " if ban else "Confirmado ") + name(final))
            elif acting and lock and final:
                if by == "player":
                    msg = f"Has elegido {what}: se confirmará {name(final)}"
                elif by == "nachero":
                    msg = f"{'Ban marcado' if ban else 'Marcado'} {name(final)} · se confirmará a falta de {secs} s"
                else:
                    msg = f"Te toca {'banear' if ban else 'elegir'}: {name(final)} · se confirmará a falta de {secs} s"
                status.append(("turn_auto", msg))
            elif by == "player":
                status.append(("turn", f"Has elegido {what}: confírmalo tú"))
            elif by == "nachero":
                status.append(("turn", f"{'Ban marcado' if ban else 'Marcado'} {name(final)}: confírmalo tú"))
            elif target:
                status.append(("turn", f"Te toca {'banear' if ban else 'elegir'}: {target['name']}"))
        elif not acting and hover and target and not ban:
            status.append(("info", f"Marcaría {target['name']}"))
        return {"marked": marked, "by": by}

    def patch(self, aid, body):
        """Cambia la acción `aid` de la champ select. True si el cliente lo acepta."""
        return self.lcu.raw("PATCH", f"/lol-champ-select/v1/session/actions/{aid}", body) is not None

    def choose(self, kind, cid):
        """Marca `cid` en tu ban o tu pick pendiente desde el panel: cuenta como elección del jugador.
        Devuelve (ok, mensaje)."""
        s = self.lcu.get("/lol-champ-select/v1/session") if self.lcu else None
        if not isinstance(s, dict) or "actions" not in s:
            return False, "No estás en la selección de campeón"
        me = s.get("localPlayerCellId")
        acts = [a for grp in s["actions"] for a in grp]
        action = next((a for a in acts if a["actorCellId"] == me and a["type"] == kind and not a["completed"]), None)
        if action is None:
            return False, "Ya no tienes ese turno pendiente"
        if kind == "ban" and not action.get("isInProgress"):
            return False, "Aún no te toca banear"
        name = self.champs.name(cid)
        prev = self.choice.get(action["id"])
        self.choice[action["id"]] = cid  # antes del cambio: que el bucle no lo pise mientras tanto
        if not self.patch(action["id"], {"championId": cid}):
            if prev is None:
                self.choice.pop(action["id"], None)
            else:
                self.choice[action["id"]] = prev
            return False, f"El cliente no deja marcar {name}"
        self.note(f"Has elegido {'banear ' if kind == 'ban' else ''}{name} desde el panel")
        return True, name

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
