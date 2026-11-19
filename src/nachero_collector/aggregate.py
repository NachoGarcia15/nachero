"""De partidas de match-v5 a conteos del esquema 1 (docs/FORMATO_DATOS.md). Lógica pura.

De cada partida solo se cuentan campeones, posiciones, victorias, bans y runas: nada que
identifique a un jugador. La partida en bruto se descarta en cuanto se ha contado.
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


def add_match(doc: dict, match: dict) -> bool:
    """Suma una partida al documento de su parche. False si no vale (cola, remake, posiciones)."""
    info = match["info"]
    doc["totals"]["games"] += 1
    players = []
    for p in info["participants"]:
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
    """Deja las `keep` páginas más jugadas de cada campeón y rol (el archivo no crece sin fin)."""
    for champ in doc["champions"].values():
        for row in champ["roles"].values():
            row["runes"] = sorted(row.get("runes", []), key=lambda r: -r["games"])[:keep]
