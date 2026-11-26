"""Ranked simulado de principio a fin: marcar y confirmar el pick como en el cliente real.

El cliente de mentira imita lo que hace el de verdad y los tests de una sola acción no cubrían:
- el `timer` de la sesión es una foto (`internalNowInEpochMs`): solo cambia cuando cambia la
  sesión. Si nadie toca nada al final de tu turno, sigue diciendo lo que quedaba al empezar;
- fuera de tu turno, marcar un pick cambia tu intención (`championPickIntent`), no la acción, y
  al empezar tu turno el cliente pasa tu intención a la acción;
- con tu ban en curso, marcar el pick no vale;
- en ranked el cliente espera al servidor: marcar puede tardar más que el tiempo de espera y
  aplicarse igual.
"""

import copy
import io
import json
import urllib.error

import pytest

from conftest import FakeLola, all_roles
from nachero.app.draft import Draft
from nachero.app.trace import KEEP, Trace
from nachero.clients.lcu import http_error_text
from nachero.config import CFG
from nachero.domain import cstimer
from nachero.domain.engine import Engine
from nachero.domain.player import Player
from test_roles_conexion import _game

ACTIONS = "/lol-champ-select/v1/session/actions/"
ROLES = ["top", "jungle", "middle", "bottom", "utility"]
ORDER = [[0], [5, 6], [1, 2], [7, 8], [3, 4], [9]]  # celdas que eligen en cada turno (1-2-2-2-2-1)
JUNGLE = {7: (54, 9000, 9, 90), 5: (53, 9000, 8, 60), 3: (56, 9000, 12, 50), 2: (55, 9000, 10, 40),
          1: (54, 9000, 7, 30), 8: (53.5, 9000, 6, 20)}  # fmt: skip
T0 = 1_700_000_000.0


