"""Vista «En partida» (#88): los drafts de los dos equipos, su puntuación y la build recomendada.

Normas de Riot (docs/ROADMAP.md): solo lo que el jugador ya ve en la pantalla de carga. Campeones
y hechizos de los diez; el rol de tus aliados (lo ves en la champ select) y el de los rivales
**estimado** a partir de sus campeones, como en el draft: nunca se lee del cliente. Ni nombres, ni
rangos, ni historiales de otros jugadores. Todo se enseña en la ventana de Nachero, no en el juego.

Puntuación, en puntos de winrate como el resto de la app (`Engine.score`):
- cada campeón: fuerza en el parche + rival de línea + resto del rival + encaje con su equipo +
  sinergias + contra su composición. Sin tu parte personal ni el riesgo de counter (ya no queda
  nadie por elegir), para que tus aliados y los rivales se midan igual;
- cada equipo: la media de sus cinco (cada puntuación ya es el WR de su equipo con ese campeón);
- ventaja de draft = (media de tu equipo − media del rival) / 2, para que los dos WR estimados
  sumen 100: WR estimado de tu equipo = 50 + ventaja.
"""

import itertools
import math

from nachero.domain import roles as R
from nachero.domain import tags as T
from nachero.domain.common import ROLE_ES, ROLE_SHORT, ROLES
from nachero.domain.engine import comp_summary, role_probs

POSITION = {"TOP": "top", "JUNGLE": "jungle", "MIDDLE": "middle", "MID": "middle", "BOTTOM": "bottom",
            "BOT": "bottom", "UTILITY": "utility", "SUPPORT": "utility"}  # fmt: skip
DRAFT_PARTS = ("meta", "lane", "enemies", "allies", "synergy", "vs_comp")


def position(p) -> str | None:
    """Rol de Nachero de una posición del cliente («JUNGLE», «jungle», «UTILITY»…), o None."""
    if not isinstance(p, str):
        return None
    return POSITION.get(p.upper()) or (p if p in ROLES else None)


def _cid(v) -> int:
    return v if isinstance(v, int) and not isinstance(v, bool) and v > 0 else 0


def parse_game(gameflow, my_puuid=None, champ_select=None) -> dict | None:
    """Equipos de la partida en curso, de `/lol-gameflow/v1/session` y de la última sesión de champ
    select (si la hay). Devuelve {"ally": [jugador], "enemy": [jugador], "me": cid}, con jugador =
    {"id": cid, "role": rol | None, "spells": [id, id], "me": bool}; None si no hay campeones.

    El rol de tus aliados sale de la champ select (`assignedPosition`) o, si no está, de la posición
    de tu equipo en la partida; el de los rivales queda vacío para estimarlo luego (`assign_roles`).
    Nada de nombres ni puuid de otros jugadores sale de aquí."""
    gd = (gameflow or {}).get("gameData") or {}
    cs = champ_select if isinstance(champ_select, dict) else {}
    one, two = gd.get("teamOne") or [], gd.get("teamTwo") or []
    spells = {}
    for sel in gd.get("playerChampionSelections") or []:
        cid = _cid(sel.get("championId"))
        if cid:
            spells[cid] = [s for s in (sel.get("spell1Id"), sel.get("spell2Id")) if _cid(s)]
    cs_me: dict = next((m for m in cs.get("myTeam") or [] if m.get("cellId") == cs.get("localPlayerCellId")), {})
    me_cid = _cid(cs_me.get("championId"))
    for m in one + two:
        if my_puuid and m.get("puuid") == my_puuid:
            me_cid = _cid(m.get("championId")) or me_cid
    cs_roles = {_cid(m.get("championId")): position(m.get("assignedPosition")) for m in cs.get("myTeam") or []}
    for m in cs.get("myTeam") or []:  # hechizos de tu equipo en la champ select, si la partida no los da
        cid = _cid(m.get("championId"))
        if cid and cid not in spells:
            spells[cid] = [s for s in (m.get("spell1Id"), m.get("spell2Id")) if _cid(s)]

    def ids(team):
        return [_cid(m.get("championId")) for m in team if _cid(m.get("championId"))]

    if one or two:

        def mine(team):
            return any(my_puuid and m.get("puuid") == my_puuid for m in team) or (me_cid and me_cid in ids(team))

        in_one, in_two = mine(one), mine(two)
        if not in_one and not in_two:  # sin puuid ni tu campeón: por tus aliados de la champ select
            in_one = len(set(cs_roles) & set(ids(one))) >= len(set(cs_roles) & set(ids(two)))
        mine_first = in_one or not in_two
        ally_team, enemy_team = (one, two) if mine_first else (two, one)
        ally = []
        for m in ally_team:
            cid = _cid(m.get("championId"))
            ally.append((cid, cs_roles.get(cid) or position(m.get("selectedPosition"))))
        enemy = [(_cid(m.get("championId")), None) for m in enemy_team]
    else:  # sin la partida: lo que se vio en la champ select
        ally = [(_cid(m.get("championId")), cs_roles.get(_cid(m.get("championId")))) for m in cs.get("myTeam") or []]
        enemy = [(_cid(m.get("championId")), None) for m in cs.get("theirTeam") or []]
    ally = [(c, r) for c, r in ally if c]
    enemy = [(c, r) for c, r in enemy if c]
    if not ally and not enemy:
        return None

    def players(team):
        return [{"id": c, "role": r, "spells": spells.get(c, []), "me": c == me_cid} for c, r in team]

    return {"ally": players(ally), "enemy": players(enemy), "me": me_cid}


