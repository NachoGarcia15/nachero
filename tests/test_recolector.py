"""Recolector de partidas con la API de Riot (issue #19): cliente, límites, agregación y pasadas."""

import copy
import json
from pathlib import Path

import pytest

from nachero.sources import dataset
from nachero.sources.history import load_history
from nachero.sources.local_stats import LocalStats
from nachero_collector import aggregate as A
from nachero_collector import collect as C
from nachero_collector import history as H
from nachero_collector.__main__ import main
from nachero_collector.riot import RateLimiter, Riot, RiotError

DATA = Path(__file__).parent / "data" / "riot"
MATCH = json.loads((DATA / "match.json").read_text(encoding="utf-8"))
LEAGUE = json.loads((DATA / "challenger.json").read_text(encoding="utf-8"))


class Api:
    """La API de Riot de mentira: rutas -> respuestas, y registro de lo pedido."""

    def __init__(self, routes, statuses=None):
        self.routes, self.statuses, self.urls = routes, statuses or {}, []

    def __call__(self, url, headers):
        assert headers["X-Riot-Token"] == "RGAPI-test"
        self.urls.append(url)
        for prefix, queue in self.statuses.items():
            if prefix in url and queue:
                return queue.pop(0)
        for prefix, body in self.routes.items():
            if prefix in url:
                return 200, {}, json.dumps(body).encode()
        return 404, {}, b""


def riot(routes, statuses=None, sleeps=None):
    sleeps = sleeps if sleeps is not None else []
    api = Api(routes, statuses)
    limiter = RateLimiter(clock=lambda: 0.0, sleep=lambda s: None, limits=((10**6, 1.0),))
    return Riot("RGAPI-test", "euw1", fetch=api, limiter=limiter, sleep=sleeps.append), api


def match(mid=1, **info):
    m = copy.deepcopy(MATCH)
    m["metadata"]["matchId"] = f"EUW1_{mid}"
    m["info"].update(gameId=mid, **info)
    return m


# ------------------------------------------------------------------ cliente
def test_sin_clave_no_arranca():
    with pytest.raises(ValueError):
        Riot("")


def test_jugadores_de_master_plus():
    r, api = riot({"challengerleagues": LEAGUE, "grandmasterleagues": {"entries": [{"puuid": "otro"}]}})
    assert r.apex_puuids() == ["puuid-0" + "x" * 70, "puuid-5" + "x" * 70, "otro"]
    assert all(u.startswith("https://euw1.api.riotgames.com/lol/league/v4/") for u in api.urls)


def test_ids_de_partidas_paginados():
    r, api = riot({"start=0": [f"EUW1_{i}" for i in range(100)], "start=100": ["EUW1_100"]})
    assert len(r.match_ids("p", 420, start_time=1000)) == 101
    assert "europe.api.riotgames.com" in api.urls[0] and "queue=420" in api.urls[0] and "startTime=1000" in api.urls[0]


def test_respeta_retry_after_en_429():
    sleeps = []
    r, _ = riot(
        {"/matches/EUW1_1": MATCH}, {"/matches/EUW1_1": [(429, {"Retry-After": "7"}, b""), (503, {}, b"")]}, sleeps
    )
    assert r.match("EUW1_1")["info"]["queueId"] == 420
    assert sleeps == [7.0, 4.0]  # Retry-After y espera creciente en el 5xx


def test_clave_caducada_falla_claro():
    r, _ = riot({}, {"/matches/": [(403, {}, b"")]})
    with pytest.raises(RiotError) as e:
        r.match("EUW1_1")
    assert e.value.status == 403


def test_limite_de_peticiones():
    clock, slept = [0.0], []

    def sleep(s):
        slept.append(s)
        clock[0] += s

    lim = RateLimiter(limits=((20, 1.0), (100, 120.0)), clock=lambda: clock[0], sleep=sleep)
    for _ in range(100):
        lim.wait()
        clock[0] += 0.01
    assert clock[0] >= 4.0  # 20 por segundo: 100 peticiones, 5 segundos
    lim.wait()  # la 101 espera a que pasen los 2 minutos
    assert clock[0] >= 120


# ------------------------------------------------------------------ agregación
def test_partida_valida_y_remakes_fuera():
    assert A.usable(MATCH)
    assert not A.usable(match(gameDuration=200))
    assert not A.usable(match(queueId=440))
    bad = match()
    bad["info"]["participants"][0]["teamPosition"] = ""
    assert not A.usable(bad)


def test_cuenta_campeones_bans_matchups_sinergias_y_runas():
    doc = A.new_doc("16.23", "euw1", "master_plus", "test")
    A.add_match(doc, MATCH)
    tali = doc["champions"]["163"]["roles"]["jungle"]
    assert (tali["games"], tali["wins"]) == (1, 1)
    assert tali["runes"][0]["pri"] == [8128, 8139, 8140, 8105] and tali["runes"][0]["mod"] == [5005, 5008, 5011]
    assert doc["champions"]["238"]["bans"] == 1 and doc["champions"]["245"]["bans"] == 1
    assert doc["matchups"]["163:jungle"]["64:jungle"] == {"games": 1, "wins": 1}
    assert doc["matchups"]["64:jungle"]["163:jungle"] == {"games": 1, "wins": 0}
    assert len(doc["matchups"]["163:jungle"]) == 5  # contra los 5 rivales
    assert doc["synergies"]["163:jungle"]["103:middle"] == {"games": 1, "wins": 1}
    assert "163:jungle" not in doc["synergies"]["163:jungle"]


