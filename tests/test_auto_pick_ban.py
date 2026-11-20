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
        self.swallow = 0  # PATCH que el cliente acepta sin error pero no aplica

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
            if self.swallow:
                self.swallow -= 1
                return b""
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


def test_no_vuelve_a_marcar_si_cambia_la_recomendacion(champs, auto):
    lcu = Client(session())
    d = Draft(lcu, champs, engine(champs))
    best = tick(d, lcu)["hero"]["id"]
    lcu.s["myTeam"][1]["championPickIntent"] = best  # un aliado lo marca: cambia la recomendación
    out = tick(d, lcu)
    assert out["hero"]["id"] != best
    assert lcu.patches == [(1, {"championId": best})]  # ya marcó una vez: no lo vuelve a tocar


def test_cambio_del_jugador_que_llega_un_tick_tarde(champs, auto):
    lcu = Client(session())
    d = Draft(lcu, champs, engine(champs))
    best = tick(d, lcu)["hero"]["id"]
    otro = next(c for c in (1, 8, 2) if c != best)
    # el jugador marca otro, pero el cliente aún devuelve lo de Nachero y la recomendación cambia
    lcu.s["myTeam"][1]["championPickIntent"] = best
    tick(d, lcu)
    lcu.player_marks(1, otro)
    out = tick(d, lcu, left=3)
    assert lcu.patches == [(1, {"championId": best}), (1, {"championId": otro, "completed": True})]
    assert out["choose"]["by"] == "player"


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
def test_ban_solo_se_marca_y_nunca_se_confirma(champs, auto):
    lcu = Client(session(ban=True))
    d = Draft(lcu, champs, engine(champs))
    out = tick(d, lcu)
    ban = out["ban_suggestions"][0]["id"]
    assert (9, {"championId": ban}) in lcu.patches
    assert out["choose"]["kind"] == "ban" and out["choose"]["marked"] == ban
    assert out["status"][0] == {
        "kind": "turn_auto",
        "msg": f"Marcado {champs.name(ban)} · lo banea el cliente al acabar el tiempo",
    }
    for left in (6, 2, 1):
        tick(d, lcu, left=left)
    assert not any(b.get("completed") for _, b in lcu.patches)  # lo confirma el temporizador del cliente
    assert [p for p in lcu.patches if p[0] == 9] == [(9, {"championId": ban})]


def test_ban_cambiado_por_el_jugador_no_se_toca(champs, auto):
    lcu = Client(session(ban=True))
    d = Draft(lcu, champs, engine(champs))
    ban = tick(d, lcu)["ban_suggestions"][0]["id"]
    otro = next(c for c in (4, 10, 6) if c != ban)
    lcu.player_marks(9, otro)
    for left in (15, 4, 1):
        out = tick(d, lcu, left=left)
    assert out["choose"]["by"] == "player" and out["choose"]["marked"] == otro
    assert (
        out["status"][0]["msg"] == f"Has elegido banear {champs.name(otro)} · lo banea el cliente al acabar el tiempo"
    )
    assert [p for p in lcu.patches if p[0] == 9] == [(9, {"championId": ban})]


def test_ban_rechazado_se_reintenta(champs, auto):
    lcu = Client(session(ban=True))
    d = Draft(lcu, champs, engine(champs))
    ban = d.tick(lcu.s, True, pickable=set(), bannable=set())["ban_suggestions"][0]["id"]
    lcu.patches.clear()
    d.reset()
    lcu.action(9)["championId"] = 0
    lcu.reject = {ban}
    out = tick(d, lcu)
    assert not [p for p in lcu.patches if p[0] == 9]
    assert out["status"][0]["msg"].startswith("Te toca banear: ")
    lcu.reject = set()
    tick(d, lcu)
    assert (9, {"championId": ban}) in lcu.patches


def soloq(phase="BAN_PICK", me=3):
    """Champ select de soloq: los 10 banean a la vez (un grupo con 10 bans en curso), luego la
    revelación de bans y los picks 1-2-2-2-2-1."""
    ban_on = phase == "BAN_PICK"
    bans = [
        {"id": 100 + c, "actorCellId": c, "championId": 0, "completed": False, "isAllyAction": c < 5,
         "isInProgress": ban_on, "type": "ban"}
        for c in range(10)
    ]  # fmt: skip
    reveal = [{"id": 200, "actorCellId": -1, "championId": 0, "completed": False, "isAllyAction": False,
               "isInProgress": False, "type": "ten_bans_reveal"}]  # fmt: skip
    order = [[0], [5, 6], [1, 2], [7, 8], [3, 4], [9]]
    picks = [
        [{"id": 300 + c, "actorCellId": c, "championId": 0, "completed": False, "isAllyAction": c < 5,
          "isInProgress": False, "type": "pick"} for c in grp]
        for grp in order
    ]  # fmt: skip
    team = [{"cellId": c, "assignedPosition": "jungle" if c == me else "", "championId": 0,
             "championPickIntent": 0} for c in range(5)]  # fmt: skip
    return {
        "localPlayerCellId": me,
        "myTeam": team,
        "theirTeam": [{"cellId": 5 + i, "championId": 0} for i in range(5)],
        "actions": [bans, reveal, *picks],
        "bans": {"myTeamBans": [], "theirTeamBans": []},
        "timer": {"phase": phase, "adjustedTimeLeftInPhase": 25000},
    }


