"""De partidas de match-v5 a conteos del esquema 1 (docs/FORMATO_DATOS.md). Lógica pura.

De cada partida solo se cuentan campeones, posiciones, victorias, bans, runas, hechizos y los
objetos completos y botas del final (#90): nada que identifique a un jugador. La partida en bruto se
descarta en cuanto se ha contado.
"""

from nachero.sources import dataset

POSITION = {"TOP": "top", "JUNGLE": "jungle", "MIDDLE": "middle", "BOTTOM": "bottom", "UTILITY": "utility"}
MIN_SECONDS = 300  # remakes fuera


def patch_of(game_version: str) -> str:
    return ".".join(str(game_version).split(".")[:2])


def rune_page(perks: dict) -> dict | None:
    """Página de runas de un participante en el formato del cliente (4 + 2 + 3)."""
    try:
        styles = perks["styles"]
        pri = [s["perk"] for s in styles[0]["selections"]]
        sec = [s["perk"] for s in styles[1]["selections"]]
        st = perks["statPerks"]
        mod = [st["offense"], st["flex"], st["defense"]]
    except (KeyError, IndexError, TypeError):
        return None
    return {"pri": pri, "sec": sec, "mod": mod} if (len(pri), len(sec)) == (4, 2) else None


def usable(match: dict, queue: int = 420) -> bool:
    info = (match or {}).get("info") or {}
    parts = info.get("participants") or []
    if info.get("queueId") != queue or info.get("gameDuration", 0) < MIN_SECONDS or len(parts) != 10:
        return False
    if any(p.get("gameEndedInEarlySurrender") for p in parts):
        return False
    return all(POSITION.get(p.get("teamPosition", "")) for p in parts)


def new_doc(patch: str, region: str, league: str, collector: str) -> dict:
    return {
        "schema": dataset.SCHEMA,
        "patch": patch,
        "region": region,
        "league": league,
        "generated": "",
        "cutoff": "",
        "collector": collector,
        "totals": {"games": 0},
        "champions": {},
        "matchups": {},
        "synergies": {},
    }


def _add(row: dict, win: bool) -> None:
    row["games"] = row.get("games", 0) + 1
    row["wins"] = row.get("wins", 0) + int(win)


def spell_pair(p: dict) -> list[int] | None:
    """Los dos hechizos del participante, ordenados (Destello + Aplastar = Aplastar + Destello)."""
    ids = sorted(x for x in (p.get("summoner1Id"), p.get("summoner2Id")) if isinstance(x, int) and x > 0)
    return ids if len(ids) == 2 else None


def final_items(p: dict, catalog: dict) -> tuple[list[int], list[int]]:
    """(objetos completos, botas) que llevaba al final: `item0`–`item5` (el 6 es el guardián)."""
    legendary, boots = set(catalog.get("legendary") or ()), set(catalog.get("boots") or ())
    held = {x for x in (p.get(f"item{i}") for i in range(6)) if isinstance(x, int)}
    return sorted(i for i in held if i in legendary), sorted(i for i in held if i in boots)


SKILL_KEYS = {1: "Q", 2: "W", 3: "E", 4: "R"}
ORDER_LEVELS = 11  # primeros niveles del orden de habilidades (hasta la 2.ª R: lo que se repite)
START_MS = 90_000  # compras de antes del minuto y medio: objetos iniciales


def timeline_builds(timeline: dict, catalog: dict | None) -> dict[int, dict]:
    """De los eventos de match-v5 (`/timeline`), por participante (1–10): orden de habilidades
    (primeros `ORDER_LEVELS` niveles, «QEWQQRQEQEE»), objetos iniciales (ordenados) y los tres
    primeros objetos completos en orden de compra. Las compras deshechas no cuentan."""
    legendary = set((catalog or {}).get("legendary") or ())
    events = sorted(
        (e for f in ((timeline or {}).get("info") or {}).get("frames") or [] for e in f.get("events") or []),
        key=lambda e: e.get("timestamp", 0),
    )
    out: dict[int, dict] = {}
    for e in events:
        pid = e.get("participantId")
        if not isinstance(pid, int):
            continue
        st = out.setdefault(pid, {"order": "", "start": [], "bought": []})
        kind = e.get("type")
        if kind == "SKILL_LEVEL_UP" and e.get("levelUpType", "NORMAL") == "NORMAL":
            if len(st["order"]) < ORDER_LEVELS and e.get("skillSlot") in SKILL_KEYS:
                st["order"] += SKILL_KEYS[e["skillSlot"]]
        elif kind == "ITEM_PURCHASED" and isinstance(e.get("itemId"), int):
            if e.get("timestamp", 0) <= START_MS:
                st["start"].append(e["itemId"])
            st["bought"].append(e["itemId"])
        elif kind == "ITEM_UNDO" and isinstance(e.get("beforeId"), int) and e["beforeId"]:
            for key in ("start", "bought"):  # deshace la última compra de ese objeto
                if e["beforeId"] in st[key]:
                    idx = len(st[key]) - 1 - st[key][::-1].index(e["beforeId"])
                    st[key].pop(idx)
    for st in out.values():
        core: list[int] = []
        for i in st.pop("bought"):
            if i in legendary and i not in core:
                core.append(i)
        st["core"] = core[:3] if len(core) >= 3 else []
        st["start"] = sorted(st["start"])
    return out


