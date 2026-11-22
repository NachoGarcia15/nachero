"""¿Acierta Nachero? Calibración de las recomendaciones (issue #9).

Al confirmar tu pick en una cola que cuenta (las de `history_queues`), se guarda el WR estimado
del campeón que jugaste, sus partes y lo que recomendaba Nachero. Cuando la partida aparece en tu
historial, se apunta el resultado. Con eso:

- **Por tramos**: WR estimado frente a WR real. Si Nachero está bien calibrado, en el tramo
  «52–54 %» ganas más o menos el 53 % de las partidas.
- **Por partes**: media de cada parte (meta, tú, matchups…) en victorias menos en derrotas. Una
  parte que no separa victorias de derrotas pesa de más; una que separa mucho, de menos.
- **Siguiendo la recomendación o no**: tu WR cuando juegas lo que recomendaba y cuando no.
- **A ciegas o de counter** (#71): Riot no publica el orden de picks de soloq, pero el cliente sí lo
  da en tus partidas. Se guarda qué rivales eligieron después de ti (solo campeones) y, al acabar,
  la posición real de cada rival sale del detalle de la partida: así se sabe sin inferir quién era
  tu rival de línea, si eligió después de ti y si te counteó. Con eso se estima η (cuánto counterea
  de verdad el rival que elige después) y se mide la probabilidad de counter y la inferencia de roles.

Lógica pura: sin red ni disco.
"""

BUCKETS = [(0, 46), (46, 48), (48, 50), (50, 52), (52, 54), (54, 56), (56, 101)]
MATCH_BEFORE_MS = 10 * 60 * 1000  # la partida se crea poco después de confirmar el pick
MATCH_AFTER_MS = 30 * 60 * 1000
EXPIRE_MS = 24 * 3600 * 1000  # sin partida en un día (esquivada o remake): se descarta
MIN_GAMES = 20  # por debajo, el informe avisa de que dice poco


ETA_PRIOR_GAMES = 20  # partidas a partir de las que η medido pesa más que el de los ajustes


def make_record(now_ms, queue, role, row, top, fit_kind=None, patch=None, order=None) -> dict:
    """Lo que se guarda al confirmar: `row` es la tarjeta del campeón confirmado y `top` la del
    mejor recomendado en ese momento (o None). `order` (#71): tu hueco y el riesgo al elegir
    ({"slot", "after", "lane_p", "p_counter", "lane_loss"})."""
    order = order or {}
    return {
        "t": int(now_ms),
        "queue": queue.get("id"),
        "role": role,
        "champ": row["id"],
        "name": row["name"],
        "est": row["est"],
        "parts": dict(row.get("parts", {})),
        "top": top["id"] if top else None,
        "top_est": top["est"] if top else None,
        "followed": bool(top) and top["id"] == row["id"],
        "fit": fit_kind,
        "patch": patch,
        "win": None,
        "gameId": None,
        "slot": order.get("slot"),
        "after": order.get("after"),
        "lane_p": order.get("lane_p"),
        "p_counter": order.get("p_counter"),
        "lane_loss": order.get("lane_loss"),
    }


def finish_order(rec: dict, before: list[int], after: list[int], pred: dict) -> dict:
    """Al acabar la champ select: rivales que eligieron antes y después de ti (solo campeones) y el
    rol que Nachero les estimaba (para medir la inferencia de roles)."""
    return {
        **rec,
        "enemy_before": [int(c) for c in before if c],
        "enemy_after": [int(c) for c in after if c],
        "enemy_pred": {str(c): r for c, r in pred.items() if c},
    }


def enrich(rec: dict, players: list[dict], lane_d2, threshold: float = 2.0) -> dict:
    """Con el detalle de la partida ya jugada (`players`: [{"team", "champ", "role"}]): posición real
    de cada rival, tu rival de línea, si eligió después de ti y el `d2` posterior del matchup que te
    tocó (`lane_d2(cid, rol, rival)`, o None sin datos). Solo campeones y posiciones, que son
    públicos al acabar la partida."""
    me = next((p for p in players if p.get("champ") == rec.get("champ")), None)
    if me is None:
        return {**rec, "enemy_roles": {}}
    enemies = {int(p["champ"]): p.get("role") or "" for p in players if p.get("team") != me.get("team")}
    opp = next((c for c, r in enemies.items() if r == rec.get("role")), None)
    out = {**rec, "enemy_roles": {str(c): r for c, r in enemies.items()}, "opp": opp}
    known = "enemy_after" in rec
    out["opp_after"] = (opp in rec.get("enemy_after", [])) if (opp and known) else None
    d2 = lane_d2(rec["champ"], rec["role"], opp) if opp else None
    out["opp_d2"] = round(d2, 2) if d2 is not None else None
    out["countered"] = bool(out["opp_after"]) and d2 is not None and d2 <= -threshold
    pred = rec.get("enemy_pred") or {}
    hits = [pred.get(str(c)) == r for c, r in enemies.items() if r and str(c) in pred]
    out["roles_ok"] = round(sum(hits) / len(hits), 2) if hits else None
    return out


