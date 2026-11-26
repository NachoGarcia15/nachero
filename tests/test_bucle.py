"""Bucle principal: fallos que se repiten y el historial al acabar una partida, sin cliente."""

import threading

import pytest

from nachero.app import state, worker
from nachero.app.state import APP, Repeats
from nachero.config import CFG
from nachero.domain.player import Player


# ------------------------------------------------------------------ fallos repetidos
def test_un_fallo_que_se_repite_se_apunta_una_vez(monkeypatch):
    out, trazas = [], []
    monkeypatch.setattr(state, "log", lambda msg, kind="info": out.append((msg, kind)))
    monkeypatch.setattr(state.logger, "warning", lambda *a, **kw: trazas.append(kw.get("exc_info")))
    now = [1000.0]
    r = Repeats(every=60, clock=lambda: now[0])
    for _ in range(5):  # cada segundo, el mismo fallo
        r.report("Fallo puntual", KeyError("x"))
        now[0] += 1
    assert out == [("Fallo puntual (KeyError: 'x'); reintento.", "warn")]
    assert len(trazas) == 1 and trazas[0][0] is KeyError  # la traza, al archivo
    r.report("Fallo puntual", ValueError("y"))  # otro fallo: dice cuántas veces se repitió el anterior
    assert out[1:] == [
        ("El fallo anterior se ha repetido 4 veces más", "warn"),
        ("Fallo puntual (ValueError: y); reintento.", "warn"),
    ]
    now[0] += 61  # pasado un minuto, se vuelve a apuntar
    r.report("Fallo puntual", ValueError("y"))
    assert out[-1] == ("Fallo puntual (ValueError: y); reintento.", "warn") and len(out) == 4


# ------------------------------------------------------------------ historial al acabar la partida
class Cliente:
    def __init__(self, mastery=None, fail=None):
        self.mastery, self.fail, self.calls = mastery, fail, []

    def get(self, path, timeout=None):
        self.calls.append(path)
        if self.fail and self.fail in path:
            raise TimeoutError("timed out")
        return self.mastery if "champion-mastery" in path else None

    def req(self, method, path, body=None, timeout=None):
        return self.get(path, timeout)


class Motor:
    def __init__(self):
        self.player = Player([], [{"championId": 163, "championPoints": 420000}])


@pytest.fixture
def sin_disco(monkeypatch, home):
    partidas = [{"gameId": 1, "t": 0, "patch": "16.23", "champ": 163, "role": "jungle", "win": True, "k": 1,
                 "d": 1, "a": 1, "gpm": 400, "dpm": 600, "cspm": 6}]  # fmt: skip
    monkeypatch.setattr(worker, "load_history", lambda *a, **kw: partidas)
    monkeypatch.setattr(worker, "resolve_records", lambda games: 0)
    monkeypatch.setattr(worker, "enrich_records", lambda lcu, engine: 0)
    monkeypatch.setitem(APP, "history", None)
    monkeypatch.setitem(CFG, "history_queues", [420])
    monkeypatch.setitem(APP, "refresh_idle", False)
    return partidas


def test_actualiza_tu_modelo_y_conserva_la_maestria_si_el_cliente_no_la_da(sin_disco):
    eng = Motor()
    assert worker.refresh_history(Cliente(mastery=None), eng)
    assert eng.player.games == sin_disco and 163 in eng.player.mastery  # antes se perdía la maestría
    assert APP["history"]["games"] == 1 and APP["refresh_idle"] is True


def test_un_fallo_del_cliente_no_reinicia_la_sesion(sin_disco, monkeypatch):
    out = []
    monkeypatch.setattr(worker, "log_error", lambda msg, exc: out.append(msg))
    eng = Motor()
    old = eng.player
    assert worker.refresh_history(Cliente(fail="champion-mastery"), eng) is False  # antes: Restart
    assert eng.player is old and out and "historial" in out[0]
    assert not worker.HISTORY_BUSY.locked()