def assign_roles(ids, free, lola, cfg=None) -> dict:
    """Asignación más probable de los roles libres `free` a los campeones `ids` (mismos pesos que
    `engine.infer_roles`: reparto por rol en Master+ con un suelo para fuera de rol)."""
    ids, free = [c for c in ids if c], [r for r in ROLES if r in free]
    if not ids or not free:
        return {}
    th = R.settings(cfg)
    splits = {c: R.split_of(lola, c) for c in ids}
    best, best_score = None, -1e18
    n = min(len(ids), len(free))
    for chosen in itertools.permutations(free, n):
        sc = sum(math.log(R.assign_weight(splits[c], r, th)) for c, r in zip(ids[:n], chosen, strict=True))
        if sc > best_score:
            best, best_score = chosen, sc
    return dict(zip(ids[:n], best or (), strict=True))


def fill_roles(players, lola, cfg=None, my_role=None) -> dict:
    """{cid: rol} del equipo: los conocidos (el tuyo, `my_role`, manda sobre el que falte) y el resto
    estimados entre los roles que quedan libres."""
    known: dict[int, str] = {}
    for p in players:
        r = p["role"] or (my_role if p.get("me") else None)
        if r and r not in known.values():
            known[p["id"]] = r
    rest = [p["id"] for p in players if p["id"] not in known]
    known.update(assign_roles(rest, set(ROLES) - set(known.values()), lola, cfg))
    return known


def draft_score(row) -> float:
    """Puntuación de draft de una tarjeta de `Engine.score`: sin tu parte ni el riesgo de counter."""
    return sum(row["parts"].get(k, 0.0) for k in DRAFT_PARTS)


def _player(engine, champs, p, role, row, spells_known=True) -> dict:
    lane = next((m for m in row["matchups"] if m["lane"]), None)
    return {
        "id": p["id"],
        "name": champs.name(p["id"]),
        "me": bool(p.get("me")),
        "role": role,
        "role_es": ROLE_ES.get(role or "", ""),
        "role_short": ROLE_SHORT.get(role or "", ""),
        "spells": p["spells"] if spells_known else [],
        "score": round(draft_score(row), 1),
        "parts": {k: row["parts"][k] for k in DRAFT_PARTS if k in row["parts"]},
        "tier": row.get("tier"),
        "loaded": bool(row["matchups_loaded"]),
        "lane": {"id": lane["id"], "name": lane["name"], "post": lane["post"], "n": lane["n"]} if lane else None,
        "why": row["why"][:3],
    }


def team_notes(ally, enemy, ally_ident, enemy_ident) -> list[str]:
    """Qué tener en cuenta en la partida: con qué defenderse y cómo pelear."""
    notes = []
    if enemy["n"] >= 3 and enemy["phys"] is not None and enemy["phys"] >= 70:
        notes.append(f"Rival muy físico ({enemy['phys']} % del daño): la armadura rinde mucho.")
    elif enemy["n"] >= 3 and enemy["phys"] is not None and enemy["phys"] <= 30:
        notes.append(f"Rival muy mágico ({100 - enemy['phys']} % del daño): la resistencia mágica rinde mucho.")
    if enemy["cc"] >= 9:
        notes.append("Mucho control en el rival: Mercurio o QSS, y cuidado con quedarte sin escapes.")
    if ally["n"] >= 4 and ally["front"] == 0:
        notes.append("Tu equipo no tiene frontline: evita las peleas largas de cara.")
    if ally["n"] >= 4 and ally_ident[2].get("E", 0) < 0.5:
        notes.append("Tu equipo no tiene engage: mejor jugar a contraatacar que a forzar peleas.")
    if enemy["n"] >= 4 and enemy_ident[2].get("E", 0) >= 2:
        notes.append("El rival tiene mucho engage: no os separéis sin visión.")
    return notes


