"""ARAM: runas de ARAM del campeón que te toque, y nada más (issue #42)."""

import json

import pytest

from conftest import FakeLola
from nachero.app.draft import Draft
from nachero.app.runes import RuneImporter
from nachero.app.worker import champ_select_view
from nachero.config import CFG
from nachero.domain.queues import classify
from nachero.sources.lolalytics import ARAM, parse_runes
from test_queues import flow
from test_runes import ELECTROCUTE, FakeCatalog

HARVEST = {"pri": [8128, 8139, 8140, 8105], "sec": [8347, 8304], "mod": [5005, 5008, 5007]}


def aram_page(pick=ELECTROCUTE, win=HARVEST):
    """Página de build de ARAM de ejemplo: el mismo estado qwik que las de la Grieta, sin matchups."""
    objs = [
        {"runes": "1"}, {"set": "2"}, pick,
        {"runes": "4"}, {"set": "5"}, win,
        {"pick": "0", "win": "3"},
    ]  # fmt: skip
    return '<html><script type="qwik/json">' + json.dumps({"objs": objs}) + "</script></html>"


class AramLola(FakeLola):
    def __init__(self, runes):
        super().__init__()
        self.aram = runes  # {cid: sets}; falta el cid = aún descargando

    def runes(self, cid, role):
        assert role == ARAM
        return self.aram.get(cid)


class Engine:
    def __init__(self, lola):
        self.lola = lola


class Client:
    """Cliente con páginas de runas: las de Nachero se reemplazan, las tuyas no se tocan."""

    def __init__(self):
        self.pages = [{"id": 1, "name": "Mi página", "isEditable": True}]
        self.calls, self.next_id = [], 100

    def get(self, path, timeout=5):
        if path == "/lol-perks/v1/pages":
            return list(self.pages)
        if path == "/lol-perks/v1/inventory":
            return {"canAddCustomPage": True}
        return None

    def req(self, method, path, body=None, timeout=5):
        self.calls.append((method, path))
        if method == "DELETE":
            pid = int(path.rsplit("/", 1)[1])
            self.pages = [p for p in self.pages if p["id"] != pid]
        if method == "POST":
            self.next_id += 1
            page = {**body, "id": self.next_id, "isEditable": True}
            self.pages.append(page)
            return page
        return None

    def mutations(self):
        return [c for c in self.calls if c[0] in ("POST", "DELETE", "PATCH", "PUT")]


def session(cid):
    return {"localPlayerCellId": 2, "myTeam": [{"cellId": 2, "championId": cid}, {"cellId": 3, "championId": 4}],
            "theirTeam": [], "actions": [], "benchChampions": [{"championId": 5}]}  # fmt: skip


@pytest.fixture
def aram(champs, monkeypatch):
    for k, v in {"import_runes": True, "runes_source": "pick", "auto_spells": True, "auto_hover_pick": True,
                 "auto_lock_pick": True, "auto_ban": True, "open_coachless_on_lock": True}.items():  # fmt: skip
        monkeypatch.setitem(CFG, k, v)
    lcu = Client()
    lola = AramLola({3: {"pick": ELECTROCUTE, "win": HARVEST}, 7: {"pick": HARVEST}})
    d = Draft(lcu, champs, Engine(lola), RuneImporter(FakeCatalog()))
    return d, lcu, lola


def view(d, s, acting=True, q=None):
    return champ_select_view(d, s, acting, q or classify(flow(450, 12, "ARAM")))


# ------------------------------------------------------------------ lector
def test_lee_las_runas_de_la_pagina_de_aram():
    assert parse_runes(aram_page()) == {"pick": ELECTROCUTE, "win": HARVEST}


def test_pagina_de_aram_sin_runas():
    assert parse_runes('<script type="qwik/json">{"objs": [1, 2]}</script>') == {}


