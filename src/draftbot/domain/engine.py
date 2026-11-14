"""Perfil del jugador y motor de recomendacion de picks y bans.

Todas las piezas se expresan en puntos de winrate (pp) para poder sumarlas:

  WR estimado = 50 + meta + tu + rival_linea + resto_rival + encaje_aliado + respuesta_comp + riesgo_counter

  meta            WR del campeon en tu rol en Master+ menos la media, encogido por muestra; penaliza fuera de rol.
  tu              (solo modo "pool") experiencia + forma + tu residuo de WR/rendimiento con el campeon.
  rival_linea     "delta 2" de Lolalytics contra el enemigo que juega tu linea (rol estimado).
  resto_rival     "delta 2" contra los demas enemigos, ponderado por cuanto interactua tu rol con su linea.
  encaje_aliado   lo que le falta a tu equipo (dano AP/AD, frontline, control, dano) y lo que sobra.
  respuesta_comp  ajustes pequenos contra la composicion rival (mucho control, mucha amenaza de entrada...).
  riesgo_counter  si tu rival de linea aun no ha elegido y le quedan picks: castiga campeones faciles de counterear.

  delta 2 = WR real del enfrentamiento - WR esperado por la fuerza de ambos campeones. Mide solo la
  interaccion, por eso se suma a la fuerza del meta sin contarla dos veces.

Bans: valor = presencia del campeon en tu rol x (0,4 x fuerza en el meta + cuanto counterea tus picks).
La fuerza pura cuenta poco porque, si nadie lo banea, puede caer igual en tu equipo que en el rival.
"""

import itertools
import math
from collections import defaultdict

from draftbot.domain import tags as T
from draftbot.domain.common import ROLES, shrink
from draftbot.domain.common import tier_name as TIER

# ---------------------------------------------------------------- utilidades del draft
# Cuanto pesa el enfrentamiento contra cada linea enemiga segun tu rol (tu linea = 1).
LANE_WEIGHT = {
    "top": {"top": 1.0, "jungle": 0.45, "middle": 0.25, "bottom": 0.2, "utility": 0.2},
    "jungle": {"top": 0.35, "jungle": 1.0, "middle": 0.5, "bottom": 0.35, "utility": 0.4},
    "middle": {"top": 0.25, "jungle": 0.5, "middle": 1.0, "bottom": 0.25, "utility": 0.3},
    "bottom": {"top": 0.2, "jungle": 0.35, "middle": 0.25, "bottom": 1.0, "utility": 0.75},
    "utility": {"top": 0.2, "jungle": 0.4, "middle": 0.3, "bottom": 0.75, "utility": 1.0},
}


def team_profile(members, champs):
    """members: [(cid, peso)]; peso 1 = elegido, 0,5 = solo marcado."""
    p = {
        "w": 0.0,
        "ap": 0.0,
        "ad": 0.0,
        "apd": 0.0,
        "add": 0.0,
        "front": 0.0,
        "cc": 0.0,
        "dmg": 0.0,
        "carry": 0.0,
        "assassin": 0.0,
        "dive": 0.0,
        "n": 0,
    }
    for cid, w in members:
        if not cid or w <= 0:
            continue
        i = champs.info(cid)
        p["w"] += w
        p["n"] += 1
        p["ap"] += w * (i["dmg"] == "AP")
        p["ad"] += w * (i["dmg"] == "AD")
        # reparto de dano ponderado por cuanto dano hace cada uno (un tanque AP aporta poco dano magico)
        share = {"AP": (1, 0), "AD": (0, 1)}.get(i["dmg"], (0.5, 0.5))
        p["apd"] += w * i["damage"] * share[0]
        p["add"] += w * i["damage"] * share[1]
        p["front"] += w * (i["durability"] >= 3 or "tank" in i["roles"])
        p["cc"] += w * i["cc"]
        p["dmg"] += w * i["damage"]
        p["carry"] += w * (i["damage"] >= 3)
        p["assassin"] += w * ("assassin" in i["roles"])
        p["dive"] += w * ("assassin" in i["roles"] or (i["mobility"] >= 3 and i["damage"] >= 2))
    return p


def comp_summary(ids, champs):
    t = team_profile([(c, 1) for c in ids], champs)
    return {"n": t["n"], "ap": round(t["ap"]), "ad": round(t["ad"]), "front": round(t["front"]), "cc": round(t["cc"])}


