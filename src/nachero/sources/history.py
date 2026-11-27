"""Historial de soloq del jugador leido del cliente (con cache local)."""

import os

from nachero.jsonio import read_json, write_json

LANE_ROLE = {"TOP": "top", "JUNGLE": "jungle", "MIDDLE": "middle", "MID": "middle"}


def role_of(p: dict) -> str:
    """Rol de una partida del historial del cliente, o "" si no se puede saber.

    El cliente da `timeline.lane`/`timeline.role` (a veces "NONE"): Smite manda; despues la linea;
    en la linea de abajo (o sin linea), el rol SUPPORT es support.
    """
    tl = p.get("timeline", {})
    lane, role = tl.get("lane", ""), tl.get("role", "")
    if 11 in (p.get("spell1Id"), p.get("spell2Id")):
        return "jungle"
    if lane in LANE_ROLE:
        return LANE_ROLE[lane]
    if "SUPPORT" in role:
        return "utility"
    if lane == "BOTTOM":
        return "bottom"
    return ""


GAME_KEYS = ("gameId", "t", "champ", "role", "win", "gpm", "dpm", "cspm")


def valid_games(data) -> list[dict]:
    """Las partidas guardadas que valen (con todo lo que usa el modelo personal). Un archivo roto u
    otro tipo no debe tumbar la sesión en cada intento («Reiniciando tras un error» cada 3 s)."""
    if not isinstance(data, list):
        return []
    return [g for g in data if isinstance(g, dict) and all(k in g for k in GAME_KEYS)]


def load_history(lcu, cache_path, queues, log, import_path=None):
    """Historial del cliente (últimas 200 partidas) unido al guardado. Con `import_path`, también las
    partidas de `history_import.json` (tu temporada completa, del recolector: ver docs/RECOLECTOR.md)."""
    cache = {}
    if os.path.exists(cache_path):
        try:
            cache = {g["gameId"]: g for g in valid_games(read_json(cache_path, []))}
        except Exception:
            cache = {}
    if import_path and os.path.exists(import_path):
        try:
            extra = [g for g in valid_games(read_json(import_path, [])) if g.get("role")]
            added = sum(1 for g in extra if g["gameId"] not in cache)
            for g in extra:
                cache.setdefault(g["gameId"], g)
            if added:
                log(f"Historial: {added} partidas importadas de tu temporada", "ok")
        except Exception:
            log("No pude leer history_import.json: lo ignoro", "warn")
    try:
        mh = (
            lcu.req(
                "GET", "/lol-match-history/v1/products/lol/current-summoner/matches?begIndex=0&endIndex=199", timeout=60
            )
            or {}
        )
    except Exception as e:
        log(f"No pude leer el historial del cliente ({e.__class__.__name__}); uso el guardado.", "warn")
        mh = {}
    for g in (mh.get("games") or {}).get("games") or []:
        try:
            game = parse_game(g, queues)
        except (KeyError, TypeError, IndexError, ValueError, AttributeError):
            continue  # una partida rara del cliente no tumba la lectura del resto
        if game:
            cache[game["gameId"]] = game
    games = sorted(cache.values(), key=lambda g: -g["t"])
    write_json(cache_path, games)
    return games


def parse_game(g: dict, queues) -> dict | None:
    """Una partida del historial del cliente en el formato del modelo personal, o None si no
    cuenta (otra cola, menos de 5 min o sin rol)."""
    if g["queueId"] not in queues or g["gameDuration"] <= 300:
        return None
    p = g["participants"][0]
    s = p["stats"]
    role = role_of(p)
    if not role:
        return None
    m = g["gameDuration"] / 60
    return {
        "gameId": g["gameId"],
        "t": g["gameCreation"],
        "patch": ".".join(g["gameVersion"].split(".")[:2]),
        "champ": p["championId"],
        "role": role,
        "win": s["win"],
        "k": s["kills"],
        "d": s["deaths"],
        "a": s["assists"],
        "gpm": s["goldEarned"] / m,
        "dpm": s["totalDamageDealtToChampions"] / m,
        "cspm": (s["totalMinionsKilled"] + s["neutralMinionsKilled"]) / m,
    }
