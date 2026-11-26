"""Tu pool: picks a ciegas y counterpicks (issue #75).

Los vídeos de MachineLoLing concluyen que un buen pool tiene campeones **seguros a ciegas** (spread
bajo: casi nadie les hace counter) y campeones **de counter** (spread alto: sus peores matchups son
malos, pero los mejores muy buenos), y que cada uno se usa en su momento: los seguros cuando eliges
antes que tu rival de línea; los de counter, cuando ya lo ves.

El pool del rival nunca se conoce (en ranked está oculto): la probabilidad de counter de cada
campeón usa el pool medio por rol y η (`blind.py`). Lógica pura: recibe las filas de Tu pool.
"""

from nachero.domain import blind as BL
from nachero.domain.common import ROLE_ES


def classify(rows: list[dict]) -> dict:
    """Filas de un rol repartidas por etiqueta a ciegas, cada grupo de mejor a peor estimado."""
    out: dict = {"safe": [], "flex": [], "counter": [], "unknown": []}
    for r in sorted(rows, key=lambda r: -r.get("est", 0)):
        lab = (r.get("blind") or {}).get("label") or "unknown"
        out[lab].append(r)
    return out


def plan(rows: list[dict], role: str, th: dict, mastery_points=(), role_games=(), suggest=()) -> dict:
    """Diagnóstico de tu pool en `role`.

    `rows`: filas de Tu pool de ese rol (con `blind`); `mastery_points`: tus puntos de maestría por
    campeón; `role_games`: tus partidas por campeón en el rol; `suggest`: candidatos del parche
    seguros a ciegas que no están en tu pool (los busca el motor), para cubrir el hueco.
    La regla del 80 % se aplica a los campeones del rol."""
    groups = classify(rows)
    known = sum(len(groups[k]) for k in ("safe", "flex", "counter"))
    missing = []
    if known and not groups["safe"]:
        missing.append("safe")
    if known and not groups["counter"]:
        missing.append("counter")
    size_m = BL.pool_size_80(mastery_points)
    size_r = BL.pool_size_80(role_games)
    names = {k: [r["name"] for r in v[:3]] for k, v in groups.items()}
    if not known:
        text = "Calculando qué campeones de tu pool son seguros a ciegas…" if rows else ""
    elif not missing:
        text = (
            f"Si eliges antes que tu rival: {_join(names['safe'])}. "
            f"Si eliges después: {_join(names['counter'])} según el rival."
        )
    elif missing == ["safe"]:
        text = "No tienes ningún pick seguro a ciegas en este rol: si eliges pronto, te pueden counterear."
    elif missing == ["counter"] and groups["flex"]:
        text = (
            f"Para elegir pronto tienes {_join(names['safe'])}, pero ningún counter: "
            "te falta uno para cuando veas a tu rival."
        )
    elif missing == ["counter"]:
        text = "Todos tus campeones son de elegir pronto: te falta un counter para cuando veas a tu rival."
    else:
        text = "Tus campeones de este rol son intermedios: ni muy seguros a ciegas ni de counter."
    return {
        "role": role,
        "role_es": ROLE_ES.get(role, role),
        "safe": names["safe"],
        "flex": names["flex"],
        "counter": names["counter"],
        "missing": missing,
        "size_mastery": size_m,
        "size_role": size_r,
        "avg_size": int(th["pool_size"].get(role, 7)),
        "suggest": list(suggest)[:3] if "safe" in missing else [],
        "text": text,
    }


def _join(names: list[str]) -> str:
    if not names:
        return "—"
    return names[0] if len(names) == 1 else ", ".join(names[:-1]) + " o " + names[-1]


def slot_line(slot: int | None, lane_after: float, lane_p: float, pool_plan: dict | None) -> str:
    """Qué toca según tu hueco en la champ select (#75): pick seguro si tu rival de línea puede
    elegir después; counter si ya lo ves."""
    head = f"Eliges {slot}.º" if slot else "Tu turno"
    safe = (pool_plan or {}).get("safe") or []
    counter = (pool_plan or {}).get("counter") or []
    if lane_after >= 0.5:
        tail = f": {_join(safe)}" if safe else ""
        pct = f"{100 * lane_after:.0f} %"
        return f"{head}: tu rival de línea elige después con un {pct}, mejor un pick seguro a ciegas{tail}."
    if lane_p >= 0.5:
        tail = f": {_join(counter)}" if counter else ""
        return f"{head}: ya ves a tu rival de línea, es el momento de un counter{tail}."
    if lane_after > 0.01:
        return f"{head}: tu rival de línea puede elegir después ({100 * lane_after:.0f} %)."
    return ""
