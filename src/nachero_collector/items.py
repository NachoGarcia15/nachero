"""Qué objetos son «completos» y cuáles botas, del catálogo público de Data Dragon (#90).

Las partidas de match-v5 solo dicen qué llevaba cada jugador al final (`item0`–`item5`): para
contar builds hay que separar los objetos completos (los de la build) de componentes, consumibles,
guardianes y objetos iniciales. Data Dragon es público (sin clave): la clave de la API de Riot
nunca va en estas peticiones. El catálogo se guarda en caché por parche.
"""

import json
import urllib.request
from pathlib import Path

VERSIONS = "https://ddragon.leagueoflegends.com/api/versions.json"
ITEMS = "https://ddragon.leagueoflegends.com/cdn/{version}/data/en_US/item.json"
UA = "nachero-collector (estadísticas agregadas)"
MIN_GOLD = 2000  # un objeto completo cuesta al menos esto (Doran, Sello oscuro… se quedan fuera)
MIN_BOOTS_GOLD = 600  # botas acabadas (las básicas cuestan 300)
SUMMONERS_RIFT = "11"


def classify(data: dict) -> dict[str, list[int]]:
    """{"legendary": [ids], "boots": [ids]} del `item.json` de Data Dragon."""
    legendary, boots = [], []
    for key, it in ((data or {}).get("data") or {}).items():
        if not key.isdigit() or not isinstance(it, dict):
            continue
        gold = it.get("gold") or {}
        tags = set(it.get("tags") or [])
        if not gold.get("purchasable", True) or not (it.get("maps") or {}).get(SUMMONERS_RIFT, True):
            continue
        if it.get("requiredChampion") or it.get("requiredAlly") or tags & {"Consumable", "Trinket"}:
            continue
        total = gold.get("total") or 0
        if "Boots" in tags:
            if total >= MIN_BOOTS_GOLD:
                boots.append(int(key))
        elif not it.get("into") and total >= MIN_GOLD:
            legendary.append(int(key))
    return {"legendary": sorted(legendary), "boots": sorted(boots)}


def _get(url: str, timeout: float = 20) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def version_for(patch: str, versions: list) -> str | None:
    """La versión de Data Dragon de un parche («16.23» → «16.23.1»), la más reciente."""
    return next((v for v in versions if isinstance(v, str) and v.startswith(f"{patch}.")), None)


def catalog(patch: str, cache_dir, fetch=_get) -> dict[str, list[int]] | None:
    """Objetos completos y botas del parche (caché en `cache_dir`), o None si no se puede leer:
    entonces el recolector no cuenta objetos en esa pasada (el resto sigue igual)."""
    path = Path(cache_dir) / f"items-{patch}.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, dict) and data.get("legendary"):
            return data
    except (OSError, ValueError):
        pass
    try:
        version = version_for(patch, json.loads(fetch(VERSIONS)))
        if not version:
            return None
        data = classify(json.loads(fetch(ITEMS.format(version=version))))
    except (OSError, ValueError):
        return None
    if not data["legendary"]:
        return None
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data), encoding="utf-8")
    return data
