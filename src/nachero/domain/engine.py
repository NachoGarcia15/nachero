"""Perfil del jugador y motor de recomendacion de picks y bans.

Todas las piezas se expresan en puntos de winrate (pp) para poder sumarlas:

  WR estimado = 50 + meta + tu + rival_linea + resto_rival + encaje_aliado + respuesta_comp + riesgo_counter

  meta            WR del campeon en tu rol en Master+ menos la media, encogido por muestra. Fuera de su rol
                  principal se encoge hacia su fuerza alli y penaliza mas cuanto menos se juega (roles.py).
  tu              (solo modo "pool") experiencia + forma + tu residuo de WR/rendimiento con el campeon.
  rival_linea     "delta 2" contra el enemigo que juega tu linea, encogido con el spread de la pareja de roles
                  (bayesiano empirico, blind.py) y ponderado por la probabilidad de que juegue tu linea.
  resto_rival     lo mismo contra los demas enemigos: el spread de cada pareja de roles dice cuanto importa.
  encaje_aliado   lo que le falta a tu equipo (dano AP/AD, frontline, control, dano) y lo que sobra.
  sinergia        (con datos propios) WR de cada duo con tus aliados menos el esperado, encogido igual.
  respuesta_comp  ajustes pequenos contra la composicion rival (mucho control, mucha amenaza de entrada...).
  riesgo_counter  lo esperado de los roles que eligen despues de ti: con η cogen su mejor respuesta entre
                  los campeones disponibles de un pool medio; si no, uno cualquiera (blindability, blind.py).
  facil           (solo en autofill) +0,8 / 0 / -1 segun la dificultad del campeon en el cliente.

  delta 2 = WR real del enfrentamiento - WR esperado por la fuerza de ambos campeones. Mide solo la
  interaccion, por eso se suma a la fuerza del meta sin contarla dos veces.

Bans: valor = presencia del campeon x (0,4 x fuerza en el meta + 2 x η x P(tu rival elige despues) x cuanto
counterea tus picks). La fuerza pura cuenta poco porque, si nadie lo banea, puede caer igual en tu equipo que
en el rival; proteger tu pick solo vale si tu rival de linea puede elegir despues que tu.
"""

import itertools
import math
from collections import defaultdict

from nachero.domain import blind as BL
from nachero.domain import roles as R
from nachero.domain import tags as T
from nachero.domain.common import ROLES, shrink
from nachero.domain.common import tier_name as TIER

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


def comp_summary(ids, champs, hovers=()):
    """Recuento de la composición. `hovers`: campeones solo marcados, que cuentan como estimación
    (`est` dice cuántos son). `phys`: % del daño del equipo que es físico (None sin campeones)."""
    hovers = [c for c in hovers if c and c not in ids]
    t = team_profile([(c, 1) for c in [*ids, *hovers]], champs)
    dmg = t["apd"] + t["add"]
    return {
        "n": t["n"],
        "ap": round(t["ap"]),
        "ad": round(t["ad"]),
        "front": round(t["front"]),
        "cc": round(t["cc"]),
        "est": len(hovers),
        "phys": round(100 * t["add"] / dmg) if dmg else None,
    }


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


def infer_roles(enemy_ids, lola, cfg=None):
    """Asignacion conjunta mas probable de roles a los enemigos (maximiza el producto de % por linea).
    Los roles casi sin partidas tienen un suelo: un Teemo jungla no descoloca al resto del equipo."""
    ids = [c for c in enemy_ids if c][:5]
    if not ids:
        return {}
    th = R.settings(cfg)
    weight = {}
    for cid in ids:
        split = R.split_of(lola, cid)
        for r in ROLES:
            weight[(cid, r)] = R.assign_weight(split, r, th)
    best, best_score = None, -1e9
    for perm in itertools.permutations(ROLES, len(ids)):
        sc = sum(math.log(weight[(c, r)]) for c, r in zip(ids, perm, strict=True))
        if sc > best_score:
            best, best_score = perm, sc
    return dict(zip(ids, best, strict=True))


def role_probs(enemy_ids, lola, cfg=None):
    """Probabilidad de que cada rival elegido juegue cada rol (#70). En ranked el rol rival está
    oculto: con campeones flex (Sylas, Pantheon…) una sola asignación puede llevar el matchup de
    línea al rival equivocado. Mismos pesos que `infer_roles`, pero con todas las asignaciones."""
    th = R.settings(cfg)
    splits = {c: R.split_of(lola, c) for c in enemy_ids if c}
    return BL.role_marginals(list(splits)[:5], lambda c, r: R.assign_weight(splits[c], r, th))


