"""Blindability: cuánto le importa a un campeón con quién se cruza (issues #68 y #69).

Idea de los vídeos de MachineLoLing («The math behind champion blindability» y «… who should pick
first in draft»), adaptada a soloq. Todo en puntos de winrate (pp), como el resto del motor.

Spread verdadero
  Los `d2` de un campeón contra los campeones de un rol rival forman una campana. Su desviación
  típica observada (ponderada por presencia) mezcla la de verdad con el ruido binomial de cada
  matchup, que solo depende de las partidas: var = 10⁴·p(1−p)/n ≈ 2500/n pp².
      spread² = spread_observado² − ruido²
  Ahri mid ~1,1 pp (ciega), Yasuo ~2,2 pp (de counter).

Encogimiento bayesiano empírico
  Con el spread como varianza previa, la media posterior de un matchup es d2·σ²/(σ²+τ²), τ² = 2500/n
  (= shrink(d2, n, 2500/σ²)), y su varianza σ²τ²/(σ²+τ²). Así no se cuentan counters a pelo: con
  1.000 partidas un matchup aún varía ±3,1 pp.

Probabilidad de counter (soloq)
  Por rol rival, q = Σ w·P(d2 ≤ −umbral) sobre los campeones **disponibles** (sin bans ni ya
  elegidos), con w la presencia renormalizada entre ellos. Con un pool de N campeones:
      p_pool = 1 − (1 − q)^N             el rival tiene algún counter en su pool
      p_counter = η · p_pool            y además lo elige (η: no todos counterean en soloq)
  Con varios roles: 1 − Π (1 − P(elige después)·p_counter_rol).

Pérdida esperada (soloq)
  Tu rival de línea, si elige después, coge con probabilidad η su mejor respuesta entre su pool de N:
  pierdes en media spread · E[máx de N normales] (×1,35 con N = 7), menos si los counters de verdad
  están baneados o elegidos. Los rivales de otras líneas eligen para su línea, no contra ti: casi
  siempre te tocan al azar (media ~0), salvo una fracción pequeña (`counter_rate_cross`).

Con pocas partidas (Master+ de un parche: 5-50 por matchup) el ruido tapa el spread: el de cada
campeón pesa según la información que tiene y, si no, manda el típico de su pareja de roles. Por
eso, por defecto, los matchups se leen de Esmeralda+ (5 veces más partidas; ver vídeo 1).

El pool de cada rival es siempre una media por rol (`pool_size`): en ranked los rivales están
ocultos y Nachero no los identifica (normas de Riot).

Lógica pura: sin red ni disco.
"""

import itertools
import math

from nachero.domain.common import ROLES

NOISE_VAR = 2500.0  # pp² por partida con p ≈ 0,5: 10⁴ · p(1 − p)
SIGMA_FLOOR = 0.3  # spread mínimo: con 0 todo se encogería a nada
CI95 = 1.96 * 50  # media anchura del intervalo del 95 % de un WR: ±98/√n pp

# Spread previo por pareja de roles (tu rol → rol rival), hasta medirlo con las páginas que llegan.
# Forma del mapa de calor del vídeo: la línea propia pesa más; el jungla reparte; ADC y support se
# miran entre ellos; el mid y el support miran también al jungla.
PAIR_PRIOR: dict = {r: {e: (1.6 if r == e else 0.7) for e in ROLES} for r in ROLES}
PAIR_PRIOR["jungle"] = {"top": 1.0, "jungle": 1.1, "middle": 1.1, "bottom": 1.0, "utility": 1.0}
PAIR_PRIOR["middle"]["jungle"] = 1.0
PAIR_PRIOR["utility"]["jungle"] = 0.9
PAIR_PRIOR["bottom"]["utility"] = PAIR_PRIOR["utility"]["bottom"] = 1.2
# Sinergias (tu rol → rol del aliado)
SYN_PRIOR: dict = {r: {e: 0.6 for e in ROLES} for r in ROLES}
for a, b in (("jungle", "middle"), ("bottom", "utility"), ("utility", "jungle")):
    SYN_PRIOR[a][b] = SYN_PRIOR[b][a] = 1.0

