"""Vista «En partida» (#88): drafts, ventaja de draft y build recomendada, sin cliente ni red."""

import json

import pytest

from conftest import FakeLola, all_roles
from nachero.app import worker
from nachero.domain import ingame as IG
from nachero.domain.engine import Engine
from nachero.domain.player import Player
from nachero.domain.stats import ChainStats
from nachero.sources.lolalytics import Lolalytics, parse_build, parse_page

PUUID = "p" * 78  # el puuid de Riot: nunca debe salir hacia el panel
ALLY = {1: "TOP", 3: "JUNGLE", 2: "MIDDLE", 4: "BOTTOM", 6: "UTILITY"}
ENEMY = [5, 7, 8, 10, 11]


class FakeItems:
    def brief(self, iid, kind="item"):
        return {"id": iid, "name": f"{kind}-{iid}"}


def _engine(champs, matchups=None):
    lola = FakeLola(
        all_roles(
            top={1: (51, 9000, 8, 90), 5: (52, 9000, 8, 90)},
            jungle={3: (50, 9000, 8, 90), 7: (51, 9000, 8, 90)},
            middle={2: (53, 9000, 8, 90), 8: (49, 9000, 8, 90)},
            bottom={4: (50, 9000, 8, 90), 10: (50, 9000, 8, 90)},
            utility={6: (51, 9000, 8, 90), 11: (50, 9000, 8, 90)},
        ),
        matchups
        if matchups is not None
        else {
            (2, "middle"): {"middle": {8: 2.0}},
            (8, "middle"): {"middle": {2: -2.0}},
        },
    )
    return Engine(champs, lola, Player([], []), {"pick_mode": "pool", "weights": {}, "main_role": "jungle"})


def _flow(mine_in_two=False, queue_id=420):
    me = {"championId": 3, "puuid": PUUID, "selectedPosition": "JUNGLE", "summonerName": "Yo"}
    ally = [me] + [
        {"championId": c, "puuid": f"a{c}", "selectedPosition": p, "summonerName": f"Aliado{c}"}
        for c, p in ALLY.items()
        if c != 3
    ]
    # la posición rival que dé el cliente no se usa: se estima por sus campeones
    enemy = [{"championId": c, "puuid": f"e{c}", "selectedPosition": "TOP", "summonerName": f"Rival{c}"} for c in ENEMY]
    sels = [{"championId": c, "spell1Id": 4, "spell2Id": 11 if c == 3 else 14} for c in [*ALLY, *ENEMY]]
    one, two = (enemy, ally) if mine_in_two else (ally, enemy)
    return {
        "phase": "InProgress",
        "map": {"id": 11},
        "gameData": {
            "queue": {"id": queue_id, "gameMode": "CLASSIC", "mapId": 11, "type": "RANKED_SOLO_5x5"},
            "teamOne": one,
            "teamTwo": two,
            "playerChampionSelections": sels,
        },
    }


def _champ_select():
    my_team = [
        {"cellId": i, "championId": c, "assignedPosition": p.lower(), "spell1Id": 4, "spell2Id": 7}
        for i, (c, p) in enumerate(ALLY.items())
    ]
    their = [{"cellId": 5 + i, "championId": c} for i, c in enumerate(ENEMY)]
    return {"localPlayerCellId": 1, "myTeam": my_team, "theirTeam": their}


# ------------------------------------------------------------------ equipos de la partida
def test_parse_game_separa_equipos_hechizos_y_roles():
    g = IG.parse_game(_flow(), PUUID, _champ_select())
    assert g["me"] == 3
    assert [p["id"] for p in g["ally"]] == [3, 1, 2, 4, 6]
    assert {p["id"]: p["role"] for p in g["ally"]}[3] == "jungle"
    assert all(p["role"] is None for p in g["enemy"])  # el rol rival nunca se lee del cliente
    assert next(p for p in g["ally"] if p["me"])["spells"] == [4, 11]


