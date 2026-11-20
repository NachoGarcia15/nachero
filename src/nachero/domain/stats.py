"""Fuentes de estadísticas intercambiables (issue #17).

El motor (`engine.py`, `roles.py`, `pro.py`) solo usa esta interfaz, así que cambiar Lolalytics por
datos propios (fase 2, ver docs/DATOS.md) no toca el motor. Implementaciones:

- `sources.lolalytics.Lolalytics`: la web de Lolalytics, con su caché en disco.
- `sources.local_stats.LocalStats`: un archivo de datos local (formato provisional en DATOS.md).
- `ChainStats` (aquí): varias fuentes en orden de preferencia, con respaldo.

Formatos (todo en puntos de winrate, como el resto de la app):
- `tier(role)`: {"avg": WR medio, "games": partidas, "champs": {"<cid>": {"wr", "games", "pr", "br",
  "tier", "rank", "pct"}}} o None.
- `matchups(cid, role)`: {rol_rival: {"<cid>": {"wr", "d1", "d2", "pr", "n"}}} o None (aún no está).
- `runes(cid, role)`: {"pick": página, "win": página} (puede estar vacío) o None (aún no está).
"""

from typing import Protocol, runtime_checkable

from nachero.domain.common import ROLES


@runtime_checkable
class StatsProvider(Protocol):
    name: str  # para el panel: de dónde salen las estadísticas
    patch: str | None
    pending: set  # matchups y runas pedidos y aún sin llegar

    def refresh_tiers(self, patch, force=False, progress=None) -> int: ...
    def roles_ready(self, patch) -> int: ...
    def tier(self, role) -> dict | None: ...
    def matchups(self, cid, role, fetch=True) -> dict | None: ...
    def counters(self, cid, role) -> dict | None: ...
    def runes(self, cid, role) -> dict | None: ...
    def request(self, cid, role, slug=None) -> None: ...
    def updated_at(self) -> float | None: ...
    def stats(self) -> dict: ...


class ChainStats:
    """Varias fuentes en orden: la principal (con su caché) y, si no tiene un dato, las de respaldo.

    Solo la principal descarga lo que falta: las de respaldo se consultan sin pedir nada."""

    def __init__(self, providers):
        if not providers:
            raise ValueError("hace falta al menos una fuente")
        self.providers = list(providers)
        self.primary = self.providers[0]
        self.name = " → ".join(p.name for p in self.providers)

    @property
    def patch(self):
        return self.primary.patch

    @property
    def pending(self) -> set:
        out: set = set()
        for p in self.providers:
            out |= set(p.pending)
        return out

    def refresh_tiers(self, patch, force=False, progress=None) -> int:
        ready = 0
        for i, p in enumerate(self.providers):
            ready = max(ready, p.refresh_tiers(patch, force=force, progress=progress if i == 0 else None))
        return ready

    def roles_ready(self, patch) -> int:
        return max(p.roles_ready(patch) for p in self.providers)

    def _first(self, fn):
        for p in self.providers:
            v = fn(p)
            if v:
                return v
        return None

    def tier(self, role):
        return self._first(lambda p: p.tier(role))

    def matchups(self, cid, role, fetch=True):
        m = self.primary.matchups(cid, role, fetch=fetch)
        if m is not None:
            return m
        for p in self.providers[1:]:
            m = p.matchups(cid, role, fetch=False)
            if m is not None:
                return m
        return None

    def counters(self, cid, role):
        m = self.matchups(cid, role)
        return None if m is None else m.get(role, {})

    def runes(self, cid, role):
        r = self.primary.runes(cid, role)
        if r:
            return r
        for p in self.providers[1:]:
            alt = p.runes(cid, role)
            if alt:
                return alt
        return r  # {} (sin runas) o None (aún no está) de la principal

    def request(self, cid, role, slug=None) -> None:
        self.primary.request(cid, role, slug)

    def updated_at(self):
        return self._first(lambda p: p.updated_at())

    def source(self) -> str:
        """Qué fuente da las tier lists ahora (la que se ve en el panel)."""
        used = set()
        for role in ROLES:
            p = next((p for p in self.providers if p.tier(role)), None)
            if p is not None:
                used.add(id(p))
        names = [p.name for p in self.providers if id(p) in used]  # en el orden de la cadena
        return " + ".join(dict.fromkeys(names)) or self.primary.name

    def stats(self) -> dict:
        per = [p.stats() for p in self.providers]
        return {
            "games": max((s.get("games", 0) for s in per), default=0),
            "builds": sum(s.get("builds", 0) for s in per),
            "source": self.source(),
        }


def source_of(provider) -> str:
    """Nombre de la fuente que da los datos ahora (para el panel)."""
    return provider.source() if hasattr(provider, "source") else getattr(provider, "name", "La fuente de estadísticas")
