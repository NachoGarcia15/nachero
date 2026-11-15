"""Dobles de prueba: campeones y estadisticas inventados, sin cliente ni red."""

import pytest

from nachero.domain.common import ROLES, norm

# id: (nombre, tipo de dano, dano, aguante, control, movilidad, utilidad, roles del cliente)
CHAMPS = {
    1: ("Tanky", "AP", 1, 3, 3, 1, 2, ["tank"]),
    2: ("Mage", "AP", 3, 1, 2, 1, 1, ["mage"]),
    3: ("Assassin", "AD", 3, 1, 1, 3, 1, ["assassin"]),
    4: ("Marksman", "AD", 3, 1, 1, 1, 1, ["marksman"]),
    5: ("Bruiser", "AD", 2, 3, 2, 2, 1, ["fighter"]),
    6: ("Enchanter", "AP", 1, 1, 2, 1, 3, ["support"]),
    7: ("Diver", "AD", 3, 2, 2, 3, 1, ["fighter"]),
    8: ("Poker", "AP", 3, 1, 1, 1, 1, ["mage"]),
    10: ("Shooter", "AD", 3, 1, 1, 2, 1, ["marksman"]),
    11: ("Warden", "AP", 1, 2, 2, 1, 3, ["support"]),
}


class FakeChamps:
    def __init__(self, data=CHAMPS):
        self.data = data
        self.by_id = {cid: {"id": cid, "name": v[0]} for cid, v in data.items()}
        self.by_name = {v[0].lower(): cid for cid, v in data.items()}

    def id(self, name):
        return self.by_name.get(name.lower())

    def name(self, cid):
        return self.data[cid][0] if cid in self.data else str(cid)

    def brief(self, cid):
        return {"id": cid, "name": self.name(cid)} if cid else None

    def slug(self, cid):
        return norm(self.name(cid))

    def info(self, cid):
        n, dmg, damage, dur, cc, mob, util, roles = self.data[cid]
        return {
            "dmg": dmg,
            "damage": damage,
            "durability": dur,
            "cc": cc,
            "mobility": mob,
            "utility": util,
            "roles": roles,
            "img": {},
        }


class FakeLola:
    """tiers: {rol: {cid: (wr, games, pr, pct)}}; matchups: {(cid, rol): {rol_rival: {cid_rival: d2}}}."""

    def __init__(self, tiers=None, matchups=None, avg=50.0):
        self.avg = avg
        self.tiers = tiers or {}
        self.mu = matchups or {}
        self.requested = []

    def tier(self, role):
        champs = {
            str(c): {"wr": wr, "games": g, "pr": pr, "br": 0, "tier": 5, "rank": 1, "pct": pct}
            for c, (wr, g, pr, pct) in self.tiers.get(role, {}).items()
        }
        return {"avg": self.avg, "games": 1, "champs": champs}

    def matchups(self, cid, role):
        lanes = self.mu.get((cid, role))
        if lanes is None:
            return None
        return {
            r: {str(e): {"wr": 50 + d2, "d1": d2, "d2": d2, "pr": 5.0, "n": 1000} for e, d2 in rows.items()}
            for r, rows in lanes.items()
        }

    def counters(self, cid, role):
        m = self.matchups(cid, role)
        return None if m is None else m.get(role, {})

    def request(self, cid, role, slug=None):
        self.requested.append((cid, role))


@pytest.fixture
def champs():
    return FakeChamps()


@pytest.fixture
def home(tmp_path, monkeypatch):
    """Carpeta de datos de usuario aislada para cada prueba."""
    monkeypatch.setenv("NACHERO_HOME", str(tmp_path / "home"))
    return tmp_path / "home"


def all_roles(**kw):
    """Tier list sencilla: cada campeon solo en el rol indicado."""
    out = {r: {} for r in ROLES}
    for role, rows in kw.items():
        out[role] = rows
    return out