class Ranked:
    """Champ select de soloq: tú eres la celda 1 (jungla), el segundo pick azul."""

    def __init__(self, me=1, sticky=False):
        self.now, self.me = T0, me  # reloj de este PC (s), el mismo para Nachero
        # sticky: la marca de la planificación queda también en la acción y fuera de tu turno solo
        # cambia tu intención (la otra forma posible de hacerlo del cliente)
        self.sticky = sticky
        self.patches: list = []
        self.slow = 0  # PATCH que el cliente aplica pero no responde a tiempo
        self.reject_lock = False  # el cliente no acepta confirmar con PATCH (sí con POST …/complete)
        self.last_error = None
        bans = [{"id": 100 + c, "actorCellId": c, "championId": 0, "completed": False, "isAllyAction": c < 5,
                 "isInProgress": False, "type": "ban"} for c in range(10)]  # fmt: skip
        reveal = [{"id": 200, "actorCellId": -1, "championId": 0, "completed": False, "isAllyAction": False,
                   "isInProgress": False, "type": "ten_bans_reveal"}]  # fmt: skip
        picks = [[{"id": 300 + c, "actorCellId": c, "championId": 0, "completed": False, "isAllyAction": c < 5,
                   "isInProgress": False, "type": "pick"} for c in grp] for grp in ORDER]  # fmt: skip
        self.s = {
            "localPlayerCellId": me,
            "myTeam": [
                {
                    "cellId": c,
                    "assignedPosition": ROLES[c],
                    "championId": 0,
                    "championPickIntent": 0,
                    "puuid": f"secreto-{c}",
                    "gameName": f"Jugador{c}",
                }
                for c in range(5)
            ],  # fmt: skip
            "theirTeam": [{"cellId": 5 + i, "championId": 0} for i in range(5)],
            "actions": [bans, reveal, *picks],
            "bans": {"myTeamBans": [], "theirTeamBans": []},
            "timer": {},
        }
        self.phase("PLANNING", 30)
        for a in bans:  # en la planificación el cliente ya da los bans como en curso
            a["isInProgress"] = True

    # ---------------------------------------------------------------- reloj (foto)
    def clock(self):
        return self.now

    def stamp(self, left_ms=None, total_ms=None):
        """La sesión cambia: foto nueva del reloj con lo que queda ahora."""
        t = self.s["timer"]
        if left_ms is None:
            left_ms = t["adjustedTimeLeftInPhase"] - (self.now * 1000 - t["internalNowInEpochMs"])
        t.update(adjustedTimeLeftInPhase=int(left_ms), internalNowInEpochMs=int(self.now * 1000))
        if total_ms is not None:
            t["totalTimeInPhase"] = int(total_ms)

    def phase(self, name, secs):
        self.s["timer"].update(phase=name, isInfinite=False)
        self.stamp(secs * 1000, secs * 1000)

    def wait(self, secs):
        self.now += secs  # nadie toca nada: la sesión (y su reloj) no cambia

    # ---------------------------------------------------------------- draft
    def action(self, aid):
        return next(a for grp in self.s["actions"] for a in grp if a["id"] == aid)

    def row(self, cell):
        return next(m for m in self.s["myTeam"] if m["cellId"] == cell)

    def to_bans(self):
        self.phase("BAN_PICK", 30)

    def end_bans(self, ally=(), enemy=()):
        for a in self.s["actions"][0]:
            a["isInProgress"], a["completed"] = False, True
        self.s["bans"] = {"myTeamBans": list(ally), "theirTeamBans": list(enemy)}
        self.stamp()

    def start_turn(self, k):
        """Empieza el turno de pick `k`: tu intención pasa a la acción (como el cliente)."""
        for i, grp in enumerate(self.s["actions"][2:]):
            for a in grp:
                a["isInProgress"] = i == k and not a["completed"]
                intent = self.row(a["actorCellId"]).get("championPickIntent") if a["isAllyAction"] else 0
                if a["isInProgress"] and intent:
                    a["championId"] = intent
        self.phase("BAN_PICK", 30)

    def lock(self, cell, cid):
        """Otro jugador confirma su campeón."""
        a = next(a for grp in self.s["actions"][2:] for a in grp if a["actorCellId"] == cell)
        a.update(championId=cid, completed=True, isInProgress=False)
        team = self.s["myTeam"] if cell < 5 else self.s["theirTeam"]
        m = next(m for m in team if m["cellId"] == cell)
        m.update(championId=cid, **({"championPickIntent": 0} if cell < 5 else {}))
        self.stamp()

    def intent(self, cell, cid):
        """Un aliado marca un campeón (su intención)."""
        self.row(cell)["championPickIntent"] = cid
        self.stamp()

    # ---------------------------------------------------------------- API local
    def get(self, path, timeout=None):
        return copy.deepcopy(self.s) if path == "/lol-champ-select/v1/session" else []

    def req(self, method, path, body=None, timeout=5):
        self.raw(method, path, body, timeout)

    def raw(self, method, path, body=None, timeout=5):
        if not path.startswith(ACTIONS):
            return b""
        if path.endswith("/complete"):  # POST …/complete: confirma lo que esté marcado
            a = self.action(int(path[len(ACTIONS) : -len("/complete")]))
            self.patches.append((a["id"], {"complete": True}))
            if not a["isInProgress"] or not a["championId"]:
                self.last_error = "HTTP 500: Invalid action"
                return None
            a.update(completed=True, isInProgress=False)
            self.row(self.me).update(championId=a["championId"], championPickIntent=0)
            self.stamp()
            return b""
        aid = int(path[len(ACTIONS) :])
        a = self.action(aid)
        self.patches.append((aid, dict(body)))
        if body.get("completed") and self.reject_lock:
            self.last_error = "HTTP 400: Invalid request"
            return None
        banning = any(b["isInProgress"] for b in self.s["actions"][0]) and self.s["timer"]["phase"] == "BAN_PICK"
        if a["completed"] or (a["type"] == "pick" and banning):
            self.last_error = "HTTP 500: Invalid action"
            return None
        if a["type"] == "pick" and not a["isInProgress"]:  # fuera de tu turno: tu intención
            if body.get("completed"):
                self.last_error = "HTTP 500: Action is not in progress"
                return None
            self.row(self.me)["championPickIntent"] = body["championId"]
            if self.sticky and self.s["timer"]["phase"] == "PLANNING":
                a["championId"] = body["championId"]
        else:
            a["championId"] = body["championId"]
            if body.get("completed"):
                a.update(completed=True, isInProgress=False)
                self.row(self.me).update(championId=body["championId"], championPickIntent=0)
        self.stamp()
        if self.slow:
            self.slow -= 1
            raise TimeoutError("timed out")  # lo ha aplicado, pero la respuesta no llega a tiempo
        return b""

    # ---------------------------------------------------------------- lo que ves en el cliente
    def mine(self):
        """Lo que tienes marcado: la acción o, si está vacía, tu intención."""
        a = self.action(300 + self.me)
        return a["championId"] or self.row(self.me)["championPickIntent"]

    def locked(self):
        return self.action(300 + self.me)["completed"]