def _add_listed(rows: list, key: str, value, win: bool) -> None:
    """Suma a la fila de `rows` cuyo `key` es `value` (la crea si no está)."""
    same = next((r for r in rows if r[key] == value), None)
    if same is None:
        same = {key: value, "games": 0, "wins": 0}
        rows.append(same)
    _add(same, win)


def add_match(doc: dict, match: dict, catalog: dict | None = None, timeline: dict | None = None) -> bool:
    """Suma una partida al documento de su parche. False si no vale (cola, remake, posiciones).
    Con `catalog` (objetos completos y botas del parche, `items.catalog`), cuenta también la build;
    con `timeline` (#90), el orden de habilidades, los objetos iniciales y el núcleo en orden."""
    info = match["info"]
    doc["totals"]["games"] += 1
    players = []
    events = timeline_builds(timeline, catalog) if timeline else {}
    for k, p in enumerate(info["participants"]):
        cid, role, win = str(p["championId"]), POSITION[p["teamPosition"]], bool(p["win"])
        players.append((cid, role, win, p["teamId"]))
        champ = doc["champions"].setdefault(cid, {"bans": 0, "roles": {}})
        row = champ["roles"].setdefault(role, {"games": 0, "wins": 0, "runes": []})
        _add(row, win)
        page = rune_page(p.get("perks") or {})
        if page:
            same = next(
                (r for r in row["runes"] if (r["pri"], r["sec"], r["mod"]) == (page["pri"], page["sec"], page["mod"])),
                None,
            )
            if same is None:
                same = {**page, "games": 0, "wins": 0}
                row["runes"].append(same)
            _add(same, win)
        pair = spell_pair(p)
        if pair:
            spells = row.setdefault("spells", [])
            same = next((s for s in spells if s["ids"] == pair), None)
            if same is None:
                same = {"ids": pair, "games": 0, "wins": 0}
                spells.append(same)
            _add(same, win)
        if catalog:
            items, boots = final_items(p, catalog)
            for i in items:
                _add(row.setdefault("items", {}).setdefault(str(i), {}), win)
            for b in boots:
                _add(row.setdefault("boots", {}).setdefault(str(b), {}), win)
        ev = events.get(p.get("participantId", k + 1))
        if ev:
            if len(ev["order"]) == ORDER_LEVELS:
                _add_listed(row.setdefault("skills", []), "order", ev["order"], win)
            if ev["start"]:
                _add_listed(row.setdefault("starts", []), "ids", ev["start"], win)
            if ev["core"]:
                _add_listed(row.setdefault("cores", []), "ids", ev["core"], win)
    for team in info.get("teams", []):
        for b in team.get("bans", []):
            if b.get("championId", -1) > 0:
                champ = doc["champions"].setdefault(str(b["championId"]), {"bans": 0, "roles": {}})
                champ["bans"] += 1
    for cid, role, win, team in players:
        key = f"{cid}:{role}"
        for ecid, erole, _, eteam in players:
            other = f"{ecid}:{erole}"
            if eteam != team:
                _add(doc["matchups"].setdefault(key, {}).setdefault(other, {}), win)
            elif other != key:
                _add(doc["synergies"].setdefault(key, {}).setdefault(other, {}), win)
    return True


def trim_runes(doc: dict, keep: int = 8) -> None:
    """Deja las `keep` páginas de runas y parejas de hechizos más jugadas de cada campeón y rol (el
    archivo no crece sin fin). Los objetos no se recortan: hay pocos completos por campeón."""
    for champ in doc["champions"].values():
        for row in champ["roles"].values():
            row["runes"] = sorted(row.get("runes", []), key=lambda r: -r["games"])[:keep]
            for key in ("spells", "skills", "starts", "cores"):
                if key in row:
                    row[key] = sorted(row[key], key=lambda r: -r["games"])[:keep]