def test_parse_game_tu_equipo_puede_ser_el_dos():
    g = IG.parse_game(_flow(mine_in_two=True), PUUID, None)
    assert sorted(p["id"] for p in g["ally"]) == sorted(ALLY)
    assert sorted(p["id"] for p in g["enemy"]) == sorted(ENEMY)
    # sin champ select, el rol de tus aliados sale de la posición de tu equipo
    assert {p["id"]: p["role"] for p in g["ally"]}[4] == "bottom"


def test_parse_game_sin_puuid_por_la_champ_select():
    g = IG.parse_game(_flow(mine_in_two=True), None, _champ_select())
    assert g["me"] == 3 and sorted(p["id"] for p in g["ally"]) == sorted(ALLY)


def test_parse_game_sin_partida_usa_la_champ_select():
    g = IG.parse_game({}, None, _champ_select())
    assert [p["id"] for p in g["enemy"]] == ENEMY
    assert next(p for p in g["ally"] if p["me"])["spells"] == [4, 7]
    assert IG.parse_game({}, None, None) is None


def test_roles_libres_estimados(champs):
    eng = _engine(champs)
    players = [{"id": c, "role": None, "spells": [], "me": False} for c in ENEMY]
    assert IG.fill_roles(players, eng.lola) == {5: "top", 7: "jungle", 8: "middle", 10: "bottom", 11: "utility"}
    # a ciegas, tu rol manda y el resto se reparte entre los libres
    mine = [{"id": 2, "role": None, "spells": [], "me": True}, {"id": 3, "role": None, "spells": [], "me": False}]
    assert IG.fill_roles(mine, eng.lola, my_role="top") == {2: "top", 3: "jungle"}


# ------------------------------------------------------------------ puntuación
def test_report_ventaja_de_draft_y_lineas(champs):
    eng = _engine(champs)
    rep = IG.report(eng, champs, IG.parse_game(_flow(), PUUID, _champ_select()))
    assert [p["role"] for p in rep["ally"]] == ["top", "jungle", "middle", "bottom", "utility"]
    assert rep["me"]["id"] == 3 and rep["my_role"] == "jungle"
    t = rep["team"]
    mean = lambda team: sum(p["score"] for p in team) / 5  # noqa: E731
    assert t["advantage"] == pytest.approx((mean(rep["ally"]) - mean(rep["enemy"])) / 2, abs=0.11)
    assert t["est"] == pytest.approx(50 + t["advantage"], abs=0.01)
    mid = next(lane for lane in rep["lanes"] if lane["role"] == "middle")
    assert mid["ally"]["id"] == 2 and mid["enemy"]["id"] == 8 and mid["post"] > 0
    assert not rep["loaded"]  # faltan matchups del resto: el panel enseña «…»
    # sin tu parte personal ni riesgo de counter: tus aliados y los rivales se miden igual
    assert all(set(p["parts"]) <= set(IG.DRAFT_PARTS) for p in rep["ally"] + rep["enemy"])


def test_report_matchups_cargados(champs):
    mus = {(c, r): {} for c, r in [(1, "top"), (3, "jungle"), (4, "bottom"), (6, "utility")]}
    mus |= {(c, r): {} for c, r in [(5, "top"), (7, "jungle"), (10, "bottom"), (11, "utility")]}
    mus[(2, "middle")], mus[(8, "middle")] = {"middle": {8: 2.0}}, {"middle": {2: -2.0}}
    rep = IG.report(_engine(champs, mus), champs, IG.parse_game(_flow(), PUUID, _champ_select()))
    assert rep["loaded"]
    mid_ally = next(p for p in rep["ally"] if p["role"] == "middle")
    mid_enemy = next(p for p in rep["enemy"] if p["role"] == "middle")
    assert mid_ally["parts"]["lane"] > 0 > mid_enemy["parts"]["lane"]


def test_notas_de_la_partida():
    ally = {"n": 5, "front": 0, "phys": 50, "cc": 4}
    enemy = {"n": 5, "front": 2, "phys": 80, "cc": 10}
    notes = IG.team_notes(ally, enemy, ("", {}, {"E": 0.0}), ("engage", {}, {"E": 2.5}))
    text = " ".join(notes)
    assert "armadura" in text and "Mercurio" in text and "frontline" in text and "engage" in text


