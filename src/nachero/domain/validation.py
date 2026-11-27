"""¿Valen los datos propios? Comparación con Lolalytics (#21).

Por rol, frente a la tier list de referencia del mismo parche:
- **WR relativo** (WR − media del rol, para que una liga distinta no lo desplace todo) y **pick
  rate**: correlación, diferencia media absoluta y sesgo;
- **desviaciones** de cada campeón en errores típicos (z): 2 pp de diferencia con 200 partidas son
  ruido; con 20.000, no;
- **muestra**: cuánto del spread de WR de los datos propios es ruido binomial (al principio de
  parche casi todo) y cuántos campeones no llegan al mínimo de partidas.

Y, por campeón y rol con página de build en las dos fuentes, los **matchups** (d2) contra los de
Lolalytics, que sí son de la misma liga (`build_tier`).

Lógica pura: recibe tier lists y tablas de matchups ya leídas (formato de `domain/stats.py`).
"""

import math

NOISE = 2500.0  # pp²·partida: varianza binomial de un WR con p ≈ 0,5 (10⁴·p(1−p))
# Criterio orientativo para el informe (la decisión es del usuario, ver docs/DATOS.md)
GOOD_CORR, FAIR_CORR = 0.8, 0.5  # correlación del WR relativo
MAX_OUTLIERS = 0.05  # fracción de campeones con |z| > 3 que aún se acepta
MIN_SIGNAL = 0.5  # fracción del spread observado que no es ruido


def pearson(xs: list[float], ys: list[float]) -> float | None:
    """Correlación de Pearson, o None con menos de 3 puntos o sin variación."""
    n = len(xs)
    if n < 3 or n != len(ys):
        return None
    mx, my = sum(xs) / n, sum(ys) / n
    sxx = sum((x - mx) ** 2 for x in xs)
    syy = sum((y - my) ** 2 for y in ys)
    if sxx <= 0 or syy <= 0:
        return None
    return sum((x - mx) * (y - my) for x, y in zip(xs, ys, strict=True)) / math.sqrt(sxx * syy)


def _num(v) -> float | None:
    return float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v) else None


def _mean(vs: list[float]) -> float | None:
    return sum(vs) / len(vs) if vs else None


def _round(v: float | None, nd: int = 2) -> float | None:
    return None if v is None else round(v, nd)


def compare_role(own: dict | None, ref: dict | None, min_games: int = 100, top: int = 8) -> dict:
    """Tier list propia frente a la de referencia de un rol ({"avg", "champs": {cid: {wr, pr,
    games}}}). Solo cuentan los campeones con `min_games` partidas en las dos."""
    oc = (own or {}).get("champs") or {}
    rc = (ref or {}).get("champs") or {}
    o_avg = _num((own or {}).get("avg")) or 50.0
    r_avg = _num((ref or {}).get("avg")) or 50.0
    rows, thin = [], 0
    for cid, o in oc.items():
        n_o = _num(o.get("games")) or 0.0
        if n_o < min_games:
            thin += 1
            continue
        r = rc.get(cid)
        n_r = _num((r or {}).get("games")) or 0.0
        wr_o, wr_r = _num(o.get("wr")), _num((r or {}).get("wr"))
        if not r or n_r < min_games or wr_o is None or wr_r is None:
            continue
        d_o, d_r = wr_o - o_avg, wr_r - r_avg
        se = math.sqrt(NOISE / n_o + NOISE / n_r)
        rows.append({
            "id": cid, "own": round(d_o, 2), "ref": round(d_r, 2), "diff": round(d_o - d_r, 2),
            "z": round((d_o - d_r) / se, 1), "n_own": int(n_o), "n_ref": int(n_r),
            "pr_own": _num(o.get("pr")), "pr_ref": _num(r.get("pr")),
        })  # fmt: skip
    diffs = [r["diff"] for r in rows]
    prs = [(r["pr_own"], r["pr_ref"]) for r in rows if r["pr_own"] is not None and r["pr_ref"] is not None]
    # muestra: spread de los WR relativos propios (con partidas) frente al ruido de cada uno
    devs = [r["own"] for r in rows]
    var_obs = _mean([d * d for d in devs]) if devs else None
    noise = _mean([NOISE / r["n_own"] for r in rows])
    signal = None if not var_obs or noise is None else max(0.0, 1 - noise / var_obs)
    return {
        "common": len(rows),
        "own_champs": len(oc),
        "thin": thin,  # campeones propios con menos de `min_games` partidas
        "own_games": int(_num((own or {}).get("games")) or 0),
        "wr_corr": _round(pearson(devs, [r["ref"] for r in rows])),
        "pr_corr": _round(pearson([a for a, _ in prs], [b for _, b in prs])),
        "mad": _round(_mean([abs(d) for d in diffs])),
        "bias": _round(_mean(diffs)),
        "outliers": sum(1 for r in rows if abs(r["z"]) > 3),
        "signal": _round(signal),
        "worst": sorted(rows, key=lambda r: -abs(r["z"]))[:top],
    }


def compare_matchups(pairs: list[tuple[dict, dict]], min_n: int = 30) -> dict:
    """Matchups propios frente a los de referencia: `pairs` = [(lanes propias, lanes de ref)] de
    los mismos campeón y rol ({rol_rival: {cid: {d2, n}}}). Solo filas con `min_n` partidas."""
    xs, ys = [], []
    for own, ref in pairs:
        for er, rows in (own or {}).items():
            for e, o in (rows or {}).items():
                r = ((ref or {}).get(er) or {}).get(e)
                if not isinstance(o, dict) or not isinstance(r, dict):
                    continue
                d_o, d_r = _num(o.get("d2")), _num(r.get("d2"))
                if d_o is None or d_r is None:
                    continue
                if (_num(o.get("n")) or 0) < min_n or (_num(r.get("n")) or 0) < min_n:
                    continue
                xs.append(d_o)
                ys.append(d_r)
    diffs = [a - b for a, b in zip(xs, ys, strict=True)]
    return {
        "pages": len(pairs),
        "rows": len(xs),
        "d2_corr": _round(pearson(xs, ys)),
        "mad": _round(_mean([abs(d) for d in diffs])),
        "bias": _round(_mean(diffs)),
    }


def verdict(res: dict) -> tuple[str, str]:
    """(clave, texto) orientativo para un rol: "good", "fair", "poor" o "thin"."""
    if res["common"] < 10 or res["wr_corr"] is None:
        return "thin", "pocos campeones con partidas en las dos fuentes: no se puede juzgar"
    corr, signal = res["wr_corr"], res["signal"] or 0.0
    many_outliers = res["outliers"] > MAX_OUTLIERS * res["common"]
    if corr >= GOOD_CORR and signal >= MIN_SIGNAL and not many_outliers:
        return "good", "coinciden: sirven como fuente principal en este rol"
    if corr >= FAIR_CORR:
        why = "mucho ruido (faltan partidas)" if signal < MIN_SIGNAL else "desviaciones grandes en algunos campeones"
        return "fair", f"se parecen, pero con {why}"
    return "poor", "no coinciden: revisa el recolector o espera más partidas"