def test_soloq_diez_bans_a_la_vez(champs, auto):
    lcu = Client(soloq("PLANNING"))
    d = Draft(lcu, champs, engine(champs))
    out = tick(d, lcu)  # planificación: solo la intención de pick, nada de ban
    assert [p[0] for p in lcu.patches] == [303] and out["my_turn"] is None
    # empieza la fase de bans: los 10 en curso; dos aliados ya han marcado su ban
    lcu.s["timer"]["phase"] = "BAN_PICK"
    for a in lcu.s["actions"][0]:
        a["isInProgress"] = True
    out = tick(d, lcu)
    ally_hover = out["ban_suggestions"][0]["id"]
    lcu.action(101)["championId"] = ally_hover
    lcu.action(106)["championId"] = 4  # un rival: no cuenta
    out = tick(d, lcu)
    assert out["my_turn"] == "ban" and out["choose"]["kind"] == "ban"
    ban_patches = [p for p in lcu.patches if p[0] != 303]
    assert len(ban_patches) == 1 and ban_patches[0][0] == 103  # tu acción, no la de otro
    assert "completed" not in ban_patches[0][1]
    assert out["choose"]["marked"] == ban_patches[0][1]["championId"]


def test_planificacion_no_marca_el_ban_y_lo_marca_en_bans(champs, auto):
    """En PLANNING el cliente da el ban como «en curso» pero ignora lo que se marque en él."""
    s = soloq("PLANNING")
    for a in s["actions"][0]:
        a["isInProgress"] = True
    lcu = Client(s)
    d = Draft(lcu, champs, engine(champs))
    out = tick(d, lcu)
    assert not [p for p in lcu.patches if p[0] == 103]  # nada en el ban durante la planificación
    assert out["my_turn"] is None and out["choose"]["kind"] == "pick"
    assert d.choose("ban", 4) == (False, "Aún no te toca banear")
    lcu.s["timer"]["phase"] = "BAN_PICK"
    out = tick(d, lcu)
    ban = out["ban_suggestions"][0]["id"]
    assert [p for p in lcu.patches if p[0] == 103] == [(103, {"championId": ban})]
    assert lcu.action(103)["championId"] == ban and out["my_turn"] == "ban"


def test_marcado_que_el_cliente_no_aplica_se_reintenta(champs, auto):
    """El PATCH del ban no da error pero la acción sigue en 0: no cuenta como hecho."""
    lcu = Client(soloq())
    lcu.swallow = 1
    d = Draft(lcu, champs, engine(champs))
    out = tick(d, lcu)
    ban = out["ban_suggestions"][0]["id"]
    assert lcu.action(103)["championId"] == 0
    out = tick(d, lcu)
    assert lcu.action(103)["championId"] == ban
    assert out["choose"] == {**out["choose"], "marked": ban, "by": "nachero"}
    tick(d, lcu)
    assert len([p for p in lcu.patches if p[0] == 103]) == 2  # ya reflejado: no vuelve a marcar


def test_pick_que_el_cliente_no_aplica_se_reintenta(champs, auto):
    lcu = Client(session())
    lcu.swallow = 1
    d = Draft(lcu, champs, engine(champs))
    best = tick(d, lcu)["hero"]["id"]
    out = tick(d, lcu)
    assert lcu.patches == [(1, {"championId": best})] * 2 and out["choose"]["by"] == "nachero"


def test_soloq_no_repite_el_ban_de_un_aliado(champs, auto):
    lcu = Client(soloq())
    d0 = Draft(Client(soloq()), champs, engine(champs))
    first = d0.tick(soloq(), False, pickable=set(), bannable=set())["ban_suggestions"][0]["id"]
    lcu.action(101)["championId"] = first  # un aliado ya lo ha marcado
    out = tick(Draft(lcu, champs, engine(champs)), lcu)
    assert out["choose"]["marked"] and out["choose"]["marked"] != first
    assert all(b["id"] != first for b in out["ban_suggestions"])


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