# ------------------------------------------------------------------ build de Lolalytics
def _summary(core, start=(1101, 2003), order=132114131343322, prio="QEW"):
    return {
        "skillpriority": {"id": prio, "n": 100, "wr": 52.0},
        "skillorder": {"id": order, "n": 50, "wr": 55.0},
        "sums": {"ids": [4, 11], "n": 100, "wr": 51.0},
        "items": {
            "start": {"set": list(start), "n": 100, "wr": 52.0},
            "core": {"set": list(core), "wr": 53.5, "n": 800},
            "item4": [{"id": 3157, "n": 90, "wr": 53.2}, {"id": 3089, "n": 30, "wr": 56.7}],
            "item5": [{"id": 3089, "n": 30, "wr": 57.6}],
            "item6": [],
        },
    }


def _page(pick, win, boots=((3020, 52.6, 82.6, 2000, 12), (3158, 48.6, 10.2, 300, 12))):
    objs = [
        "counter",
        {"type": "0"},
        "jungle",
        ["4"],
        [64, 56.3, 7.2, 1.6, 10.1, 1736],
        {"data": "3", "lane": "2", "$$type": "1"},
        {"data": [list(b) for b in boots], "type": "boots"},
        {"pick": pick, "win": win},
    ]
    return '<script type="qwik/json">' + json.dumps({"objs": objs}) + "</script>"


def test_parse_page_saca_la_build():
    html = _page(_summary([2503, 3020, 4645]), _summary([2503, 4645, 3165], start=(1101,), order=131214131343322))
    page = parse_page(html)
    pick, win = page["build"]["pick"], page["build"]["win"]
    assert pick["start"] == [1101, 2003] and pick["core"] == [2503, 3020, 4645]
    assert pick["boots"] == 3020  # las del núcleo
    assert win["boots"] == 3020  # sin botas en el núcleo: las más jugadas de la tabla
    assert pick["skills"] == "QEW" and pick["order"] == "QEWQQRQEQEREEWW"
    assert win["order"].startswith("QEQW")
    assert pick["spells"] == [4, 11] and pick["core_wr"] == 53.5
    assert [len(o) for o in pick["options"]] == [2, 1, 0]
    assert page["lanes"]["jungle"]["64"]["d2"] == 1.6
    # parse_build sigue devolviendo lo de siempre
    lanes, slugs, runes = parse_build(html)
    assert lanes == page["lanes"] and slugs == {} and runes == {}


def test_parse_page_sin_build_devuelve_vacio():
    objs = ["counter", {"type": "0"}, "jungle", ["4"], [64, 56.3, 7.2, 1.6, 10.1, 1736],
            {"data": "3", "lane": "2", "$$type": "1"}]  # fmt: skip
    page = parse_page('<script type="qwik/json">' + json.dumps({"objs": objs}) + "</script>")
    assert page["build"] == {}


def test_lolalytics_build_de_la_cache(tmp_path, monkeypatch):
    lola = Lolalytics(str(tmp_path), lambda *a, **k: None)
    asked = []
    monkeypatch.setattr(lola, "request", lambda cid, role, slug=None: asked.append((cid, role)))
    lola.patch = "16.22"
    assert lola.build(163, "jungle") is None and asked == [(163, "jungle")]
    # entrada de antes de guardar builds: se vuelve a pedir, sin perder los matchups
    lola.cache["builds"]["163:jungle"] = {
        "t": 9e12,
        "patch": "16.22",
        "tier": lola.build_tier,
        "lanes": {},
        "runes": {},
    }
    assert lola.build(163, "jungle") is None and len(asked) == 2
    lola.cache["builds"]["163:jungle"]["build"] = {"pick": {"core": [1]}}
    assert lola.build(163, "jungle") == {"pick": {"core": [1]}} and len(asked) == 2


class _Src:
    def __init__(self, name, build):
        self.name, self.b = name, build

    def build(self, cid, role):
        return self.b