DEFAULTS: dict = {
    "threshold": 2.0,  # pp por debajo de lo esperado para llamarlo counter
    "pool_size": {r: 7 for r in ROLES},  # campeones del pool medio de un rival (80 % de su maestría)
    "counter_rate": 0.5,  # η: fracción de veces que el rival que elige después counterea
    "counter_rate_by_role": {},  # η por rol (opcional), p. ej. {"top": 0.6}
    "counter_rate_cross": 0.1,  # fracción de rivales de otras líneas que eligen contra ti
    "min_matchups": 8,  # matchups con partidas para medir el spread del campeón
    "prior_matchups": 10,  # cuánto pesa el spread de la pareja de roles frente al del campeón
    # etiquetas con la probabilidad de que tu rival de línea tenga un counter en su pool si eliges
    # el primero (sin η: solo depende del campeón). Pool de 7: spread 1,3 pp → 35 %, 1,85 pp → 65 %
    "safe_pct": 35.0,  # «Seguro a ciegas» hasta aquí
    "counter_pct": 65.0,  # «Mejor de counter» desde aquí
    "matchup_model": "measured",  # "measured" (bayesiano, sin LANE_WEIGHT) o "classic"
    "swap_min_gain": 0.5,  # pp que tiene que ganar el equipo para sugerir un intercambio
}
LABEL_ES = {"safe": "Seguro a ciegas", "flex": "Intermedio", "counter": "Mejor de counter"}


def settings(cfg: dict | None) -> dict:
    """Valores por defecto con lo que el usuario haya cambiado en `cfg["blind"]`."""
    th = dict(DEFAULTS)
    user = (cfg or {}).get("blind") or {}
    for k, v in user.items():
        if k == "pool_size" and isinstance(v, dict):
            th[k] = {**DEFAULTS[k], **{r: int(n) for r, n in v.items() if r in ROLES and _num(n) and 1 <= n <= 20}}
        elif k == "counter_rate_by_role" and isinstance(v, dict):
            th[k] = {r: float(x) for r, x in v.items() if r in ROLES and _num(x) and 0 <= x <= 1}
        elif (k == "matchup_model" and v in ("measured", "classic")) or (
            k in DEFAULTS and _num(v) and not isinstance(DEFAULTS[k], (dict, str))
        ):
            th[k] = v
    return th


def _num(v) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def eta(th: dict, role: str) -> float:
    """η del rol rival (o el general)."""
    return float(th["counter_rate_by_role"].get(role, th["counter_rate"]))


# ---------------------------------------------------------------- estadística básica
def phi(x: float) -> float:
    """Función de distribución de la normal estándar."""
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def noise_var(n: float, wr: float | None = None) -> float:
    """Varianza del ruido binomial de un WR (pp²) con `n` partidas."""
    if not n or n <= 0:
        return math.inf
    p = 0.5 if wr is None else min(0.95, max(0.05, wr / 100))
    return 1e4 * p * (1 - p) / n


def ci95(n: float) -> float:
    """Media anchura del intervalo del 95 % de un WR con `n` partidas (pp)."""
    return CI95 / math.sqrt(n) if n and n > 0 else math.inf


def spread(rows) -> dict:
    """Spread de una tabla de matchups `{cid: {"d2", "n", "pr", "wr"}}` (un rol rival).

    Devuelve media (`mu`), dispersión observada (`obs`), ruido (`noise`), spread verdadero
    (`spread`), cuántos matchups tienen partidas (`m`) y partidas totales (`games`). Pesos: presencia
    (`pr`); si no hay, partidas."""
    items = [r for r in (rows or {}).values() if r and r.get("n", 0) > 0 and _num(r.get("d2"))]
    if not items:
        return {"mu": 0.0, "obs": 0.0, "noise": 0.0, "spread": None, "raw": 0.0, "tau2": [], "m": 0, "games": 0}
    ws = [float(r.get("pr") or 0) for r in items]
    if sum(ws) <= 0:
        ws = [float(r["n"]) for r in items]
    tot = sum(ws)
    ws = [w / tot for w in ws]
    mu = sum(w * r["d2"] for w, r in zip(ws, items, strict=True))
    obs2 = sum(w * (r["d2"] - mu) ** 2 for w, r in zip(ws, items, strict=True))
    nz2 = sum(w * noise_var(r["n"], r.get("wr")) for w, r in zip(ws, items, strict=True))
    true2 = max(0.0, obs2 - nz2)
    return {
        "mu": mu,
        "obs": math.sqrt(obs2),
        "noise": math.sqrt(nz2),
        "spread": math.sqrt(true2),
        "raw": obs2 - nz2,  # estimador sin sesgo de spread² (puede salir negativo con mucho ruido)
        "tau2": [noise_var(r["n"], r.get("wr")) for r in items],
        "m": len(items),
        "games": int(sum(r["n"] for r in items)),
    }


def info(tau2s, prior: float) -> float:
    """Información de una tabla para medir su spread: cada matchup cuenta (σ²/(σ²+τ²))², casi 1 con
    muchas partidas y casi 0 si el ruido lo tapa (Master+ de un parche: 5-50 partidas)."""
    s2 = max(SIGMA_FLOOR, prior) ** 2
    return sum((s2 / (s2 + t)) ** 2 for t in _finite(tau2s))


