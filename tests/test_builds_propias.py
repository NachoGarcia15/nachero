"""Builds con datos propios (#90): objetos completos, botas y hechizos del final de la partida.

Sin red: el catálogo de Data Dragon es un doble y las partidas, la de ejemplo de la API de Riot."""

import copy
import json
from pathlib import Path

from nachero.domain import ingame as IG
from nachero.sources import dataset
from nachero.sources.local_stats import LocalStats
from nachero_collector import aggregate as A
from nachero_collector import items as I

DATA = Path(__file__).parent / "data" / "riot"
MATCH = json.loads((DATA / "match.json").read_text(encoding="utf-8"))

DDRAGON = {
    "data": {
        "1001": {"name": "Boots", "gold": {"total": 300, "purchasable": True}, "tags": ["Boots"], "into": ["3047"]},
        "3047": {"name": "Plated Steelcaps", "gold": {"total": 1100, "purchasable": True}, "tags": ["Boots"]},
        "3111": {"name": "Mercury's Treads", "gold": {"total": 1250, "purchasable": True}, "tags": ["Boots"]},
        "3078": {"name": "Trinity Force", "gold": {"total": 3333, "purchasable": True}, "tags": ["Damage"]},
        "6630": {"name": "Goredrinker", "gold": {"total": 3300, "purchasable": True}},
        "3053": {"name": "Sterak's Gage", "gold": {"total": 3200, "purchasable": True}},
        "3071": {"name": "Black Cleaver", "gold": {"total": 3000, "purchasable": True}},
        "6610": {"name": "Sundered Sky", "gold": {"total": 3100, "purchasable": True}},
        "1055": {"name": "Doran's Blade", "gold": {"total": 450, "purchasable": True}},
        "3057": {"name": "Sheen", "gold": {"total": 900, "purchasable": True}, "into": ["3078"]},
        "2003": {"name": "Health Potion", "gold": {"total": 50, "purchasable": True}, "tags": ["Consumable"]},
        "3340": {"name": "Stealth Ward", "gold": {"total": 0, "purchasable": True}, "tags": ["Trinket"]},
        "7001": {"name": "Ornn upgrade", "gold": {"total": 3300, "purchasable": False}, "requiredAlly": "Ornn"},
        "9999": {"name": "ARAM only", "gold": {"total": 3000, "purchasable": True}, "maps": {"11": False}},
    }
}  # fmt: skip
CATALOGO = I.classify(DDRAGON)


def test_objetos_completos_y_botas_de_data_dragon():
    assert CATALOGO == {"legendary": [3053, 3071, 3078, 6610, 6630], "boots": [3047, 3111]}
    assert I.version_for("16.23", ["16.24.1", "16.23.1", "16.22.1"]) == "16.23.1"
    assert I.version_for("16.25", ["16.24.1"]) is None


def test_catalogo_en_cache_por_parche(tmp_path):
    pedido = []

    def fetch(url):
        pedido.append(url)
        return json.dumps(["16.23.1", "16.22.1"] if url == I.VERSIONS else DDRAGON).encode()

    assert I.catalog("16.23", tmp_path, fetch) == CATALOGO
    assert pedido[-1].endswith("/cdn/16.23.1/data/en_US/item.json")

    def sin_red(url):
        raise OSError("sin red")

    assert I.catalog("16.23", tmp_path, sin_red) == CATALOGO  # de la caché
    assert I.catalog("16.22", tmp_path, sin_red) is None  # sin caché ni red: esa pasada no cuenta objetos


def partida(builds):
    """La partida de ejemplo con objetos y hechizos: {índice de participante: (objetos, hechizos)}."""
    m = copy.deepcopy(MATCH)
    for k, p in enumerate(m["info"]["participants"]):
        held, spells = builds.get(k, ([], (4, 14)))
        for i in range(7):
            p[f"item{i}"] = held[i] if i < len(held) else 0
        p["summoner1Id"], p["summoner2Id"] = spells
    return m


