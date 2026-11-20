"""Aviso de nueva versión.

Nachero lee un `latest.json` público (ajuste `update_url`; vacío = sin aviso) con este formato:

    {"version": "0.17.0", "url": "https://…/Nachero.exe", "notes": "Qué cambia, en una línea"}

Mientras el repositorio sea privado, la API de GitHub no deja leer sus Releases sin token: hace
falta publicar ese archivo en un sitio público (issue #26). No se envía nada del usuario: es una
petición GET sin datos, como abrir una página.
"""

import json
import re
import urllib.request
from collections.abc import Callable

_VERSION = re.compile(r"v?(\d+)\.(\d+)\.(\d+)")


def parse_version(text) -> tuple[int, int, int] | None:
    m = _VERSION.fullmatch(text.strip()) if isinstance(text, str) else None
    return (int(m.group(1)), int(m.group(2)), int(m.group(3))) if m else None


def newer(latest: str, current: str) -> bool:
    a, b = parse_version(latest), parse_version(current)
    return bool(a and b and a > b)


def read_latest(data, current: str) -> dict | None:
    """La versión nueva de `data` (el latest.json) si es mayor que `current`, o None."""
    if not isinstance(data, dict):
        return None
    version, url = data.get("version"), data.get("url")
    if not isinstance(version, str) or not newer(version, current):
        return None
    if not isinstance(url, str) or not url.startswith("https://") or len(url) > 500:
        return None
    notes = data.get("notes")
    notes = notes.strip()[:300] if isinstance(notes, str) else ""
    return {"version": version.lstrip("v"), "url": url, "notes": notes}


def _fetch(url: str, timeout: float) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "Nachero"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read(64_000)


def check(url: str, current: str, fetch: Callable[[str, float], bytes] = _fetch, timeout: float = 8) -> dict | None:
    """Comprueba `url`. None si no hay nada nuevo, no está configurado o falla (sin avisar)."""
    if not url or not url.startswith("https://"):
        return None
    try:
        return read_latest(json.loads(fetch(url, timeout)), current)
    except (OSError, ValueError):
        return None
