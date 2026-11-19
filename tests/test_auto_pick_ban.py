"""Auto ban y auto pick que respetan la elección del jugador (issue #30)."""

import json

import pytest

from conftest import FakeLola, all_roles
from nachero.app import server
from nachero.app.draft import Draft
from nachero.app.state import APP, CTX, OPTS
from nachero.config import CFG
from nachero.domain.engine import Engine
from nachero.domain.player import Player
from test_roles_conexion import _game

ACTIONS = "/lol-champ-select/v1/session/actions/"


class Client:
    """Cliente de mentira con una champ select: aplica los PATCH de las acciones a la sesión."""

    def __init__(self, session, reject=()):
        self.s, self.reject, self.patches = session, set(reject), []

    def action(self, aid):
        return next(a for grp in self.s["actions"] for a in grp if a["id"] == aid)

    def get(self, path, timeout=None):
        return self.s if path == "/lol-champ-select/v1/session" else []

    def req(self, method, path, body=None):
        self.raw(method, path, body)

    def raw(self, method, path, body=None, timeout=5):
        if path.startswith(ACTIONS):
            aid = int(path[len(ACTIONS) :])
            if body.get("championId") in self.reject:
                return None  # el cliente no lo acepta (p. ej. no lo tienes)
            self.patches.append((aid, dict(body)))
            self.action(aid).update(body)
        return b""

    def player_marks(self, aid, cid):
        """El jugador marca otro campeón en el cliente."""
        self.action(aid)["championId"] = cid


def session(ban=False, left=20):
    me = {"cellId": 0, "assignedPosition": "jungle", "championId": 0, "championPickIntent": 0}
    allies = [{"cellId": i, "assignedPosition": "", "championId": 0, "championPickIntent": 0} for i in range(1, 5)]
    acts = []
    if ban:
        acts.append([{"id": 9, "actorCellId": 0, "championId": 0, "completed": False, "isAllyAction": True,
                      "isInProgress": True, "type": "ban"}])  # fmt: skip
    acts.append([{"id": 1, "actorCellId": 0, "championId": 0, "completed": False, "isAllyAction": True,
                  "isInProgress": not ban, "type": "pick"}])  # fmt: skip
    return {
        "localPlayerCellId": 0,
        "myTeam": [me, *allies],
        "theirTeam": [{"cellId": 5 + i, "championId": 0} for i in range(5)],
        "actions": acts,
        "bans": {"myTeamBans": [], "theirTeamBans": []},
        "timer": {"phase": "BAN_PICK", "adjustedTimeLeftInPhase": left * 1000},
    }


def engine(champs):
    jungle = {7: (54, 9000, 9, 90), 5: (53, 9000, 8, 60), 3: (56, 9000, 12, 50), 2: (55, 9000, 10, 40),
              1: (54, 9000, 7, 30), 8: (53.5, 9000, 6, 20)}  # fmt: skip
    cfg = {"pick_mode": "meta", "weights": {}, "main_role": "jungle"}
    return Engine(champs, FakeLola(all_roles(jungle=jungle)), Player([_game("jungle")] * 5, []), cfg)


@pytest.fixture
def auto(monkeypatch):
    """Activo con marcar y confirmar (pick y ban), a falta de 8 s; sin hechizos ni runas."""
    for k, v in {
        "auto_ban": True,
        "auto_hover_pick": True,
        "auto_lock_pick": True,
        "lock_when_seconds_left": 8,
        "auto_spells": False,
        "spells_by_role": {},
        "import_runes": False,
        "open_coachless_on_lock": False,
    }.items():
        monkeypatch.setitem(CFG, k, v)


def tick(d, lcu, left=None, acting=True):
    if left is not None:
        lcu.s["timer"]["adjustedTimeLeftInPhase"] = left * 1000
    return d.tick(lcu.s, acting, pickable=set(), bannable=set())


# ------------------------------------------------------------------ pick
def test_sin_cambio_marca_y_confirma_la_recomendacion_al_final(champs, auto):
    lcu = Client(session())
    d = Draft(lcu, champs, engine(champs))
    out = tick(d, lcu)
    best = out["hero"]["id"]
    assert lcu.patches == [(1, {"championId": best})]  # marca, pero no confirma con 20 s
    out = tick(d, lcu)
    assert len(lcu.patches) == 1  # no vuelve a marcar lo mismo
    assert out["choose"]["marked"] == best and out["choose"]["by"] == "nachero"
    assert out["status"][0] == {
        "kind": "turn_auto",
        "msg": f"Marcado {champs.name(best)} · se confirmará a falta de 8 s",
    }
    tick(d, lcu, left=8)
    assert lcu.patches[-1] == (1, {"championId": best, "completed": True})


