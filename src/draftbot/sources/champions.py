"""Datos de campeones del cliente (o de CommunityDragon)."""

import re
import threading


class Champs:
    def __init__(self, lcu):
        summ = lcu.get("/lol-game-data/assets/v1/champion-summary.json") or []
        self.by_id = {c["id"]: c for c in summ if 0 < c["id"] < 10000}
        self.by_name = {c["name"].lower(): c["id"] for c in self.by_id.values()}
        self.lcu, self.detail, self.lock = lcu, {}, threading.Lock()

    def id(self, name):
        return self.by_name.get(name.lower())

    def name(self, cid):
        return self.by_id.get(cid, {}).get("name", str(cid))

    def brief(self, cid):
        return {"id": cid, "name": self.name(cid)} if cid else None

    def slug(self, cid):
        return re.sub(r"[^a-z0-9]", "", self.name(cid).lower())

    def info(self, cid):
        with self.lock:
            if cid in self.detail:
                return self.detail[cid]
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