def comp_notes(ally, enemy):
    notes = []
    if ally["n"] >= 2 and ally["ap"] == 0:
        notes.append("Tu equipo no tiene daño mágico todavía.")
    if ally["n"] >= 2 and ally["ad"] == 0:
        notes.append("Tu equipo no tiene daño físico todavía.")
    if ally["n"] >= 3 and ally["front"] == 0:
        notes.append("Sin frontline aliada: un pick con aguante vale más.")
    if enemy["n"] >= 3 and enemy["ad"] >= 3:
        notes.append(f"Rival muy físico ({enemy['ad']} AD): la armadura rinde mucho.")
    if enemy["n"] >= 3 and enemy["ap"] >= 3:
        notes.append(f"Rival muy mágico ({enemy['ap']} AP): la resistencia mágica rinde mucho.")
    if enemy["cc"] >= 9:
        notes.append("Mucho control en el rival: Mercurio o QSS, y cuidado con picks inmóviles.")
    return notes


def infer_roles(enemy_ids, lola):
    """Asignacion conjunta mas probable de roles a los enemigos (maximiza el producto de % por linea)."""
    ids = [c for c in enemy_ids if c][:5]
    if not ids:
        return {}
    pct = {}
    for cid in ids:
        for r in ROLES:
            t = lola.tier(r)
            pct[(cid, r)] = (t or {}).get("champs", {}).get(str(cid), {}).get("pct", 0) if t else 0
    best, best_score = None, -1e9
    for perm in itertools.permutations(ROLES, len(ids)):
        sc = sum(math.log(pct[(c, r)] + 0.5) for c, r in zip(ids, perm, strict=True))
        if sc > best_score:
            best, best_score = perm, sc
    return dict(zip(ids, best, strict=True))