def test_cadena_de_fuentes_con_build():
    class Sin:
        name = "Sin builds"

    full = {"pick": {"core": [1]}}
    assert ChainStats([_Src("a", None), _Src("b", full)]).build(1, "top") == full
    assert ChainStats([Sin(), _Src("b", full)]).build(1, "top") == full
    assert ChainStats([_Src("a", {}), _Src("b", None)]).build(1, "top") == {}
    assert ChainStats([Sin()]).build(1, "top") is None


def test_build_view_con_varias_opciones():
    build = {
        "pick": {"start": [1101], "core": [2503, 3020, 4645], "boots": 3020, "core_wr": 52.1, "core_n": 800,
                 "options": [[{"id": 3157, "wr": 53.2, "n": 90}, {"id": 3089, "wr": 56.7, "n": 30}], [], []],
                 "skills": "QEW", "order": "QEW", "spells": [4, 11]},
        "win": {"start": [1101], "core": [2503, 4645, 3020], "core_wr": 54.0, "options": []},
    }  # fmt: skip
    v = IG.build_view(build, FakeItems())
    assert v["which"] == "pick" and [i["id"] for i in v["core"]] == [2503, 3020, 4645]
    assert v["boots"] == {"id": 3020, "name": "item-3020"}
    assert [len(s["items"]) for s in v["slots"]] == [2] and v["slots"][0]["slot"] == 4
    assert [i["id"] for i in v["alt_core"]] == [2503, 4645, 3020] and v["alt_core_wr"] == 54.0
    assert IG.build_view({"win": build["win"]}, FakeItems(), "pick")["which"] == "win"
    assert IG.build_view(None, FakeItems()) is None and IG.build_view({}, FakeItems()) is None


# ------------------------------------------------------------------ vista completa y normas de Riot
class BuildLola(FakeLola):
    def build(self, cid, role):
        return {"pick": {"start": [1101], "core": [2503], "boots": 3020, "options": [], "spells": [4, 11]}}


def test_game_view_sin_datos_personales_de_otros(champs):
    eng = _engine(champs)
    eng.lola.__class__ = BuildLola
    g = worker.game_view(eng, champs, FakeItems(), _flow(), _champ_select(), PUUID)
    assert g["me"]["id"] == 3 and g["build"]["core"][0]["id"] == 2503
    assert g["build"]["spells"][0] == {"id": 4, "name": "spell-4"}
    assert g["ally"][0]["spells"][0]["name"].startswith("spell-")
    assert g["coachless"].startswith("https://coachless.gg/builds/assassin")  # solo el enlace
    text = json.dumps(g)
    for private in (PUUID, "Rival", "Aliado", "Yo"):  # ni puuid ni nombres de jugadores
        assert private not in text


def test_game_view_build_pendiente(champs):
    class Pending(FakeLola):
        def build(self, cid, role):
            return None

    eng = _engine(champs)
    eng.lola.__class__ = Pending
    g = worker.game_view(eng, champs, FakeItems(), _flow(), _champ_select(), PUUID)
    assert g["build"] is None and g["build_pending"]


def test_game_view_fuera_de_la_grieta(champs):
    flow = _flow(queue_id=450)
    flow["gameData"]["queue"] = {"id": 450, "gameMode": "ARAM", "mapId": 12}
    flow["map"] = {"id": 12}
    assert worker.game_view(_engine(champs), champs, FakeItems(), flow, None, PUUID) is None


def test_items_del_cliente_en_segundo_plano():
    from nachero.sources.items import Items

    class Src:
        def get(self, path, timeout=5):
            if path == "/lol-game-data/assets/v1/items.json":
                return [{"id": 3020, "name": "Botas", "iconPath": "/x.png"}]
            return None

    src = Src()
    items = Items(src)
    assert items.icon("item", 3020) == "/x.png"  # el servidor espera al catálogo
    assert items.brief(3020) == {"id": 3020, "name": "Botas"}
    assert items.brief(1) == {"id": 1, "name": "1"}


def test_panel_tiene_la_vista_en_partida():
    from nachero import paths

    js = (paths.UI_DIR / "app.js").read_text(encoding="utf-8")
    assert "function renderGame" in js and "roles rivales estimados" in js
