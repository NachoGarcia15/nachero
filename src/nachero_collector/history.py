"""Tu historial completo de la temporada para «Tu pool» (el cliente solo da las últimas 200).

Solo tu propio puuid (por tu Riot ID): no se identifica a nadie más. Escribe un archivo con el
formato del historial de la app, que Nachero importa si lo dejas en la carpeta de tu perfil
(`history_import.json`).
"""

import json
import time
from pathlib import Path

from nachero_collector.aggregate import MIN_SECONDS, POSITION, patch_of


def game_of(match: dict, puuid: str) -> dict | None:
    """Tu partida en el formato del historial de la app, o None (remake, sin posición…)."""
    info = (match or {}).get("info") or {}
    me = next((p for p in info.get("participants", []) if p.get("puuid") == puuid), None)
    secs = info.get("gameDuration", 0)
    role = POSITION.get((me or {}).get("teamPosition", ""))
    if not me or not role or secs < MIN_SECONDS or me.get("gameEndedInEarlySurrender"):
        return None
    mins = secs / 60
    return {
        "gameId": int(str(info.get("gameId") or match["metadata"]["matchId"].split("_")[-1])),
        "t": info.get("gameCreation", 0),
        "patch": patch_of(info.get("gameVersion", "")),
        "champ": me["championId"],
        "role": role,
        "win": bool(me["win"]),
        "k": me.get("kills", 0),
        "d": me.get("deaths", 0),
        "a": me.get("assists", 0),
        "gpm": me.get("goldEarned", 0) / mins,
        "dpm": me.get("totalDamageDealtToChampions", 0) / mins,
        "cspm": (me.get("totalMinionsKilled", 0) + me.get("neutralMinionsKilled", 0)) / mins,
    }


def import_history(riot, riot_id: str, out_path, since: float, queues=(420, 440), known=(), log=print) -> int:
    """Descarga tus partidas desde `since` (epoch) y las escribe en `out_path`. Devuelve cuántas."""
    name, _, tag = riot_id.partition("#")
    puuid = riot.puuid_of(name, tag) if name and tag else None
    if not puuid:
        raise ValueError(f"no encuentro la cuenta {riot_id!r} (formato Nombre#TAG)")
    out_path = Path(out_path)
    try:
        games = {g["gameId"]: g for g in json.loads(out_path.read_text(encoding="utf-8"))}
    except (OSError, ValueError, TypeError, KeyError):
        games = {}
    known = set(known) | set(games)
    ids = []
    for q in queues:
        ids += riot.match_ids(puuid, q, start_time=since)
    todo = [m for m in dict.fromkeys(ids) if int(m.split("_")[-1]) not in known]
    log(f"{len(todo)} partidas tuyas por descargar")
    for mid in todo:
        g = game_of(riot.match(mid), puuid)
        if g:
            games[g["gameId"]] = g
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(sorted(games.values(), key=lambda g: -g["t"])), encoding="utf-8")
    return len(games)


def season_start(year: int | None = None) -> float:
    """Principio de la temporada (enero del año en curso), en epoch."""
    year = year or time.gmtime().tm_year
    return time.mktime((year, 1, 8, 0, 0, 0, 0, 0, 0))