def test_cuenta_objetos_botas_y_hechizos():
    m = partida({0: ([3078, 6630, 3047, 1055, 3053, 0, 3340], (11, 4))})
    doc = A.new_doc("16.23", "euw1", "emerald_plus", "test")
    A.add_match(doc, m, CATALOGO)
    p0 = m["info"]["participants"][0]
    row = doc["champions"][str(p0["championId"])]["roles"][A.POSITION[p0["teamPosition"]]]
    assert set(row["items"]) == {"3078", "6630", "3053"}  # sin Doran ni guardián
    assert row["boots"] == {"3047": {"games": 1, "wins": int(p0["win"])}}
    assert row["spells"] == [{"ids": [4, 11], "games": 1, "wins": int(p0["win"])}]  # ordenados
    sin = A.new_doc("16.23", "euw1", "emerald_plus", "test")
    A.add_match(sin, m)  # sin catálogo: solo hechizos
    row = sin["champions"][str(p0["championId"])]["roles"][A.POSITION[p0["teamPosition"]]]
    assert "items" not in row and row["spells"]


def documento(games=200):
    """Un campeón con builds: Trinity + Goredrinker + Sterak lo más jugado; Black Cleaver gana más."""
    row = {
        "games": games, "wins": games // 2,
        "items": {"3078": {"games": 150, "wins": 75}, "6630": {"games": 140, "wins": 70},
                  "3053": {"games": 120, "wins": 60}, "3071": {"games": 60, "wins": 42},
                  "6610": {"games": 50, "wins": 26}},
        "boots": {"3047": {"games": 120, "wins": 58}, "3111": {"games": 70, "wins": 42}},
        "spells": [{"ids": [4, 11], "games": 190, "wins": 95}, {"ids": [6, 11], "games": 10, "wins": 9}],
    }  # fmt: skip
    return {"schema": 1, "patch": "16.23", "region": "euw1", "league": "emerald_plus",
            "generated": "2026-11-27T00:00:00Z", "collector": "t", "totals": {"games": 1000},
            "champions": {"86": {"bans": 0, "roles": {"top": row}}}, "matchups": {}, "synergies": {}}  # fmt: skip


def test_de_los_conteos_a_la_build_del_motor():
    doc = documento()
    assert dataset.validate(doc) == []
    b = dataset.derive(doc)["builds"]["86:top"]
    assert b["pick"]["core"] == [3078, 6630, 3053] and b["pick"]["boots"] == 3047 and b["pick"]["spells"] == [4, 11]
    assert b["pick"]["options"][0][0] == {"id": 3071, "wr": 70.0, "n": 60}
    assert b["win"]["core"][0] == 3071 and b["win"]["boots"] == 3111  # mayor WR con muestra suficiente
    assert b["win"]["spells"] == [4, 11]  # Ghost tiene 10 partidas: menos del 5 % y de 30
    assert b["pick"]["start"] == [] and b["pick"]["order"] == "" and b["pick"]["core_wr"] is None


def test_objetos_no_validos_se_rechazan():
    doc = documento()
    doc["champions"]["86"]["roles"]["top"]["items"]["3078"]["wins"] = 999
    assert any("objetos" in e for e in dataset.validate(doc))
    doc = documento()
    doc["champions"]["86"]["roles"]["top"]["spells"] = [{"ids": [4], "games": 1, "wins": 0}]
    assert dataset.validate(doc)


def test_principio_de_parche_mezcla_los_objetos():
    prev, cur = documento(), documento(games=10)
    prev["patch"] = "16.22"
    row = cur["champions"]["86"]["roles"]["top"]
    row.update(items={"6610": {"games": 8, "wins": 6}}, boots={}, spells=[{"ids": [4, 11], "games": 10, "wins": 5}])
    b = dataset.derive(cur, prev)["builds"]["86:top"]
    assert 3078 in b["pick"]["core"]  # del parche anterior, que aún pesa casi todo


def test_local_stats_y_vista_en_partida(tmp_path):
    f = tmp_path / "16.23" / "euw1"
    f.mkdir(parents=True)
    (f / "emerald_plus.json").write_text(json.dumps(documento()), encoding="utf-8")
    s = LocalStats(tmp_path, region="euw1", league="emerald_plus")

    class Items:
        def brief(self, iid, kind="item"):
            return {"id": iid, "name": str(iid)}

    view = IG.build_view(s.build(86, "top"), Items(), "pick")
    assert [i["id"] for i in view["core"]] == [3078, 6630, 3053] and view["boots"]["id"] == 3047
    assert view["slots"][0]["slot"] == 4 and view["slots"][0]["items"][0]["id"] == 3071
    assert IG.build_view(s.build(86, "top"), Items(), "win")["which"] == "win"