def engine(champs, mu=None):
    cfg = {"pick_mode": "meta", "weights": {}, "main_role": "jungle"}
    return Engine(champs, FakeLola(all_roles(jungle=JUNGLE), matchups=mu or {}), Player([_game("jungle")] * 5, []), cfg)


@pytest.fixture
def auto(monkeypatch):
    """Modo Activo con marcar y confirmar pick a falta de 8 s; sin bans, hechizos ni runas."""
    for k, v in {"auto_hover_pick": True, "auto_lock_pick": True, "lock_when_seconds_left": 8, "auto_ban": False,
                 "auto_spells": False, "spells_by_role": {}, "import_runes": False,
                 "open_coachless_on_lock": False}.items():  # fmt: skip
        monkeypatch.setitem(CFG, k, v)


def draft(champs, lcu, mu=None):
    d = Draft(lcu, champs, engine(champs, mu))
    d.clock = lcu.clock
    return d


def tick(d, lcu):
    # como el bucle: la sesión y las listas de campeones se leen del cliente
    return d.tick(lcu.get("/lol-champ-select/v1/session"), True)


def mine_patches(lcu):
    return [b for aid, b in lcu.patches if aid == 300 + lcu.me]


# ------------------------------------------------------------------ draft completo
def test_sigue_la_recomendacion_fuera_de_turno_y_confirma_con_el_reloj_congelado(champs, auto):
    lcu = Ranked()
    d = draft(champs, lcu)
    b1 = tick(d, lcu)["hero"]["id"]
    assert lcu.mine() == b1 and mine_patches(lcu) == [{"championId": b1}]  # intención en la planificación

    lcu.to_bans()
    for _ in range(3):
        out = tick(d, lcu)
        lcu.wait(5)
    assert out["my_turn"] == "ban" and len(mine_patches(lcu)) == 1  # con tu ban en curso no se toca el pick

    lcu.end_bans(ally=[4], enemy=[10])
    lcu.start_turn(0)
    tick(d, lcu)
    lcu.lock(0, 6)
    lcu.start_turn(1)
    lcu.intent(2, b1)  # tu mid marca tu campeón: la recomendación cambia (sigue libre: no es «taken»)
    out = tick(d, lcu)
    b2 = out["hero"]["id"]
    assert b2 != b1 and lcu.mine() == b2 and mine_patches(lcu)[-1] == {"championId": b2}
    assert out["choose"] is None or out["choose"]["by"] != "player"
    lcu.lock(5, 11)
    lcu.lock(6, 4)
    tick(d, lcu)

    lcu.start_turn(2)  # tu turno: el cliente pasa tu intención a la acción
    out = tick(d, lcu)
    assert out["my_turn"] == "pick" and out["choose"]["marked"] == b2 and out["choose"]["by"] == "nachero"
    n = len(lcu.patches)
    for _ in range(4):  # 20 s sin que cambie nada: la sesión sigue diciendo 30 s
        lcu.wait(5)
        out = tick(d, lcu)
        assert not lcu.locked() and len(lcu.patches) == n
    assert out["timer_left"] == 10  # el panel cuenta de verdad
    assert out["choose"]["lock_in"] == 2  # «Nachero confirma lo marcado en 2 s»
    lcu.wait(2.5)  # quedan 7,5 s de verdad
    tick(d, lcu)
    assert lcu.locked() and mine_patches(lcu)[-1] == {"championId": b2, "completed": True}


