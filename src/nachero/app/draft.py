"""Logica de la seleccion de campeon en soloq: lee la sesion del cliente, recomienda y (en modo activo) actua."""

import time
import webbrowser

from nachero.app.state import SPELL_IDS, TIMER_ES, log
from nachero.config import CFG
from nachero.domain import blind as BL
from nachero.domain import calibration
from nachero.domain import pool as POOL
from nachero.domain import runes as R
from nachero.domain import swaps as SW
from nachero.domain import tags as T
from nachero.domain.common import ROLE_ES, ROLE_SHORT
from nachero.domain.engine import ban_context, comp_notes, comp_summary
from nachero.domain.queues import has_bans


class Draft:
    def __init__(self, lcu, champs, engine, runes=None):
        self.lcu, self.champs, self.engine, self.runes = lcu, champs, engine, runes
        self.pool_plans: dict = {}  # plan de Tu pool por rol (#75), lo pone el bucle
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
        self.last_ids: dict[str, set[int]] = {}  # última lista válida de pickable/bannable en esta selección
        self.timings: dict[str, float] = {}  # cuánto tarda cada parte del último tick (registro)
        self.context = None  # rol, aliados y rivales del último tick (para «Evaluar cualquier campeón»)
        # ARAM: campeón que tienes, desde cuándo (los rerolls van rápido) y para cuál se importaron
        self.aram_seen: tuple[int, float] = (0, 0.0)
        self.aram_done: int = 0
        # calibración (#9): la mejor recomendación antes de confirmar y el registro al confirmar
        self.last_top: dict | None = None
        self.record: dict | None = None
        self.recorded = False
        self.record_ready = False  # con el orden de picks completo (#71)
        self.pre: dict = {}  # tu situación en el último tick antes de confirmar (hueco, riesgo)

    def note(self, msg, kind="action"):
        if msg not in self.seen:
            self.seen.add(msg)
            log(msg, kind)

    def tick(self, s, acting, pickable=None, bannable=None, queue=None):
        """Recomienda (y en modo activo actua) en la champ select `s`. `queue` es el tipo de cola
        de `domain.queues.classify`; si falta, se trata como un draft de la Grieta."""
        clock = time.perf_counter()
        self.timings = {}

        def lap(part):
            nonlocal clock
            now = time.perf_counter()
            self.timings[part] = self.timings.get(part, 0.0) + now - clock
            clock = now

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
            pickable = self.valid_ids("pickable", self.lcu.get("/lol-champ-select/v1/pickable-champion-ids"))
        # tu ban pendiente; si hubiera varios, primero el que está en curso (en soloq, los 10 a la vez)
        mine_bans = [a for a in acts if a["actorCellId"] == me and a["type"] == "ban" and not a["completed"]]
        my_ban = next((a for a in mine_bans if a.get("isInProgress")), mine_bans[0] if mine_bans else None)
        my_pick = next((a for a in acts if a["actorCellId"] == me and a["type"] == "pick"), None)
        if my_pick and not my_pick["completed"] and not my_pick.get("championId") and my.get("championPickIntent"):
            # tu intención de pick (planificación) cuenta como lo marcado en la acción
            my_pick = {**my_pick, "championId": my["championPickIntent"]}
        timer = s.get("timer", {})
        left = max(0, timer.get("adjustedTimeLeftInPhase", 0) / 1000)
        # en planificación el cliente ya da los bans como «en curso», pero ignora lo que se marque
        # en ellos (sin error): el turno de ban empieza de verdad en BAN_PICK
        planning = timer.get("phase") == "PLANNING"
        if my_ban and planning:
            my_ban = {**my_ban, "isInProgress": False}

        unavailable = banned | set(ally_ids) | set(enemy_ids) | ally_intent
        locked = my_pick["championId"] if my_pick and my_pick["completed"] and my_pick["championId"] else None
        # aliados: elegidos pesan 1; los que solo marcan, 0,5
        allies = [
            (m["championId"], 1.0) if m["championId"] else (m.get("championPickIntent") or 0, 0.5)
            for m in s["myTeam"]
            if m["cellId"] != me
        ]
        allies = [(c, w) for c, w in allies if c]
        # orden de picks: picks rivales sin hacer y los que quedan despues de tu turno (riesgo de counter)
        order = BL.pick_order(s["actions"])
        enemy_open = 0 if blind else (
            sum(1 for p in order if not p["ally"] and not p["completed"]) if order else 5 - len(enemy_ids)
        )  # fmt: skip
        enemy_left_after = 0 if blind else 5 - len(enemy_ids)
        if my_pick and not blind and order:
            enemy_left_after = 0 if my_pick["completed"] else BL.enemy_after(order, me)
        # rol de tus aliados (el cliente lo da en ranked): sinergias por pareja de roles
        ally_roles = {
            (m["championId"] or m.get("championPickIntent") or 0): m.get("assignedPosition")
            for m in s["myTeam"]
            if m["cellId"] != me and m.get("assignedPosition") and (m["championId"] or m.get("championPickIntent"))
        }
        self.context = {
            "role": role,
            "allies": allies,
            "enemy_ids": enemy_ids,
            "enemy_left_after": enemy_left_after,
            "unavailable": sorted(unavailable),
            "ally_roles": ally_roles,
        }
        lap("sesión")
        picks, ctx = eng.picks(
            role, unavailable, pickable, allies, enemy_ids, enemy_left_after=enemy_left_after, include=[locked],
            enemy_open=enemy_open, ally_roles=ally_roles,
        )  # fmt: skip
        enemy_roles = ctx["enemy_roles"]
        probs = ctx["enemy_role_probs"]
        if not locked:  # para la calibración: tu situación justo antes de confirmar
            self.pre = {
                "after": enemy_left_after,
                "open": enemy_open,
                "probs": probs,
                "gone": set(unavailable),
                "lane_p": ctx["lane_p"],
            }
        # «Tu equipo» en el panel: contigo y con lo marcado (como estimación) hasta que se confirme
        mine_now = my_pick.get("championId") if my_pick else None
        ally = comp_summary(
            [*ally_ids, *([mine_now] if locked else [])],
            ch,
            [c for c, w in allies if w < 1] + ([mine_now] if mine_now and not locked else []),
        )
        enemy = comp_summary(enemy_ids, ch)
        ally_ident = T.identity(allies, ch)
        enemy_ident = T.identity([(e, 1.0) for e in enemy_ids], ch)
        ally["identity"], enemy["identity"] = T.IDENTITY_ES[ally_ident[0]], T.IDENTITY_ES[enemy_ident[0]]
        ally["engage"], enemy["engage"] = round(ally_ident[2]["E"], 1), round(enemy_ident[2]["E"], 1)
        mine = next((p for p in picks if p["id"] == locked), None)
        picks = [p for p in picks if p["id"] != locked]
        best = picks[0] if picks else None
        if not locked:
            self.last_top = best
        elif mine and not self.recorded and queue.get("id") in CFG.get("history_queues", []):
            # para medir si acierta: tu campeón, su WR estimado y lo que recomendaba (sin demo)
            self.recorded = True
            fit = ctx.get("role_fit") or {}
            self.record = calibration.make_record(
                time.time() * 1000, queue, role, mine, self.last_top, fit.get("kind"),
                order=self.order_info(mine["id"], role, order, me),
            )  # fmt: skip
        if self.record and not self.record_ready and order and all(p["completed"] for p in order):
            # champ select terminada: quién eligió antes y después de ti (#71)
            mine_p = next((p for p in order if p["ally"] and p["cell"] == me), None)
            if mine_p:
                enemies = [p for p in order if not p["ally"] and p["cid"]]
                self.record = calibration.finish_order(
                    self.record,
                    [p["cid"] for p in enemies if p["group"] < mine_p["group"]],
                    [p["cid"] for p in enemies if p["group"] > mine_p["group"]],
                    enemy_roles,
                )
            self.record_ready = True
        # en soloq todos banean a la vez: no repetir el ban que ya ha marcado un aliado
        ally_ban_intent = {
            a["championId"]
            for a in acts
            if a["type"] == "ban" and not a["completed"] and a.get("isAllyAction") and a["actorCellId"] != me
        } - {0}
        blocked = (
            banned
            | set(ally_ids)
            | set(enemy_ids)
            | ally_intent
            | ally_ban_intent
            | {p["id"] for p in picks[:2]}
            | {locked}
        )
        bans = []
        if my_ban:  # solo mientras tu ban este pendiente
            if bannable is None:
                bannable = self.valid_ids("bannable", self.lcu.get("/lol-champ-select/v1/bannable-champion-ids"))
            # contra tu pick recomendado (o el que tengas marcado) y los picks o intenciones de tus aliados
            mine_now = (my_pick or {}).get("championId") or 0
            top = ([{"id": mine_now, "name": ch.name(mine_now)}] if mine_now and mine_now != (best or {}).get("id")
                   else []) + picks[:2]  # fmt: skip
            ally_roles = [
                (m["championId"] or m.get("championPickIntent") or 0, m.get("assignedPosition") or "",
                 1.0 if m["championId"] else 0.5)
                for m in s["myTeam"]
                if m["cellId"] != me
            ]  # fmt: skip
            # con qué probabilidad el rival de línea de cada uno elige después (#73)
            after_p = {
                m["cellId"]: (BL.enemy_after(order, m["cellId"]) / enemy_open if enemy_open and order else 1.0)
                for m in s["myTeam"]
            }
            ally_bans = [
                (c, r, w, after_p.get(m["cellId"], 1.0))
                for (c, r, w), m in zip(ally_roles, [m for m in s["myTeam"] if m["cellId"] != me], strict=True)
                if c and r
            ]
            my_after = None if blind else after_p.get(me, 1.0)
            bans = [
                b for b in eng.bans(role, top, blocked, ally_bans, my_after=my_after)
                if not bannable or b["id"] in bannable
            ][:5]  # fmt: skip
        status = []

        lap("picks y bans")
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

        # ban: con `auto_ban`, Nachero marca el recomendado en BAN_PICK y lo banea el cliente al acabar
        # el tiempo (nunca lo confirma). Pick: Nachero marca su recomendación (una vez por acción) y
        # confirma lo que esté marcado al final del turno. Si el jugador marca otro campeón (en el
        # cliente o en el panel), manda el jugador
        taken = banned | set(ally_ids) | set(enemy_ids)
        choose = None
        if my_ban and my_ban["isInProgress"]:  # en planificación ya sale como no en curso
            turn = self.ban_turn(my_ban, bans[0] if bans else None, taken, acting, status)
            choose = {"kind": "ban", "options": [ch.brief(b["id"]) for b in bans[:5]], **turn}
        if my_pick and not my_pick["completed"] and best:
            turn = self.turn(
                my_pick,
                best,
                taken,
                acting,
                CFG.get("auto_hover_pick", False),
                CFG.get("auto_lock_pick", False),
                left,
                status,
            )
            if not (my_ban and my_ban["isInProgress"]):
                choose = {"kind": "pick", "options": [ch.brief(p["id"]) for p in picks[:5]], **turn}
        if choose:
            choose["enabled"] = acting
        self.last_best = best["id"] if best else None

        # runas: la recomendada para el campeon confirmado (o vista previa del recomendado)
        lap("marcar")
        runes_info = self.handle_runes(locked or (best["id"] if best else None), role, bool(locked), acting, status)

        # coachless
        coach = None
        if my_pick and my_pick["completed"] and my_pick["championId"]:
            coach = f"https://coachless.gg/builds/{ch.slug(my_pick['championId'])}?role={role}"
            if acting and CFG["open_coachless_on_lock"] and not self.coachless_opened:
                self.coachless_opened = True
                webbrowser.open(coach)
                self.note(f"Abierta la build de {ch.name(my_pick['championId'])} en Coachless")

        lap("runas")
        for _kind, msg in status:
            self.note(("Observando · " if not acting else "") + msg, "hint")

        in_progress = {
            a["actorCellId"]: a["type"]
            for a in acts
            if a.get("isInProgress") and not a["completed"] and not (planning and a["type"] == "ban")
        }
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
        # intercambio de orden de pick (#74) y qué toca según tu hueco (#75)
        swap = None
        slot_line = ""
        if not blind and order and my_pick and not my_pick["completed"]:
            swap = self.swap_advice(s, order, role, me, (my_pick or {}).get("championId") or (best or {}).get("id"),
                                    probs, enemy_open, unavailable, acting)  # fmt: skip
            slot_line = POOL.slot_line(
                BL.ally_slot(order, me), ctx["lane_after"], ctx["lane_p"], self.pool_plans.get(role)
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
            "ban_context": ban_context(None if blind else (my_after if my_ban else None)),
            "swap": swap,
            "slot_line": slot_line,
            "lane_p": ctx["lane_p"],
            "risk_open": ctx["risk_open"],
            "enemy_open": enemy_open,
            "status": [{"kind": k, "msg": m} for k, m in status],
            "coachless": coach,
            "runes": runes_info,
            "mode": ctx["mode"],
            "queue": queue.get("name", ""),
            "blind": blind,
            "lane_known": ctx["lane_known"],
            "role_fit": ctx["role_fit"],
            "enemy_left_after": enemy_left_after,
            "choose": choose,
            # en tu turno de ban, el panel pone el ban recomendado en primer plano y el pick debajo
            "focus": "ban" if my_turn == "ban" and bans else "pick",
            "my_pick": (
                {**ch.brief(my_pick["championId"]), "completed": my_pick["completed"]}
                if my_pick and my_pick["championId"]
                else None
            ),
        }

    def turn(self, action, target, taken, acting, hover, lock, left, status):
        """Tu pick en la acción pendiente `action` (los bans solo se recomiendan, no se tocan).

        Con `hover`, Nachero marca la recomendación `target` una sola vez por acción; solo la
        vuelve a marcar si lo marcado deja de estar disponible (lo elige o lo banea otro). Si lo
        marcado no es lo que marcó Nachero, es la elección del jugador y manda en ese turno. Así
        no pisa al jugador aunque el cliente devuelva su cambio un tick tarde. Con `lock`, confirma
        lo que esté marcado a falta de `lock_when_seconds_left` s.
        Devuelve qué hay marcado y quién lo marcó, para el panel."""
        name = self.champs.name
        aid, cur = action["id"], action.get("championId") or 0
        secs = CFG.get("lock_when_seconds_left", 8)
        if cur and cur != self.hovered.get(aid):  # lo ha marcado el jugador (el registro lo dice el estado)
            self.choice[aid] = cur
        choice = self.choice.get(aid)
        if choice and choice in taken:  # lo ha elegido o baneado otro: vuelve la recomendación
            self.choice.pop(aid)
            if acting:
                self.note(f"{name(choice)} ya no está disponible: vuelvo a la recomendación", "warn")
            choice = None
        marked = choice or (cur if cur not in taken else 0)
        can_hover = not choice and hover and acting and target
        # una vez por acción: si ya marcó y el cliente lo refleja, no vuelve a hacerlo salvo que lo
        # marcado ya no valga. Si la acción sigue vacía (el cliente aceptó el PATCH pero no lo
        # aplicó), no cuenta como hecho y se reintenta
        fresh = aid not in self.hovered or not cur or cur in taken
        if can_hover and fresh and cur != target["id"]:
            # la sesión del tick puede ir con retraso: antes de marcar, lo que hay ahora en el cliente
            now = self.action_now(aid)
            if now and now != self.hovered.get(aid) and now not in taken:  # lo acaba de marcar el jugador
                self.choice[aid] = choice = marked = now
            elif now is not None and self.patch(aid, {"championId": target["id"]}):
                self.hovered[aid] = marked = target["id"]
            elif now is not None:  # se reintenta en el siguiente tick
                self.note(f"El cliente no deja marcar {name(target['id'])}: lo reintento", "warn")
        by = "player" if choice else ("nachero" if marked and marked == self.hovered.get(aid) else None)
        if action["isInProgress"]:
            final = marked or (target["id"] if target else 0)
            if acting and lock and final and 0 < left <= secs:  # sin reloj (0) no se confirma a ciegas
                now = self.action_now(aid) if aid not in self.confirmed else None
                final = now if now and now not in taken else final  # lo marcado en este momento
                if aid not in self.confirmed and self.patch(aid, {"championId": final, "completed": True}):
                    self.confirmed.add(aid)
                    self.note(f"Confirmado {name(final)}")
            elif acting and lock and final:
                if by == "player":
                    msg = f"Has elegido {name(final)}: se confirmará {name(final)}"
                elif by == "nachero":
                    msg = f"Marcado {name(final)} · se confirmará a falta de {secs} s"
                else:
                    msg = f"Te toca elegir: {name(final)} · se confirmará a falta de {secs} s"
                status.append(("turn_auto", msg))
            elif by == "player":
                status.append(("turn", f"Has elegido {name(final)}: confírmalo tú"))
            elif by == "nachero":
                status.append(("turn", f"Marcado {name(final)}: confírmalo tú"))
            elif target:
                status.append(("turn", f"Te toca elegir: {target['name']}"))
        elif not acting and hover and target:
            status.append(("info", f"Marcaría {target['name']}"))
        return {"marked": marked, "by": by}

    def ban_turn(self, action, target, taken, acting, status):
        """Tu ban en curso (solo en BAN_PICK). Con `auto_ban` en modo Activo marca `target` sin
        confirmarlo: lo banea el cliente al acabar el tiempo. Comprueba en el siguiente tick que el
        cliente lo muestra (si sigue en 0, reintenta) y nunca pisa un ban que marque el jugador."""
        name = self.champs.name
        aid, cur = action["id"], action.get("championId") or 0
        mine = self.hovered.get(aid)
        if cur and cur != mine:  # lo ha marcado el jugador (en el cliente o en el panel)
            self.choice[aid] = cur
        choice = self.choice.get(aid)
        if choice and choice in taken:
            self.choice.pop(aid)
            choice = None
        if (CFG.get("auto_ban", False) and acting and target and not choice
                and (not cur or cur in taken) and cur != target["id"]):  # fmt: skip
            now = self.action_now(aid)  # la sesión del tick puede ir con retraso
            if now and now != mine and now not in taken:
                self.choice[aid] = choice = now
            elif now is not None and self.patch(aid, {"championId": target["id"]}):
                self.hovered[aid] = target["id"]
            elif now is not None:
                self.note(f"El cliente no deja marcar {name(target['id'])}: lo reintento", "warn")
        mine = self.hovered.get(aid)
        if choice:
            status.append(("turn", f"Has elegido banear {name(choice)}"))
            return {"marked": choice, "by": "player"}
        if cur and cur == mine:  # solo cuando el cliente ya lo muestra
            msg = f"Ban marcado: {name(cur)} · lo banea el cliente al acabar el tiempo"
            self.note(msg)
            status.append(("turn_auto", msg))
            return {"marked": cur, "by": "nachero"}
        if target:
            why = f" · {target['reasons'][0]}" if target.get("reasons") else ""
            status.append(("turn", f"Te toca banear: {target['name']}{why}"))
        return {"marked": 0, "by": None}

    def valid_ids(self, kind, ids):
        """Ids de campeón reales (> 0) de `pickable`/`bannable`. En BAN_PICK el cliente devuelve
        `[-1]` en bannable: entonces vale la última lista válida (la de planificación) o, sin ella,
        ninguna (no se filtra; lo baneado o elegido ya se excluye aparte)."""
        got = {c for c in ids or [] if isinstance(c, int) and not isinstance(c, bool) and c > 0}
        if got:
            self.last_ids[kind] = got
            return got
        return set(self.last_ids.get(kind, set()))

    def action_now(self, aid):
        """El campeón marcado ahora mismo en la acción `aid` (0 si ninguno), leído del cliente; en un
        pick sin campeón, tu intención. None si no se puede leer."""
        s = self.lcu.get("/lol-champ-select/v1/session")
        if not isinstance(s, dict):
            return None
        action = next((a for grp in s.get("actions") or [] for a in grp if a.get("id") == aid), None)
        if action is None:
            return None
        cid = action.get("championId") or 0
        if not cid and action.get("type") == "pick":
            me = s.get("localPlayerCellId")
            cid = next((m.get("championPickIntent") or 0 for m in s.get("myTeam", []) if m.get("cellId") == me), 0)
        return cid

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
        planning = (s.get("timer") or {}).get("phase") == "PLANNING"
        if kind == "ban" and (planning or not action.get("isInProgress")):
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

    def pop_record(self) -> dict | None:
        """El registro de calibración pendiente de guardar (una vez por champ select), cuando ya se
        sabe quién eligió antes y después de ti. Si se esquiva antes, no se guarda."""
        if not self.record_ready:
            return None
        rec, self.record = self.record, None
        return rec

    def order_info(self, cid, role, order, me) -> dict:
        """Tu hueco y tu riesgo de counter al elegir (#71), con la situación del tick anterior."""
        pre, eng = self.pre or {}, self.engine
        aprobs = BL.after_probs(pre.get("probs", {}), pre.get("after", 0), pre.get("open", 0))
        gone = pre.get("gone", set())
        br = eng.blind_risk(cid, role, aprobs, gone)
        lane = eng.blind_risk(cid, role, {role: 1.0}, gone, eta=1.0)
        return {
            "slot": BL.ally_slot(order, me),
            "after": pre.get("after"),
            "lane_p": pre.get("lane_p"),
            "p_counter": round(br["p"], 3) if br["loaded"] else None,
            "lane_loss": round(-lane["risk"], 2) if lane["loaded"] else None,
        }

    def swap_advice(self, s, order, role, me, my_cid, probs, enemy_open, gone, acting):
        """Consejo de intercambio de orden de pick con un aliado (#74): solo aconseja; proponer,
        aceptar o rechazar es un clic del jugador en el panel."""
        if not my_cid:
            return None
        eng, ch = self.engine, self.champs

        def loss(cid, r, after):
            res = eng.blind_risk(cid, r, BL.after_probs(probs, after, enemy_open), gone)
            return -res["risk"], res["p"]

        allies = []
        for m in s["myTeam"]:
            pos = m.get("assignedPosition") or ""
            pa = next((p for p in order if p["ally"] and p["cell"] == m["cellId"]), None)
            if m["cellId"] == me or not pos or not pa or pa["completed"]:
                continue
            allies.append(
                {
                    "cell": m["cellId"],
                    "cid": m.get("championPickIntent") or 0,
                    "role": pos,
                    "after": BL.enemy_after(order, m["cellId"]),
                    "name": f"tu {ROLE_ES.get(pos, pos)}",
                    "slot": BL.ally_slot(order, m["cellId"]),
                }
            )
        me_d = {"cell": me, "cid": my_cid, "role": role, "after": BL.enemy_after(order, me)}
        adv = SW.advise(me_d, allies, loss, s.get("pickOrderSwaps") or [], eng.bl["swap_min_gain"])
        if not adv:
            return None
        ally_name = ch.name(adv["ally_cid"]) if adv["ally_cid"] else ""
        return {
            **adv,
            "text": SW.message(adv, ch.name(my_cid), ally_name),
            "chat": SW.chat_line(adv, ch.name(my_cid), ally_name),
            "ally": adv["ally"],
            "can_act": bool(acting and adv.get("swap_id") is not None),
        }

    def swap(self, op, swap_id):
        """Pide, acepta o rechaza un intercambio de orden de pick (clic del jugador en el panel).
        Devuelve (ok, mensaje)."""
        if op not in ("request", "accept", "decline", "cancel"):
            return False, "Operación no válida"
        ok = self.lcu.raw("POST", f"/lol-champ-select/v1/session/swaps/{swap_id}/{op}") is not None
        verb = {"request": "Cambio pedido", "accept": "Cambio aceptado", "decline": "Cambio rechazado",
                "cancel": "Petición cancelada"}[op]  # fmt: skip
        if ok:
            self.note(f"{verb} desde el panel")
            return True, verb
        return False, "El cliente no deja hacer el cambio"

    ARAM_SETTLE = 1.5  # segundos con el mismo campeón antes de importar (reroll, banquillo)

    def aram_tick(self, s, acting, now=None):
        """ARAM: importa la página de runas de ARAM del campeón que tengas y la cambia si cambias de
        campeón (reroll o banquillo). Nada más: ni picks, ni bans, ni hechizos. Resumen para el panel."""
        now = time.time() if now is None else now
        me = s.get("localPlayerCellId")
        cid = next((m.get("championId") or 0 for m in s.get("myTeam", []) if m.get("cellId") == me), 0)
        if not cid:
            return {"champ": None, "runes": None}
        if cid != self.aram_seen[0]:
            self.aram_seen = (cid, now)
        name = self.champs.name(cid)
        out = {"champ": self.champs.brief(cid), "runes": None}
        if not self.runes or not CFG.get("import_runes", True):
            return out
        sets = self.engine.lola.runes(cid, "aram")
        if sets is None:
            out["runes"] = {"state": "loading"}
            return out
        source = CFG.get("runes_source", "pick")
        rune_set = sets.get(source) or sets.get("pick") or sets.get("win")
        if not rune_set:
            out["runes"] = {"state": "none"}
            return out
        info = {**(self.runes.describe(rune_set) or {}), "source": "ARAM"}
        if self.aram_done == cid:
            out["runes"] = {**info, "state": self.runes_state}
            return out
        if not acting:
            out["runes"] = {**info, "state": "would"}
            self.note(f"Observando · Importaría runas de ARAM para {name}", "hint")
            return out
        if now - self.aram_seen[1] < self.ARAM_SETTLE:  # espera a que deje de cambiar
            out["runes"] = {**info, "state": "preview"}
            return out
        self.aram_done = cid
        ok, msg = self.runes.apply(self.lcu, name, "ARAM", rune_set)
        self.runes_state = "imported" if ok else "failed"
        self.note(f"Runas de ARAM importadas para {name}" if ok else msg, "action" if ok else "warn")
        out["runes"] = {**info, "state": self.runes_state}
        return out

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