# ---------------------------------------------------------------- autofill
# Un rol que no es el principal ni el secundario es autofill si tienes pocas partidas en él.
AUTOFILL_GAMES = 15
AUTOFILL_SHARE = 0.10
ROLE_FIT_ES = {
    "main": "tu rol principal",
    "secondary": "tu rol secundario",
    "familiar": "un rol que juegas a menudo",
    "autofill": "autofill",
    "unknown": "",
}
# En autofill: campeones fáciles (dificultad del cliente, 1 a 3), más peso a la fuerza en el
# parche y más castigo al riesgo de counter (vas a ciegas en un rol que no dominas).
EASE = {1: 0.8, 2: 0.0, 3: -1.0}
AUTOFILL_META, AUTOFILL_RISK = 1.25, 1.6


# ---------------------------------------------------------------- motor
class Engine:
    def __init__(self, champs, lola, player, cfg):
        self.champs, self.lola, self.player, self.cfg = champs, lola, player, cfg
        self.roles = R.RoleBook(lola, cfg)
        # blindability (#69): spread por campeón y rol (se rehace si cambia la tabla de matchups),
        # spread medido por pareja de roles y distribución de rivales disponibles por rol
        self._profiles: dict = {}
        self._pairs: dict = defaultdict(dict)
        self._dists: dict = {}

    def w(self, k):
        return float(self.cfg.get("weights", {}).get(k, 1.0))

    @property
    def bl(self):
        return BL.settings(self.cfg)

    # -- blindability (#69, #70)
    PAIR_K = 20.0  # el previo de la pareja de roles pesa como 20 matchups bien medidos

    def profile(self, cid, role, lanes=None):
        """Spread de `cid` en `role` contra cada rol rival ({rol_rival: BL.spread}), o None sin
        matchups en caché. Alimenta el spread medido de cada pareja de roles."""
        lanes = lanes if lanes is not None else self.lola.matchups(cid, role, fetch=False)
        if not lanes:
            return None
        hit = self._profiles.get((cid, role))
        if hit and hit[0] is lanes:
            return hit[1]
        prof = {er: BL.spread(rows) for er, rows in lanes.items()}
        self._profiles[(cid, role)] = (lanes, prof)
        for er, sp in prof.items():
            m = BL.info(sp["tau2"], BL.PAIR_PRIOR.get(role, {}).get(er, 1.0))
            if m > 0:
                self._pairs[(role, er)][cid] = (sp["raw"], m)
        return prof

    def pair_sigma(self, role, er):
        """Spread típico de la pareja de roles: lo medido en todas las páginas descargadas (cada una
        según su información), mezclado con el previo."""
        prior = BL.PAIR_PRIOR.get(role, {}).get(er, 1.0)
        seen = self._pairs.get((role, er), {}).values()
        m = sum(w for _, w in seen)
        if m <= 0:
            return prior
        raw = sum(r * w for r, w in seen) / m
        return BL.mix_sigma(raw, m, prior, self.PAIR_K)

    def sigma(self, cid, role, er, lanes=None):
        """Spread que se usa para encoger los matchups de `cid` en `role` contra el rol `er`: el del
        campeón según su información, mezclado con el de la pareja de roles."""
        prof = self.profile(cid, role, lanes) or {}
        sp = prof.get(er)
        pair = self.pair_sigma(role, er)
        if not sp:
            return pair
        m = BL.info(sp["tau2"], pair)
        return BL.mix_sigma(sp["raw"], m, pair, self.bl["prior_matchups"])

    def _dist(self, cid, role, er, rows, lanes, gone):
        """Rivales disponibles del rol `er` contra `cid` (caché por tabla y por lo no disponible)."""
        th = self.bl
        key = (cid, role, er, gone, th["threshold"])
        hit = self._dists.get(key)
        if hit and hit[0] is rows:
            return hit[1]
        dist = BL.available_dist(rows, self.sigma(cid, role, er, lanes), gone, th["threshold"])
        if len(self._dists) > 4000:
            self._dists.clear()
        self._dists[key] = (rows, dist)
        return dist

    def _role_stats(self, cid, role, er, rows, lanes, unavailable):
        """(q, media, spread, fracción de counters disponibles, dist) de `cid` contra el rol `er`."""
        gone = frozenset(str(c) for c in unavailable if str(c) in rows)
        dist = self._dist(cid, role, er, rows, lanes, gone)
        q = BL.q_of(dist)
        q_all = BL.q_of(self._dist(cid, role, er, rows, lanes, frozenset())) if gone else q
        tot = sum(x["w"] for x in dist)
        mean = sum(x["w"] * x["mean"] for x in dist) / tot if tot else 0.0
        # los counters ya baneados o elegidos no pueden salir: la pérdida baja en proporción
        avail = 1.0 if q_all <= 0 else min(1.0, q * (1.0 - self._gone_w(rows, gone)) / q_all)
        return q, mean, self.sigma(cid, role, er, lanes), avail, dist

    @staticmethod
    def _gone_w(rows, gone):
        """Presencia (fracción) de los campeones de la tabla que ya no están disponibles."""
        if not gone:
            return 0.0
        tot = sum(float(r.get("pr") or 0) for r in rows.values()) or 1.0
        return min(1.0, sum(float(rows[c].get("pr") or 0) for c in gone if c in rows) / tot)

    def blind_risk(self, cid, role, aprobs, unavailable=(), eta=None, pool=None, eta_cross=None):
        """Riesgo de counter (#72) de `cid` en `role` para los roles rivales que pueden elegir
        después (`aprobs`: {rol: P(elige después)}), con los rivales disponibles (sin bans ni ya
        elegidos). Lo esperado de cada uno: con η coge su mejor respuesta entre su pool (pierdes
        spread · E[máx de N]); si no, uno cualquiera (la media, ~0). En soloq solo tu rival de línea
        elige contra ti; los de otras líneas lo hacen poco (`counter_rate_cross`).

        Devuelve {"risk" (pp, ≤ 0 casi siempre), "p" (probabilidad de que tu rival de línea te
        countee, 0-1),
        "p_lane" (la de que tu rival de línea tenga un counter en su pool, sin η), "items" (los
        rivales que más aportan), "loaded"}. `eta`, `eta_cross` y `pool` para el simulador pro."""
        lanes = self.lola.matchups(cid, role, fetch=False)
        alt = None
        home = self.roles.main(cid)
        if home and home != role:
            alt = self.lola.matchups(cid, home, fetch=False)
        th = self.bl
        if not lanes and not alt:
            # sin su página aún: lo típico de cada pareja de roles, para no premiar al que no tiene datos
            risk = 0.0
            for er, a in aprobs.items():
                e = (eta if eta is not None else BL.eta(th, er)) if er == role else (
                    eta_cross if eta_cross is not None else float(th["counter_rate_cross"]))  # fmt: skip
                n = int(pool or th["pool_size"].get(er, 7))
                risk -= a * e * BL.expected_loss(self.pair_sigma(role, er), n)
            return {"risk": risk, "p": 0.0, "p_lane": None, "items": [], "loaded": False}
        risk, ps, contrib, p_lane = 0.0, [], [], None
        for er, a in aprobs.items():
            if a <= 1e-3:
                continue
            rows, src_role, src_lanes, wgt = (lanes or {}).get(er), role, lanes, 1.0
            if not rows and alt:  # sin datos en este rol: los de su rol principal, con menos peso
                rows, src_role, src_lanes = alt.get(er), home, alt
                wgt = float(self.roles.th["other_role_weight"])
            if not rows:
                continue
            lane = er == role
            if lane:
                e = eta if eta is not None else BL.eta(th, er)
            else:
                e = eta_cross if eta_cross is not None else float(th["counter_rate_cross"])
            n = int(pool or th["pool_size"].get(er, 7))
            q, mean, sig, avail, dist = self._role_stats(cid, src_role, er, rows, src_lanes, unavailable)
            loss = BL.expected_loss(sig, n, avail)
            risk += a * wgt * (mean - e * loss)
            if lane:  # la probabilidad que se enseña (y se calibra) es la de tu rival de línea
                p_lane = BL.p_pool(q, n)
                ps.append(a * e * p_lane)
            # quién te puede counterear: presencia × probabilidad de ser counter × η de su línea
            contrib += [(a * e * x["w"] * x["pc"], er, x) for x in dist if x["pc"] >= 0.05]
        contrib.sort(key=lambda t: -t[0])
        items = [
            {
                "id": x["id"],
                "name": self.champs.name(x["id"]),
                "role": er,
                "d2": round(x["mean"], 1),
                "pct": round(100 * x["pc"], 1),
            }
            for c, er, x in contrib[:3]
        ]
        return {"risk": risk, "p": BL.combine(ps), "p_lane": p_lane, "items": items, "loaded": True}

    def blind_summary(self, cid, role, unavailable=()):
        """Cómo de seguro es `cid` a ciegas en `role` si eligiera el primero (los cinco roles rivales
        después): `p_pool`, probabilidad de que tu rival de línea tenga un counter en su pool (solo
        depende del campeón: da la etiqueta); `p_blind`, la de que además lo elija (con η); `loss`,
        lo que costaría con todas las líneas. También el spread contra su línea. None sin matchups."""
        res = self.blind_risk(cid, role, dict.fromkeys(ROLES, 1.0), unavailable)
        if not res["loaded"]:
            return None
        p_pool = round(100 * res["p_lane"], 1) if res["p_lane"] is not None else None
        lab = BL.label(p_pool, self.bl)
        return {
            "p_pool": p_pool,
            "p_blind": round(100 * res["p"], 1),
            "loss": round(-res["risk"], 2),
            "label": lab,
            "label_es": BL.LABEL_ES.get(lab or "", ""),
            "spread": round(self.sigma(cid, role, role), 2),
        }

    def main_role(self):
        """Rol fuera de la champ select: el elegido en ajustes o, en "auto", el que mas juegas."""
        r = self.cfg.get("main_role", "auto")
        return r if r in ROLES else self.player.main_role

    def role_fit(self, role):
        """Cuánto es tuyo el rol asignado: principal, secundario, habitual o autofill.
        Sin historial no se sabe ("unknown") y no cambia nada."""
        games = self.player.role_games.get(role, 0)
        total = len(self.player.games)
        second = self.cfg.get("secondary_role")
        main = self.main_role()
        if role == main:
            kind = "main"
        elif role == second:
            kind = "secondary"
        elif not total:
            kind = "unknown"
        elif games >= AUTOFILL_GAMES and games / total >= AUTOFILL_SHARE:
            kind = "familiar"
        else:
            kind = "autofill"
        return {"kind": kind, "kind_es": ROLE_FIT_ES[kind], "games": games, "main": main}

    @property
    def mode(self):
        return "meta" if self.cfg.get("pick_mode") == "meta" else "pool"

    # -- fuerza del campeon en el parche
    def meta(self, cid, role):
        """(pp de fuerza en el rol, fila de la tier list o None). Cualquier rol: ver `roles.estimate`."""
        t = self.lola.tier(role)
        if not t:
            return 0.0, None
        return self.roles.estimate(cid, role)["value"], t["champs"].get(str(cid))

    def strong(self, role, n):
        """Los `n` mas fuertes del parche entre los que juegan el rol como principal o flex."""
        t = self.lola.tier(role)
        if not t:
            return []
        ids = [int(c) for c in t["champs"] if R.at_least(self.roles.category(int(c), role), "flex")]
        ids.sort(key=lambda c: -self.meta(c, role)[0])
        return ids[:n]

    def candidates(self, role):
        """Principal y flex del rol entre los fuertes del parche; con tu pool, ademas lo que has jugado
        en el rol (desde 1 partida) y tus campeones con maestria si el rol es al menos ocasional."""
        out = set()
        if self.mode == "meta":
            out |= set(self.strong(role, 45))
        else:
            for cid, r in self.player.by_cr:
                if r == role:
                    out.add(cid)
            # en autofill tu historial en el rol dice poco: más campeones fuertes del parche
            out |= set(self.strong(role, 30 if self.role_fit(role)["kind"] == "autofill" else 18))
            for cid, m in self.player.mastery.items():
                if m.get("championPoints", 0) >= 40000 and R.at_least(self.roles.category(cid, role), "occasional"):
                    out.add(cid)
            # los que estás practicando (puntos extra), aunque aún no los hayas jugado
            for name, bonus in self.cfg.get("pool_bonus", {}).items():
                cid = self.champs.id(name)
                practicing = isinstance(bonus, (int, float)) and bonus > 0
                if cid and practicing and R.at_least(self.roles.category(cid, role), "occasional"):
                    out.add(cid)
        never = {self.champs.id(n) for n in self.cfg.get("never_pick", [])}
        return {c for c in out if c and c not in never}

    # -- contra el rival
    def vs_enemy(self, cid, role, enemy_roles):
        """Matchups contra los rivales elegidos. Devuelve (linea, resto, items, cargado).

        `enemy_roles`: {cid_rival: rol} (roles conocidos, simulador pro) o {cid_rival: {rol: P}}
        (soloq: el rol rival está oculto, #70). Modelo «measured» (por defecto): cada `d2` se encoge
        con el spread de su pareja de roles (bayesiano empírico) y se pondera por la probabilidad
        del rol; el spread ya dice cuánto importa cada línea. Modelo «classic»: rol más probable,
        `shrink` fijo y `LANE_WEIGHT`.

        Si en este rol faltan datos de un enemigo (o de todos, porque apenas se juega ahi), usa los
        del rol principal del campeon con menos peso, marcados como datos de otro rol."""
        lanes = self.lola.matchups(cid, role)
        home = self.roles.main(cid)
        alt = None
        if home and home != role:
            # con poca muestra en el rol se pide tambien su pagina principal; si no, solo si ya esta
            thin = not R.at_least(self.roles.category(cid, role), "flex")
            alt = self.lola.matchups(cid, home, fetch=thin)
        if lanes is None and alt is None:
            return 0.0, 0.0, [], False
        alt_weight = float(self.roles.th["other_role_weight"])
        classic = self.bl["matchup_model"] == "classic"
        lane_sum, rest_sum, items = 0.0, 0.0, []
        for e, spec in enemy_roles.items():
            probs = {spec: 1.0} if isinstance(spec, str) else dict(spec)
            if classic and probs:
                top = max(probs, key=probs.get)
                probs = {top: 1.0}
            best = None
            for er, pr in sorted(probs.items(), key=lambda kv: -kv[1]):
                if pr < 0.02:
                    continue
                row, other, src_role, src = (lanes or {}).get(er, {}).get(str(e)), False, role, lanes
                if not row and alt:
                    row = alt.get(er, {}).get(str(e)) or max(
                        (rows[str(e)] for rows in alt.values() if str(e) in rows), key=lambda x: x["n"], default=None
                    )
                    other, src_role, src = bool(row), home, alt
                if not row:
                    continue
                is_lane = er == role
                if classic:
                    weight = LANE_WEIGHT[role][er] * (alt_weight if other else 1.0)
                    mean = shrink(row["d2"], row["n"], 250 if is_lane else 400)
                    v = mean * weight
                else:
                    sig = self.sigma(cid, src_role, er, src)
                    mean, _ = BL.posterior(row["d2"], row["n"], sig, row.get("wr"))
                    weight = pr * (alt_weight if other else 1.0)
                    v = mean * weight
                if is_lane:
                    lane_sum += v
                else:
                    rest_sum += v
                ci = BL.ci95(row["n"])
                item = {
                    "id": e,
                    "name": self.champs.name(e),
                    "d2": round(row["d2"], 1),
                    "post": round(mean, 1),
                    "ci": round(ci, 1) if ci != float("inf") else None,
                    "noise": abs(row["d2"]) < ci,
                    "wr": row["wr"],
                    "n": row["n"],
                    "lane": is_lane,
                    "role": er,
                    "p_role": round(pr, 2),
                    "weight": weight,
                    "value": round(v, 2),
                    "other_role": other,
                }
                if best is None:
                    best = item
                else:
                    best["value"] = round(best["value"] + v, 2)
            if best:
                items.append(best)
        items.sort(key=lambda x: (not x["lane"], x["d2"]))
        return lane_sum, rest_sum, items, True

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

    # -- sinergias medidas (#77)
    def pair_synergies(self, cid, role, ar):
        """Sinergia medida (datos propios, esquema 1) de `cid` en `role` con cada aliado posible del
        rol `ar`: {cid del aliado (str): pp}. Es el WR del dúo menos el esperado por la fuerza de los
        dos (producto de odds), encogido con el spread de sinergia de `cid` con ese rol, mezclado con
        el previo de la pareja de roles. Vacío sin datos (Lolalytics no da sinergias)."""
        fn = getattr(self.lola, "synergies", None)
        rows = fn(cid, role) if callable(fn) else None
        if not rows or role not in BL.SYN_PRIOR:
            return {}
        th = self.bl
        base = 50 + self.meta(cid, role)[0]
        same = {}
        for k, r in rows.items():
            kc, _, kr = k.partition(":")
            if kr == ar and r.get("n") and kc.isdigit():
                exp = BL.expected_duo(base, 50 + self.meta(int(kc), ar)[0])
                same[kc] = {"d2": r["wr"] - exp, "n": r["n"], "wr": r["wr"]}
        if not same:
            return {}
        sp = BL.spread(same)
        m = sp["m"] if sp["m"] >= th["min_matchups"] else 0
        sig = BL.mix_sigma(sp["spread"], m, BL.SYN_PRIOR[role].get(ar, 0.6), th["prior_matchups"])
        return {kc: BL.posterior(v["d2"], v["n"], sig, v.get("wr"))[0] for kc, v in same.items()}

    def synergy(self, cid, role, allies, ally_roles=None):
        """Sinergia medida con tus aliados (`pair_synergies`). `allies`: [(cid, peso)] (elegido 1,
        marcado 0,5); `ally_roles`: {cid: rol} del cliente. Sin rol (cola a ciegas), el rol principal
        del aliado con la mitad de peso. Devuelve (pp, motivos, hay_datos): sin datos propios, 0."""
        fn = getattr(self.lola, "synergies", None)
        if not callable(fn) or not fn(cid, role):
            return 0.0, [], False
        ally_roles = ally_roles or {}
        by_role: dict = {}
        total, why = 0.0, []
        for a, w in allies:
            if not a or w <= 0:
                continue
            ar = ally_roles.get(a) or self.roles.main(a)
            if not ar:
                continue
            w = w * (1.0 if a in ally_roles else 0.5)
            if ar not in by_role:
                by_role[ar] = self.pair_synergies(cid, role, ar)
            mean = by_role[ar].get(str(a))
            if mean is None:
                continue
            total += w * mean
            if abs(mean) >= 0.4:
                why.append(("+" if mean > 0 else "-", f"sinergia con tu {self.champs.name(a)} {mean:+.1f}"))
        return total, why, True

    def ally_combos(self, allies) -> tuple[dict, dict]:
        """Parejas de combo de tus aliados (#85): campeones de los roles aún libres en tu equipo con
        los que lo que han elegido o marcado gana `COMBO_MIN` pp o más. Devuelve ({(rol, cid str):
        pp × peso}, {cid str: [nombres de tus aliados]}). Sin datos propios, vacío."""
        locked = {a[1] for a in allies if a[1] in ROLES and a[2] >= 1}
        combo: dict = defaultdict(float)
        who = defaultdict(list)
        for a in allies:
            cid, r, w = a[0], a[1], a[2]
            if not cid or r not in ROLES or w <= 0:
                continue
            for lane in ROLES:
                if lane == r or lane in locked:
                    continue
                for partner, s in self.pair_synergies(cid, r, lane).items():
                    if s >= self.COMBO_MIN:
                        combo[(lane, partner)] += w * s
                        if self.champs.name(cid) not in who[partner]:
                            who[partner].append(self.champs.name(cid))
        return combo, who

    # -- recomendacion principal
    def score(self, cid, role, allies, enemy_ids, enemy_roles, enemy_left_after, autofill=False,
              unavailable=(), enemy_open=None, ally_roles=None):  # fmt: skip
        """Tarjeta de un campeon en un rol: WR estimado, partes, matchups, rol y confianza.

        `enemy_roles`: {cid: {rol: P}} de `role_probs` (o {cid: rol}). `enemy_left_after`: picks
        rivales después del tuyo; `enemy_open`: picks rivales sin hacer (por defecto, 5 − elegidos).
        `unavailable`: baneados y elegidos (no pueden ser counter). Con `autofill`, suma lo fácil que
        es y pesa más la fuerza en el parche y el riesgo de counter."""
        probs = {e: ({r: 1.0} if isinstance(r, str) else r) for e, r in enemy_roles.items()}
        lane_p = min(1.0, sum(p.get(role, 0.0) for p in probs.values()))
        open_slots = enemy_open if enemy_open is not None else 5 - len([e for e in enemy_ids if e])
        aprobs = BL.after_probs(probs, enemy_left_after, open_slots)
        pool_mode = self.mode == "pool"
        meta, tierrow = self.meta(cid, role)
        est = self.roles.estimate(cid, role)
        you = self.player.components(cid, role)
        lane_v, rest_v, mu_items, loaded = self.vs_enemy(cid, role, probs)
        gone = set(unavailable) | {e for e in enemy_ids if e} | {a for a, _ in allies}
        br = self.blind_risk(cid, role, aprobs, gone)
        fit, fit_why = self.ally_fit(cid, allies)
        syn, syn_why, has_syn = self.synergy(cid, role, allies, ally_roles)
        vc, vc_why = self.vs_comp(cid, enemy_ids)
        parts = {
            "you": you["total"] * self.w("pool") if pool_mode else 0.0,
            "meta": meta * self.w("meta"),
            "lane": lane_v * self.w("matchup"),
            "enemies": rest_v * self.w("matchup"),
            "allies": (fit + self.style(cid)) * self.w("comp"),
            "vs_comp": vc * self.w("comp"),
            "risk": br["risk"] * self.w("matchup"),
        }
        if has_syn:
            parts["synergy"] = syn * self.w("comp")
        why_af = []
        if autofill:
            difficulty = self.champs.info(cid).get("difficulty", 2)
            parts["ease"] = EASE.get(difficulty, 0.0)
            parts["meta"] *= AUTOFILL_META
            parts["risk"] *= AUTOFILL_RISK
            if difficulty == 1:
                why_af.append(("+", "fácil de jugar: buena opción de autofill"))
            elif difficulty == 3:
                why_af.append(("-", "difícil de jugar sin práctica en el rol"))
        bonus = self.cfg.get("pool_bonus", {}).get(self.champs.name(cid), 0)
        bonus = float(bonus) if pool_mode and isinstance(bonus, (int, float)) else 0.0
        total = sum(parts.values()) + bonus
        summary = self.blind_summary(cid, role)
        risk_open = any(v > 1e-3 for v in aprobs.values())
        why_bl = []
        if summary and risk_open and summary["label"] == "safe":
            why_bl.append(("+", f"seguro a ciegas: {summary['p_blind']:.0f} % de que te counteen si eliges primero"))
        elif summary and risk_open and summary["label"] == "counter":
            why_bl.append(("-", "mejor de counter: guárdalo para cuando veas a tu rival"))
        return {
            "id": cid,
            "name": self.champs.name(cid),
            "role": role,
            "est": round(50 + total, 1),
            "total": total,
            "parts": {k: round(v, 1) for k, v in parts.items()},
            "why": [{"sign": s, "text": t} for s, t in why_af + why_bl + fit_why + syn_why + vc_why],
            "dmg": self.champs.info(cid)["dmg"],
            "games": you["games"],
            "wr": round(100 * you["wins"] / you["games"]) if you["games"] else None,
            "mastery": you["mastery"],
            "exp": round(you["exp_games"]),
            "recent30": you["recent30"],
            "tier": TIER(tierrow) if est["games"] else None,
            "meta_wr": tierrow["wr"] if tierrow and est["games"] else None,
            "meta_games": est["games"],
            "role_pct": round(est["pct"], 1),
            "role_cat": est["category"],
            "role_cat_es": est["category_es"],
            "confidence": est["confidence"],
            "confidence_es": est["confidence_es"],
            "roles_label": self.roles.label(cid),
            "matchups": mu_items,
            "matchups_loaded": loaded,
            "matchups_other_role": any(m["other_role"] for m in mu_items),
            "risk_items": br["items"] if risk_open else [],
            "blind": {
                "p": round(100 * br["p"], 1) if risk_open and br["loaded"] else None,
                **(summary or {"p_pool": None, "p_blind": None, "label": None, "label_es": "", "spread": None}),
            },
            "lane_p": round(lane_p, 2),
            "risk_open": risk_open,
        }

    def picks(self, role, unavailable, pickable, allies, enemy_ids, enemy_left_after=5, include=(),
              enemy_open=None, ally_roles=None):  # fmt: skip
        """allies: [(cid, peso)] de tus aliados (peso 0,5 si solo marcan). enemy_ids: picks rivales.
        `ally_roles`: {cid: rol} de tus aliados (sinergias); `enemy_open`: picks rivales sin hacer."""
        enemy_roles = infer_roles(enemy_ids, self.lola, self.cfg)
        probs = role_probs(enemy_ids, self.lola, self.cfg)
        forced = {c for c in include if c}
        fit = self.role_fit(role)
        autofill = fit["kind"] == "autofill"
        out = []
        for cid in self.candidates(role) | forced:
            if cid not in forced and (cid in unavailable or (pickable and cid not in pickable)):
                continue
            out.append(
                self.score(
                    cid, role, allies, enemy_ids, probs, enemy_left_after, autofill, unavailable, enemy_open, ally_roles
                )  # fmt: skip
            )
        out.sort(key=lambda r: -r["total"])
        for r in out[:12]:
            if not r["matchups_loaded"]:
                self.lola.request(r["id"], role, self.champs.slug(r["id"]))
        lane_p = min(1.0, sum(p.get(role, 0.0) for p in probs.values()))
        open_slots = enemy_open if enemy_open is not None else 5 - len([e for e in enemy_ids if e])
        aprobs = BL.after_probs(probs, enemy_left_after, open_slots)
        ctx = {
            "enemy_roles": enemy_roles,
            "enemy_role_probs": probs,
            "lane_known": lane_p >= 0.5,
            "lane_p": round(lane_p, 2),
            "lane_after": round(aprobs.get(role, 0.0), 2),
            "risk_open": any(v > 1e-3 for v in aprobs.values()),
            "enemy_left_after": enemy_left_after,
            "mode": self.mode,
            "role_fit": fit,
        }
        return out, ctx

    def evaluate(self, cid, role, allies=(), enemy_ids=(), enemy_left_after=5, unavailable=(), ally_roles=None):
        """Cualquier campeon en cualquier rol (buscador del panel), aunque no sea candidato."""
        probs = role_probs(list(enemy_ids), self.lola, self.cfg)
        autofill = self.role_fit(role)["kind"] == "autofill"
        row = self.score(cid, role, list(allies), list(enemy_ids), probs, enemy_left_after, autofill,
                         unavailable, None, ally_roles)  # fmt: skip
        if not row["matchups_loaded"]:
            self.lola.request(cid, role, self.champs.slug(cid))
        row["split"] = self.roles.describe(cid)
        lane_p = min(1.0, sum(p.get(role, 0.0) for p in probs.values()))
        row["ctx"] = {
            "lane_known": lane_p >= 0.5,
            "lane_p": round(lane_p, 2),
            "risk_open": row["risk_open"],
            "enemy_left_after": enemy_left_after,
            "mode": self.mode,
        }
        return row

    BAN_PROTECT = 2.0  # escala de la protección frente a la fuerza (0,4 × fuerza, que puede caer en tu equipo)
    COMBO_MIN = 1.5  # pp de sinergia medida para llamarlo combo (#85)

    def bans(self, role, my_top, blocked, allies=(), my_after=None):
        """Bans recomendados (#73). my_top: tus picks recomendados (el primero, el que juegas); allies:
        [(cid, rol, peso[, P(su rival elige después)])] de tus aliados (elegidos 1, marcados 0,5).
        `my_after`: probabilidad de que tu rival de línea elija después que tú (huecos rivales
        posteriores al tuyo / huecos rivales sin elegir); None = 1 (sin champ select).

        Proteger un pick solo vale si su rival puede elegir después: con el primer pick casi todo es
        protección; con el último, casi todo fuerza. En ranked los bans son simultáneos y ocultos: si
        el rival banea lo mismo, es un ban perdido, y no se intenta adivinar.
        Prioriza a los que countean a tu pick y a tus aliados (matchups en caché, encogidos con el
        spread de la pareja de roles) y la fuerza en el parche en tu línea. blocked: ids que no se
        pueden/quieren banear."""
        t = self.lola.tier(role)
        if not t:
            return []
        th = self.bl
        mine_after = 1.0 if my_after is None else max(0.0, min(1.0, my_after))
        # a quién proteger: tu pick pesa más; cada aliado, según si ya eligió o solo marca
        mine = list({p["id"]: p for p in my_top[:3]}.values())  # sin repetir: manda la primera posición
        targets = [(p["id"], role, w * mine_after, f"{p['name']} (tu pick)" if k == 0 else p["name"])
                   for k, (w, p) in enumerate(zip([0.6, 0.25, 0.15], mine, strict=False))]  # fmt: skip
        for a in allies:
            cid, r, w = a[0], a[1], a[2]
            pa = a[3] if len(a) > 3 else 1.0
            if r in ROLES:
                targets.append((cid, r, 0.4 * w * pa, self.champs.name(cid)))
        counter_map: dict = defaultdict(float)  # (línea, cid rival) -> puntos
        counter_who = defaultdict(list)
        for cid, lane, wgt, who in targets:
            if wgt <= 0:
                continue
            # solo caché: el bucle de la champ select no espera a la red
            lanes = self.lola.matchups(cid, lane, fetch=False) or {}
            rows = lanes.get(lane, {})
            sig = self.sigma(cid, lane, lane, lanes) if rows else 1.0
            e = BL.eta(th, lane)
            for en, row in rows.items():
                mean, _ = BL.posterior(row["d2"], row["n"], sig, row.get("wr"))
                counter_map[(lane, en)] += wgt * self.BAN_PROTECT * e * -mean
                if mean <= -1.0 and who not in counter_who[en]:
                    counter_who[en].append(who)
        # combos de tus aliados (datos propios, #85): banear la pareja de lo que han elegido o
        # marcado te quita a ti la opción (no banear Ashe si tu support ha marcado Seraphine)
        combo, combo_who = self.ally_combos(allies)
        best: dict = {}
        for lane in dict.fromkeys([role] + [lane for lane, _ in counter_map]):
            lt = t if lane == role else self.lola.tier(lane)
            for cid, c in ((lt or {}).get("champs") or {}).items():
                icid = int(cid)
                if icid in blocked or c["games"] < 1000:
                    continue
                counter = counter_map.get((lane, cid), 0.0)
                if lane != role and counter <= 0:
                    continue  # de otra línea, solo si countea a un aliado
                presence = c["pr"] / 100
                strength = shrink(c["wr"] - (lt or {}).get("avg", 50.0), c["games"], 1500)
                protect = combo.get((lane, cid), 0.0)
                value = presence * (0.4 * strength + counter - self.BAN_PROTECT * protect) * 100
                if value <= 0 or value <= best.get(icid, {}).get("value", 0):
                    continue
                reasons = []
                if counter_who.get(cid):
                    reasons.append("countea a " + " y a ".join(counter_who[cid][:3]))
                if protect > 0:
                    reasons.append("pero hace combo con tu " + " y tu ".join(combo_who[cid][:2]))
                if strength >= 1:
                    reasons.append(f"{c['wr']:.1f}% WR en Master+")
                reasons.append(f"{c['pr']:.1f}% pick · {c['br']:.0f}% ban")
                best[icid] = {
                    "id": icid,
                    "name": self.champs.name(icid),
                    "value": round(value, 2),
                    "reasons": reasons,
                    "tier": TIER(c),
                }
        out = list(best.values())
        prio = {self.champs.id(n): i for i, n in enumerate(self.cfg.get("ban_priority", {}).get(role, []))}
        for b in out:
            if b["id"] in prio:
                b["value"] += 5 - prio[b["id"]] * 0.5
                b["reasons"].insert(0, "en tu lista de bans")
        return sorted(out, key=lambda b: -b["value"])


def ban_context(my_after):
    """Frase para el panel: qué buscan los bans según tu posición de pick (#73)."""
    if my_after is None:
        return "según tu pool"
    if my_after >= 0.6:
        return f"eliges antes que tu rival ({100 * my_after:.0f} %): bans para proteger tu pick"
    if my_after <= 0.01:
        return "eliges después de todos los rivales: bans por fuerza"
    return f"tu rival elige después con un {100 * my_after:.0f} %: entre proteger tu pick y quitar fuerza"
