"""¿Acierta Nachero? Calibración de las recomendaciones (issue #9).

Al confirmar tu pick en una cola que cuenta (las de `history_queues`), se guarda el WR estimado
del campeón que jugaste, sus partes y lo que recomendaba Nachero. Cuando la partida aparece en tu
historial, se apunta el resultado. Con eso:

- **Por tramos**: WR estimado frente a WR real. Si Nachero está bien calibrado, en el tramo
  «52–54 %» ganas más o menos el 53 % de las partidas.
- **Por partes**: media de cada parte (meta, tú, matchups…) en victorias menos en derrotas. Una
  parte que no separa victorias de derrotas pesa de más; una que separa mucho, de menos.
- **Siguiendo la recomendación o no**: tu WR cuando juegas lo que recomendaba y cuando no.

Lógica pura: sin red ni disco.
"""

BUCKETS = [(0, 46), (46, 48), (48, 50), (50, 52), (52, 54), (54, 56), (56, 101)]
MATCH_BEFORE_MS = 10 * 60 * 1000  # la partida se crea poco después de confirmar el pick
MATCH_AFTER_MS = 30 * 60 * 1000
EXPIRE_MS = 24 * 3600 * 1000  # sin partida en un día (esquivada o remake): se descarta
MIN_GAMES = 20  # por debajo, el informe avisa de que dice poco


def make_record(now_ms, queue, role, row, top, fit_kind=None, patch=None) -> dict:
    """Lo que se guarda al confirmar: `row` es la tarjeta del campeón confirmado y `top` la del
    mejor recomendado en ese momento (o None)."""
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
    }


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


def report(records: list[dict]) -> dict:
    """Informe de calibración con los registros ya resueltos."""
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