def _finite(tau2s):
    return (t for t in tau2s if not math.isinf(t))


def mix_sigma(raw: float | None, m_eff: float, prior: float, k0: float) -> float:
    """Spread que se usa: el medido (`raw` = spread² sin sesgo) pesado por su información `m_eff`,
    mezclado con el de la pareja de roles (`prior`), que pesa como `k0` matchups bien medidos."""
    if raw is None or m_eff <= 0:
        return max(SIGMA_FLOOR, prior)
    s2 = (k0 * prior**2 + m_eff * raw) / (k0 + m_eff)
    return max(SIGMA_FLOOR, math.sqrt(max(0.0, s2)))


def posterior(d2: float, n: float, sigma: float, wr: float | None = None) -> tuple[float, float]:
    """Media y varianza posteriores del `d2` real de un matchup (encogimiento bayesiano empírico)."""
    s2 = max(SIGMA_FLOOR, sigma) ** 2
    t2 = noise_var(n, wr)
    if math.isinf(t2):
        return 0.0, s2
    k = s2 / (s2 + t2)
    return d2 * k, s2 * t2 / (s2 + t2)


def shrink_k(sigma: float) -> float:
    """Equivalente en `shrink(x, n, k)`: k = 2500/σ²."""
    return NOISE_VAR / max(SIGMA_FLOOR, sigma) ** 2


def p_below(mean: float, var: float, threshold: float) -> float:
    """P(d2 real ≤ −umbral) con la posterior (media, varianza)."""
    if var <= 0:
        return 1.0 if mean <= -threshold else 0.0
    return phi((-threshold - mean) / math.sqrt(var))


def available_dist(rows, sigma: float, unavailable=(), threshold: float = 2.0) -> list[dict]:
    """Campeones disponibles de un rol rival con su peso (presencia renormalizada), su posterior y
    su probabilidad de ser counter. Sin bans ni campeones ya elegidos (`unavailable`)."""
    gone = {str(c) for c in unavailable or ()}
    out = []
    for e, r in (rows or {}).items():
        if str(e) in gone or not r or r.get("n", 0) <= 0 or not _num(r.get("d2")):
            continue
        w = float(r.get("pr") or 0) or float(r["n"])
        mean, var = posterior(r["d2"], r["n"], sigma, r.get("wr"))
        out.append({"id": int(e), "w": w, "mean": mean, "var": var, "pc": p_below(mean, var, threshold)})
    tot = sum(x["w"] for x in out)
    for x in out:
        x["w"] = x["w"] / tot if tot else 0.0
    return out


def q_of(dist: list[dict]) -> float:
    """Probabilidad de que un campeón al azar (por presencia) del rol sea counter."""
    return sum(x["w"] * x["pc"] for x in dist)


def p_pool(q: float, n: int) -> float:
    """Probabilidad de que un pool de `n` campeones al azar tenga algún counter."""
    return 1.0 - (1.0 - min(1.0, max(0.0, q))) ** max(1, n)


_EMAX: dict = {}


def e_max(n: int) -> float:
    """E[máximo de n normales estándar] (0; 0,564; 0,846; 1,029; 1,163; 1,267; 1,352 con n = 1…7)."""
    n = max(1, int(n))
    if n not in _EMAX:
        step, acc = 0.005, 0.0
        for i in range(-1600, 1601):
            x = i * step
            acc += x * n * math.exp(-x * x / 2) / math.sqrt(2 * math.pi) * phi(x) ** (n - 1) * step
        _EMAX[n] = 0.0 if n == 1 else acc
    return _EMAX[n]


def expected_loss(sigma: float, n: int, avail: float = 1.0) -> float:
    """Pérdida esperada (pp) si el rival elige su mejor respuesta entre `n` campeones: spread ·
    E[máx de n], por la fracción de counters que siguen disponibles (`avail`)."""
    return max(0.0, sigma) * e_max(n) * min(1.0, max(0.0, avail))


def combine(ps) -> float:
    """Probabilidad de que pase al menos uno de varios sucesos independientes."""
    out = 1.0
    for p in ps:
        out *= 1.0 - min(1.0, max(0.0, p))
    return 1.0 - out


def label(p_pool: float | None, th: dict) -> str | None:
    """Etiqueta a ciegas a partir de la probabilidad (en %) de que algún rival tenga un counter en
    su pool si eligieras el primero, sin η (solo depende del campeón)."""
    if p_pool is None:
        return None
    if p_pool <= th["safe_pct"]:
        return "safe"
    if p_pool >= th["counter_pct"]:
        return "counter"
    return "flex"