def test_cambio_en_el_cliente_confirma_lo_del_jugador_y_no_vuelve_a_marcar(champs, auto):
    lcu = Client(session())
    d = Draft(lcu, champs, engine(champs))
    best = tick(d, lcu)["hero"]["id"]
    otro = next(c for c in (1, 8, 2) if c != best)
    lcu.player_marks(1, otro)
    for _ in range(3):
        out = tick(d, lcu)
    assert lcu.patches == [(1, {"championId": best})]  # no pisa la elección del jugador
    assert out["choose"] == {**out["choose"], "marked": otro, "by": "player"}
    assert out["status"][0]["msg"] == f"Has elegido {champs.name(otro)}: se confirmará {champs.name(otro)}"
    tick(d, lcu, left=5)
    assert lcu.patches[-1] == (1, {"championId": otro, "completed": True})


def test_marcado_previo_del_jugador_se_respeta(champs, auto):
    s = session()
    s["actions"][0][0]["championId"] = 8  # lo marcó antes de que Nachero viera la sesión
    lcu = Client(s)
    d = Draft(lcu, champs, engine(champs))
    out = tick(d, lcu)
    assert lcu.patches == [] and out["choose"]["by"] == "player"


def test_si_cambia_la_recomendacion_actualiza_su_marca(champs, auto):
    lcu = Client(session())
    d = Draft(lcu, champs, engine(champs))
    best = tick(d, lcu)["hero"]["id"]
    lcu.s["theirTeam"][0]["championId"] = best  # el rival se lo lleva
    out = tick(d, lcu)
    nuevo = out["hero"]["id"]
    assert nuevo != best and lcu.patches[-1] == (1, {"championId": nuevo})
    assert out["choose"]["by"] == "nachero"


def test_eleccion_del_jugador_que_se_lleva_otro_vuelve_a_la_recomendacion(champs, auto):
    lcu = Client(session())
    d = Draft(lcu, champs, engine(champs))
    best = tick(d, lcu)["hero"]["id"]
    otro = next(c for c in (1, 8, 2) if c != best)
    lcu.player_marks(1, otro)
    tick(d, lcu)
    lcu.s["theirTeam"][0]["championId"] = otro
    out = tick(d, lcu)
    assert lcu.patches[-1] == (1, {"championId": best}) and out["choose"]["by"] == "nachero"


def test_sin_marcar_confirma_la_recomendacion(champs, auto, monkeypatch):
    monkeypatch.setitem(CFG, "auto_hover_pick", False)
    lcu = Client(session())
    d = Draft(lcu, champs, engine(champs))
    out = tick(d, lcu)
    assert lcu.patches == [] and out["status"][0]["kind"] == "turn_auto"
    assert out["status"][0]["msg"].startswith("Te toca elegir: ")
    tick(d, lcu, left=3)
    assert lcu.patches == [(1, {"championId": out["hero"]["id"], "completed": True})]


def test_solo_marcar_no_confirma(champs, auto, monkeypatch):
    monkeypatch.setitem(CFG, "auto_lock_pick", False)
    lcu = Client(session())
    d = Draft(lcu, champs, engine(champs))
    out = tick(d, lcu, left=2)
    assert lcu.patches == [(1, {"championId": out["hero"]["id"]})]
    out = tick(d, lcu, left=1)
    assert out["status"][0] == {"kind": "turn", "msg": f"Marcado {out['hero']['name']}: confírmalo tú"}


def test_confirma_una_sola_vez(champs, auto):
    lcu = Client(session(left=3))
    d = Draft(lcu, champs, engine(champs))
    tick(d, lcu)
    lcu.action(1)["completed"] = False  # el cliente aún no lo refleja
    tick(d, lcu)
    assert sum(1 for _, b in lcu.patches if b.get("completed")) == 1


def test_observar_no_toca_el_cliente(champs, auto):
    lcu = Client(session(ban=True, left=2))
    d = Draft(lcu, champs, engine(champs))
    out = tick(d, lcu, acting=False)
    assert lcu.patches == [] and out["choose"]["enabled"] is False


# ------------------------------------------------------------------ ban
def test_ban_se_marca_y_no_se_confirma_enseguida(champs, auto):
    lcu = Client(session(ban=True))
    d = Draft(lcu, champs, engine(champs))
    out = tick(d, lcu)
    ban = out["ban_suggestions"][0]["id"]
    assert (9, {"championId": ban}) in lcu.patches
    assert not any(b.get("completed") for _, b in lcu.patches)  # nada de banear a los 1,5–3 s
    assert out["choose"]["kind"] == "ban" and out["choose"]["marked"] == ban
    assert out["status"][0] == {
        "kind": "turn_auto",
        "msg": f"Ban marcado {champs.name(ban)} · se confirmará a falta de 8 s",
    }
    tick(d, lcu, left=6)
    assert lcu.patches[-1] == (9, {"championId": ban, "completed": True})


