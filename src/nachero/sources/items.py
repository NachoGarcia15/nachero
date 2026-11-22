"""Objetos y hechizos de invocador del cliente (o de CommunityDragon) para la vista «En partida» (#88).

Se cargan la primera vez que hacen falta, en segundo plano: el bucle nunca espera al cliente."""

import threading


class Items:
    PATHS = {"item": "/lol-game-data/assets/v1/items.json", "spell": "/lol-game-data/assets/v1/summoner-spells.json"}

    def __init__(self, src):
        self.src, self.lock = src, threading.Lock()
        self.data: dict[str, dict[int, dict]] = {}
        self.loading: set[str] = set()

    def _table(self, kind, wait=False) -> dict[int, dict]:
        with self.lock:
            if kind in self.data:
                return self.data[kind]
            busy = kind in self.loading
            self.loading.add(kind)
        if wait:
            self._load(kind)
        elif not busy:
            threading.Thread(target=self._load, args=(kind,), daemon=True).start()
        with self.lock:
            return self.data.get(kind, {})

    def _load(self, kind) -> None:
        try:
            rows = self.src.get(self.PATHS[kind], timeout=20) or []
        except Exception:
            rows = []
        table = {r["id"]: r for r in rows if isinstance(r, dict) and isinstance(r.get("id"), int)}
        with self.lock:
            if table:
                self.data[kind] = table
            self.loading.discard(kind)

    def brief(self, iid, kind="item") -> dict:
        """{id, name}; sin el catálogo todavía, el nombre es el número (el panel pinta el icono)."""
        row = self._table(kind).get(iid) or {}
        return {"id": iid, "name": row.get("name") or str(iid)}

    def icon(self, kind, iid) -> str | None:
        """Ruta del icono en el cliente (espera al catálogo: lo pide el servidor del panel)."""
        row = self._table(kind, wait=True).get(iid) or {}
        return row.get("iconPath") or None