def test_aram_se_marca_en_la_cola():
    assert classify(flow(450, 12, "ARAM"))["aram"] is True
    assert classify(flow(-1, 0, "", custom=True, fmap={"id": 12, "gameMode": "ARAM"}))["aram"] is True
    assert "aram" not in classify(flow(1700, 30, "CHERRY"))
    assert "aram" not in classify(flow(420))


# ------------------------------------------------------------------ champ select de ARAM
def test_importa_al_tener_campeon(aram):
    d, lcu, _ = aram
    out = view(d, session(3), q=None)
    assert out["unsupported"] and out["aram"]["champ"]["id"] == 3
    assert out["aram"]["runes"]["state"] == "preview" and lcu.mutations() == []  # espera a que no cambie
    d.aram_seen = (3, 0.0)  # ya lleva un rato con él
    out = view(d, session(3))
    assert out["aram"]["runes"]["state"] == "imported"
    assert out["aram"]["runes"]["keystone"] == "Electrocute"
    nombres = [p["name"] for p in lcu.pages]
    assert nombres == ["Mi página", "Nachero · Assassin ARAM"]
    view(d, session(3))
    assert len([c for c in lcu.calls if c[0] == "POST"]) == 1  # una sola vez


def test_reemplaza_al_cambiar_de_campeon(aram):
    d, lcu, _ = aram
    d.aram_tick(session(3), True, now=10)
    d.aram_tick(session(3), True, now=12)
    d.aram_tick(session(7), True, now=13)  # reroll
    assert [p["name"] for p in lcu.pages] == ["Mi página", "Nachero · Assassin ARAM"]
    out = d.aram_tick(session(7), True, now=15)
    assert out["runes"]["state"] == "imported"
    assert [p["name"] for p in lcu.pages] == ["Mi página", "Nachero · Diver ARAM"]  # sin páginas sueltas


def test_reroll_rapido_no_importa_cada_campeon(aram):
    d, lcu, _ = aram
    for i, cid in enumerate([3, 7, 3, 7]):
        d.aram_tick(session(cid), True, now=10 + i * 0.5)
    assert lcu.mutations() == []


def test_mientras_descarga_no_toca_nada(aram):
    d, lcu, lola = aram
    del lola.aram[3]
    out = d.aram_tick(session(3), True, now=100)
    out = d.aram_tick(session(3), True, now=200)
    assert out["runes"] == {"state": "loading"} and lcu.mutations() == []


def test_campeon_sin_runas_de_aram(aram):
    d, lcu, lola = aram
    lola.aram[3] = {}
    assert d.aram_tick(session(3), True, now=100)["runes"] == {"state": "none"}
    assert lcu.mutations() == []


def test_en_observar_no_importa(aram):
    d, lcu, _ = aram
    d.aram_seen = (3, 0.0)
    out = view(d, session(3), acting=False)
    assert out["aram"]["runes"]["state"] == "would" and lcu.mutations() == []


def test_sin_importar_runas_no_hace_nada(aram, monkeypatch):
    d, lcu, _ = aram
    monkeypatch.setitem(CFG, "import_runes", False)
    d.aram_seen = (3, 0.0)
    out = view(d, session(3))
    assert out["aram"]["runes"] is None and lcu.mutations() == []


def test_solo_runas_ni_picks_ni_hechizos(aram):
    d, lcu, _ = aram
    d.aram_seen = (3, 0.0)
    view(d, session(3))
    assert {path for _, path in lcu.mutations()} <= {
        "/lol-perks/v1/pages",
        *(f"/lol-perks/v1/pages/{i}" for i in range(200)),
    }


@pytest.mark.parametrize("q", [flow(1700, 30, "CHERRY"), flow(900, 11, "URF")])
def test_arena_y_urf_siguen_sin_tocar_nada(aram, q):
    d, lcu, _ = aram
    d.aram_seen = (3, 0.0)
    out = view(d, session(3), q=classify(q))
    assert "aram" not in out and lcu.mutations() == []