def report(engine, champs, game, my_role=None) -> dict:
    """Drafts y estadísticas de la partida `game` (de `parse_game`), con el motor de siempre."""
    lola, cfg = engine.lola, engine.cfg
    ally_roles = fill_roles(game["ally"], lola, cfg, my_role)
    enemy_roles = fill_roles(game["enemy"], lola, cfg)  # estimados: el cliente no los enseña
    ally_ids = [p["id"] for p in game["ally"]]
    enemy_ids = [p["id"] for p in game["enemy"]]
    every = set(ally_ids) | set(enemy_ids)
    probs = role_probs(enemy_ids, lola, cfg)

    def side(players, roles, mates, rivals, rival_roles):
        out = []
        for p in players:
            role = roles.get(p["id"])
            if not role:
                continue
            allies = [(c, 1.0) for c in mates if c != p["id"]]
            mate_roles = {c: roles[c] for c in mates if c != p["id"] and c in roles}
            row = engine.score(p["id"], role, allies, rivals, rival_roles, 0, False, every, 0, mate_roles)
            out.append(_player(engine, champs, p, role, row))
        out.sort(key=lambda x: ROLES.index(x["role"]))
        return out

    ally = side(game["ally"], ally_roles, ally_ids, enemy_ids, probs)
    enemy = side(game["enemy"], enemy_roles, enemy_ids, ally_ids, {c: r for c, r in ally_roles.items()})
    mean_a = sum(p["score"] for p in ally) / len(ally) if ally else 0.0
    mean_e = sum(p["score"] for p in enemy) / len(enemy) if enemy else 0.0
    adv = (mean_a - mean_e) / 2 if ally and enemy else 0.0
    lanes = []
    for r in ROLES:
        a = next((p for p in ally if p["role"] == r), None)
        e = next((p for p in enemy if p["role"] == r), None)
        if not a or not e:
            continue
        # el matchup desde tu lado (su delta 2 encogido); si aún no está, el del rival cambiado de signo
        post = a["lane"]["post"] if a["lane"] and a["lane"]["id"] == e["id"] else None
        if post is None and e["lane"] and e["lane"]["id"] == a["id"]:
            post = -e["lane"]["post"]
        lanes.append(
            {
                "role": r,
                "role_es": ROLE_ES[r],
                "role_short": ROLE_SHORT[r],
                "ally": {"id": a["id"], "name": a["name"], "me": a["me"]},
                "enemy": {"id": e["id"], "name": e["name"]},
                "post": post,
                "loaded": a["loaded"] or e["loaded"],
            }
        )
    ally_comp, enemy_comp = comp_summary(ally_ids, champs), comp_summary(enemy_ids, champs)
    ally_ident = T.identity([(c, 1.0) for c in ally_ids], champs)
    enemy_ident = T.identity([(c, 1.0) for c in enemy_ids], champs)
    ally_comp["identity"], enemy_comp["identity"] = T.IDENTITY_ES[ally_ident[0]], T.IDENTITY_ES[enemy_ident[0]]
    ally_comp["engage"], enemy_comp["engage"] = round(ally_ident[2]["E"], 1), round(enemy_ident[2]["E"], 1)
    me = next((p for p in ally if p["me"]), None)
    return {
        "ally": ally,
        "enemy": enemy,
        "me": me,
        "my_role": me["role"] if me else my_role,
        "lanes": lanes,
        "ally_comp": ally_comp,
        "enemy_comp": enemy_comp,
        "notes": team_notes(ally_comp, enemy_comp, ally_ident, enemy_ident),
        "team": {
            "ally": round(mean_a, 1),
            "enemy": round(mean_e, 1),
            "advantage": round(adv, 1),
            "est": round(50 + adv, 1),
        },
        "loaded": all(p["loaded"] for p in ally + enemy),
    }


def build_view(build, items, which="pick") -> dict | None:
    """Build recomendada para el panel, con nombres de objetos (`items.brief(id)` → {id, name}).
    `which`: «pick» (la más jugada, por defecto) o «win» (la más ganadora); si no está, la otra.
    Varias opciones para los objetos 4.º a 6.º, nunca una sola respuesta."""
    if not build:
        return None
    page = build.get(which) or build.get("win" if which == "pick" else "pick")
    if not page:
        return None
    other = build.get("win" if which == "pick" else "pick") or {}

    def brief(i):
        return items.brief(i) if i else None

    alt_core = [brief(i) for i in other.get("core", [])] if other.get("core") and other["core"] != page["core"] else []
    slots = []
    for n, opts in enumerate(page.get("options") or [], start=4):
        if opts:
            slots.append({"slot": n, "items": [{**brief(o["id"]), "wr": o.get("wr"), "n": o.get("n")} for o in opts]})
    return {
        "which": which if build.get(which) else ("win" if which == "pick" else "pick"),
        "start": [brief(i) for i in page.get("start", [])],
        "core": [brief(i) for i in page.get("core", [])],
        "core_wr": page.get("core_wr"),
        "core_n": page.get("core_n"),
        "boots": brief(page.get("boots")),
        "slots": slots,
        "skills": page.get("skills", ""),
        "order": page.get("order", ""),
        "spells": page.get("spells", []),
        "alt_core": alt_core,
        "alt_core_wr": other.get("core_wr") if alt_core else None,
    }
