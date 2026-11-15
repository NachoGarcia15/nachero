"""Datos estaticos del cliente desde CommunityDragon (cuando el cliente esta cerrado)."""

import contextlib
import json
import re
import time
import urllib.request

from draftbot.jsonio import read_json, write_json


class CDragon:
    """Datos estaticos del cliente desde CommunityDragon, para cuando el cliente esta cerrado.
    Imita lcu.get/raw solo para rutas /lol-game-data/assets/..."""

    BASE = "https://raw.communitydragon.org/latest/plugins/rcp-be-lol-game-data/global/default/"
    PREFIX = "/lol-game-data/assets/"

    def raw(self, method, path, body=None, timeout=20):
        if method != "GET" or not path.startswith(self.PREFIX):
            return None
        url = self.BASE + path[len(self.PREFIX) :].lower()
        req = urllib.request.Request(url, headers={"User-Agent": "draftbot/2.0"})
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return resp.read()
        except Exception:
            return None

    def req(self, method, path, body=None, timeout=20):
        b = self.raw(method, path, body, timeout)
        return json.loads(b) if b else None

    def get(self, path, timeout=20):
        return self.req("GET", path, timeout=timeout)


# ---------------------------------------------------------------- parche actual sin cliente
VERSION_URLS = (
    "https://ddragon.leagueoflegends.com/api/versions.json",  # ["16.22.1", "16.21.1", ...]
    "https://raw.communitydragon.org/latest/content-metadata.json",  # {"version": "16.22.83..."}
)
PATCH_TTL = 6 * 3600


def short_patch(version) -> str | None:
    """'16.22.1' o '16.22.8348910+branch…' -> '16.22' (el formato de Lolalytics), o None."""
    m = re.match(r"(\d+)\.(\d+)", str(version or ""))
    return f"{m[1]}.{m[2]}" if m else None


def parse_versions(data) -> str | None:
    """Parche de la respuesta de Data Dragon (lista, la primera es la actual) o de CommunityDragon."""
    if isinstance(data, list) and data:
        return short_patch(data[0])
    if isinstance(data, dict):
        return short_patch(data.get("version"))
    return None


def _fetch_json(url):
    req = urllib.request.Request(url, headers={"User-Agent": "draftbot/2.0"})
    with urllib.request.urlopen(req, timeout=15) as resp:
        return json.loads(resp.read())


def latest_patch(cache_path, fetch=_fetch_json, now=time.time) -> str | None:
    """Parche actual del juego sin el cliente: Data Dragon y, si falla, CommunityDragon.

    Se guarda en `cache_path` unas horas; sin red se usa el último guardado aunque sea viejo.
    Devuelve None si nunca se ha podido saber."""
    try:
        cached = read_json(cache_path, {})
    except Exception:
        cached = {}
    if not isinstance(cached, dict):
        cached = {}
    if cached.get("patch") and now() - cached.get("t", 0) < PATCH_TTL:
        return cached["patch"]
    for url in VERSION_URLS:
        try:
            patch = parse_versions(fetch(url))
        except Exception:
            patch = None
        if patch:
            with contextlib.suppress(OSError):
                write_json(cache_path, {"patch": patch, "t": now()})
            return patch
    return cached.get("patch")