def test_lo_contado_cumple_el_esquema_y_no_lleva_jugadores():
    doc = A.new_doc("16.23", "euw1", "master_plus", "test")
    A.add_match(doc, MATCH)
    doc["generated"] = doc["cutoff"] = "2026-11-19T00:00:00Z"
    assert dataset.validate(doc) == []
    texto = json.dumps(doc)
    assert "puuid" not in texto and "Jugador" not in texto and "EUW1_" not in texto


# ------------------------------------------------------------------ una pasada
def routes(n=3):
    out = {"challengerleagues": LEAGUE, "/ids": [f"EUW1_{i}" for i in range(1, n + 1)]}
    for i in range(1, n + 1):
        out[f"/matches/EUW1_{i}"] = match(i)
    return out


def test_pasada_completa(tmp_path):
    r, _ = riot(routes(3))
    s = C.collect(r, tmp_path / "data", tmp_path / "state.json", now=lambda: 1_795_100_000, log=lambda *a: None)
    assert s["counted"] == 3 and s["patches"] == ["16.23"]
    f = tmp_path / "data" / "16.23" / "euw1" / "master_plus.json.gz"
    doc = dataset.load_file(f)
    assert dataset.validate(doc) == [] and doc["totals"]["games"] == 3
    assert doc["cutoff"] == "2026-11-18T11:36:40Z" and doc["generated"].startswith("2026-11")
    # y la app lo lee como fuente
    assert LocalStats(tmp_path / "data").refresh_tiers("16.23") == 5


def test_no_cuenta_dos_veces_y_acumula(tmp_path):
    r, _ = riot(routes(2))
    kw = {"now": lambda: 1_795_100_000, "log": lambda *a: None}
    C.collect(r, tmp_path / "d", tmp_path / "s.json", **kw)
    s = C.collect(r, tmp_path / "d", tmp_path / "s.json", **kw)
    assert s["new"] == 0
    r2, _ = riot(routes(4))
    C.collect(r2, tmp_path / "d", tmp_path / "s.json", **kw)
    assert dataset.load_file(tmp_path / "d" / "16.23" / "euw1" / "master_plus.json.gz")["totals"]["games"] == 4


def test_un_archivo_por_parche(tmp_path):
    rt = routes(2)
    rt["/matches/EUW1_2"] = match(2, gameVersion="16.22.1.1")
    r, _ = riot(rt)
    s = C.collect(r, tmp_path / "d", tmp_path / "s.json", now=lambda: 1_795_100_000, log=lambda *a: None)
    assert s["patches"] == ["16.22", "16.23"]


def test_rota_entre_jugadores(tmp_path):
    league = {"entries": [{"puuid": f"p{i}"} for i in range(5)]}
    r, api = riot({"challengerleagues": league, "/ids": []})
    kw = {"players": 2, "now": lambda: 1_795_100_000, "log": lambda *a: None}
    C.collect(r, tmp_path / "d", tmp_path / "s.json", **kw)
    C.collect(r, tmp_path / "d", tmp_path / "s.json", **kw)
    pedidos = [u.split("/by-puuid/")[1].split("/")[0] for u in api.urls if "/by-puuid/" in u]
    assert pedidos == ["p0", "p1", "p2", "p3"]


def test_el_estado_no_se_publica(tmp_path):
    r, _ = riot(routes(1))
    C.collect(r, tmp_path / "data", tmp_path / "privado" / "s.json", now=lambda: 1_795_100_000, log=lambda *a: None)
    publicados = [p.name for p in (tmp_path / "data").rglob("*") if p.is_file()]
    assert publicados == ["master_plus.json.gz"]


# ------------------------------------------------------------------ tu historial completo
def test_tu_partida_en_el_formato_del_historial():
    g = H.game_of(MATCH, "puuid-1" + "x" * 70)
    assert g["gameId"] == 7000000001 and g["champ"] == 163 and g["role"] == "jungle" and g["win"] is True
    assert g["patch"] == "16.23" and g["cspm"] == pytest.approx(200 / 30)
    assert H.game_of(MATCH, "nadie") is None


def test_importar_tu_historial(tmp_path):
    me = "puuid-1" + "x" * 70
    rt = {"/accounts/by-riot-id/Nacho/EUW": {"puuid": me}, "/ids": ["EUW1_1", "EUW1_2"],
          "/matches/EUW1_1": match(1), "/matches/EUW1_2": match(2, gameDuration=100)}  # fmt: skip
    r, _ = riot(rt)
    out = tmp_path / "history_import.json"
    assert H.import_history(r, "Nacho#EUW", out, since=0, queues=(420,), log=lambda *a: None) == 1
    with pytest.raises(ValueError):
        H.import_history(r, "sin-tag", out, since=0)
    # la app lo une a tu historial
    games = load_history(None, str(tmp_path / "h.json"), [420], lambda *a: None, str(out))
    assert [g["gameId"] for g in games] == [1]


# ------------------------------------------------------------------ línea de órdenes
def test_sin_clave_avisa(monkeypatch, capsys):
    monkeypatch.delenv("RIOT_API_KEY", raising=False)
    assert main(["recoger"]) == 2
    assert "RIOT_API_KEY" in capsys.readouterr().err