def test_ban_cambiado_por_el_jugador(champs, auto):
    lcu = Client(session(ban=True))
    d = Draft(lcu, champs, engine(champs))
    ban = tick(d, lcu)["ban_suggestions"][0]["id"]
    otro = next(c for c in (4, 10, 6) if c != ban)
    lcu.player_marks(9, otro)
    out = tick(d, lcu)
    assert out["choose"]["by"] == "player"
    assert out["status"][0]["msg"] == f"Has elegido banear {champs.name(otro)}: se confirmará {champs.name(otro)}"
    tick(d, lcu, left=4)
    assert lcu.patches[-1] == (9, {"championId": otro, "completed": True})


def test_sin_auto_ban_no_toca_el_ban(champs, auto, monkeypatch):
    monkeypatch.setitem(CFG, "auto_ban", False)
    lcu = Client(session(ban=True, left=2))
    d = Draft(lcu, champs, engine(champs))
    out = tick(d, lcu)
    assert not [p for p in lcu.patches if p[0] == 9]
    assert out["status"][0]["msg"].startswith("Te toca banear: ")


# ------------------------------------------------------------------ elegir desde el panel
def test_clic_en_el_panel_marca_y_cuenta_como_eleccion(champs, auto):
    lcu = Client(session())
    d = Draft(lcu, champs, engine(champs))
    out = tick(d, lcu)
    otro = out["choose"]["options"][2]["id"]
    assert d.choose("pick", otro) == (True, champs.name(otro))
    out = tick(d, lcu)
    assert out["choose"]["marked"] == otro and out["choose"]["by"] == "player"
    assert lcu.patches[-1] == (1, {"championId": otro})
    tick(d, lcu, left=2)
    assert lcu.patches[-1] == (1, {"championId": otro, "completed": True})


def test_clic_que_el_cliente_rechaza(champs, auto):
    lcu = Client(session(), reject={8})
    d = Draft(lcu, champs, engine(champs))
    tick(d, lcu)
    ok, msg = d.choose("pick", 8)
    assert not ok and "no deja" in msg
    assert tick(d, lcu)["choose"]["by"] == "nachero"


def test_clic_sin_turno_pendiente(champs, auto):
    s = session(ban=True)
    s["actions"][0][0]["isInProgress"] = False  # el ban aún no es tuyo
    lcu = Client(s)
    assert Draft(lcu, champs, engine(champs)).choose("ban", 3) == (False, "Aún no te toca banear")
    lcu.action(1)["completed"] = True
    assert Draft(lcu, champs, engine(champs)).choose("pick", 3) == (False, "Ya no tienes ese turno pendiente")
    assert Draft(Client(None), champs, engine(champs)).choose("pick", 3)[0] is False


@pytest.fixture
def panel(champs, auto, monkeypatch):
    lcu = Client(session())
    d = Draft(lcu, champs, engine(champs))
    tick(d, lcu)
    monkeypatch.setitem(CTX, "draft", d)
    monkeypatch.setitem(CTX, "champs", champs)
    monkeypatch.setitem(APP, "mode", "active")
    monkeypatch.setitem(APP, "phase", "ChampSelect")
    monkeypatch.setitem(OPTS, "demo", False)
    return lcu


@pytest.mark.parametrize(
    ("body", "mode", "code"),
    [
        ({"kind": "pick", "id": 8}, "active", 200),
        ({"kind": "pick", "id": 8}, "observe", 409),
        ({"kind": "lock", "id": 8}, "active", 400),
        ({"kind": "pick", "id": 999}, "active", 400),
        ({"kind": "pick", "id": "8"}, "active", 400),
    ],
)
def test_api_elegir(panel, monkeypatch, body, mode, code):
    monkeypatch.setitem(APP, "mode", mode)
    got, out = server.choose_request(body)
    assert got == code, out
    if code == 200:
        assert panel.patches[-1] == (1, {"championId": 8})
    else:
        assert "error" in out and json.dumps(out)


def test_sin_reloj_no_confirma(champs, auto):
    s = session()
    s["timer"] = {}
    lcu = Client(s)
    tick(Draft(lcu, champs, engine(champs)), lcu)
    assert not any(b.get("completed") for _, b in lcu.patches)
