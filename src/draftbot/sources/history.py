"""Historial de soloq del jugador leido del cliente (con cache local)."""

import os

from draftbot.jsonio import read_json, write_json


def load_history(lcu, cache_path, queues, log):
    cache = {}
    if os.path.exists(cache_path):
        try:
            cache = {g["gameId"]: g for g in read_json(cache_path, [])}
        except Exception:
            cache = {}
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
    for g in mh.get("games", {}).get("games", []):
        if g["queueId"] not in queues or g["gameDuration"] <= 300:
            continue
        p = g["participants"][0]
        s, tl = p["stats"], p.get("timeline", {})
        role = (
            "jungle"
            if 11 in (p["spell1Id"], p["spell2Id"])
            else {"TOP": "top", "MIDDLE": "middle", "MID": "middle"}.get(tl.get("lane"), "")
        )
        if not role and tl.get("lane") == "BOTTOM":
            role = "utility" if "SUPPORT" in tl.get("role", "") else "bottom"
        if not role:
            continue
        m = g["gameDuration"] / 60
        cache[g["gameId"]] = {
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
    games = sorted(cache.values(), key=lambda g: -g["t"])
    write_json(cache_path, games)
    return games