# ---------------------------------------------------------------- motor
class Engine:
    def __init__(self, champs, lola, player, cfg):
        self.champs, self.lola, self.player, self.cfg = champs, lola, player, cfg

    def w(self, k):
        return float(self.cfg.get("weights", {}).get(k, 1.0))

    @property
    def mode(self):
        return "meta" if self.cfg.get("pick_mode") == "meta" else "pool"

    # -- fuerza del campeon en el parche
    def meta(self, cid, role):
        t = self.lola.tier(role)
        if not t:
            return 0.0, None
        c = t["champs"].get(str(cid))
        if not c:
            return -2.5, None
        delta = shrink(c["wr"] - t["avg"], c["games"], 1500)
        offrole = -2.5 * (1 - min(1.0, c["games"] / 1500))
        return delta + offrole, c

    def candidates(self, role):
        t = self.lola.tier(role)
        out = set()
        if self.mode == "meta":
            if t:
                viable = [(int(cid), c) for cid, c in t["champs"].items() if c["games"] >= 1000]
                viable.sort(key=lambda x: -self.meta(x[0], role)[0])
                out |= {cid for cid, _ in viable[:45]}
        else:
            for cid, r in self.player.by_cr:
                if r == role:
                    out.add(cid)
            if t:
                ranked = sorted(
                    t["champs"].items(), key=lambda kv: -(kv[1]["wr"] - t["avg"]) * min(1, kv[1]["games"] / 3000)
                )
                out |= set([int(cid) for cid, c in ranked if c["games"] >= 1500][:18])
                for cid, m in self.player.mastery.items():
                    c = t["champs"].get(str(cid))
                    if m.get("championPoints", 0) >= 40000 and c and c["games"] >= 1500:
                        out.add(cid)
        never = {self.champs.id(n) for n in self.cfg.get("never_pick", [])}
        return {c for c in out if c and c not in never}

    # -- contra el rival
    def vs_enemy(self, cid, role, enemy_roles):
        """Suma de delta 2 contra cada enemigo, ponderada por linea. Devuelve (linea, resto, items, cargado)."""
        lanes = self.lola.matchups(cid, role)
        if lanes is None:
            return 0.0, 0.0, [], False
        lane_sum, rest_sum, items = 0.0, 0.0, []
        for e, er in enemy_roles.items():
            row = lanes.get(er, {}).get(str(e))
            if not row:
                continue
            is_lane = er == role
            weight = LANE_WEIGHT[role][er]
            v = shrink(row["d2"], row["n"], 250 if is_lane else 400) * weight
            if is_lane:
                lane_sum += v
            else:
                rest_sum += v
            items.append(
                {
                    "id": e,
                    "name": self.champs.name(e),
                    "d2": round(row["d2"], 1),
                    "wr": row["wr"],
                    "n": row["n"],
                    "lane": is_lane,
                    "role": er,
                    "weight": weight,
                    "value": round(v, 2),
                }
            )
        items.sort(key=lambda x: (not x["lane"], x["d2"]))
        return lane_sum, rest_sum, items, True

    def counter_risk(self, cid, role, lane_known, enemy_left_after):
        """Si tu rival de linea aun puede elegir despues de ti: media de los 3 peores matchups habituales."""
        if lane_known or enemy_left_after <= 0:
            return 0.0, []
        rows = self.lola.counters(cid, role)
        if not rows:
            return 0.0, []
        common = sorted(
            (r["d2"], int(e)) for e, r in rows.items() if r.get("pr", 0) >= 2.0 and r["n"] >= 150 and r["d2"] < 0
        )[:3]
        if not common:
            return 0.0, []
        avg_bad = sum(min(0.0, d) for d, _ in common) / len(common)
        scale = 0.3 * min(1.0, enemy_left_after / 2)
        return scale * avg_bad, [{"id": e, "name": self.champs.name(e), "d2": round(d, 1)} for d, e in common]

    # -- encaje con tu equipo
    def ally_fit(self, cid, allies):
        i = self.champs.info(cid)
        a = team_profile(allies, self.champs)
        known = min(1.0, a["w"] / 4)
        b, why = 0.0, []
        if a["w"] >= 1.5:
            typed = a["apd"] + a["add"]
            if typed and a["apd"] / typed < 0.2:
                if i["dmg"] == "AP":
                    b += 1.6 * known
                    why.append(("+", "aporta el daño mágico que falta"))
                elif i["dmg"] == "AD":
                    b -= 0.6 * known
                    why.append(("-", "más daño físico a un equipo físico"))
            if typed and a["add"] / typed < 0.2:
                if i["dmg"] == "AD":
                    b += 1.6 * known
                    why.append(("+", "aporta el daño físico que falta"))
                elif i["dmg"] == "AP":
                    b -= 0.6 * known
                    why.append(("-", "más daño mágico a un equipo mágico"))
        if a["front"] < 0.5 and a["w"] >= 2:
            if i["durability"] >= 3:
                b += 1.1 * known
                why.append(("+", "da la frontline que falta"))
            elif i["durability"] == 1 and a["w"] >= 3:
                b -= 0.4
                why.append(("-", "otro campeón frágil sin frontline"))
        if a["w"] >= 2 and a["cc"] / a["w"] < 1.6 and i["cc"] >= 3:
            b += 0.7 * known
            why.append(("+", "aporta el control que le falta al equipo"))
        if a["w"] >= 2 and a["dmg"] / a["w"] < 2.0 and i["damage"] >= 3:
            b += 0.7 * known
            why.append(("+", "aporta daño a un equipo con poco"))
        if a["carry"] >= 3 and i["damage"] >= 3 and i["utility"] <= 1 and i["durability"] <= 1:
            b -= 0.5
            why.append(("-", "ya hay muchos carries"))
        cb, cwhy = T.cohesion(cid, allies, self.champs)  # condicion de victoria (engage, identidad, followup)
        return b + cb, why + cwhy

    # -- respuesta a la composicion rival (heuristicas pequenas: los matchups ya miden lo principal)
    def vs_comp(self, cid, enemies):
        i = self.champs.info(cid)
        e = team_profile([(c, 1) for c in enemies], self.champs)
        b, why = 0.0, []
        if e["n"] >= 3 and e["cc"] >= 9 and i["mobility"] <= 1:
            b -= 0.6
            why.append(("-", "poco móvil contra mucho control"))
        if e["n"] >= 2 and e["dive"] >= 2 and i["durability"] <= 1 and i["mobility"] <= 1:
            b -= 0.6
            why.append(("-", "frágil contra mucha amenaza de entrada"))
        if e["n"] >= 3 and e["front"] < 0.5 and "assassin" in i["roles"]:
            b += 0.4
            why.append(("+", "rival sin frontline: objetivos blandos"))
        if (
            e["n"] >= 3
            and e["front"] >= 2
            and i["dmg"] in ("AD", "AP")
            and i["damage"] >= 3
            and "marksman" in i["roles"]
        ):
            b += 0.3
            why.append(("+", "daño sostenido contra mucha frontline"))
        cb, cwhy = T.counter_comp(cid, enemies, self.champs)
        # tope: responder a la comp nunca debe pesar mas que perder la linea
        return max(-1.2, min(1.2, b + cb)), why + cwhy

    def style(self, cid):
        i = self.champs.info(cid)
        st = self.cfg.get("style", {})
        return (i["damage"] - 2) * st.get("carry_weight", 1.0) * 0.3 - (i["utility"] - 2) * st.get(
            "utility_weight", 0.2
        ) * 0.3

    # -- recomendacion principal
    def picks(self, role, unavailable, pickable, allies, enemy_ids, enemy_left_after=5, include=()):
        """allies: [(cid, peso)] de tus aliados (peso 0,5 si solo marcan). enemy_ids: picks rivales."""
        enemy_roles = infer_roles(enemy_ids, self.lola)
        lane_known = any(r == role for r in enemy_roles.values())
        forced = {c for c in include if c}
        pool_mode = self.mode == "pool"
        out = []
        for cid in self.candidates(role) | forced:
            if cid not in forced and (cid in unavailable or (pickable and cid not in pickable)):
                continue
            meta, tierrow = self.meta(cid, role)
            you = self.player.components(cid, role)
            lane_v, rest_v, mu_items, loaded = self.vs_enemy(cid, role, enemy_roles)
            risk, risk_items = self.counter_risk(cid, role, lane_known, enemy_left_after)
            fit, fit_why = self.ally_fit(cid, allies)
            vc, vc_why = self.vs_comp(cid, enemy_ids)
            parts = {
                "you": you["total"] * self.w("pool") if pool_mode else 0.0,
                "meta": meta * self.w("meta"),
                "lane": lane_v * self.w("matchup"),
                "enemies": rest_v * self.w("matchup"),
                "allies": (fit + self.style(cid)) * self.w("comp"),
                "vs_comp": vc * self.w("comp"),
                "risk": risk * self.w("matchup"),
            }
            bonus = float(self.cfg.get("pool_bonus", {}).get(self.champs.name(cid), 0)) if pool_mode else 0.0
            total = sum(parts.values()) + bonus
            out.append(
                {
                    "id": cid,
                    "name": self.champs.name(cid),
                    "est": round(50 + total, 1),
                    "total": total,
                    "parts": {k: round(v, 1) for k, v in parts.items()},
                    "why": [{"sign": s, "text": t} for s, t in fit_why + vc_why],
                    "dmg": self.champs.info(cid)["dmg"],
                    "games": you["games"],
                    "wr": round(100 * you["wins"] / you["games"]) if you["games"] else None,
                    "mastery": you["mastery"],
                    "exp": round(you["exp_games"]),
                    "recent30": you["recent30"],
                    "tier": TIER(tierrow),
                    "meta_wr": tierrow["wr"] if tierrow else None,
                    "meta_games": tierrow["games"] if tierrow else 0,
                    "matchups": mu_items,
                    "matchups_loaded": loaded,
                    "risk_items": risk_items,
                }
            )
        out.sort(key=lambda r: -r["total"])
        for r in out[:12]:
            if not r["matchups_loaded"]:
                self.lola.request(r["id"], role, self.champs.slug(r["id"]))
        ctx = {
            "enemy_roles": enemy_roles,
            "lane_known": lane_known,
            "enemy_left_after": enemy_left_after,
            "mode": self.mode,
        }
        return out, ctx

    def bans(self, role, my_top, blocked):
        """my_top: lista de picks recomendados (ya ordenada). blocked: ids que no se pueden/quieren banear."""
        t = self.lola.tier(role)
        if not t:
            return []
        weights = [0.5, 0.3, 0.2]
        counter_map = defaultdict(float)
        counter_who = defaultdict(list)
        for wgt, p in zip(weights, my_top[:3], strict=False):
            rows = self.lola.counters(p["id"], role) or {}
            for e, row in rows.items():
                counter_map[e] += wgt * -shrink(row["d2"], row["n"], 250)
                if row["d2"] <= -2:
                    counter_who[e].append((p["name"], round(row["d2"], 1)))
        out = []
        for cid, c in t["champs"].items():
            icid = int(cid)
            if icid in blocked or c["games"] < 1000:
                continue
            presence = c["pr"] / 100
            strength = shrink(c["wr"] - t["avg"], c["games"], 1500)
            value = presence * (0.4 * strength + counter_map.get(cid, 0.0)) * 100
            if value <= 0:
                continue
            reasons = []
            if counter_who.get(cid):
                reasons.append("counterea a " + ", ".join(f"{n} ({d:+.1f})" for n, d in counter_who[cid][:2]))
            if strength >= 1:
                reasons.append(f"{c['wr']:.1f}% WR en Master+")
            reasons.append(f"{c['pr']:.1f}% pick · {c['br']:.0f}% ban")
            out.append(
                {
                    "id": icid,
                    "name": self.champs.name(icid),
                    "value": round(value, 2),
                    "reasons": reasons,
                    "tier": TIER(c),
                }
            )
        prio = {self.champs.id(n): i for i, n in enumerate(self.cfg.get("ban_priority", {}).get(role, []))}
        for b in out:
            if b["id"] in prio:
                b["value"] += 5 - prio[b["id"]] * 0.5
                b["reasons"].insert(0, "en tu lista de bans")
        return sorted(out, key=lambda b: -b["value"])