def test_cliente_que_deja_la_marca_vieja_en_la_accion(champs, auto):
    """Si fuera de tu turno solo cambia tu intención y la acción guarda la marca de la
    planificación, manda la intención (lo que ven tus aliados) y no se repite el PATCH."""
    lcu = Ranked(sticky=True)
    d = draft(champs, lcu)
    b1 = tick(d, lcu)["hero"]["id"]
    lcu.to_bans()
    lcu.end_bans()
    lcu.start_turn(1)
    lcu.intent(2, b1)
    b2 = tick(d, lcu)["hero"]["id"]
    assert lcu.action(301)["championId"] == b1 and lcu.mine() == b1  # la acción, con la marca vieja
    assert lcu.row(1)["championPickIntent"] == b2
    for _ in range(3):
        out = tick(d, lcu)
    assert mine_patches(lcu) == [{"championId": b1}, {"championId": b2}] and out["choose"]["by"] == "nachero"
    lcu.start_turn(2)  # el cliente pasa tu intención a la acción
    tick(d, lcu)
    lcu.wait(23)
    tick(d, lcu)
    assert mine_patches(lcu)[-1] == {"championId": b2, "completed": True}


def test_en_tu_turno_cambia_la_marca_si_cambia_la_recomendacion(champs, auto):
    lcu = Ranked()
    d = draft(champs, lcu)
    b1 = tick(d, lcu)["hero"]["id"]
    lcu.to_bans()
    lcu.end_bans()
    lcu.start_turn(2)
    assert tick(d, lcu)["choose"]["marked"] == b1
    lcu.intent(2, b1)  # tu mid, que elige a la vez que tú, marca tu campeón
    out = tick(d, lcu)
    b2 = out["hero"]["id"]
    assert b2 != b1 and lcu.action(301)["championId"] == b2 and out["choose"]["by"] == "nachero"
    lcu.wait(25)
    tick(d, lcu)
    assert mine_patches(lcu)[-1] == {"championId": b2, "completed": True}


def test_marca_que_tarda_no_cuenta_como_del_jugador(champs, auto):
    lcu = Ranked()
    d = draft(champs, lcu)
    lcu.slow = 1  # el cliente aplica la marca, pero no responde a tiempo
    out = tick(d, lcu)  # sin excepción: la vuelta sigue
    b1 = out["hero"]["id"]
    assert lcu.mine() == b1 and out["choose"]["by"] != "player"
    out = tick(d, lcu)
    assert b1 not in d.choice.values()  # antes: «Has elegido» y Nachero ya no la cambiaba
    lcu.to_bans()
    lcu.end_bans()
    lcu.start_turn(1)
    lcu.intent(2, b1)
    b2 = tick(d, lcu)["hero"]["id"]
    assert lcu.mine() == b2
    lcu.start_turn(2)
    lcu.slow = 1
    lcu.wait(23)  # confirma, pero la respuesta no llega a tiempo
    tick(d, lcu)
    assert lcu.locked()
    tick(d, lcu)  # el siguiente tick ya lo trae confirmado: no lo repite
    assert sum(1 for b in mine_patches(lcu) if b.get("completed")) == 1


