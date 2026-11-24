"""Auto ban y auto pick que respetan la elección del jugador (issue #30)."""

import copy
import json
import threading
import time

import pytest

from conftest import CHAMPS, FakeLola, all_roles
from nachero.app import server
from nachero.app.draft import Draft
from nachero.app.state import APP, CTX, OPTS
from nachero.config import CFG
from nachero.domain.engine import Engine
from nachero.domain.player import Player
from nachero.sources.champions import Champs
from nachero.sources.lolalytics import Lolalytics
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


JUNGLE = {7: (54, 9000, 9, 90), 5: (53, 9000, 8, 60), 3: (56, 9000, 12, 50), 2: (55, 9000, 10, 40),
          1: (54, 9000, 7, 30), 8: (53.5, 9000, 6, 20)}  # fmt: skip


def engine(champs):
    cfg = {"pick_mode": "meta", "weights": {}, "main_role": "jungle"}
    return Engine(champs, FakeLola(all_roles(jungle=JUNGLE)), Player([_game("jungle")] * 5, []), cfg)


@pytest.fixture
def auto(monkeypatch):
    """Activo con marcar y confirmar (pick y ban), a falta de 8 s; sin hechizos ni runas."""
    for k, v in {
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


def test_sigue_la_recomendacion_si_cambia(champs, auto):
    lcu = Client(session())
    d = Draft(lcu, champs, engine(champs))
    best = tick(d, lcu)["hero"]["id"]
    lcu.s["myTeam"][1]["championPickIntent"] = best  # un aliado lo marca: cambia la recomendación
    out = tick(d, lcu)
    nuevo = out["hero"]["id"]
    assert nuevo != best and lcu.patches == [(1, {"championId": best}), (1, {"championId": nuevo})]
    assert out["choose"] == {**out["choose"], "marked": nuevo, "by": "nachero"}
    tick(d, lcu)
    assert len(lcu.patches) == 2  # no vuelve a marcar lo mismo
    tick(d, lcu, left=3)
    assert lcu.patches[-1] == (1, {"championId": nuevo, "completed": True})


def test_marca_anterior_que_el_cliente_devuelve_tarde_no_es_del_jugador(champs, auto):
    lcu = Client(session())
    d = Draft(lcu, champs, engine(champs))
    best = tick(d, lcu)["hero"]["id"]
    lcu.s["myTeam"][1]["championPickIntent"] = best
    vieja = copy.deepcopy(lcu.s)  # aún con la marca anterior de Nachero
    nuevo = tick(d, lcu)["hero"]["id"]
    out = d.tick(vieja, True, pickable=set(), bannable=set())
    assert out["choose"]["by"] != "player" and nuevo not in d.choice.values()
    assert len(lcu.patches) == 2  # el cliente ya lo muestra: no repite el PATCH
    lcu.s["myTeam"][1]["championPickIntent"] = 0  # vuelve a ser la mejor: la vuelve a marcar
    out = tick(d, lcu)
    assert lcu.patches[-1] == (1, {"championId": best}) and out["choose"]["by"] == "nachero"


def test_el_jugador_puede_volver_a_una_marca_anterior_de_nachero(champs, auto):
    lcu = Client(session())
    d = Draft(lcu, champs, engine(champs))
    best = tick(d, lcu)["hero"]["id"]
    lcu.s["myTeam"][1]["championPickIntent"] = best  # un aliado lo marca: Nachero marca la segunda
    segunda = tick(d, lcu)["hero"]["id"]
    lcu.s["myTeam"][1]["championPickIntent"] = segunda  # el aliado cambia: Nachero vuelve a la primera
    tick(d, lcu)
    tick(d, lcu)  # el cliente ya muestra la nueva marca
    assert lcu.patches == [(1, {"championId": c}) for c in (best, segunda, best)]
    lcu.s["myTeam"][1]["championPickIntent"] = 0
    lcu.player_marks(1, segunda)  # el jugador marca a mano lo que Nachero marcó antes
    out = tick(d, lcu)
    assert out["hero"]["id"] == best  # hay otra mejor, pero no pisa al jugador
    assert len(lcu.patches) == 3 and out["choose"] == {**out["choose"], "marked": segunda, "by": "player"}


def test_cambio_del_jugador_que_llega_un_tick_tarde(champs, auto):
    lcu = Client(session())
    d = Draft(lcu, champs, engine(champs))
    best = tick(d, lcu)["hero"]["id"]
    # el jugador marca otro, pero la sesión del tick aún trae lo de Nachero y la recomendación cambia
    lcu.s["myTeam"][1]["championPickIntent"] = best
    vieja = copy.deepcopy(lcu.s)
    otro = next(c for c in (1, 8, 2) if c != best)
    lcu.player_marks(1, otro)
    out = d.tick(vieja, True, pickable=set(), bannable=set())
    assert lcu.patches == [(1, {"championId": best})]  # no pisa al jugador
    assert out["choose"] == {**out["choose"], "marked": otro, "by": "player"}
    for _ in range(2):
        out = tick(d, lcu)
    tick(d, lcu, left=3)
    assert lcu.patches == [(1, {"championId": best}), (1, {"championId": otro, "completed": True})]


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
    lcu = Client(session(left=2))
    d = Draft(lcu, champs, engine(champs))
    out = tick(d, lcu, acting=False)
    assert lcu.patches == [] and out["choose"]["enabled"] is False


# ------------------------------------------------------------------ ban: solo se recomienda
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


BAN_IDS = {9, *range(100, 110)}


def ban_lcu(phase="PLANNING"):
    """Cliente con los datos reales: bannable [-1] en BAN_PICK, 174 ids en planificación."""
    lcu = Client(soloq(phase))
    reales = list(CHAMPS)

    def get(path, timeout=None):
        if path.endswith("bannable-champion-ids"):
            return reales if lcu.s["timer"]["phase"] == "PLANNING" else [-1]
        if path.endswith("pickable-champion-ids"):
            return reales
        return Client.get(lcu, path, timeout)

    lcu.get = get
    return lcu


def to_bans(lcu):
    lcu.s["timer"]["phase"] = "BAN_PICK"
    for a in lcu.s["actions"][0]:
        a["isInProgress"] = True


def ban_patches(lcu):
    return [p for p in lcu.patches if p[0] in BAN_IDS]


def test_auto_ban_marca_en_bans_sin_confirmar(champs, auto, monkeypatch):
    monkeypatch.setitem(CFG, "auto_ban", True)
    lcu = ban_lcu()
    d = Draft(lcu, champs, engine(champs))
    for a in lcu.s["actions"][0]:
        a["isInProgress"] = True  # en planificación el cliente ya los da en curso
    d.tick(lcu.s, True)
    assert ban_patches(lcu) == []  # nada en PLANNING
    to_bans(lcu)
    lcu.swallow = 1  # el primer PATCH no se aplica: se reintenta
    out = d.tick(lcu.s, True)
    ban = out["ban_suggestions"][0]["id"]
    assert lcu.action(103)["championId"] == 0
    d.tick(lcu.s, True)
    assert ban_patches(lcu) == [(103, {"championId": ban})] * 2  # sin completed
    out = d.tick(lcu.s, True)  # el cliente ya lo muestra
    assert out["status"][0] == {
        "kind": "turn_auto",
        "msg": f"Ban marcado: {champs.name(ban)} · lo banea el cliente al acabar el tiempo",
    }
    assert out["choose"] == {**out["choose"], "kind": "ban", "marked": ban, "by": "nachero"}
    for _ in range(2):
        d.tick(lcu.s, True)
    assert len(ban_patches(lcu)) == 2


def test_auto_ban_no_pisa_al_jugador(champs, auto, monkeypatch):
    monkeypatch.setitem(CFG, "auto_ban", True)
    lcu = ban_lcu("BAN_PICK")
    to_bans(lcu)
    d = Draft(lcu, champs, engine(champs))
    ban = d.tick(lcu.s, True)["ban_suggestions"][0]["id"]
    otro = next(c for c in CHAMPS if c != ban)
    lcu.player_marks(103, otro)
    for _ in range(3):
        out = d.tick(lcu.s, True)
    assert ban_patches(lcu) == [(103, {"championId": ban})]
    assert out["status"][0]["msg"] == f"Has elegido banear {champs.name(otro)}"
    # desde el panel también cuenta como elección del jugador
    assert d.choose("ban", ban) == (True, champs.name(ban))
    out = d.tick(lcu.s, True)
    assert out["choose"]["by"] == "player" and ban_patches(lcu)[-1] == (103, {"championId": ban})


def test_auto_ban_no_marca_lo_de_un_aliado(champs, auto, monkeypatch):
    monkeypatch.setitem(CFG, "auto_ban", True)
    lcu = ban_lcu("BAN_PICK")
    to_bans(lcu)
    first = Draft(ban_lcu("BAN_PICK"), champs, engine(champs)).tick(soloq(), False)["ban_suggestions"][0]["id"]
    lcu.action(101)["championId"] = first  # un aliado ya lo ha marcado
    Draft(lcu, champs, engine(champs)).tick(lcu.s, True)
    assert ban_patches(lcu) and all(b["championId"] != first for a, b in ban_patches(lcu) if a == 103)


@pytest.mark.parametrize("acting", [True, False])
def test_sin_auto_ban_no_hay_patch_de_ban(champs, auto, monkeypatch, acting):
    monkeypatch.setitem(CFG, "auto_ban", acting is False)  # observar con el ajuste activo tampoco
    lcu = ban_lcu("BAN_PICK")
    to_bans(lcu)
    d = Draft(lcu, champs, engine(champs))
    for _ in range(3):
        out = d.tick(lcu.s, acting)
    assert ban_patches(lcu) == []
    b = out["ban_suggestions"][0]
    assert out["status"][0]["msg"].startswith(f"Te toca banear: {b['name']} · ")


def ban_engine(champs, mu=None, top=None):
    cfg = {"pick_mode": "meta", "weights": {}, "main_role": "jungle"}
    lola = FakeLola(all_roles(jungle=JUNGLE, top=top or {}), matchups=mu or {})
    return Engine(champs, lola, Player([_game("jungle")] * 5, []), cfg)


def bans_for(champs, s, mu=None, top=None):
    lcu = Client(s)
    return tick(Draft(lcu, champs, ban_engine(champs, mu, top)), lcu, acting=False)


def test_ban_segun_tu_pick_y_tus_aliados(champs, auto):
    # eliges el primero (B1): tu rival de línea elige después seguro, así que se protege tu pick
    base = bans_for(champs, soloq(me=0))
    best = base["hero"]["id"]
    ids = [b["id"] for b in base["ban_suggestions"]]
    # el que menos se recomendaba banear de la jungla pasa a ser el primero si countea a tu pick
    rival = next(c for c in reversed(list(JUNGLE)) if c != best and c not in [p["id"] for p in base["picks"][:2]])
    # su tabla de matchups: el counter entre muchos neutros (como una página real)
    mu = {(best, "jungle"): {"jungle": {rival: -12, **{200 + i: 0.0 for i in range(20)}}}}
    first = soloq(me=0)
    first["myTeam"][0]["championPickIntent"] = best  # lo tienes marcado: es tu pick
    out = bans_for(champs, first, mu=mu)
    assert out["ban_suggestions"][0]["id"] == rival != (ids[0] if ids else None)
    assert out["ban_suggestions"][0]["reasons"][0] == f"countea a {champs.name(best)} (tu pick)"
    assert out["status"][0]["msg"] == (
        f"Te toca banear: {champs.name(rival)} · countea a {champs.name(best)} (tu pick)"
    )
    assert out["ban_context"].startswith("eliges antes que tu rival (100 %)")
    # eliges 4.º (solo queda un pick rival después): el mismo counter pesa poco, se banea por fuerza
    late_s = soloq(me=3)
    late_s["myTeam"][3]["championPickIntent"] = best
    late = bans_for(champs, late_s, mu=mu)
    assert late["ban_suggestions"][0]["id"] != rival
    assert "20 %" in late["ban_context"]
    # un aliado top ya ha elegido a Marksman (4): se recomienda banear a quien le countea en top,
    # aunque sea flojo en el parche y no salga sin ese pick
    top = {10: (49, 9000, 5, 90)}
    s = soloq()
    s["myTeam"][0].update(assignedPosition="top", championId=4)
    sin = bans_for(champs, s, top=top)
    con = bans_for(champs, s, mu={(4, "top"): {"top": {10: -5}}}, top=top)
    assert 10 not in [b["id"] for b in sin["ban_suggestions"]]
    shooter = next(b for b in con["ban_suggestions"] if b["id"] == 10)
    assert shooter["reasons"][0] == f"countea a {champs.name(4)}"


def test_ban_no_repite_lo_que_marcan_o_eligen_los_aliados(champs, auto):
    first = bans_for(champs, soloq())["ban_suggestions"][0]["id"]
    s = soloq()
    s["actions"][0][1]["championId"] = first  # un aliado ya lo ha marcado como ban
    assert first not in [b["id"] for b in bans_for(champs, s)["ban_suggestions"]]


def test_pick_que_el_cliente_no_aplica_se_reintenta(champs, auto):
    lcu = Client(session())
    lcu.swallow = 1
    d = Draft(lcu, champs, engine(champs))
    best = tick(d, lcu)["hero"]["id"]
    out = tick(d, lcu)
    assert lcu.patches == [(1, {"championId": best})] * 2 and out["choose"]["by"] == "nachero"


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
    assert Draft(lcu, champs, engine(champs)).choose("ban", 3)[0] is False
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


# ------------------------------------------------------------------ el bucle no espera a la red
class SlowClient(Client):
    """Cliente cuyas fichas de campeón tardan; apunta en qué hilo se pide cada una."""

    def __init__(self, session, data, delay=0.3):
        super().__init__(session)
        self.data, self.delay, self.calls = data, delay, []

    def get(self, path, timeout=None):
        if path == "/lol-game-data/assets/v1/champion-summary.json":
            return [{"id": c, "name": v[0], "roles": v[7]} for c, v in self.data.items()]
        if path.startswith("/lol-game-data/assets/v1/champions/"):
            self.calls.append(threading.current_thread())
            time.sleep(self.delay)
            cid = int(path.rsplit("/", 1)[1].split(".")[0])
            n, dmg, damage, dur, cc, mob, util, roles = self.data[cid]
            return {
                "tacticalInfo": {"damageType": {"AP": "kMagic", "AD": "kPhysical"}[dmg], "difficulty": 2},
                "playstyleInfo": {"damage": damage, "durability": dur, "crowdControl": cc, "mobility": mob,
                                  "utility": util},
                "roles": roles,
            }  # fmt: skip
        return super().get(path, timeout)


def slow_lola(tmp_path, delay=0.3):
    """Lolalytics de verdad (caché en disco) con las tier lists ya guardadas y una red lenta."""
    lola = Lolalytics(str(tmp_path), lambda *a: None)
    fake = FakeLola(all_roles(jungle=JUNGLE))
    lola.patch = "16.23"
    for role in ("top", "jungle", "middle", "bottom", "utility"):
        lola.cache["tiers"][role] = {"t": time.time(), "patch": "16.23", **fake.tier(role)}
    lola.net = []

    def fetch(url):
        lola.net.append(threading.current_thread())
        time.sleep(delay)
        raise OSError("sin red en los tests")

    lola._fetch = fetch
    return lola


def test_tick_no_espera_a_la_red(auto, tmp_path):
    lcu = SlowClient(session(ban=True), CHAMPS)
    champs = Champs(lcu)
    champs.preload()
    lola = slow_lola(tmp_path)
    eng = Engine(champs, lola, Player([_game("jungle")] * 5, []), {"pick_mode": "meta", "weights": {}})
    d = Draft(lcu, champs, eng)
    t = time.time()
    out = tick(d, lcu)
    assert time.time() - t < 1.0  # sin fichas ni matchups: recomienda con lo que hay
    main = threading.current_thread()
    assert main not in lcu.calls and main not in lola.net  # nada de red en el hilo del bucle
    assert out["ban_suggestions"] and out["my_turn"] == "ban"  # recomienda el ban sin esperar a los matchups
    assert not [p for p in lcu.patches if p[0] == 9]
    assert {"picks y bans", "marcar", "runas"} <= set(d.timings)  # para el aviso de selección lenta


def test_catalogo_de_runas_en_segundo_plano():
    from nachero.app.runes import RuneImporter

    class SlowCatalog:
        def __init__(self):
            self.calls = []

        def get(self, path, timeout=None):
            self.calls.append(threading.current_thread())
            time.sleep(0.3)
            return {"styles": []} if path.endswith("perkstyles.json") else []

    cat = SlowCatalog()
    runes = RuneImporter(cat)
    runes.preload()
    t = time.time()
    assert runes.describe({"primary": [8112], "secondary": [8139]}) is None  # aún llegando: no espera
    assert time.time() - t < 0.1 and threading.current_thread() not in cat.calls


def test_intencion_del_jugador_en_planificacion_es_su_eleccion(champs, auto, monkeypatch):
    """El jugador marca un campeón en la planificación: sale en su intención, no en la acción."""
    monkeypatch.setitem(CFG, "auto_lock_pick", False)
    s = session()
    s["myTeam"][0]["championPickIntent"] = 8
    lcu = Client(s)
    d = Draft(lcu, champs, engine(champs))
    out = tick(d, lcu)
    assert lcu.patches == [] and out["choose"]["by"] == "player"
    assert out["status"][0] == {"kind": "turn", "msg": f"Has elegido {champs.name(8)}: confírmalo tú"}


def test_sesion_atrasada_no_pisa_lo_que_acaba_de_marcar_el_jugador(champs, auto):
    lcu = Client(session())
    d = Draft(lcu, champs, engine(champs))
    vieja = copy.deepcopy(lcu.s)  # el tick trabaja con una sesión de hace un rato
    lcu.player_marks(1, 8)
    out = d.tick(vieja, True, pickable=set(), bannable=set())
    assert lcu.patches == [] and out["choose"]["by"] == "player" and out["choose"]["marked"] == 8


def test_bannable_menos_uno_en_bans(champs, auto):
    """Captura real: en BAN_PICK el cliente devuelve bannable = [-1]; antes dejaba fuera todos los bans."""
    s = soloq("PLANNING")
    lcu = Client(s)
    reales = list(CHAMPS)

    def get(path, timeout=None):
        if path.endswith("bannable-champion-ids"):
            return reales if lcu.s["timer"]["phase"] == "PLANNING" else [-1]
        if path.endswith("pickable-champion-ids"):
            return reales
        return Client.get(lcu, path, timeout)

    lcu.get = get
    d = Draft(lcu, champs, engine(champs))
    antes = d.tick(lcu.s, True)["ban_suggestions"]
    lcu.s["timer"]["phase"] = "BAN_PICK"
    for a in lcu.s["actions"][0]:
        a["isInProgress"] = True
    out = d.tick(lcu.s, True)
    assert out["my_turn"] == "ban" and out["ban_suggestions"] == antes != []
    assert out["status"][0]["msg"].startswith(f"Te toca banear: {antes[0]['name']} · ")
    # sin lista válida previa (Nachero abierto ya en BAN_PICK): no se filtra
    d2 = Draft(lcu, champs, engine(champs))
    assert d2.tick(lcu.s, True)["ban_suggestions"]
    assert d2.valid_ids("bannable", [-1, 0, True, "7"]) == set()


def test_turno_de_ban_pone_el_ban_en_primer_plano(champs, auto):
    lcu = ban_lcu()
    d = Draft(lcu, champs, engine(champs))
    out = d.tick(lcu.s, True)
    assert out["focus"] == "pick" and out["choose"]["kind"] == "pick"  # planificación: como siempre
    to_bans(lcu)
    out = d.tick(lcu.s, True)
    assert out["focus"] == "ban" and out["choose"]["kind"] == "ban"
    assert [o["id"] for o in out["choose"]["options"]] == [b["id"] for b in out["ban_suggestions"]][:5]
    assert out["hero"]  # el pick recomendado sigue en la vista, en segundo plano
    # acaba tu ban y llega tu pick: vuelve el pick
    lcu.action(103).update(completed=True, isInProgress=False, championId=out["ban_suggestions"][0]["id"])
    lcu.action(303)["isInProgress"] = True
    out = d.tick(lcu.s, True)
    assert out["focus"] == "pick" and out["choose"]["kind"] == "pick" and out["my_turn"] == "pick"
