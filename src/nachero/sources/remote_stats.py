"""Datos propios publicados (issue #20): la app descarga los archivos del esquema 1 de un sitio
estático (GitHub Pages, Releases, R2…) y los lee como `LocalStats` desde su caché.

En el sitio hay un `index.json` (lo escribe `python -m nachero_collector publicar`):

    {"schema": 1, "generated": "2026-11-19T08:00:00Z",
     "files": [{"patch": "16.23", "region": "euw1", "league": "master_plus",
                "path": "16.23/euw1/master_plus.json.gz", "games": 18234,
                "generated": "…", "sha256": "…"}]}

Se comprueba al arrancar y cada hora con `ETag` / `If-None-Match`: si no ha cambiado, el servidor
responde 304 y no se descarga nada. Solo se piden el archivo del parche actual y el del anterior
(para principio de parche). Nada del usuario sale de la app: son peticiones GET sin datos.
"""

import hashlib
import json
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from pathlib import Path

from nachero.sources.local_stats import LocalStats, _patch_key

CHECK_EVERY = 3600


def _http(url: str, headers: dict, timeout: float = 20) -> tuple[int, dict, bytes]:
    req = urllib.request.Request(url, headers={"User-Agent": "Nachero", **headers})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, {k.lower(): v for k, v in r.headers.items()}, r.read()
    except urllib.error.HTTPError as e:
        return e.code, {k.lower(): v for k, v in (e.headers or {}).items()}, b""


def pick_files(index: dict, patch: str, region: str, league: str) -> list[dict]:
    """Del manifiesto, el archivo de este parche y el del anterior más reciente (misma región y liga)."""
    files = [
        f
        for f in (index.get("files") or [])
        if isinstance(f, dict) and f.get("region") == region and f.get("league") == league and f.get("path")
    ]
    cur = [f for f in files if f.get("patch") == patch]
    older = sorted(
        (f for f in files if _patch_key(str(f.get("patch"))) and _patch_key(str(f["patch"])) < _patch_key(patch)),
        key=lambda f: _patch_key(f["patch"]),
    )
    return cur[:1] + older[-1:]


class RemoteStats(LocalStats):
    name = "Datos propios"

    def __init__(
        self,
        base_url: str,
        cache_root,
        log=None,
        region="euw1",
        league="master_plus",
        fetch: Callable[[str, dict], tuple[int, dict, bytes]] = _http,
        clock=time.time,
    ) -> None:
        self.base = base_url.rstrip("/")
        self.root = Path(cache_root)
        self.fetch, self.clock = fetch, clock
        self.last_sync: float | None = None  # aún no se ha comprobado
        self.sync_error: str | None = None
        super().__init__(self.root, log, region, league)

    # -- etags guardados junto a la caché
    def _etags(self) -> dict:
        try:
            d = json.loads((self.root / "etags.json").read_text(encoding="utf-8"))
            return d if isinstance(d, dict) else {}
        except (OSError, ValueError):
            return {}

    def _save_etags(self, etags: dict) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        (self.root / "etags.json").write_text(json.dumps(etags), encoding="utf-8")

    def _get(self, rel: str, etags: dict) -> tuple[int, bytes]:
        headers = {"If-None-Match": etags[rel]} if rel in etags and (self.root / rel).is_file() else {}
        status, h, body = self.fetch(f"{self.base}/{rel}", headers)
        if status == 200 and h.get("etag"):
            etags[rel] = h["etag"]
        return status, body

    def sync(self, patch: str) -> int:
        """Descarga lo que haya cambiado para `patch`. Devuelve cuántos archivos ha bajado."""
        self.last_sync = self.clock()
        if not self.base.startswith("https://") and not self.base.startswith("http://127.0.0.1"):
            self.sync_error = "sin dirección de los datos propios"
            return 0
        etags = self._etags()
        try:
            status, body = self._get("index.json", etags)
            if status == 304:
                index = json.loads((self.root / "index.json").read_text(encoding="utf-8"))
            elif status == 200:
                index = json.loads(body.decode("utf-8"))
                self.root.mkdir(parents=True, exist_ok=True)
                (self.root / "index.json").write_bytes(body)
            else:
                raise OSError(f"HTTP {status} en index.json")
            got = 0
            for f in pick_files(index, patch, self.region, self.league):
                rel = f["path"]
                if ".." in rel or rel.startswith("/"):
                    continue
                status, body = self._get(rel, etags)
                if status == 304:
                    continue
                if status != 200:
                    raise OSError(f"HTTP {status} en {rel}")
                if f.get("sha256") and hashlib.sha256(body).hexdigest() != f["sha256"]:
                    raise ValueError(f"{rel} no coincide con su sha256")
                dest = self.root / rel
                dest.parent.mkdir(parents=True, exist_ok=True)
                tmp = dest.with_suffix(dest.suffix + ".tmp")
                tmp.write_bytes(body)
                tmp.replace(dest)
                got += 1
            self._save_etags(etags)
            self.sync_error = None
            if got:
                self.log(f"Datos propios: {got} archivo(s) nuevo(s) del parche {patch}", "ok")
            return got
        except (OSError, ValueError) as e:
            self.sync_error = f"{e.__class__.__name__}: {e}"
            self.health.fail("descarga", e)
            self.log(f"Datos propios: no he podido actualizarlos ({self.sync_error}); uso los guardados", "warn")
            return 0

    def refresh_tiers(self, patch, force=False, progress=None) -> int:
        if force or self.last_sync is None or self.clock() - self.last_sync >= CHECK_EVERY:
            self.sync(patch)
        return super().refresh_tiers(patch)
