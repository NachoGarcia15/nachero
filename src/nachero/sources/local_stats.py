"""Fuente de estadísticas en un archivo local (`domain.stats.StatsProvider`).

Sirve para los datos propios de la fase 2 (recolector con la API de Riot, ver docs/DATOS.md) y
para probar la app sin red. Formato provisional (versión 1; el definitivo llega con #18):

    {
      "format": "nachero-stats", "version": 1,
      "patch": "16.23", "region": "euw", "tier": "master_plus", "generated": 1763500000,
      "roles": {"jungle": {"avg": 50.4, "games": 12345,
                           "champs": {"163": {"wr": 53.1, "games": 900, "pr": 4.2, "br": 1.0,
                                              "tier": 3, "rank": 12, "pct": 51.0}}}},
      "matchups": {"163:jungle": {"jungle": {"64": {"wr": 51.0, "d1": 1.2, "d2": 0.8, "pr": 9.0, "n": 300}}}},
      "runes": {"163:jungle": {"pick": {"pri": [...4], "sec": [...2], "mod": [...3]}}}
    }

No descarga nada: lo que no está en el archivo, no está.
"""

import os

from nachero.domain.common import ROLES
from nachero.jsonio import read_json

FORMAT, VERSION = "nachero-stats", 1


def validate(data) -> str | None:
    """Por qué el archivo no vale, o None si vale."""
    if not isinstance(data, dict):
        return "no es un objeto JSON"
    if data.get("format") != FORMAT:
        return f"no es un archivo {FORMAT}"
    if data.get("version") != VERSION:
        return f"versión {data.get('version')!r} no soportada (se espera {VERSION})"
    roles = data.get("roles")
    if not isinstance(roles, dict) or not roles:
        return "sin tier lists por rol"
    for r, t in roles.items():
        if r not in ROLES or not isinstance(t, dict) or not isinstance(t.get("champs"), dict):
            return f"tier list de {r!r} no válida"
    return None


class LocalStats:
    name = "Archivo local"

    def __init__(self, path, log=None):
        self.path, self.log = str(path), log or (lambda *a, **k: None)
        self.data: dict = {}
        self.mtime = None
        self.pending: set = set()
        self.problem: str | None = None
        self.load()

    def load(self) -> bool:
        """(Re)carga el archivo si ha cambiado. True si hay datos."""
        try:
            mtime = os.path.getmtime(self.path)
        except OSError:
            self.data, self.mtime, self.problem = {}, None, "no existe"
            return False
        if mtime == self.mtime:
            return bool(self.data)
        self.mtime = mtime
        try:
            data = read_json(self.path, None)
        except (OSError, ValueError):
            data = None
        self.problem = validate(data)
        if self.problem:
            self.data = {}
            self.log(f"Estadísticas locales: {self.path} {self.problem}", "warn")
            return False
        self.data = data
        return True

    @property
    def patch(self):
        return self.data.get("patch")

    def refresh_tiers(self, patch, force=False, progress=None) -> int:
        self.load()
        return self.roles_ready(patch)

    def roles_ready(self, patch) -> int:
        if not self.data or (patch and self.data.get("patch") != patch):
            return 0
        return sum(1 for r in ROLES if self.tier(r))

    def tier(self, role):
        t = (self.data.get("roles") or {}).get(role)
        if not t:
            return None
        return {"avg": t.get("avg", 50.0), "games": t.get("games", 0), "champs": t["champs"], "patch": self.patch}

    def matchups(self, cid, role, fetch=True):
        return (self.data.get("matchups") or {}).get(f"{cid}:{role}")

    def counters(self, cid, role):
        m = self.matchups(cid, role)
        return None if m is None else m.get(role, {})

    def runes(self, cid, role):
        return (self.data.get("runes") or {}).get(f"{cid}:{role}")

    def request(self, cid, role, slug=None) -> None:
        pass  # todo está en el archivo

    def updated_at(self):
        g = self.data.get("generated")
        return float(g) if isinstance(g, (int, float)) else None

    def stats(self):
        roles = self.data.get("roles") or {}
        return {"games": sum(t.get("games", 0) for t in roles.values()), "builds": len(self.data.get("matchups") or {})}
