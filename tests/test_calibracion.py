"""¿Acierta Nachero? Registro de picks, resultado y calibración (issue #9)."""

import pytest

from nachero import paths
from nachero.app import worker
from nachero.app.draft import Draft
from nachero.config import CFG
from nachero.domain import calibration as C
from nachero.jsonio import read_json
from test_roles_conexion import _engine, _game, session

T0 = 1_763_500_000_000  # ms


def rec(champ=7, est=53.0, t=T0, win=None, followed=True, parts=None, gid=None):
    r = C.make_record(t, {"id": 420}, "jungle", {"id": champ, "name": str(champ), "est": est, "parts": parts or {}},
                      {"id": champ if followed else 99, "est": est})  # fmt: skip
    return {**r, "win": win, "gameId": gid}


def game(gid, champ=7, t=T0 + 60_000, win=True):
    return {"gameId": gid, "champ": champ, "t": t, "win": win}


# ------------------------------------------------------------------ registro
def test_registro_al_confirmar():
    r = C.make_record(T0, {"id": 420, "name": "x"}, "jungle", {"id": 7, "name": "Diver", "est": 54.2,
                      "parts": {"meta": 1.0}}, {"id": 5, "est": 55.0}, "autofill", "16.23")  # fmt: skip
    assert r["est"] == 54.2 and r["top"] == 5 and r["followed"] is False and r["fit"] == "autofill"
    assert r["win"] is None and r["queue"] == 420 and r["patch"] == "16.23"


# ------------------------------------------------------------------ resultado
def test_apunta_el_resultado_con_el_historial():
    recs, done = C.resolve([rec()], [game(1, win=False)], T0 + 3_600_000)
    assert done == 1 and recs[0]["win"] is False and recs[0]["gameId"] == 1


def test_no_confunde_campeon_ni_hora():
    games = [game(1, champ=8), game(2, t=T0 - 3_600_000), game(3, t=T0 + 2 * 3_600_000)]
    recs, done = C.resolve([rec()], games, T0 + 3_600_000)
    assert done == 0 and recs[0]["win"] is None


def test_una_partida_no_cuenta_dos_veces():
    recs, done = C.resolve([rec(t=T0), rec(t=T0 + 1000)], [game(1)], T0 + 3_600_000)
    assert done == 1 and sum(r["win"] is not None for r in recs) == 1


def test_sin_partida_en_un_dia_se_descarta():
    recs, _ = C.resolve([rec()], [], T0 + 25 * 3_600_000)
    assert recs == []


def test_los_ya_resueltos_no_cambian():
    r = rec(win=True, gid=5)
    assert C.resolve([r], [game(6, win=False)], T0)[0] == [r]


# ------------------------------------------------------------------ informe
def test_informe_vacio():
    rep = C.report([])
    assert rep["n"] == 0 and not rep["enough"] and rep["wr"] is None


def test_informe_por_tramos_y_partes():
    recs = [rec(est=53, win=True, parts={"meta": 2.0, "you": 0.5}) for _ in range(6)]
    recs += [rec(est=53, win=False, parts={"meta": 0.0, "you": 0.5}) for _ in range(4)]
    recs += [rec(est=47, win=False, followed=False, parts={"meta": -1.0}) for _ in range(10)]
    recs += [rec()]  # pendiente
    rep = C.report(recs)
    assert rep["n"] == 20 and rep["pending"] == 1 and rep["enough"]
    tramo = next(b for b in rep["buckets"] if b["label"] == "52–54 %")
    assert tramo == {"label": "52–54 %", "n": 10, "est": 53.0, "wr": 60.0}
    assert next(b for b in rep["buckets"] if b["label"] == "46–48 %")["wr"] == 0.0
    meta = next(p for p in rep["parts"] if p["part"] == "meta")
    assert meta["gap"] > 1  # la fuerza en el parche separa victorias de derrotas
    assert rep["followed"] == {"n": 10, "wr": 60.0} and rep["other"] == {"n": 10, "wr": 0.0}
    assert 0 < rep["brier"] < 1 and len(rep["recent"]) == 10


def test_tramos_extremos():
    rep = C.report([rec(est=40, win=True), rec(est=70, win=False)])
    assert rep["buckets"][0]["label"] == "< 46 %" and rep["buckets"][0]["n"] == 1
    assert rep["buckets"][-1]["label"] == "≥ 56 %" and rep["buckets"][-1]["n"] == 1


# ------------------------------------------------------------------ en la champ select y en disco
@pytest.fixture
def quiet(monkeypatch):
    for k, v in {"auto_spells": False, "spells_by_role": {}, "auto_hover_pick": False, "import_runes": False,
                 "open_coachless_on_lock": False, "history_queues": [420, 440, 400, 490]}.items():  # fmt: skip
        monkeypatch.setitem(CFG, k, v)


def test_al_confirmar_en_soloq_se_registra_una_vez(champs, quiet):
    d = Draft(None, champs, _engine(champs, [_game("jungle")] * 5))
    s = session("jungle")
    top = d.tick(s, False, pickable=set(), bannable=set(), queue={"kind": "draft", "id": 420})["hero"]
    s["actions"][0][0].update(championId=5, completed=True)  # confirma otro campeón
    d.tick(s, False, pickable=set(), bannable=set(), queue={"kind": "draft", "id": 420})
    r = d.pop_record()
    assert r["champ"] == 5 and r["top"] == top["id"] and r["followed"] is (top["id"] == 5) and r["role"] == "jungle"
    d.tick(s, False, pickable=set(), bannable=set(), queue={"kind": "draft", "id": 420})
    assert d.pop_record() is None


@pytest.mark.parametrize("queue", [{"kind": "draft", "name": "Demo"}, {"kind": "blind", "id": 3140}])
def test_demo_y_practice_tool_no_cuentan(champs, quiet, queue):
    d = Draft(None, champs, _engine(champs, [_game("jungle")] * 5))
    s = session("jungle")
    s["actions"][0][0].update(championId=5, completed=True)
    d.tick(s, False, pickable=set(), bannable=set(), queue=queue)
    assert d.pop_record() is None


def test_guardar_y_resolver_en_el_perfil(home):
    worker.save_record(rec(), "16.23")
    assert read_json(paths.predictions_file(), [])[0]["patch"] == "16.23"
    assert worker.resolve_records([game(1)]) == 1
    assert read_json(paths.predictions_file(), [])[0]["win"] is True
    assert worker.resolve_records([]) == 0