def pool_size_80(values) -> int:
    """Cuántos elementos (de mayor a menor) suman el 80 % del total: la regla del vídeo para el
    tamaño de un pool con los puntos de maestría o las partidas."""
    vs = sorted((float(v) for v in values if v and v > 0), reverse=True)
    tot = sum(vs)
    if not tot:
        return 0
    acc = 0.0
    for i, v in enumerate(vs, 1):
        acc += v
        if acc >= 0.8 * tot - 1e-9:
            return i
    return len(vs)


# ---------------------------------------------------------------- WR esperado por odds
def _odds(wr: float) -> float:
    p = min(99.0, max(1.0, wr))
    return p / (100.0 - p)


def _from_odds(o: float) -> float:
    return 100.0 * o / (1.0 + o)


def expected_wr(wr_a: float, wr_b: float) -> float:
    """WR esperado de A contra B por la fuerza de cada uno: cociente de sus odds (vídeo 1).
    Ahri 50,9 % contra Mel 45,5 % → 55,6 %."""
    return _from_odds(_odds(wr_a) / _odds(wr_b))


def expected_duo(wr_a: float, wr_b: float) -> float:
    """WR esperado de A y B en el mismo equipo: producto de sus odds (sin sinergia)."""
    return _from_odds(_odds(wr_a) * _odds(wr_b))


# ---------------------------------------------------------------- roles con probabilidades
def role_marginals(ids, weight) -> dict:
    """Probabilidad de que cada campeón de un equipo juegue cada rol: todas las asignaciones
    posibles (permutaciones) pesadas por el producto de `weight(cid, rol)` y normalizadas."""
    ids = [c for c in ids if c][:5]
    out: dict = {c: dict.fromkeys(ROLES, 0.0) for c in ids}
    if not ids:
        return out
    w = {(c, r): max(1e-6, weight(c, r)) for c in ids for r in ROLES}
    perms = []
    for perm in itertools.permutations(ROLES, len(ids)):
        perms.append((perm, sum(math.log(w[(c, r)]) for c, r in zip(ids, perm, strict=True))))
    top = max(s for _, s in perms)
    tot = 0.0
    for perm, s in perms:
        p = math.exp(s - top)
        tot += p
        for c, r in zip(ids, perm, strict=True):
            out[c][r] += p
    for c in ids:
        out[c] = {r: v / tot for r, v in out[c].items()}
    return out


def free_roles(probs: dict) -> dict:
    """Probabilidad de que cada rol rival siga sin elegir: 1 − Σ P(rival elegido juega el rol)."""
    return {r: max(0.0, 1.0 - sum(p.get(r, 0.0) for p in probs.values())) for r in ROLES}


def after_probs(probs: dict, after: int, open_slots: int) -> dict:
    """P(el rol rival r elige después de ti): sigue libre × huecos rivales después del tuyo /
    huecos rivales sin elegir. En ranked no se sabe qué rol tiene cada hueco: reparto uniforme."""
    if after <= 0 or open_slots <= 0:
        return dict.fromkeys(ROLES, 0.0)
    share = min(1.0, after / open_slots)
    return {r: f * share for r, f in free_roles(probs).items()}


# ---------------------------------------------------------------- orden de picks del cliente
def pick_order(actions) -> list[dict]:
    """Picks de la champ select en orden: [{"cell", "ally", "group", "completed", "cid"}]."""
    out = []
    for gi, grp in enumerate(actions or []):
        for a in grp:
            if a.get("type") == "pick":
                out.append(
                    {
                        "cell": a.get("actorCellId"),
                        "ally": bool(a.get("isAllyAction")),
                        "group": gi,
                        "completed": bool(a.get("completed")),
                        "cid": a.get("championId") or 0,
                    }
                )
    return out


def enemy_after(order: list[dict], cell) -> int:
    """Picks rivales sin hacer en grupos posteriores al del pick de `cell` (aunque `cell` ya haya
    elegido: su rival de línea aún puede elegir después)."""
    mine = next((p for p in order if p["cell"] == cell and p["ally"]), None)
    if mine is None:
        return 0
    return sum(1 for p in order if not p["ally"] and not p["completed"] and p["group"] > mine["group"])


def ally_slot(order: list[dict], cell) -> int | None:
    """Posición (1–5) del pick de `cell` dentro de su equipo."""
    allies = [p for p in order if p["ally"]]
    return next((i for i, p in enumerate(allies, 1) if p["cell"] == cell), None)
