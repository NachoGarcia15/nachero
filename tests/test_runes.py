"""Importacion de runas: lector de Lolalytics, construccion de la pagina e importacion al cliente."""

import json

from draftbot.app.draft import Draft
from draftbot.app.runes import RuneImporter
from draftbot.config import CFG, apply_settings
from draftbot.domain import runes as R
from draftbot.sources.lolalytics import parse_build

# Catalogo minimo: dos ramas con sus runas y la fila de fragmentos (que aparece en todas)
PERKSTYLES = {
    "styles": [
        {
            "id": 8100,
            "name": "Domination",
            "slots": [
                {"perks": [8112, 8128]},
                {"perks": [8126, 8139]},
                {"perks": [8137, 8140]},
                {"perks": [8135, 8105]},
                {"perks": [5008, 5005, 5007]},
            ],
        },
        {
            "id": 8300,
            "name": "Inspiration",
            "slots": [
                {"perks": [8351]},
                {"perks": [8304, 8306]},
                {"perks": [8347, 8345]},
                {"perks": [8410]},
                {"perks": [5008, 5005, 5007]},
            ],
        },
    ]
}
PERKS = [
    {"id": 8112, "name": "Electrocute"},
    {"id": 8128, "name": "Dark Harvest"},
    {"id": 8139, "name": "Taste of Blood"},
    {"id": 8140, "name": "Grisly Mementos"},
    {"id": 8105, "name": "Relentless Hunter"},
    {"id": 8347, "name": "Cosmic Insight"},
    {"id": 8304, "name": "Magical Footwear"},
]
ELECTROCUTE = {"pri": [8112, 8139, 8140, 8105], "sec": [8347, 8304], "mod": [5008, 5008, 5007]}


class FakeCatalog:
    def get(self, path, timeout=20):
        return {
            "/lol-game-data/assets/v1/perkstyles.json": PERKSTYLES,
            "/lol-game-data/assets/v1/perks.json": PERKS,
        }.get(path)


class FakeLCU:
    def __init__(self, pages, can_add=True):
        self.pages, self.can_add, self.calls = pages, can_add, []

    def get(self, path, timeout=5):
        if path == "/lol-perks/v1/pages":
            return self.pages
        if path == "/lol-perks/v1/inventory":
            return {"canAddCustomPage": self.can_add}
        return None

    def req(self, method, path, body=None, timeout=5):
        self.calls.append((method, path, body))
        return {"id": 99, **body} if method == "POST" else None


# ------------------------------------------------------------------ lector de Lolalytics
def test_parse_build_extrae_las_dos_paginas():
    objs = [
        "counter",
        {"type": "0"},
        "jungle",
        ["4"],
        [64, 56.3, 7.2, 1.6, 10.1, 1736],
        {"data": "3", "lane": "2", "$$type": "1"},
        # 6: build "pick" -> runes -> set
        {"runes": "7"},
        {"set": "8"},
        {"pri": [8112, 8139, 8140, 8105], "sec": [8347, 8304], "mod": [5008, 5008, 5007]},
        # 9: build "win"
        {"runes": "a"},
        {"set": "b"},
        {"pri": [8128, 8139, 8140, 8105], "sec": [8347, 8304], "mod": [5005, 5008, 5007]},
        {"pick": "6", "win": "9"},
    ]
    html = '<script type="qwik/json">' + json.dumps({"objs": objs}) + "</script>"
    _, _, runes = parse_build(html)
    assert runes["pick"]["pri"][0] == 8112
    assert runes["win"]["pri"][0] == 8128
    assert runes["win"]["mod"] == [5005, 5008, 5007]


def test_parse_build_sin_runas_devuelve_vacio():
    objs = [
        "counter",
        {"type": "0"},
        "jungle",
        ["4"],
        [64, 56.3, 7.2, 1.6, 10.1, 1736],
        {"data": "3", "lane": "2", "$$type": "1"},
    ]
    html = '<script type="qwik/json">' + json.dumps({"objs": objs}) + "</script>"
    assert parse_build(html)[2] == {}


# ------------------------------------------------------------------ dominio
def test_ramas_sin_fragmentos():
    styles = R.perk_styles(PERKSTYLES)
    assert styles[8112] == 8100 and styles[8347] == 8300
    assert 5008 not in styles


