"""Simulador pro, lectores de datos externos y servidor del panel."""

import json

from conftest import FakeLola, all_roles
from draftbot.app.server import Handler
from draftbot.domain.common import norm
from draftbot.domain.engine import Engine
from draftbot.domain.player import Player
from draftbot.domain.pro import DRAFT_ORDER, ProEngine
from draftbot.sources.golgg import parse_gol
from draftbot.sources.lolalytics import parse_build


# ------------------------------------------------------------------ orden de draft
def test_orden_de_draft_de_torneo():
    assert len(DRAFT_ORDER) == 20
    for side in ("blue", "red"):
        assert sum(1 for s, k in DRAFT_ORDER if s == side and k == "ban") == 5
        assert sum(1 for s, k in DRAFT_ORDER if s == side and k == "pick") == 5
    assert DRAFT_ORDER[6] == ("blue", "pick")  # B1 abre la primera rotacion
    assert DRAFT_ORDER[12] == ("red", "ban")  # segunda ronda de bans la abre rojo


class FakeGol:
    loading: set = set()

    def __init__(self, ds):
        self.ds = ds

    def dataset(self, t):
        return self.ds


def make_pro(champs):
    names = {cid: champs.name(cid) for cid in champs.by_id}
    allrows = {
        norm(n): {"name": n, "picks": 10, "bans": 10, "prio": 60.0 + cid, "wins": 5, "losses": 5}
        for cid, n in names.items()
    }
    roles = {
        "top": {"bruiser": 10},
        "jungle": {"tanky": 10, "assassin": 10, "diver": 10},
        "middle": {"mage": 10, "poker": 10},
        "bottom": {"marksman": 10, "shooter": 10},
        "utility": {"enchanter": 10, "warden": 10},
    }
    ds = {"t": 0, "games": 20, "all": allrows, "roles": roles}
    lola = FakeLola(all_roles())
    eng = Engine(champs, lola, Player([], []), {"pick_mode": "meta", "weights": {}, "style": {}})
    return ProEngine(champs, lola, eng, FakeGol(ds))


def draft(blue_bans=(), blue_picks=(), red_bans=(), red_picks=()):
    return {
        "tournament": "Prueba",
        "blue": {"bans": list(blue_bans), "picks": list(blue_picks)},
        "red": {"bans": list(red_bans), "picks": list(red_picks)},
    }


def test_paso_actual_y_roles(champs):
    pe = make_pro(champs)
    st = draft(blue_bans=[8, 6, 5], blue_picks=[3], red_bans=[4, 2, 1])
    _, step = pe.state(st)
    assert step == 7  # 6 bans + B1
    res = pe.suggest(st)
    assert (res["side"], res["kind"]) == ("red", "pick")
    assert res["roles"]["blue"] == {3: "jungle"}
    assert "jungle" not in res["open_roles"]["blue"]


def test_no_banea_lo_que_va_a_coger(champs):
    pe = make_pro(champs)
    # Primer ban de azul: azul elige antes que rojo, asi que sus 2 picks preferidos no deben salir como bans
    res = pe.suggest(draft())
    teams, _ = pe.state(draft())
    todos = ["top", "jungle", "middle", "bottom", "utility"]
    ds = pe.gol.dataset("Prueba")
    plan = pe.picks(
        ds, pe.candidates(ds, set()), "blue", "red", teams, {"blue": {}, "red": {}}, {"blue": todos, "red": todos}, 0
    )[:2]
    assert (res["side"], res["kind"]) == ("blue", "ban")
    assert not {p["id"] for p in plan} & {b["id"] for b in res["suggestions"]}


def test_segunda_ronda_apunta_a_los_roles_libres_del_rival(champs):
    pe = make_pro(champs)
    # Azul tiene top, jungla y mid (le faltan ADC y support); rojo tiene mid, ADC y support.
    # Bans con ids que no existen para llegar a la segunda ronda sin gastar campeones.
    st = draft(blue_bans=[9001, 9002, 9003], blue_picks=[5, 3, 2], red_bans=[9004, 9005, 9006], red_picks=[8, 4, 6])
    res = pe.suggest(st)
    assert (res["side"], res["kind"]) == ("red", "ban")
    assert set(res["open_roles"]["blue"]) == {"bottom", "utility"}
    assert {b["id"] for b in res["suggestions"]} == {10, 11}  # el ADC y el support que quedan
    assert all("le falta" in " ".join(w["text"] for w in b["why"]) for b in res["suggestions"])


# ------------------------------------------------------------------ lectores
def test_parse_gol_tabla():
    fila = (
        "<tr><td><a href='../champion/champion-stats/67/'>Orianna</a></td><td>16</td><td>46</td><td>82%</td>"
        "<td>9</td><td>7</td><td>56%</td><td>3.9</td><td>3.5</td><td>1.50</td><td>93.8</td></tr>"
    )
    rows = parse_gol(f"<table><tr><th>Champion</th></tr>{fila}</table>")
    assert rows["orianna"]["picks"] == 16
    assert rows["orianna"]["prio"] == 82.0
    assert rows["orianna"]["wr"] == 56.0


def test_parse_build_estado_qwik():
    objs = [
        "counter",
        {"type": "0"},
        "jungle",
        ["4"],
        [64, 56.3, 7.2, 1.6, 10.1, 1736],
        {"data": "3", "lane": "2", "$$type": "1"},
    ]
    html = '<script type="qwik/json">' + json.dumps({"objs": objs}) + "</script>"
    lanes, slugs, runes = parse_build(html)
    assert lanes == {"jungle": {"64": {"wr": 56.3, "d1": 7.2, "d2": 1.6, "pr": 10.1, "n": 1736}}}
    assert slugs == {}
    assert runes == {}


# ------------------------------------------------------------------ servidor
def test_estaticos_no_salen_de_ui():
    assert Handler.static_file("/").name == "index.html"
    assert Handler.static_file("/style.css").name == "style.css"
    assert Handler.static_file("/../pyproject.toml") is None
    assert Handler.static_file("/config.py") is None
    assert Handler.static_file("/no-existe.js") is None
