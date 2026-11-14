"""Datos estaticos del cliente desde CommunityDragon (cuando el cliente esta cerrado)."""

import json
import urllib.request


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