def resolve(records: list[dict], games: list[dict], now_ms: float) -> tuple[list[dict], int]:
    """Apunta el resultado de los registros pendientes con las partidas del historial (mismo
    campeón, creada poco después de confirmar). Descarta los que llevan un día sin partida.
    Devuelve (registros, cuántos se han resuelto)."""
    used = {r["gameId"] for r in records if r.get("gameId")}
    out, done = [], 0
    for r in records:
        if r.get("win") is not None:
            out.append(r)
            continue
        match = next(
            (
                g
                for g in sorted(games, key=lambda g: g["t"])
                if g["champ"] == r["champ"]
                and g["gameId"] not in used
                and r["t"] - MATCH_BEFORE_MS <= g["t"] <= r["t"] + MATCH_AFTER_MS
            ),
            None,
        )
        if match:
            used.add(match["gameId"])
            out.append({**r, "win": bool(match["win"]), "gameId": match["gameId"]})
            done += 1
        elif now_ms - r["t"] < EXPIRE_MS:
            out.append(r)
    return out, done


def _wr(rs):
    return round(100 * sum(r["win"] for r in rs) / len(rs), 1) if rs else None


def report(records: list[dict], eta_prior: float = 0.5) -> dict:
    """Informe de calibración con los registros ya resueltos. `eta_prior`: η de los ajustes."""
    done = [r for r in records if r.get("win") is not None]
    n = len(done)
    buckets = []
    for lo, hi in BUCKETS:
        rs = [r for r in done if lo <= r["est"] < hi]
        buckets.append(
            {
                "label": f"< {hi} %" if lo == 0 else f"≥ {lo} %" if hi > 100 else f"{lo}–{hi} %",
                "n": len(rs),
                "est": round(sum(r["est"] for r in rs) / len(rs), 1) if rs else None,
                "wr": _wr(rs),
            }
        )
    wins = [r for r in done if r["win"]]
    losses = [r for r in done if not r["win"]]
    keys = sorted({k for r in done for k in r.get("parts", {})})
    parts = []
    for k in keys:
        mw = sum(r["parts"].get(k, 0) for r in wins) / len(wins) if wins else 0.0
        ml = sum(r["parts"].get(k, 0) for r in losses) / len(losses) if losses else 0.0
        parts.append({"part": k, "wins": round(mw, 2), "losses": round(ml, 2), "gap": round(mw - ml, 2)})
    brier = sum((r["est"] / 100 - r["win"]) ** 2 for r in done) / n if n else None
    followed = [r for r in done if r.get("followed")]
    other = [r for r in done if not r.get("followed")]
    return {
        "order": order_report(done, eta_prior),
        "n": n,
        "pending": sum(1 for r in records if r.get("win") is None),
        "enough": n >= MIN_GAMES,
        "est": round(sum(r["est"] for r in done) / n, 1) if n else None,
        "wr": _wr(done),
        "brier": round(brier, 4) if brier is not None else None,
        "buckets": buckets,
        "parts": parts,
        "followed": {"n": len(followed), "wr": _wr(followed)},
        "other": {"n": len(other), "wr": _wr(other)},
        "recent": [
            {k: r.get(k) for k in ("t", "name", "role", "est", "win", "followed")}
            for r in sorted(done, key=lambda r: -r["t"])[:10]
        ],
    }


def _group(rs):
    d2s = [r["opp_d2"] for r in rs if r.get("opp_d2") is not None]
    return {"n": len(rs), "wr": _wr(rs), "d2": round(sum(d2s) / len(d2s), 2) if d2s else None}


def estimate_eta(records: list[dict], prior: float = 0.5) -> dict:
    """η medido con tus partidas: cuando tu rival de línea eligió después de ti, ¿cuánto peor fue tu
    matchup frente a lo que se perdería si siempre te counterease (η = 1)?
        η̂ = Σ(−d2 del matchup) / Σ(pérdida esperada con η = 1)
    Con pocas partidas se mezcla con el valor de los ajustes (pesa como 20 partidas)."""
    rs = [r for r in records if r.get("opp_after") and r.get("opp_d2") is not None and (r.get("lane_loss") or 0) > 0.05]
    n = len(rs)
    raw = sum(-r["opp_d2"] for r in rs) / sum(r["lane_loss"] for r in rs) if rs else None
    raw = None if raw is None else max(0.0, min(1.0, raw))
    mixed = prior if raw is None else (n * raw + ETA_PRIOR_GAMES * prior) / (n + ETA_PRIOR_GAMES)
    return {"n": n, "raw": round(raw, 2) if raw is not None else None, "value": round(mixed, 2)}


def order_report(done: list[dict], eta_prior: float = 0.5) -> dict:
    """A ciegas (tu rival de línea eligió después) frente a de counter, calibración de la
    probabilidad de counter, η medido y acierto de la inferencia de roles."""
    blind = [r for r in done if r.get("opp_after") is True]
    counter = [r for r in done if r.get("opp_after") is False]
    pcs = [r for r in blind if r.get("p_counter") is not None]
    roles = [r["roles_ok"] for r in done if r.get("roles_ok") is not None]
    by_role: dict = {}
    for r in blind:
        by_role.setdefault(r.get("role"), []).append(r)
    return {
        "blind": _group(blind),
        "counter": _group(counter),
        "p_counter": {
            "n": len(pcs),
            "pred": round(100 * sum(r["p_counter"] for r in pcs) / len(pcs), 1) if pcs else None,
            "obs": round(100 * sum(bool(r.get("countered")) for r in pcs) / len(pcs), 1) if pcs else None,
        },
        "eta": estimate_eta(done, eta_prior),
        "eta_by_role": {k: estimate_eta(v, eta_prior) for k, v in by_role.items() if k},
        "roles": {"n": len(roles), "pct": round(100 * sum(roles) / len(roles)) if roles else None},
    }
