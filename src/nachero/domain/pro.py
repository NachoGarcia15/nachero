"""Simulador de drafts competitivos.

Datos de competitivo: nachero.sources.golgg.

Conceptos aplicados (draft profesional):
  - Prioridad: campeones fuertes y seguros a ciegas (PrioScore de gol.gg).
  - Flex: un campeon que va a varios roles esconde informacion en la primera rotacion.
  - Composicion cohesionada con condicion de victoria (engage/dive, outrange, proteger) y siempre algo de engage.
  - Matchups favorables (datos Master+ de Lolalytics como aproximacion; en pro las muestras son pequenas).
  - Counter a la composicion rival en los ultimos picks, sin sacrificar la linea.
  - Denegar: quitar al rival un pick que le encaja.
  - Bans: no banear lo que vas a coger; en la segunda ronda, banear los roles que le faltan al rival
    y los counters de tus picks.
"""

import itertools
import math

from nachero.domain import roles as R
from nachero.domain import tags as T
from nachero.domain.common import ROLE_SHORT, ROLES, norm

# Orden de draft de torneo: 6 bans, 6 picks, 4 bans, 4 picks
DRAFT_ORDER = [
    ("blue", "ban"),
    ("red", "ban"),
    ("blue", "ban"),
    ("red", "ban"),
    ("blue", "ban"),
    ("red", "ban"),
    ("blue", "pick"),
    ("red", "pick"),
    ("red", "pick"),
    ("blue", "pick"),
    ("blue", "pick"),
    ("red", "pick"),
    ("red", "ban"),
    ("blue", "ban"),
    ("red", "ban"),
    ("blue", "ban"),
    ("red", "pick"),
    ("blue", "pick"),
    ("blue", "pick"),
    ("red", "pick"),
]


def parse_fixed(raw):
    """Roles elegidos a mano en el panel ({"cid": "rol"} en JSON) como {cid: rol}; ignora lo invalido."""
    out = {}
    for k, v in (raw or {}).items() if isinstance(raw, dict) else ():
        try:
            cid = int(k)
        except (TypeError, ValueError):
            continue
        if v in ROLES:
            out[cid] = v
    return out


