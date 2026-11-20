"""Fuente de estadísticas en un archivo local (`domain.stats.StatsProvider`).

Sirve para los datos propios de la fase 2 (recolector con la API de Riot, ver docs/DATOS.md) y
para probar la app sin red. Lee el **esquema 1** publicado (docs/FORMATO_DATOS.md, conteos que
calcula `sources/dataset.py`) y también este formato ya calculado, el que usa el motor:

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

from datetime import datetime
from pathlib import Path

from nachero.domain.common import ROLES
from nachero.sources import dataset
from nachero.sources.health import FormatChanged, Health

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


def _patch_key(p: str) -> tuple:
    try:
        return tuple(int(x) for x in p.split("."))
    except ValueError:
        return ()


def _epoch(v) -> float | None:
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        return float(v)
    if isinstance(v, str):
        try:
            return datetime.fromisoformat(v.replace("Z", "+00:00")).timestamp()
        except ValueError:
            return None
    return None


class LocalStats:
    """Estadísticas de un archivo local. `path` puede ser:

    - un archivo con el **esquema 1** (docs/FORMATO_DATOS.md, .json o .json.gz) o con el formato
      ya calculado de arriba;
    - una **carpeta** con la estructura publicada `<parche>/<región>/<liga>.json.gz`: se usa el del
      parche actual y, para principio de parche, se mezcla con el del parche anterior."""

    name = "Archivo local"

    def __init__(self, path, log=None, region="euw1", league="master_plus") -> None:
        self.path, self.log = str(path), log or (lambda *a, **k: None)
        self.region, self.league = region, league
        self.data: dict = {}
        self.mtime: tuple | None = None
        self.pending: set = set()
        self.problem: str | None = None
        self.want_patch: str | None = None
        self.health = Health(self.name, self.log)
        self.load()

    # -- archivos
    def _file_for(self, patch: str) -> Path | None:
        for ext in (".json.gz", ".json"):
            f = Path(self.path) / patch / self.region / f"{self.league}{ext}"
            if f.is_file():
                return f
        return None

    def _previous(self, patch: str) -> Path | None:
        root = Path(self.path)
        older = sorted(
            (
                d.name
                for d in root.iterdir()
                if d.is_dir() and _patch_key(d.name) and _patch_key(d.name) < _patch_key(patch)
            ),
            key=_patch_key,
        )
        for name in reversed(older):
            f = self._file_for(name)
            if f:
                return f
        return None

    def _target(self) -> tuple[Path | None, Path | None]:
        """(archivo de este parche, del anterior) según `path`."""
        root = Path(self.path)
        if not root.is_dir():
            return (root if root.is_file() else None), None
        patches = sorted((d.name for d in root.iterdir() if d.is_dir() and _patch_key(d.name)), key=_patch_key)
        patch = self.want_patch or (patches[-1] if patches else None)
        if not patch:
            return None, None
        return self._file_for(patch), self._previous(patch)

    def load(self) -> bool:
        """(Re)carga el archivo si ha cambiado. True si hay datos."""
        cur, prev = self._target()
        if cur is None:
            self.data, self.mtime, self.problem = {}, None, "no existe"
            return False
        try:
            mtime = (cur.stat().st_mtime, prev.stat().st_mtime if prev else None, str(cur))
        except OSError:
            self.data, self.mtime, self.problem = {}, None, "no existe"
            return False
        if mtime == self.mtime:
            return bool(self.data)
        self.mtime = mtime
        try:
            doc = dataset.load_file(cur)
        except (OSError, ValueError):
            doc = None
        if isinstance(doc, dict) and "schema" in doc:
            errors = dataset.validate(doc)
            self.problem = "; ".join(errors[:3]) if errors else None
            if not self.problem:
                prev_doc = None
                if prev:
                    try:
                        prev_doc = dataset.load_file(prev)
                    except (OSError, ValueError):
                        prev_doc = None
                    if prev_doc is not None and dataset.validate(prev_doc):
                        prev_doc = None
                doc = dataset.derive(doc, prev_doc)
        else:
            self.problem = validate(doc)
        if self.problem:
            self.data = {}
            self.health.fail("archivo", FormatChanged(self.problem))
            return False
        self.data = doc if isinstance(doc, dict) else {}
        self.health.ok("archivo")
        return True

    @property
    def patch(self):
        return self.data.get("patch")

    def refresh_tiers(self, patch, force=False, progress=None) -> int:
        self.want_patch = patch
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

    def synergies(self, cid, role):
        """Dúos con este campeón (esquema 1): {"<cid>:<rol>": {"wr", "n"}}, o None."""
        return (self.data.get("synergies") or {}).get(f"{cid}:{role}")

    def request(self, cid, role, slug=None) -> None:
        pass  # todo está en el archivo

    def updated_at(self):
        return _epoch(self.data.get("generated"))

    def stats(self):
        roles = self.data.get("roles") or {}
        return {"games": sum(t.get("games", 0) for t in roles.values()), "builds": len(self.data.get("matchups") or {})}
