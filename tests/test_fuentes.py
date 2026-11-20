"""Fuentes de estadísticas intercambiables (issue #17): contrato común, archivo local y respaldo."""

import json
import os
import time

import pytest

from conftest import REAL_AVG, REAL_CHAMPS, REAL_SPLITS, FakeChamps
from nachero.app import worker
from nachero.config import CFG
from nachero.domain.common import ROLES
from nachero.domain.engine import Engine
from nachero.domain.player import Player
from nachero.domain.stats import ChainStats, StatsProvider, source_of
from nachero.sources.local_stats import FORMAT, VERSION, LocalStats, validate
from nachero.sources.lolalytics import Lolalytics

PATCH = "16.23"
PAGE = {"pri": [8112, 8139, 8140, 8105], "sec": [8347, 8304], "mod": [5008, 5008, 5007]}
TALIYAH, LEE = 163, 64


def roles_data():
    out = {}
    for r in ROLES:
        champs = {
            str(cid): {"wr": wr, "games": g, "pr": pr, "br": 1.0, "tier": 3, "rank": 1, "pct": pct}
            for cid, split in REAL_SPLITS.items()
            for role, (wr, g, pr, pct) in split.items()
            if role == r
        }
        out[r] = {"avg": REAL_AVG, "games": sum(c["games"] for c in champs.values()) // 10, "champs": champs}
    return out


MATCHUPS = {"jungle": {str(LEE): {"wr": 49.0, "d1": -1.0, "d2": -1.5, "pr": 14.0, "n": 900}}}


def stats_file(tmp_path, **extra):
    data = {
        "format": FORMAT,
        "version": VERSION,
        "patch": PATCH,
        "region": "euw",
        "tier": "master_plus",
        "generated": 1763500000,
        "roles": roles_data(),
        "matchups": {f"{TALIYAH}:jungle": MATCHUPS},
        "runes": {f"{TALIYAH}:jungle": {"pick": PAGE}},
        **extra,
    }
    f = tmp_path / "nachero-stats.json"
    f.write_text(json.dumps(data), encoding="utf-8")
    return f


def lolalytics(tmp_path, monkeypatch):
    lola = Lolalytics(str(tmp_path), lambda *a, **k: None)
    monkeypatch.setattr(lola, "_fetch", lambda url: (_ for _ in ()).throw(OSError("sin red en los tests")))
    now = time.time()
    lola.cache["tiers"] = {r: {"t": now, "patch": PATCH, **t} for r, t in roles_data().items()}
    lola.cache["builds"] = {f"{TALIYAH}:jungle": {"t": now, "patch": PATCH, "lanes": MATCHUPS, "runes": {"pick": PAGE}}}
    lola.patch = PATCH
    return lola


@pytest.fixture(params=["lolalytics", "local", "cadena"])
def provider(request, tmp_path, monkeypatch):
    if request.param == "lolalytics":
        return lolalytics(tmp_path, monkeypatch)
    local = LocalStats(stats_file(tmp_path))
    if request.param == "local":
        return local
    return ChainStats([LocalStats(tmp_path / "no-existe.json"), local])


# ------------------------------------------------------------------ contrato
def test_cumple_la_interfaz(provider):
    assert isinstance(provider, StatsProvider)
    assert isinstance(provider.name, str) and provider.name
    assert isinstance(source_of(provider), str)
    assert len(provider.pending) >= 0


def test_tier_list(provider):
    assert provider.refresh_tiers(PATCH) == 5 and provider.roles_ready(PATCH) == 5
    t = provider.tier("jungle")
    assert {"avg", "games", "champs"} <= t.keys()
    row = t["champs"][str(TALIYAH)]
    assert {"wr", "games", "pr", "br", "tier", "rank", "pct"} <= row.keys()
    assert all(isinstance(row[k], (int, float)) for k in ("wr", "games", "pr", "pct"))


def test_otro_parche_no_cuenta_como_listo(provider):
    assert provider.roles_ready("1.1") == 0


def test_matchups_y_counters(provider):
    m = provider.matchups(TALIYAH, "jungle", fetch=False)
    assert m["jungle"][str(LEE)] == {"wr": 49.0, "d1": -1.0, "d2": -1.5, "pr": 14.0, "n": 900}
    assert provider.counters(TALIYAH, "jungle") == m["jungle"]
    assert provider.matchups(999, "jungle", fetch=False) is None


def test_runas(provider):
    r = provider.runes(TALIYAH, "jungle")
    assert r["pick"] == PAGE
    assert provider.runes(999, "top") is None  # aún no está (o no está)


def test_fecha_y_resumen(provider):
    assert isinstance(provider.updated_at(), float)
    st = provider.stats()
    assert st["games"] > 0 and st["builds"] >= 1


def test_el_motor_funciona_con_cualquier_fuente(provider):
    champs = FakeChamps(REAL_CHAMPS)
    eng = Engine(champs, provider, Player([], []), {"pick_mode": "meta", "weights": {}})
    picks, ctx = eng.picks("jungle", set(), set(), [], [LEE])
    ids = [p["id"] for p in picks]
    assert TALIYAH in ids
    tali = next(p for p in picks if p["id"] == TALIYAH)
    assert tali["matchups_loaded"] and tali["parts"]["lane"] < 0  # su matchup contra Lee Sin


# ------------------------------------------------------------------ cadena de respaldo
class Partial:
    """Fuente principal con pocos datos: solo jungla, sin matchups ni runas."""

    name = "Principal"
    patch = PATCH

    def __init__(self):
        self.pending, self.requested = set(), []

    def refresh_tiers(self, patch, force=False, progress=None):
        return 1

    def roles_ready(self, patch):
        return 1

    def tier(self, role):
        return roles_data()["jungle"] if role == "jungle" else None

    def matchups(self, cid, role, fetch=True):
        return None

    def counters(self, cid, role):
        return None

    def runes(self, cid, role):
        return {}

    def request(self, cid, role, slug=None):
        self.requested.append((cid, role))

    def updated_at(self):
        return None

    def stats(self):
        return {"games": 1, "builds": 0}


def test_la_cadena_cubre_lo_que_le_falta_a_la_principal(tmp_path):
    primary = Partial()
    chain = ChainStats([primary, LocalStats(stats_file(tmp_path))])
    assert chain.name == "Principal → Archivo local"
    assert chain.tier("jungle") == primary.tier("jungle")  # manda la principal
    assert chain.tier("top")["champs"]  # el resto, de respaldo
    assert chain.matchups(TALIYAH, "jungle")["jungle"]  # de respaldo
    assert chain.runes(TALIYAH, "jungle") == {"pick": PAGE}
    assert chain.roles_ready(PATCH) == 5
    assert chain.source() == "Principal + Archivo local"
    assert chain.stats()["source"] == "Principal + Archivo local"
    chain.request(1, "top")
    assert primary.requested == [(1, "top")]  # solo la principal descarga


def test_cadena_vacia_no_vale():
    with pytest.raises(ValueError):
        ChainStats([])


# ------------------------------------------------------------------ archivo local
def test_archivo_que_no_existe(tmp_path):
    s = LocalStats(tmp_path / "nada.json")
    assert s.problem == "no existe" and s.tier("jungle") is None and s.roles_ready(PATCH) == 0


@pytest.mark.parametrize(
    ("data", "motivo"),
    [
        ([], "no es un objeto"),
        ({"format": "otro"}, "no es un archivo"),
        ({"format": FORMAT, "version": 2}, "versión 2"),
        ({"format": FORMAT, "version": VERSION, "roles": {}}, "sin tier lists"),
        ({"format": FORMAT, "version": VERSION, "roles": {"jungla": {"champs": {}}}}, "no válida"),
    ],
)
def test_archivos_no_validos(data, motivo):
    assert motivo in validate(data)


def test_archivo_roto_avisa_y_no_da_datos(tmp_path):
    f = tmp_path / "x.json"
    f.write_text("{roto", encoding="utf-8")
    avisos = []
    s = LocalStats(f, lambda msg, kind="info": avisos.append(msg))
    assert s.tier("jungle") is None and avisos


def test_recarga_si_cambia_el_archivo(tmp_path):
    f = stats_file(tmp_path)
    s = LocalStats(f)
    assert s.patch == PATCH
    stats_file(tmp_path, patch="16.24")
    os.utime(f, (time.time() + 5, time.time() + 5))
    assert s.refresh_tiers("16.24") == 5 and s.patch == "16.24"


# ------------------------------------------------------------------ elegir fuentes en los ajustes
@pytest.mark.parametrize(
    ("sources", "tipo", "nombre"),
    [
        (None, Lolalytics, "Lolalytics"),
        (["raro"], Lolalytics, "Lolalytics"),
        (["local"], LocalStats, "Archivo local"),
        (["lolalytics", "local"], ChainStats, "Lolalytics → Archivo local"),
        (["local", "local"], LocalStats, "Archivo local"),
    ],
)
def test_fuentes_segun_los_ajustes(home, monkeypatch, sources, tipo, nombre):
    monkeypatch.setitem(CFG, "stats_sources", sources)
    monkeypatch.setitem(CFG, "stats_file", "")
    p = worker.build_stats(FakeChamps(REAL_CHAMPS))
    assert type(p) is tipo and p.name == nombre


def test_archivo_local_por_defecto_en_la_carpeta_de_datos(home, monkeypatch):
    monkeypatch.setitem(CFG, "stats_file", "")
    assert worker.stats_file() == home / "stats" / "nachero-stats.json"


def test_el_panel_sabe_de_que_fuente_salen_los_datos(tmp_path):
    st = worker.data_status(LocalStats(stats_file(tmp_path)), PATCH)
    assert st["source"] == "Archivo local" and st["games"] > 0 and st["counters"] == 1
