"""Roles de cada campeón en Master+: principal, flex, ocasional o fuera de rol.

Lolalytics da, en la tier list de cada línea, las partidas del campeón ahí y `pct` (qué parte de
sus partidas son en esa línea). Con eso cualquier campeón se puede evaluar en cualquier rol:

  principal    su rol con más partidas                       Katarina mid
  flex         >= 10 % de sus partidas o >= 3.000 partidas    Katarina ADC, Jayce jungla
  ocasional    >= 2 % o >= 300 partidas                       Teemo jungla, Taliyah ADC
  fuera de rol el resto: se puede evaluar, con poca confianza Katarina jungla

Estimación (en puntos de winrate, como el resto de la fórmula): en su rol principal, el WR menos
la media encogido hacia 0 por muestra. En otro rol, el WR de ese rol se encoge hacia un previo: su
fuerza en el rol principal menos una penalización que crece cuanto menos se juega ahí (hasta
`offrole_penalty` pp con 0 %, nada desde `flex_pct`). Con muchas partidas en el rol manda su WR ahí.

La penalización sale de la caché real (parche 16.22, Master+, roles con 100+ partidas): WR en el
rol menos WR en su principal, ponderado por partidas, es -4,0 pp por debajo del 1 % de sus
partidas, -2,5 entre el 1 y el 5 %, -1,2 entre el 5 y el 10 % y ~0 a partir del 10 %.

Lógica pura: recibe la fuente de estadísticas (`lola.tier(rol)`) y los ajustes (`cfg["roles"]`).
"""

from nachero.domain.common import ROLE_ES, ROLES, shrink

CATEGORIES = ("main", "flex", "occasional", "off")  # de más a menos jugado
CATEGORY_ES = {"main": "principal", "flex": "flex", "occasional": "ocasional", "off": "fuera de rol"}
CONFIDENCE_ES = {"high": "Alta", "medium": "Media", "low": "Baja", "none": "Sin datos"}

DEFAULTS: dict = {
    "flex_pct": 10.0,
    "flex_games": 3000,
    "occasional_pct": 2.0,
    "occasional_games": 300,
    "shrink_games": 1500,  # partidas a partir de las que el WR del rol pesa más que el previo
    "offrole_penalty": 4.0,  # pp con el 0 % de sus partidas en el rol; 0 desde flex_pct
    "other_role_weight": 0.5,  # peso de los matchups prestados del rol principal
    "assign_floor_pct": 1.0,  # suelo del reparto al estimar los roles de un equipo
    "confidence_games": {"high": 5000, "medium": 1000, "low": 50},
}


def settings(cfg: dict | None) -> dict:
    """Umbrales por defecto con lo que el usuario haya cambiado en `cfg["roles"]`."""
    th = dict(DEFAULTS)
    user = (cfg or {}).get("roles") or {}
    for k, v in user.items():
        if k == "confidence_games" and isinstance(v, dict):
            th[k] = {**DEFAULTS[k], **v}
        elif k in DEFAULTS and isinstance(v, (int, float)) and not isinstance(v, bool):
            th[k] = v
    return th


# ---------------------------------------------------------------- reparto de un campeón
def split_of(lola, cid) -> dict:
    """{rol: {"pct", "games", "wr", "avg"}} del campeón en Master+. Sin datos en un rol: 0 partidas."""
    out = {}
    for r in ROLES:
        t = lola.tier(r)
        if not t:
            continue
        c = t["champs"].get(str(cid))
        out[r] = {
            "pct": float(c.get("pct", 0) or 0) if c else 0.0,
            "games": int(c.get("games", 0) or 0) if c else 0,
            "wr": float(c["wr"]) if c else 0.0,
            "avg": float(t.get("avg", 50.0)),
        }
    return out


def main_role(split: dict) -> str | None:
    """El rol con más partidas (None si el campeón no tiene ninguna)."""
    best = max(split, key=lambda r: split[r]["games"], default=None)
    return best if best and split[best]["games"] > 0 else None


def category(split: dict, role: str, th: dict) -> str:
    row = split.get(role)
    if not row or row["games"] <= 0:
        return "off"
    if role == main_role(split):
        return "main"
    if row["pct"] >= th["flex_pct"] or row["games"] >= th["flex_games"]:
        return "flex"
    if row["pct"] >= th["occasional_pct"] or row["games"] >= th["occasional_games"]:
        return "occasional"
    return "off"


def at_least(cat: str, minimum: str) -> bool:
    """¿La categoría `cat` es `minimum` o más jugada? (principal > flex > ocasional > fuera de rol)."""
    return CATEGORIES.index(cat) <= CATEGORIES.index(minimum)


