"""El bucle principal entero (`worker.run_session`) con un cliente de mentira: arranque, sala, champ
select (marca en modo Activo), partida y fin de partida. Sin red ni cliente: cualquier error de
cableado entre las piezas salta aquí y no en el PC del jugador."""

import copy
import threading
import time

import pytest

from conftest import CHAMPS, FakeLola, all_roles
from nachero.app import worker
from nachero.app.state import APP, OPTS
from nachero.config import CFG
from test_ranked_simulado import JUNGLE, Ranked


class Parar(BaseException):
    """Corta el bucle (BaseException: el bucle no la toma por un «Fallo puntual»)."""


class Lola(FakeLola):
    name, patch = "Lolalytics", "16.23"

    def __init__(self):
        super().__init__(all_roles(jungle=JUNGLE))
        self.pending: set = set()

    def refresh_tiers(self, patch, force=False, progress=None):
        return 5

    def roles_ready(self, patch):
        return 5

    def stats(self):
        return {"games": 1000, "builds": 0}

    def updated_at(self):
        return time.time()

    def runes(self, cid, role):
        return {}

    def build(self, cid, role):
        return {}


class Gol:
    loading: set = set()

    def dataset(self, name):
        return None

    def updated(self):
        return None


class Cliente:
    """La API local del cliente que usa el bucle, con una champ select de soloq (la de
    `test_ranked_simulado.Ranked`) y las fases que se le pasen."""

    def __init__(self, phases):
        self.phases, self.calls, self.patches = list(phases), [], []
        self.cs = Ranked()
        self.cs.to_bans()
        self.cs.end_bans()
        self.cs.start_turn(2)  # bans hechos y tu turno de pick

    def connect(self):
        return True

    def get(self, path, timeout=5):
        self.calls.append(path)
        if path == "/lol-gameflow/v1/gameflow-phase":
            return self.phases.pop(0) if len(self.phases) > 1 else self.phases[0]
        if path == "/lol-champ-select/v1/session":
            return copy.deepcopy(self.cs.s)
        if path == "/lol-gameflow/v1/session":
            return {"gameData": {"queue": {"id": 420, "gameMode": "CLASSIC", "type": "RANKED_SOLO_5x5", "mapId": 11},
                                 "teamOne": [{"championId": 7, "puuid": "yo"}], "teamTwo": [{"championId": 3}]},
                    "map": {"id": 11}}  # fmt: skip
        if path == "/lol-summoner/v1/current-summoner":
            return {"puuid": "yo", "gameName": "Jugador", "tagLine": "EUW"}
        if path == "/lol-ranked/v1/current-ranked-stats":
            return {"queues": [{"queueType": "RANKED_SOLO_5x5", "tier": "MASTER", "leaguePoints": 50, "wins": 10,
                                "losses": 8}]}  # fmt: skip
        if path == "/lol-patch/v1/game-version":
            return "16.23.123.4567"
        if path == "/lol-game-data/assets/v1/champion-summary.json":
            return [{"id": c, "name": v[0], "roles": v[7]} for c, v in CHAMPS.items()]
        if path.startswith("/lol-game-data/assets/v1/champions/"):
            cid = int(path.rsplit("/", 1)[1].split(".")[0])
            n, dmg, damage, dur, cc, mob, util, roles = CHAMPS.get(cid, ("?", "AD", 1, 1, 1, 1, 1, []))
            return {"tacticalInfo": {"damageType": {"AP": "kMagic"}.get(dmg, "kPhysical"), "difficulty": 2},
                    "playstyleInfo": {"damage": damage, "durability": dur, "crowdControl": cc, "mobility": mob,
                                      "utility": util}, "roles": roles}  # fmt: skip
        if path.endswith("champion-mastery"):
            return []
        return None

    def req(self, method, path, body=None, timeout=5):
        if method == "GET":
            return {"games": {"games": []}} if "match-history" in path else self.get(path, timeout)
        self.raw(method, path, body, timeout)
        return None

    def raw(self, method, path, body=None, timeout=5):
        self.calls.append(f"{method} {path}")
        if path.startswith("/lol-champ-select/v1/session/actions/"):
            self.patches.append(body)
            return self.cs.raw(method, path, body, timeout)
        return b""


@pytest.fixture
def bucle(monkeypatch, home):
    """run_session con el cliente de mentira: devuelve una función que lo corre `vueltas` veces."""
    for k, v in {"auto_hover_pick": True, "auto_lock_pick": False, "auto_accept": False, "auto_spells": False,
                 "import_runes": False, "open_coachless_on_lock": False, "history_queues": [420],
                 "main_role": "jungle", "pick_mode": "meta", "weights": {}, "spells_by_role": {}}.items():  # fmt: skip
        monkeypatch.setitem(CFG, k, v)
    monkeypatch.setitem(APP, "mode", "active")
    monkeypatch.setitem(OPTS, "demo", False)
    monkeypatch.setattr(worker, "find_client", lambda lcu, tries=3: True)
    monkeypatch.setattr(worker, "build_stats", lambda champs: Lola())
    monkeypatch.setattr(worker, "gol", lambda: Gol())
    log = []
    monkeypatch.setattr(worker, "log", lambda msg, kind="info": log.append((kind, msg)))

    def run(phases, vueltas):
        client = Cliente(phases)
        monkeypatch.setattr(worker, "LCU", lambda: client)
        n = [0]
        real_sleep = time.sleep

        def sleep(s):
            if threading.current_thread() is not threading.main_thread():
                return real_sleep(min(s, 0.01))
            n[0] += 1
            if n[0] >= vueltas:
                raise Parar()

        monkeypatch.setattr(worker.time, "sleep", sleep)
        with pytest.raises(Parar):
            worker.run_session()
        return client, log

    return run


def test_del_arranque_al_fin_de_partida(bucle):
    client, log = bucle(["Lobby", "ChampSelect", "ChampSelect", "InProgress", "EndOfGame", "Lobby"], 7)
    fallos = [m for k, m in log if "Fallo puntual" in m or "Reiniciando" in m]
    assert not fallos, fallos
    assert any("Listo" in m for _, m in log) and any("Fase: Selección de campeón" in m for _, m in log)
    assert client.patches and client.patches[0] == {"championId": client.cs.mine()}  # marcó tu pick
    assert APP["game"] is None or APP["game"].get("ally") is not None  # «En partida» calculada o vacía
    for _ in range(100):  # el historial del fin de partida va en segundo plano
        if not worker.HISTORY_BUSY.locked() and sum("match-history" in c for c in client.calls) >= 1:
            break
        threading.Event().wait(0.02)  # time.sleep está sustituido para cortar el bucle
    assert APP["rank"]["tier"] == "Master" and APP["profile"]["name"] == "Jugador#EUW"


def test_un_fallo_de_lectura_de_la_fase_no_reinicia_la_champ_select(bucle):
    """La fase vacía (None) cuenta como fallo de lectura: la champ select sigue y lo marcado también."""
    client, log = bucle(["ChampSelect", "ChampSelect", None, "ChampSelect", "ChampSelect"], 6)
    fases = [m for _, m in log if m.startswith("Fase: ")]
    assert fases == ["Fase: Selección de campeón"]  # sin pasar por «Sin cliente» ni volver a empezar
    assert any("no responde (NoPhase)" in m for _, m in log)
    assert len(client.patches) == 1  # la marca no se repite: el draft no se ha reiniciado
