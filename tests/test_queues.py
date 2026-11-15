"""Tipo de cola: draft, a ciegas o fuera de la Grieta (y que en este ultimo no se toque el cliente)."""

import json
from pathlib import Path

import pytest

from draftbot.app.draft import Draft
from draftbot.app.worker import champ_select_view
from draftbot.config import CFG
from draftbot.domain.queues import classify, has_bans
from test_roles_conexion import _engine, _game, session

DATA = Path(__file__).parent / "data"


def flow(qid=-1, map_id=11, mode="CLASSIC", custom=False, desc="", fmap=None):
    """Sesion de /lol-gameflow/v1/session reducida a lo que se usa."""
    return {
        "phase": "ChampSelect",
        "gameData": {
            "isCustomGame": custom,
            "queue": {"id": qid, "mapId": map_id, "gameMode": mode, "description": desc},
        },
        "map": fmap or {"id": map_id, "gameMode": mode},
    }


# ------------------------------------------------------------------ clasificacion
@pytest.mark.parametrize(
    ("f", "kind", "name"),
    [
        (flow(420), "draft", "Clasificatoria solo/dúo"),
        (flow(440), "draft", "Clasificatoria flexible"),
        (flow(400), "draft", "Normal (reclutamiento)"),
        (flow(700), "draft", "Clash"),
        (flow(430), "blind", "Normal (a ciegas)"),
        (flow(490), "blind", "Partida rápida"),
        # por si una personalizada llega con la cola casi vacia: el mapa va en `map`
        (flow(-1, 0, "", custom=True, fmap={"id": 11, "gameMode": "CLASSIC"}), "blind", "Personalizada"),
        (flow(-1, 0, "", custom=True, fmap={"id": 11, "gameMode": "PRACTICETOOL"}), "blind", "Herramienta de práctica"),
        (flow(-1, 11, "PRACTICETOOL"), "blind", "Herramienta de práctica"),
        (flow(450, 12, "ARAM"), "other", "ARAM"),
        (flow(1700, 30, "CHERRY"), "other", "Arena"),
        (flow(900, 11, "URF"), "other", "URF"),  # en la Grieta, pero con otras reglas
        (flow(1020, 11, "ONEFORALL"), "other", "Uno para todos"),
        (flow(-1, 0, "", custom=True, fmap={"id": 12, "gameMode": "ARAM"}), "other", "Personalizada · ARAM"),
        (flow(2400, 35, "BRAWL", desc="Brawl"), "other", "Brawl"),  # modo nuevo: nombre del cliente
    ],
)
def test_clasifica_la_cola(f, kind, name):
    q = classify(f)
    assert (q["kind"], q["name"]) == (kind, name)


# sesiones reales del cliente (parche 16.22, solo `gameData.queue` y `map`, sin datos personales):
# en personalizadas y Practice Tool la cola llega completa, con su propio id
@pytest.mark.parametrize(
    ("fichero", "qid", "name"),
    [
        ("gameflow_practice.json", 3140, "Herramienta de práctica"),
        ("gameflow_custom.json", 3100, "Personalizada"),
    ],
)
def test_clasifica_sesiones_reales_del_cliente(fichero, qid, name):
    real = json.loads((DATA / fichero).read_text(encoding="utf-8"))
    assert classify(real) == {"kind": "blind", "id": qid, "name": name}


@pytest.mark.parametrize("f", [None, {}, {"gameData": {}}, "texto", {"gameData": {"queue": {"id": -1}}}])
def test_sin_datos_de_cola_es_desconocida(f):
    assert classify(f)["kind"] == "unknown"


def test_detecta_fase_de_bans():
    s = session("jungle")
    assert not has_bans(s)
    s["actions"].insert(0, [{"id": 9, "actorCellId": 0, "type": "ban", "completed": False}])
    assert has_bans(s)


# ------------------------------------------------------------------ champ select segun la cola
class FakeLCU:
    def __init__(self):
        self.calls = []

    def get(self, path, timeout=None):
        return []

    def req(self, method, path, body=None):
        self.calls.append((method, path))


@pytest.fixture
def activo(monkeypatch):
    """Modo activo con hechizos y marcado: lo que podria tocar el cliente."""
    for k, v in {
        "auto_spells": True,
        "spells_by_role": {"jungle": ["Smite", "Flash"], "utility": ["Ignite", "Flash"]},
        "auto_hover_pick": True,
        "auto_lock_pick": False,
        "import_runes": False,
        "open_coachless_on_lock": False,
    }.items():
        monkeypatch.setitem(CFG, k, v)


def test_fuera_de_la_grieta_no_recomienda_ni_actua(champs, activo):
    lcu = FakeLCU()
    d = Draft(lcu, champs, _engine(champs, [_game("jungle")] * 5))
    out = champ_select_view(d, session(""), True, classify(flow(450, 12, "ARAM")))
    assert out == {"unsupported": True, "queue": "ARAM"}
    assert lcu.calls == []  # ni Smite + Flash, ni marcar pick


def test_en_la_grieta_si_actua(champs, activo):
    lcu = FakeLCU()
    d = Draft(lcu, champs, _engine(champs, [_game("jungle")] * 5))
    out = champ_select_view(d, session("jungle"), True, classify(flow(420)))
    assert out["queue"] == "Clasificatoria solo/dúo" and not out["blind"]
    assert ("PATCH", "/lol-champ-select/v1/session/my-selection") in lcu.calls


def test_a_ciegas_usa_tu_rol_principal_y_sin_riesgo_de_counter(champs, activo):
    d = Draft(FakeLCU(), champs, _engine(champs, [_game("utility")] * 5))
    out = d.tick(session("jungle"), False, pickable=set(), bannable=set(), queue=classify(flow(430)))
    assert out["blind"] and out["role"] == "utility"
    assert out["enemy_left_after"] == 0 and out["ban_suggestions"] == []


def test_personalizada_con_bans_se_trata_como_draft(champs, activo):
    s = session("")
    s["actions"].insert(0, [{"id": 9, "actorCellId": 7, "type": "ban", "completed": True, "championId": 0}])
    s["actions"].append([{"id": 10, "actorCellId": 6, "type": "pick", "completed": False, "championId": 0,
                          "isAllyAction": False, "isInProgress": False}])  # fmt: skip
    d = Draft(FakeLCU(), champs, _engine(champs, [_game("jungle")] * 5))
    out = d.tick(s, False, pickable=set(), bannable=set(), queue=classify(flow(-1, custom=True)))
    assert not out["blind"] and out["enemy_left_after"] == 1  # el rival que elige despues si te ve


def test_cola_desconocida_recomienda_como_en_la_grieta(champs, activo):
    d = Draft(FakeLCU(), champs, _engine(champs, [_game("jungle")] * 5))
    out = champ_select_view(d, session("top"), False, classify(None))
    assert out["role"] == "top" and not out["blind"]