# ---------------------------------------------------------------- motor
class ProEngine:
    def __init__(self, champs, lola, engine, gol):
        self.champs, self.lola, self.engine, self.gol = champs, lola, engine, gol

    # -- datos por campeon
    def pro(self, ds, cid):
        return ds["all"].get(norm(self.champs.name(cid))) if ds else None

    def pro_share(self, ds, cid, role):
        """Fraccion de partidas pro del campeon en ese rol, o None si no hay datos pro suficientes."""
        key = norm(self.champs.name(cid))
        if ds:
            tot = sum(ds["roles"][r].get(key, 0) for r in ROLES)
            if tot >= 2:
                return ds["roles"][role].get(key, 0) / tot
        return None

    def role_share(self, ds, cid, role):
        """Fraccion de partidas pro del campeon en ese rol; si no hay datos pro, % de Master+."""
        p = self.pro_share(ds, cid, role)
        return p if p is not None else self.engine.roles.split(cid).get(role, {}).get("pct", 0.0) / 100

    def role_weight(self, ds, cid, role):
        """Peso del rol para asignar roles: lo que dicen el torneo y Master+, con suelo para fuera de rol."""
        return max(self.pro_share(ds, cid, role) or 0.0, self.engine.roles.weight(cid, role))

    def assign(self, ds, picks, fixed=None):
        """Roles mas probables de un equipo (maximiza el producto de reparto por rol).
        `fixed` = {cid: rol} elegidos a mano en el panel: se respetan y el resto se reparte."""
        ids = [c for c in picks if c][:5]
        if not ids:
            return {}
        fixed = {c: r for c, r in (fixed or {}).items() if c in ids and r in ROLES}
        taken = set()
        for c in ids:  # dos picks fijados al mismo rol: gana el primero
            if c in fixed and fixed[c] in taken:
                del fixed[c]
            elif c in fixed:
                taken.add(fixed[c])
        free = [c for c in ids if c not in fixed]
        roles_left = [r for r in ROLES if r not in taken]
        best, bs = (), -1e9
        for perm in itertools.permutations(roles_left, len(free)):
            sc = sum(math.log(self.role_weight(ds, c, r)) for c, r in zip(free, perm, strict=True))
            if sc > bs:
                best, bs = perm, sc
        out = dict(zip(free, best, strict=True)) | fixed
        return {c: out[c] for c in ids}

    def priority(self, ds, cid):
        p = self.pro(ds, cid)
        if not p:
            meta = max((self.engine.meta(cid, r)[0] for r in ROLES), default=0.0)
            return 0.4 * max(-2.0, meta), None
        games = p["wins"] + p["losses"]
        wr_part = (p["wins"] - games * 0.5) / (games + 20) * 100 * 0.15
        return 4.0 * p["prio"] / 100 + wr_part, p

    # -- estado del draft
    def state(self, st):
        side_lists = {
            s: {
                "bans": [c for c in st.get(s, {}).get("bans", []) if c],
                "picks": [c for c in st.get(s, {}).get("picks", []) if c],
            }
            for s in ("blue", "red")
        }
        counts = {("blue", "ban"): 0, ("red", "ban"): 0, ("blue", "pick"): 0, ("red", "pick"): 0}
        step = 0
        for side, kind in DRAFT_ORDER:
            have = len(side_lists[side]["bans" if kind == "ban" else "picks"])
            if counts[(side, kind)] < have:
                counts[(side, kind)] += 1
                step += 1
            else:
                break
        return side_lists, step

    def suggest(self, st):
        tour = st.get("tournament")
        ds = self.gol.dataset(tour) if tour else None
        teams, step = self.state(st)
        fearless = set(c for c in st.get("fearless", []) if c)
        used = fearless | {c for s in teams.values() for k in ("bans", "picks") for c in s[k]}
        fixed = {s: parse_fixed((st.get("roles") or {}).get(s)) for s in teams}
        roles = {s: self.assign(ds, teams[s]["picks"], fixed[s]) for s in teams}
        open_roles = {s: [r for r in ROLES if r not in roles[s].values()] for s in teams}
        done = step >= len(DRAFT_ORDER)
        side, kind = DRAFT_ORDER[step] if not done else (None, None)
        res = {
            "step": step,
            "side": side,
            "kind": kind,
            "done": done,
            "roles": roles,
            "open_roles": open_roles,
            "teams": {},
            "data": self.data_info(ds, tour),
        }
        for s in ("blue", "red"):
            other = "red" if s == "blue" else "blue"
            res["teams"][s] = self.team_summary(teams[s]["picks"], teams[other]["picks"], roles[s], roles[other])
            for p in res["teams"][s]["picks"]:
                p["fixed"] = p["id"] in fixed[s]
        if done:
            res["verdict"] = self.verdict(res["teams"])
            return res
        other = "red" if side == "blue" else "blue"
        cands = self.candidates(ds, used)
        if kind == "pick":
            res["suggestions"] = self.picks(ds, cands, side, other, teams, roles, open_roles, step)[:8]
        else:
            res["suggestions"] = self.bans(ds, cands, side, other, teams, roles, open_roles, step)[:8]
        return res

    def data_info(self, ds, tour):
        if not ds:
            return {"tournament": tour, "loaded": False, "loading": tour in self.gol.loading}
        return {"tournament": tour, "loaded": True, "games": ds["games"], "updated": ds["t"]}

    def candidates(self, ds, used):
        """Lo jugado o baneado en el torneo y, por rol, los 12 mas jugados en Master+ entre los que lo
        tienen de rol principal o flex. Cada uno se sugiere en cualquiera de sus roles viables."""
        ids = set()
        if ds:
            for key, p in ds["all"].items():
                if p["picks"] + p["bans"] > 0:
                    cid = self.champs.by_name.get(p["name"].lower()) or self._by_norm(key)
                    if cid:
                        ids.add(cid)
        for r in ROLES:
            t = self.lola.tier(r)
            if t:
                ranked = sorted(t["champs"].items(), key=lambda kv: -kv[1]["pr"])
                viable = [int(c) for c, _ in ranked if R.at_least(self.engine.roles.category(int(c), r), "flex")]
                ids |= set(viable[:12])
        return [c for c in ids if c not in used and c in self.champs.by_id]

    def _by_norm(self, key):
        if not hasattr(self, "_norm_map"):
            self._norm_map = {norm(c["name"]): cid for cid, c in self.champs.by_id.items()}
            self._norm_map.update(
                {
                    "nunu": self.champs.id("Nunu & Willump"),
                    "wukong": self.champs.id("Wukong"),
                    "renata": self.champs.id("Renata Glasc"),
                }
            )
        return self._norm_map.get(key)

    def feasible(self, ds, cid, open_r, thr=0.12):
        """Roles libres que el campeon puede jugar, con su peso: los que juega en el torneo (>= `thr`
        de sus partidas pro) y sus roles principal y flex en Master+."""
        out = []
        for r in open_r:
            pro = self.pro_share(ds, cid, r)
            if (pro is not None and pro >= thr) or R.at_least(self.engine.roles.category(cid, r), "flex"):
                out.append((r, self.role_weight(ds, cid, r)))
        return out

    def roles_of(self, ds, cid):
        """Roles viables del campeon (filtro por rol de la cuadricula del simulador)."""
        return [r for r, _ in self.feasible(ds, cid, ROLES)]

    def enemy_left_in_role(self, step, other):
        """Picks que le quedan al rival despues de este paso."""
        return sum(1 for s, k in DRAFT_ORDER[step + 1 :] if s == other and k == "pick")

    # -- picks
    def picks(self, ds, cands, side, other, teams, roles, open_roles, step):
        mine, theirs = teams[side]["picks"], teams[other]["picks"]
        enemy_roles = {c: r for c, r in roles[other].items()}
        first_rotation = step < 12
        left_after = self.enemy_left_in_role(step, other)
        out = []
        for cid in cands:
            feas = self.feasible(ds, cid, open_roles[side])
            if not feas:
                continue
            role, share = max(feas, key=lambda x: x[1])
            prio, p = self.priority(ds, cid)
            parts = {"prio": prio}
            why = []
            if p and p["prio"] >= 50:
                why.append(("+", f"prioridad alta ({p['prio']:.0f}%)"))
            nflex = len(self.feasible(ds, cid, ROLES, 0.15))
            parts["flex"] = 0.6 if (first_rotation and nflex >= 2 and len(open_roles[side]) >= 3) else 0.0
            if parts["flex"]:
                why.append(("+", "flex: esconde a qué rol va"))
            fit, fit_why = self.engine.ally_fit(cid, [(c, 1.0) for c in mine])
            parts["comp"] = fit
            why += fit_why
            vc, vc_why = self.engine.vs_comp(cid, theirs)  # incluye el counter a la composicion rival
            parts["counter"] = vc
            why += vc_why
            lane_v, rest_v, items, loaded = self.engine.vs_enemy(cid, role, enemy_roles)
            parts["matchup"] = 0.6 * lane_v + 0.4 * rest_v  # Master+ como aproximacion
            opp_known = role in enemy_roles.values()
            risk, risk_items = (0.0, [])
            if not opp_known and left_after > 0:
                risk, risk_items = self.engine.counter_risk(cid, role, False, left_after)
                risk *= 0.8
            parts["risk"] = risk
            deny = 0.0
            if p and self.feasible(ds, cid, open_roles[other], 0.15):
                deny = 0.3 * 4.0 * p["prio"] / 100
            parts["deny"] = deny if step < 12 else deny * 0.5
            if parts["deny"] >= 0.5:
                why.append(("+", "se lo quitas al rival"))
            if not loaded:
                self.lola.request(cid, role, self.champs.slug(cid))
            total = sum(parts.values())
            out.append(
                {
                    "id": cid,
                    "name": self.champs.name(cid),
                    "role": role,
                    "role_short": ROLE_SHORT[role],
                    "role_cat": self.engine.roles.category(cid, role),
                    "score": round(total, 2),
                    "parts": {k: round(v, 2) for k, v in parts.items()},
                    "why": [{"sign": a, "text": b} for a, b in why][:5],
                    "matchups": items[:3],
                    "risk_items": risk_items,
                    "pro": p,
                    "loaded": loaded,
                    "tags": "".join(sorted(T.tags(self.champs, cid))),
                }
            )
        out.sort(key=lambda x: -x["score"])
        return out

    # -- bans
    def bans(self, ds, cands, side, other, teams, roles, open_roles, step):
        theirs = teams[other]["picks"]
        second_phase = step >= 12
        # no banear lo que vas a coger tu antes de que elija el rival
        next_pick = next(((s, i) for i, (s, k) in enumerate(DRAFT_ORDER[step:]) if k == "pick"), (None, 0))
        my_plan = set()
        if next_pick[0] == side:
            my_top = self.picks(ds, cands, side, other, teams, roles, open_roles, step)[:2]
            my_plan = {p["id"] for p in my_top}
        my_roles = roles[side]
        out = []
        for cid in cands:
            if cid in my_plan:
                continue
            feas = self.feasible(ds, cid, open_roles[other])
            if not feas:
                continue
            role, share = max(feas, key=lambda x: x[1])
            prio, p = self.priority(ds, cid)
            parts, why = {"prio": prio * (0.7 if second_phase else 1.0)}, []
            if p and p["prio"] >= 50:
                why.append(("+", f"prioridad alta ({p['prio']:.0f}%)"))
            fit, _ = self.engine.ally_fit(cid, [(c, 1.0) for c in theirs])
            parts["their_comp"] = 0.6 * fit
            if fit >= 0.8:
                why.append(("+", "encaja en la comp rival"))
            # cuanto counterea a tus picks (desde las paginas de tus campeones)
            counter = 0.0
            for my_c, my_r in my_roles.items():
                rows = (self.lola.matchups(my_c, my_r) or {}).get(role, {})
                row = rows.get(str(cid))
                if row and row["d2"] < 0:
                    wgt = 1.0 if my_r == role else 0.4
                    counter += -row["d2"] * row["n"] / (row["n"] + 250) * wgt
                    if row["d2"] <= -2:
                        why.append(("+", f"counterea a tu {self.champs.name(my_c)} ({row['d2']:+.1f})"))
            parts["counter"] = 0.5 * counter
            if second_phase and role in open_roles[other]:
                parts["role_need"] = 0.4
                why.append(("+", f"al rival le falta {ROLE_SHORT[role]}"))
            total = sum(parts.values())
            out.append(
                {
                    "id": cid,
                    "name": self.champs.name(cid),
                    "role": role,
                    "role_short": ROLE_SHORT[role],
                    "role_cat": self.engine.roles.category(cid, role),
                    "score": round(total, 2),
                    "parts": {k: round(v, 2) for k, v in parts.items()},
                    "why": [{"sign": a, "text": b} for a, b in why][:4],
                    "pro": p,
                }
            )
        out.sort(key=lambda x: -x["score"])
        return out

    # -- resumen de equipos
    def team_summary(self, picks, enemy_picks, roles, enemy_roles):
        ident, sc, cnt = T.identity([(c, 1.0) for c in picks], self.champs)
        notes = []
        if len(picks) >= 3 and cnt["E"] < 0.5:
            notes.append("Sin engage: le costará forzar peleas.")
        if len(picks) >= 4 and cnt["T"] < 0.5:
            notes.append("Sin frontline.")
        prof = {"AP": 0.0, "AD": 0.0}
        for c in picks:
            i = self.champs.info(c)
            if i["dmg"] in prof:
                prof[i["dmg"]] += i["damage"]
        tot = prof["AP"] + prof["AD"]
        if len(picks) >= 4 and tot and min(prof.values()) / tot < 0.2:
            notes.append("Daño casi todo " + ("físico." if prof["AD"] > prof["AP"] else "mágico."))
        if ident == "" and len(picks) >= 4:
            notes.append("Sin condición de victoria clara.")
        lanes = []
        for c, r in roles.items():
            opp = next((e for e, er in enemy_roles.items() if er == r), None)
            if opp:
                row = ((self.lola.matchups(c, r) or {}).get(r, {})).get(str(opp))
                lanes.append(
                    {
                        "role": ROLE_SHORT[r],
                        "me": self.champs.name(c),
                        "vs": self.champs.name(opp),
                        "d2": round(row["d2"], 1) if row else None,
                    }
                )
        return {
            "identity": ident,
            "identity_es": T.IDENTITY_ES[ident],
            "scores": {k: round(v, 1) for k, v in sc.items()},
            "notes": notes,
            "lanes": lanes,
            "picks": [
                {
                    "id": c,
                    "name": self.champs.name(c),
                    "role": roles.get(c, ""),
                    "role_short": ROLE_SHORT.get(roles.get(c, ""), ""),
                }
                for c in picks
            ],
        }

    def verdict(self, teams):
        def score(t):
            s = {"engage": 1.0, "range": 1.0, "protect": 0.8, "": 0.0}[t["identity"]]
            s -= 0.6 * len(t["notes"])
            s += 0.15 * sum(lane["d2"] for lane in t["lanes"] if lane["d2"] is not None)
            return s

        b, r = score(teams["blue"]), score(teams["red"])
        lean = "blue" if b - r > 0.3 else "red" if r - b > 0.3 else ""
        return {"blue": round(b, 2), "red": round(r, 2), "lean": lean}
