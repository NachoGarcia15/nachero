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
