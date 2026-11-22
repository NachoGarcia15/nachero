"""Intercambios de orden de pick: el campeón, no el rol (issue #74).

Conclusión del segundo vídeo de MachineLoLing: quién elige primero depende del campeón que va a
jugar cada uno, no del rol. Entre roles la diferencia media de probabilidad de counter es ~16 %;
dentro de un rol, enorme (Nami es más ciega que Nocturne). Ante un intercambio, se compara el
riesgo de counter de los dos campeones en cada hueco.

Solo con campeón marcado: sin él, la media del rol no basta. El beneficio es del equipo: lo que baja
tu pérdida esperada menos lo que sube la del aliado. Nachero aconseja; proponer, aceptar o rechazar
el cambio es siempre un clic del jugador (normas de Riot).

Lógica pura: `loss(cid, rol, picks_rivales_después)` devuelve (pérdida en pp ≥ 0, probabilidad de
counter 0-1) y la pone quien llama (el motor).
"""

SWAP_STATES_OPEN = ("AVAILABLE",)  # se puede pedir el cambio
SWAP_STATE_IN = "RECEIVED"  # te lo piden a ti
SWAP_STATE_OUT = "SENT"  # lo has pedido tú


def _eval(loss, who, after):
    lo, p = loss(who["cid"], who["role"], after)
    return lo, p


def compare(me: dict, ally: dict, loss) -> dict:
    """Ganancia del equipo (pp) si `me` y `ally` cambian de hueco. Cada uno: {"cid", "role",
    "after"} (picks rivales después de su hueco). Devuelve los riesgos antes y después."""
    me_now, pm_now = _eval(loss, me, me["after"])
    me_then, pm_then = _eval(loss, me, ally["after"])
    al_now, pa_now = _eval(loss, ally, ally["after"])
    al_then, pa_then = _eval(loss, ally, me["after"])
    return {
        "gain": (me_now + al_now) - (me_then + al_then),
        "me": (pm_now, pm_then),
        "ally": (pa_now, pa_then),
    }


def advise(me: dict | None, allies: list[dict], loss, swaps=(), min_gain: float = 0.5) -> dict | None:
    """Consejo de intercambio para el panel.

    `me`: tu pick pendiente {"cell", "cid", "role", "after"} (o None si ya elegiste). `allies`:
    aliados con pick pendiente {"cell", "cid" (0 si no marca), "role", "after", "name", "slot"}.
    `swaps`: `pickOrderSwaps` del cliente [{"cellId", "id", "state"}].

    Prioridad: una petición que te llega (aceptar o rechazar) y, si no, el mejor cambio que puedes
    proponer con una ganancia de al menos `min_gain` pp. None si no hay nada que decir."""
    if not me or not me.get("cid"):
        return None
    by_cell = {s.get("cellId"): s for s in swaps or () if isinstance(s, dict)}
    pending = [a for a in allies if a.get("cell") != me.get("cell")]
    # 1) te piden cambiar
    for a in pending:
        sw = by_cell.get(a["cell"])
        if not sw or sw.get("state") != SWAP_STATE_IN:
            continue
        if a.get("cid"):
            c = compare(me, a, loss)
            gain = c["gain"]
        else:  # no marca campeón: solo se sabe lo tuyo
            me_now, pm_now = _eval(loss, me, me["after"])
            me_then, pm_then = _eval(loss, me, a["after"])
            c = {"gain": me_now - me_then, "me": (pm_now, pm_then), "ally": None}
            gain = c["gain"]
        return {
            "kind": "incoming",
            "verdict": "accept" if gain >= 0 else "decline",
            "swap_id": sw.get("id"),
            "cell": a["cell"],
            "slot": a.get("slot"),
            "name": a.get("name", ""),
            "ally_cid": a.get("cid") or 0,
            "gain": round(gain, 2),
            "me": c["me"],
            "ally": c["ally"],
        }
    # 2) propón tú el cambio que más gana
    best = None
    for a in pending:
        if not a.get("cid") or a["after"] == me["after"]:
            continue
        c = compare(me, a, loss)
        if c["gain"] >= min_gain and (best is None or c["gain"] > best[1]["gain"]):
            best = (a, c)
    if not best:
        return None
    a, c = best
    sw = by_cell.get(a["cell"]) or {}
    state = sw.get("state")
    return {
        "kind": "propose",
        "verdict": "sent" if state == SWAP_STATE_OUT else "propose",
        "swap_id": sw.get("id") if state in (*SWAP_STATES_OPEN, SWAP_STATE_OUT) else None,
        "cell": a["cell"],
        "slot": a.get("slot"),
        "name": a.get("name", ""),
        "ally_cid": a["cid"],
        "gain": round(c["gain"], 2),
        "me": c["me"],
        "ally": c["ally"],
    }


def message(adv: dict | None, my_name: str, ally_champ: str) -> str:
    """Frase del consejo para el panel (y para copiar al chat)."""
    if not adv:
        return ""
    pm_now, pm_then = (round(100 * x) for x in adv["me"])
    mine = f"tu {my_name} pasa del {pm_now} % al {pm_then} % de counter"
    theirs = ""
    if adv.get("ally"):
        pa_now, pa_then = (round(100 * x) for x in adv["ally"])
        theirs = f" y su {ally_champ} del {pa_now} % al {pa_then} %"
    who = f"{adv['name']} (pick {adv['slot']})" if adv.get("slot") else adv["name"]
    if adv["kind"] == "incoming":
        head = "Acepta el cambio con" if adv["verdict"] == "accept" else "Mejor no cambies con"
        return f"{head} {who}: {mine}{theirs}."
    if adv["verdict"] == "sent":
        return f"Has pedido cambiar con {who}: {mine}{theirs}."
    return f"Propón cambiar de turno con {who}: {mine}{theirs}."


def chat_line(adv: dict | None, my_name: str, ally_champ: str) -> str:
    """Mensaje corto para el chat de la champ select (lo copia el jugador si quiere)."""
    if not adv or adv["kind"] != "propose" or not adv.get("ally"):
        return ""
    pm_now, pm_then = (round(100 * x) for x in adv["me"])
    pa_now, pa_then = (round(100 * x) for x in adv["ally"])
    return (
        f"¿Cambiamos turno? Así nos counterean menos: {my_name} {pm_now}%→{pm_then}%, {ally_champ} {pa_now}%→{pa_then}%"
    )
