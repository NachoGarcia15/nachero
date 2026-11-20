"""Datos de campeones del cliente (o de CommunityDragon)."""

import queue
import re
import threading


class Champs:
    def __init__(self, lcu):
        summ = lcu.get("/lol-game-data/assets/v1/champion-summary.json") or []
        self.by_id = {c["id"]: c for c in summ if 0 < c["id"] < 10000}
        self.by_name = {c["name"].lower(): c["id"] for c in self.by_id.values()}
        self.lcu, self.detail, self.lock = lcu, {}, threading.Lock()
        # con `background` (tras `preload`), info() no espera al cliente: devuelve una ficha neutra
        # y pide la de verdad en segundo plano. El bucle de la champ select nunca espera a la red.
        self.background = False
        self.q = queue.Queue()
        self.queued = set()
        self.loader = None

    def id(self, name):
        return self.by_name.get(name.lower())

    def name(self, cid):
        return self.by_id.get(cid, {}).get("name", str(cid))

    def brief(self, cid):
        return {"id": cid, "name": self.name(cid)} if cid else None

    def slug(self, cid):
        return re.sub(r"[^a-z0-9]", "", self.name(cid).lower())

    def preload(self):
        """Pide en segundo plano la ficha de todos los campeones; desde ahora info() no espera."""
        self.background = True
        for cid in sorted(self.by_id):
            self._queue(cid)

    def _queue(self, cid):
        with self.lock:
            if cid in self.detail or cid in self.queued:
                return
            self.queued.add(cid)
            if self.loader is None:
                self.loader = threading.Thread(target=self._loader, daemon=True)
                self.loader.start()
        self.q.put(cid)

    def _loader(self):
        while True:
            cid = self.q.get()
            try:
                self._load(cid)
            except Exception:
                pass  # se queda la ficha neutra; se vuelve a pedir la próxima vez
            finally:
                with self.lock:
                    self.queued.discard(cid)

    def neutral(self, cid):
        """Ficha provisional (sin pedir nada al cliente) con lo que trae el resumen de campeones."""
        c = self.by_id.get(cid, {})
        return {
            "dmg": "MIX",
            "damage": 2,
            "durability": 2,
            "cc": 1,
            "mobility": 1,
            "utility": 1,
            "difficulty": 2,
            "roles": c.get("roles", []),
            "img": {"tile": None, "splash": None, "icon": c.get("squarePortraitPath")},
        }

    def info(self, cid, wait=None):
        """Ficha del campeón. Con `wait=False` (o en segundo plano tras `preload`), si aún no está
        devuelve la neutra y la pide sin esperar."""
        with self.lock:
            if cid in self.detail:
                return self.detail[cid]
        if not (self.background if wait is None else not wait):
            return self._load(cid)
        self._queue(cid)
        return self.neutral(cid)

    def _load(self, cid):
        d = self.lcu.get(f"/lol-game-data/assets/v1/champions/{cid}.json") or {}
        t, p = d.get("tacticalInfo", {}), d.get("playstyleInfo", {})
        skin = (d.get("skins") or [{}])[0]
        info = {
            "dmg": {"kMagic": "AP", "kPhysical": "AD"}.get(t.get("damageType"), "MIX"),
            "damage": p.get("damage", 2),
            "durability": p.get("durability", 2),
            "cc": p.get("crowdControl", 1),
            "mobility": p.get("mobility", 1),
            "utility": p.get("utility", 1),
            "roles": d.get("roles", []),
            "img": {
                "tile": skin.get("tilePath"),
                "splash": skin.get("uncenteredSplashPath") or skin.get("splashPath"),
                "icon": d.get("squarePortraitPath"),
            },
        }
        with self.lock:
            self.detail[cid] = info
        return info