def test_build_page_valida():
    page = R.build_page(ELECTROCUTE, R.perk_styles(PERKSTYLES), "draftbot · Naafiri JG")
    assert page == {
        "name": "draftbot · Naafiri JG",
        "primaryStyleId": 8100,
        "subStyleId": 8300,
        "selectedPerkIds": [8112, 8139, 8140, 8105, 8347, 8304, 5008, 5008, 5007],
        "current": True,
    }


def test_build_page_rechaza_paginas_invalidas():
    styles = R.perk_styles(PERKSTYLES)
    assert R.build_page({**ELECTROCUTE, "pri": [8112, 8139, 8140]}, styles, "x") is None  # faltan runas
    assert R.build_page({**ELECTROCUTE, "sec": [8139, 8140]}, styles, "x") is None  # misma rama
    assert R.build_page({**ELECTROCUTE, "sec": [8347, 8139]}, styles, "x") is None  # ramas mezcladas
    assert R.build_page({**ELECTROCUTE, "mod": [5008, 5008, 8112]}, styles, "x") is None  # fragmento falso


def test_nombre_de_pagina_corto_y_reconocible():
    name = R.page_name("Nunu & Willump", "JG")
    assert name.startswith(R.PAGE_PREFIX) and len(name) <= 25


# ------------------------------------------------------------------ importacion
def test_importa_y_solo_reemplaza_paginas_de_draftbot():
    lcu = FakeLCU(
        [
            {"id": 1, "name": "Mi página", "isEditable": True},
            {"id": 2, "name": "draftbot · Taliyah JG", "isEditable": True},
            {"id": 3, "name": "Recomendada", "isEditable": False},
        ]
    )
    ok, msg = RuneImporter(FakeCatalog()).apply(lcu, "Naafiri", "JG", ELECTROCUTE)
    assert ok and "Electrocute" in msg
    assert ("DELETE", "/lol-perks/v1/pages/2", None) in lcu.calls
    assert not any(m == "DELETE" and p.endswith(("/1", "/3")) for m, p, _ in lcu.calls)
    post = next(b for m, p, b in lcu.calls if m == "POST")
    assert post["name"] == "draftbot · Naafiri JG" and post["current"] is True


def test_sin_hueco_no_toca_tus_paginas():
    lcu = FakeLCU([{"id": 1, "name": "Mi página", "isEditable": True}], can_add=False)
    ok, msg = RuneImporter(FakeCatalog()).apply(lcu, "Naafiri", "JG", ELECTROCUTE)
    assert not ok and "hueco" in msg
    assert lcu.calls == []


# ------------------------------------------------------------------ champ select
class FakeLola:
    def __init__(self, sets):
        self.sets = sets

    def runes(self, cid, role):
        return self.sets


class FakeEngine:
    def __init__(self, sets):
        self.lola = FakeLola(sets)


class FakeChampsNames:
    def name(self, cid):
        return {1: "Naafiri", 2: "Zeri"}[cid]


def make_draft(sets, lcu=None):
    CFG.update({"import_runes": True, "runes_source": "pick"})
    d = Draft(lcu or FakeLCU([]), FakeChampsNames(), FakeEngine(sets), RuneImporter(FakeCatalog()))
    return d


def test_sin_datos_no_importa_nada():
    lcu = FakeLCU([])
    d = make_draft({}, lcu)
    info = d.handle_runes(2, "jungle", locked=True, acting=True, status=[])
    assert info == {"state": "none"}
    assert lcu.calls == []


def test_importa_una_sola_vez_al_confirmar():
    lcu = FakeLCU([])
    d = make_draft({"pick": ELECTROCUTE}, lcu)
    assert d.handle_runes(1, "jungle", locked=False, acting=True, status=[])["state"] == "preview"
    assert lcu.calls == []
    for _ in range(3):
        info = d.handle_runes(1, "jungle", locked=True, acting=True, status=[])
    assert info["state"] == "imported" and info["keystone"] == "Electrocute"
    assert sum(1 for m, _, _ in lcu.calls if m == "POST") == 1


def test_observando_no_importa():
    lcu = FakeLCU([])
    status = []
    info = make_draft({"pick": ELECTROCUTE}, lcu).handle_runes(1, "jungle", locked=True, acting=False, status=status)
    assert info["state"] == "would" and lcu.calls == []
    assert status and "Importaría runas" in status[0][1]


def test_ajuste_de_fuente_de_runas():
    cfg = {}
    assert apply_settings(cfg, {"runes_source": "win"}) == ["runas de mayor WR"]
    assert apply_settings(cfg, {"runes_source": "otra"}) == []
    assert apply_settings(cfg, {"import_runes": False}) == ["import_runes"]
