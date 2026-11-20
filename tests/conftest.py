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

# Campeones reales con sus ids del cliente, para los repartos por rol de Lolalytics
REAL_CHAMPS = {
    55: ("Katarina", "AP", 3, 1, 1, 3, 1, ["assassin"]),
    126: ("Jayce", "AD", 3, 2, 1, 2, 1, ["fighter"]),
    69: ("Cassiopeia", "AP", 3, 1, 2, 1, 1, ["mage"]),
    17: ("Teemo", "AP", 2, 1, 1, 2, 1, ["marksman"]),
    163: ("Taliyah", "AP", 3, 1, 2, 2, 1, ["mage"]),
    64: ("Lee Sin", "AD", 2, 2, 2, 3, 1, ["fighter"]),
    516: ("Ornn", "AP", 1, 3, 3, 1, 2, ["tank"]),
    103: ("Ahri", "AP", 3, 1, 2, 3, 1, ["mage"]),
    222: ("Jinx", "AD", 3, 1, 1, 1, 1, ["marksman"]),
    412: ("Thresh", "AP", 1, 2, 3, 1, 3, ["support"]),
}

# Reparto real por rol en Master+ (caché de Lolalytics, parche 16.22): {cid: {rol: (wr, partidas, pr, pct)}}
REAL_AVG = 52.37
REAL_SPLITS = {
    55: {"top": (50.54, 839, 0.18, 2.45), "jungle": (48.0, 50, 0.01, 0.15), "middle": (54.42, 28453, 6.12, 83.25),
         "bottom": (56.01, 4572, 0.98, 13.38), "utility": (50.76, 264, 0.06, 0.77)},
    126: {"top": (50.07, 36127, 7.77, 63.12), "jungle": (47.7, 15466, 3.33, 27.02), "middle": (50.82, 5238, 1.13, 9.15),
          "bottom": (44.18, 292, 0.06, 0.51), "utility": (42.61, 115, 0.02, 0.2)},
    69: {"top": (52.85, 3118, 0.67, 20.47), "jungle": (66.67, 3, 0, 0.02), "middle": (50.97, 9389, 2.02, 61.63),
         "bottom": (53.21, 2599, 0.56, 17.06), "utility": (47.2, 125, 0.03, 0.82)},
    17: {"top": (53.25, 10405, 2.24, 79.59), "jungle": (48.13, 989, 0.21, 7.57), "middle": (44.44, 297, 0.06, 2.27),
         "bottom": (54.93, 284, 0.06, 2.17), "utility": (50.55, 1098, 0.24, 8.4)},
    163: {"top": (53.58, 517, 0.11, 1.21), "jungle": (53.36, 21896, 4.71, 51.26), "middle": (53.77, 16791, 3.61, 39.31),
          "bottom": (53.45, 2374, 0.51, 5.56), "utility": (52.54, 1140, 0.25, 2.67)},
    64: {"top": (46.21, 818, 0.18, 1.15), "jungle": (51.03, 69224, 14.89, 97.04), "middle": (47.64, 571, 0.12, 0.8),
         "bottom": (52.7, 74, 0.02, 0.1), "utility": (44.51, 647, 0.14, 0.91)},
    516: {"top": (53.35, 19893, 4.28, 96.74), "jungle": (50.7, 71, 0.02, 0.35), "middle": (51.33, 376, 0.08, 1.83),
          "bottom": (28.57, 14, 0, 0.07), "utility": (50.48, 210, 0.05, 1.02)},
    103: {"top": (55.02, 2141, 0.46, 4.13), "jungle": (25.0, 12, 0, 0.02), "middle": (53.52, 48818, 10.5, 94.15),
          "bottom": (51.38, 471, 0.1, 0.91), "utility": (45.21, 407, 0.09, 0.78)},
    222: {"top": (29.41, 17, 0, 0.04), "jungle": (27.27, 11, 0, 0.03), "middle": (41.18, 85, 0.02, 0.21),
          "bottom": (53.12, 40090, 8.63, 99.67), "utility": (15.0, 20, 0, 0.05)},
    412: {"top": (46.67, 45, 0.01, 0.07), "jungle": (20.0, 5, 0, 0.01), "middle": (31.03, 29, 0.01, 0.05),
          "bottom": (16.67, 12, 0, 0.02), "utility": (54.22, 62133, 13.37, 99.85)},
}  # fmt: skip


def real_tiers(*ids):
    """Tier lists por rol con los repartos reales de los campeones pedidos (todos si no se indica)."""
    ids = ids or tuple(REAL_SPLITS)
    return {r: {cid: REAL_SPLITS[cid][r] for cid in ids} for r in ROLES}


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

    def matchups(self, cid, role, fetch=True):
        lanes = self.mu.get((cid, role))
        if lanes is None:
            if fetch:
                self.requested.append((cid, role))
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
def real_champs():
    return FakeChamps(REAL_CHAMPS)


@pytest.fixture(autouse=True)
def sin_perfil(monkeypatch):
    """Cada prueba empieza sin perfil de cuenta en uso."""
    from nachero import paths

    monkeypatch.setitem(paths._PROFILE, "id", None)


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