def confidence(games: int, th: dict) -> str:
    """Alta / Media / Baja / Sin datos según las partidas del campeón en ese rol."""
    c = th["confidence_games"]
    if games >= c["high"]:
        return "high"
    if games >= c["medium"]:
        return "medium"
    if games >= c["low"]:
        return "low"
    return "none"


def offrole_gap(pct: float, th: dict) -> float:
    """Cuánto peor rinde un campeón fuera de su rol principal según qué parte de sus partidas son
    ahí: -`offrole_penalty` pp con el 0 %, en línea recta hasta 0 en `flex_pct`."""
    return -float(th["offrole_penalty"]) * max(0.0, 1 - pct / th["flex_pct"]) if th["flex_pct"] > 0 else 0.0


def estimate(split: dict, role: str, th: dict) -> dict:
    """Fuerza del campeón en `role` en pp: `value` = `delta` + `penalty`.

    `delta`: su WR en el rol encogido hacia su fuerza en el rol principal. `penalty`: lo que resta
    jugarlo fuera de rol, que pesa menos cuantas más partidas tiene ahí (entonces manda su WR)."""
    row = split.get(role) or {"pct": 0.0, "games": 0, "wr": 0.0, "avg": 50.0}
    games, k = row["games"], th["shrink_games"]
    main = main_role(split)
    if main is None:
        delta, penalty = 0.0, offrole_gap(0.0, th)
    else:
        m = split[main]
        base = shrink(m["wr"] - m["avg"], m["games"], k)  # su fuerza donde más se juega
        if role == main:
            delta, penalty = base, 0.0
        else:
            raw = row["wr"] - row["avg"] if games else 0.0
            delta = (games * raw + k * base) / (games + k)
            penalty = offrole_gap(row["pct"], th) * k / (games + k)
    cat = category(split, role, th)
    conf = confidence(games, th)
    return {
        "value": delta + penalty,
        "delta": delta,
        "penalty": penalty,
        "games": games,
        "pct": row["pct"],
        "main": main,
        "category": cat,
        "category_es": CATEGORY_ES[cat],
        "confidence": conf,
        "confidence_es": CONFIDENCE_ES[conf],
    }


def describe(split: dict, th: dict) -> list[dict]:
    """Los roles del campeón de más a menos jugado, con su categoría (para las pestañas por rol)."""
    rows = [
        {
            "role": r,
            "role_es": ROLE_ES[r],
            "pct": round(split[r]["pct"], 1),
            "games": split[r]["games"],
            "category": category(split, r, th),
        }
        for r in split
    ]
    rows.sort(key=lambda x: -x["games"])
    return rows


def label(split: dict, th: dict) -> str:
    """Sus roles en corto: «Mid · ADC flex» (principal y flex)."""
    parts = []
    for d in describe(split, th):
        if d["category"] == "main":
            parts.append(d["role_es"])
        elif d["category"] == "flex":
            parts.append(f"{d['role_es']} flex")
    return " · ".join(parts)


def assign_weight(split: dict, role: str, th: dict) -> float:
    """Peso del rol al estimar los roles de un equipo: su reparto, con un suelo para fuera de rol."""
    row = split.get(role)
    pct = row["pct"] if row else 0.0
    return max(pct, th["assign_floor_pct"], 1e-3) / 100


# ---------------------------------------------------------------- acceso cómodo desde los motores
class RoleBook:
    """Roles de cualquier campeón a partir de la fuente Master+ y los ajustes (en vivo)."""

    def __init__(self, lola, cfg: dict | None = None):
        self.lola = lola
        self.cfg = cfg if cfg is not None else {}

    @property
    def th(self) -> dict:
        return settings(self.cfg)

    def split(self, cid) -> dict:
        return split_of(self.lola, cid)

    def main(self, cid) -> str | None:
        return main_role(self.split(cid))

    def category(self, cid, role) -> str:
        return category(self.split(cid), role, self.th)

    def estimate(self, cid, role) -> dict:
        return estimate(self.split(cid), role, self.th)

    def roles(self, cid, minimum: str = "flex") -> list[str]:
        """Roles del campeón con categoría `minimum` o mejor, de más a menos jugado."""
        th = self.th
        return [d["role"] for d in describe(self.split(cid), th) if at_least(d["category"], minimum)]

    def describe(self, cid) -> list[dict]:
        return describe(self.split(cid), self.th)

    def label(self, cid) -> str:
        return label(self.split(cid), self.th)

    def weight(self, cid, role) -> float:
        return assign_weight(self.split(cid), role, self.th)