def test_el_jugador_cambia_fuera_de_turno_y_se_confirma_lo_suyo(champs, auto):
    lcu = Ranked()
    d = draft(champs, lcu)
    b1 = tick(d, lcu)["hero"]["id"]
    otro = next(c for c in JUNGLE if c != b1)
    lcu.row(1)["championPickIntent"] = otro  # lo cambia el jugador en el cliente
    lcu.stamp()
    lcu.to_bans()
    lcu.end_bans()
    lcu.start_turn(1)
    lcu.intent(2, otro)  # aunque la recomendación cambie, no se toca lo del jugador
    out = tick(d, lcu)
    assert out["choose"] is None or out["choose"]["by"] == "player"
    lcu.intent(2, 0)
    lcu.start_turn(2)
    out = tick(d, lcu)
    assert out["choose"] == {**out["choose"], "marked": otro, "by": "player"}
    lcu.wait(23)
    tick(d, lcu)
    assert mine_patches(lcu) == [{"championId": b1}, {"championId": otro, "completed": True}]


def test_si_el_cliente_rechaza_confirmar_con_patch_usa_complete(champs, auto):
    lcu = Ranked()
    lcu.reject_lock = True
    d = draft(champs, lcu)
    b1 = tick(d, lcu)["hero"]["id"]
    lcu.to_bans()
    lcu.end_bans()
    lcu.start_turn(2)
    tick(d, lcu)
    lcu.wait(23)
    tick(d, lcu)
    assert lcu.locked() and lcu.row(1)["championId"] == b1
    assert lcu.patches[-2:] == [(301, {"championId": b1, "completed": True}), (301, {"complete": True})]


def test_cliente_que_rechaza_marcar_lo_dice_con_su_motivo(champs, auto):
    lcu = Ranked()
    d = draft(champs, lcu)
    lcu.to_bans()
    lcu.end_bans()
    lcu.start_turn(2)
    real = lcu.raw

    def rechaza(method, path, body=None, timeout=5):
        lcu.patches.append((int(path[len(ACTIONS) :]), dict(body)))
        lcu.last_error = "HTTP 500: Champion not owned"
        return None

    lcu.raw = rechaza
    tick(d, lcu)
    assert d.last_error == "HTTP 500: Champion not owned"
    lcu.raw = real
    tick(d, lcu)  # se reintenta
    assert lcu.mine()


# ------------------------------------------------------------------ reloj
def test_reloj_descuenta_desde_la_foto():
    now = T0 * 1000
    foto = {"phase": "BAN_PICK", "adjustedTimeLeftInPhase": 30000, "internalNowInEpochMs": now - 25000,
            "totalTimeInPhase": 30000}  # fmt: skip
    assert cstimer.time_left(foto, now) == 5.0
    assert cstimer.time_left(foto, now + 6000) == 0.0  # se acabó el turno
    # sin marca de tiempo (o una que no cuadra con este PC): lo que ha pasado desde que se vio
    sin = {"adjustedTimeLeftInPhase": 30000}
    assert cstimer.time_left(sin, now, now - 4000) == 26.0
    rara = {**foto, "internalNowInEpochMs": now - 600_000}
    assert cstimer.time_left(rara, now, now - 4000) == 26.0
    # sin reloj, None (no se confirma a ciegas); infinito, lo que diga la foto
    assert cstimer.time_left({}, now) is None and cstimer.time_left({"adjustedTimeLeftInPhase": 0}, now) is None
    assert cstimer.time_left({**foto, "isInfinite": True}, now) == 30.0


def test_draft_recuerda_cuando_vio_cada_foto(champs, auto):
    lcu = Ranked()
    d = draft(champs, lcu)
    del lcu.s["timer"]["internalNowInEpochMs"]  # sin marca de tiempo: cuenta desde que la ve
    assert d.time_left(lcu.s["timer"]) == 30.0
    lcu.wait(12)
    assert d.time_left(lcu.s["timer"]) == 18.0
    lcu.s["timer"]["adjustedTimeLeftInPhase"] = 20000  # foto nueva
    assert d.time_left(lcu.s["timer"]) == 20.0