def test_una_sola_lectura_a_la_vez(sin_disco):
    worker.HISTORY_BUSY.acquire()
    try:
        assert worker.refresh_history(Cliente(), Motor()) is False
    finally:
        worker.HISTORY_BUSY.release()
    t = threading.Thread(target=worker.refresh_history, args=(Cliente(mastery=[]), Motor()))
    t.start()
    t.join(5)
    assert not worker.HISTORY_BUSY.locked()


# ------------------------------------------------------------------ historial roto
def test_historial_con_archivos_rotos_y_partidas_raras(tmp_path):
    import json

    from nachero.sources.history import load_history, valid_games

    buena = {"gameId": 1, "t": 5, "patch": "16.23", "champ": 163, "role": "jungle", "win": True, "k": 1, "d": 1,
             "a": 1, "gpm": 400, "dpm": 600, "cspm": 6}  # fmt: skip
    cache = tmp_path / "history_cache.json"
    cache.write_text(json.dumps([buena, {"gameId": 2}, "x", None]), encoding="utf-8")  # a medias y basura
    imp = tmp_path / "history_import.json"
    imp.write_text(json.dumps({"no": "es una lista"}), encoding="utf-8")

    def partida(gid, **cambios):
        g = {"gameId": gid, "queueId": 420, "gameDuration": 1800, "gameCreation": 10 + gid, "gameVersion": "16.23.1",
             "participants": [{"championId": 64, "spell1Id": 11, "spell2Id": 4, "timeline": {},
                               "stats": {"win": False, "kills": 3, "deaths": 2, "assists": 9, "goldEarned": 12000,
                                         "totalDamageDealtToChampions": 15000, "totalMinionsKilled": 40,
                                         "neutralMinionsKilled": 150}}]}  # fmt: skip
        g.update(cambios)
        return g

    class Cliente:
        def req(self, method, path, timeout=None):
            raras = [partida(4, participants=[]), partida(5, gameVersion=None), {"queueId": 420}]
            return {"games": {"games": [partida(3), *raras]}}

    games = load_history(Cliente(), str(cache), [420], lambda *a: None, str(imp))
    assert [g["gameId"] for g in games] == [3, 1]  # las raras no tumban la lectura del resto
    assert valid_games(json.loads(cache.read_text(encoding="utf-8"))) == games
    assert valid_games({"a": 1}) == [] and valid_games(None) == []


# ------------------------------------------------------------------ avisos desde la bandeja
def test_avisos_de_la_champ_select_uno_de_cada():
    seen = set()
    hero = {"name": "Taliyah", "est": 54.3}
    base = {"hero": hero, "my_turn": None, "ban_suggestions": [{"name": "Kayn"}], "locked": False}
    assert worker.turn_notice(base, seen) == ("Selección de campeón", "Nachero recomienda Taliyah · 54,3 % WR estimado")
    assert worker.turn_notice(base, seen) is None  # una vez
    assert worker.turn_notice({**base, "my_turn": "ban"}, seen) == ("Te toca banear", "Nachero recomienda banear Kayn")
    assert worker.turn_notice({**base, "my_turn": "ban"}, seen) is None
    assert worker.turn_notice({**base, "my_turn": "pick"}, seen)[0] == "Te toca elegir"
    assert worker.turn_notice({**base, "my_turn": "pick"}, seen) is None
    # si la app arranca ya en tu turno, el de tu turno sustituye al de inicio
    otra = set()
    assert worker.turn_notice({**base, "my_turn": "pick"}, otra)[0] == "Te toca elegir" and "start" in otra
    for d in (None, {"unsupported": True}, {**base, "hero": None}, {**base, "locked": True}):
        assert worker.turn_notice(d, set()) is None


def test_la_bandeja_avisa_solo_con_el_ajuste(monkeypatch):
    from nachero.app import main as M

    ctl = M.window_controls(hidden=True)
    got = []
    ctl["register_notify"](lambda title, text: got.append(title))
    try:
        state.OPTS["notify"]("Te toca elegir", "x")
        assert got == ["Te toca elegir"]
    finally:
        state.OPTS["notify"] = None