# ------------------------------------------------------------------ registro de diagnóstico
def test_registro_de_la_seleccion_sin_datos_de_jugadores(champs, auto, tmp_path):
    lcu = Ranked()
    d = draft(champs, lcu)
    d.trace = Trace(tmp_path, clock=lcu.clock)
    d.reset()
    for _ in range(3):
        tick(d, lcu)
    lcu.to_bans()
    tick(d, lcu)
    files = list(tmp_path.glob("*.jsonl"))
    assert len(files) == 1
    text = files[0].read_text(encoding="utf-8")
    assert "secreto" not in text and "Jugador" not in text  # ni puuid ni nombres
    lines = [json.loads(x) for x in text.splitlines()]
    kinds = [x["kind"] for x in lines]
    assert kinds.count("session") == 2  # solo cuando cambia (planificación y bans)
    assert {"timer", "pick", "patch"} <= set(kinds)
    patch = next(x for x in lines if x["kind"] == "patch")
    assert patch["ok"] is True and patch["body"]["championId"] and patch["aid"] == 301


def test_registro_guarda_las_ultimas_selecciones(tmp_path):
    for i in range(KEEP + 3):
        (tmp_path / f"2026-01-{i + 1:02d}_00-00-00.jsonl").write_text("{}\n")
    t = Trace(tmp_path, clock=lambda: T0)
    t.write("x", {"a": 1})
    assert len(list(tmp_path.glob("*.jsonl"))) == KEEP
    assert not (tmp_path / "2026-01-01_00-00-00.jsonl").exists()


def test_demo_no_deja_registro(champs, auto, tmp_path):
    lcu = Ranked()
    d = draft(champs, lcu)
    d.trace = Trace(tmp_path)
    d.tick(lcu.s, False, pickable=set(), bannable=set(), queue={"kind": "draft", "name": "Demo", "demo": True})
    assert not list(tmp_path.glob("*.jsonl"))


def test_motivo_del_error_del_cliente():
    body = io.BytesIO(json.dumps({"errorCode": "RPC_ERROR", "httpStatus": 500, "message": "Invalid action"}).encode())
    e = urllib.error.HTTPError("https://127.0.0.1/x", 500, "Internal", {}, body)  # type: ignore[arg-type]
    assert http_error_text(e) == "HTTP 500: Invalid action"
    e = urllib.error.HTTPError("https://127.0.0.1/x", 404, "Not Found", {}, io.BytesIO(b""))  # type: ignore[arg-type]
    assert http_error_text(e) == "HTTP 404"


def test_cronologia_legible_del_registro(champs, auto, tmp_path):
    """scripts/ver_seleccion.py: lo que pasó en la selección, a partir del registro de diagnóstico."""
    from nachero.app.trace import timeline

    lcu = Ranked()
    d = draft(champs, lcu)
    d.trace = Trace(tmp_path, clock=lcu.clock)
    d.reset()
    b1 = tick(d, lcu)["hero"]["id"]
    lcu.to_bans()
    lcu.end_bans()
    lcu.start_turn(2)
    tick(d, lcu)
    lcu.wait(23)
    tick(d, lcu)
    tick(d, lcu)  # la vuelta siguiente ya ve el pick confirmado
    lines = [json.loads(x) for x in next(tmp_path.glob("*.jsonl")).read_text(encoding="utf-8").splitlines()]
    text = "\n".join(timeline(lines, lambda c: f"C{c}"))
    assert "Fase PLANNING · quedan 30 s" in text and "Fase BAN_PICK" in text
    assert f"Marcar C{b1} → aceptado" in text and f"Confirmar C{b1} → aceptado" in text
    assert f"Nachero recomienda C{b1} · marcado C{b1} (de Nachero)" in text
    assert "Cliente: tu pick, confirmado" in text
    assert text.index("Fase PLANNING") < text.index("Cliente: tu pick, aún no es tu turno")
