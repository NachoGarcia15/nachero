"""Recolector de partidas con la API de Riot (issue #19): cliente, límites, agregación y pasadas."""

import copy
import json
import re
from pathlib import Path

import pytest

from nachero.app import worker
from nachero.config import CFG
from nachero.sources import dataset
from nachero.sources.history import load_history
from nachero.sources.local_stats import LocalStats
from nachero_collector import aggregate as A
from nachero_collector import collect as C
from nachero_collector import history as H
from nachero_collector.__main__ import main
from nachero_collector.riot import PAGE, RateLimiter, Riot, RiotError

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


# ------------------------------------------------------------------ Esmeralda+ y Diamante+ (#86)
class Ladder:
    """La escalera de soloq de mentira: apex y divisiones con `sizes[(tier, div)]` jugadores, en
    páginas de 205 (la API devuelve una lista vacía pasada la última). Sin partidas."""

    def __init__(self, sizes, apex=0, ids=()):
        self.sizes, self.apex, self.ids, self.urls = sizes, apex, list(ids), []

    def __call__(self, url, headers):
        self.urls.append(url)
        m = re.search(r"/entries/RANKED_SOLO_5x5/(\w+)/(\w+)\?page=(\d+)", url)
        if m:
            tier, div, page = m.group(1), m.group(2), int(m.group(3))
            n = self.sizes.get((tier, div), 0)
            rows = [{"puuid": f"{tier}{div}-{i}", "tier": tier} for i in range((page - 1) * PAGE, min(n, page * PAGE))]
            return 200, {}, json.dumps(rows).encode()
        if "challengerleagues" in url:
            return 200, {}, json.dumps({"entries": [{"puuid": f"apex-{i:04d}"} for i in range(self.apex)]}).encode()
        if "leagues/by-queue" in url:
            return 200, {}, b'{"entries": []}'
        if "/ids" in url:
            return 200, {}, json.dumps(self.ids).encode()
        return 404, {}, b""


def ladder_riot(ladder):
    limiter = RateLimiter(clock=lambda: 0.0, sleep=lambda s: None, limits=((10**6, 1.0),))
    return Riot("RGAPI-test", "euw1", fetch=ladder, limiter=limiter, sleep=lambda s: None)


def test_pagina_de_una_division():
    lad = Ladder({("DIAMOND", "II"): 300})
    r = ladder_riot(lad)
    assert len(r.entries_puuids("DIAMOND", "II", 1)) == PAGE
    assert r.entries_puuids("DIAMOND", "II", 2)[0] == f"DIAMONDII-{PAGE}"
    assert r.entries_puuids("DIAMOND", "II", 3) == []
    assert lad.urls[1] == "https://euw1.api.riotgames.com/lol/league/v4/entries/RANKED_SOLO_5x5/DIAMOND/II?page=2"


def test_fuentes_de_cada_liga():
    assert C.sources_of("master_plus") == ["APEX"]
    assert C.sources_of("diamond_plus") == ["APEX", "DIAMOND/I", "DIAMOND/II", "DIAMOND/III", "DIAMOND/IV"]
    assert len(C.sources_of("emerald_plus")) == 9 and C.sources_of("emerald_plus")[-1] == "EMERALD/IV"


def test_pagina_a_pagina_sin_repetir_y_vuelta_a_empezar():
    """Una división de 300 (dos páginas): de 100 en 100, sin repetir, y al acabar vuelve a la página 1
    sabiendo su tamaño."""
    lad = Ladder({("DIAMOND", "I"): 300})
    r = ladder_riot(lad)
    src: dict = {"APEX": {"lap": 99}}  # que solo mire Diamante I
    for k in ("DIAMOND/II", "DIAMOND/III", "DIAMOND/IV"):
        src[k] = {"lap": 99}
    got = [C.pick_players(r, "diamond_plus", src, 100) for _ in range(3)]
    assert sum(got, []) == [f"DIAMONDI-{i}" for i in range(300)]
    assert src["DIAMOND/I"] == {"page": 3, "skip": 0}
    nxt = C.pick_players(r, "diamond_plus", src, 50)  # página 3 vacía: vuelta 1, tamaño 2 páginas
    assert nxt == [f"DIAMONDI-{i}" for i in range(50)]
    assert src["DIAMOND/I"] == {"page": 1, "skip": 50, "lap": 1, "size": 2}


def test_rota_por_divisiones_en_proporcion_a_su_tamano():
    """Con el tiempo, cada división aporta según sus jugadores (una de 8 páginas da 4 veces más que
    una de 2), y nadie se queda fuera."""
    sizes = {("DIAMOND", d): 2 * PAGE for d in ("I", "II", "III")} | {("DIAMOND", "IV"): 8 * PAGE}
    lad = Ladder(sizes, apex=PAGE)
    r = ladder_riot(lad)
    src: dict = {}
    seen: list[str] = []
    for _ in range(60):
        seen += C.pick_players(r, "diamond_plus", src, 500)
    by = {
        k: sum(1 for p in seen if p.startswith(k))
        for k in ("apex", "DIAMONDI-", "DIAMONDII-", "DIAMONDIII-", "DIAMONDIV-")
    }
    assert all(by.values())
    assert 3.0 < by["DIAMONDIV-"] / by["DIAMONDII-"] < 5.0  # 8 páginas frente a 2
    assert 1.5 < by["DIAMONDII-"] / by["apex"] < 2.5  # 2 páginas frente a 1
    assert src["DIAMOND/IV"]["size"] == 8 and src["APEX"]["size"] == 1


def test_una_pasada_no_repite_jugadores_aunque_haya_pocos():
    lad = Ladder({("DIAMOND", "I"): 3}, apex=2)
    got = C.pick_players(ladder_riot(lad), "diamond_plus", {}, 500)
    assert sorted(got) == ["DIAMONDI-0", "DIAMONDI-1", "DIAMONDI-2", "apex-0000", "apex-0001"]


def test_pasada_de_esmeralda_plus(tmp_path):
    """La partida va al archivo de la liga de la muestra, y la rotación y los ids, a su estado."""
    rt = routes(2)
    lad = Ladder({("EMERALD", "IV"): 5}, apex=0, ids=["EUW1_1", "EUW1_2"])

    def fetch(url, headers):
        for k, body in rt.items():
            if k.startswith("/matches/") and url.endswith(k):
                return 200, {}, json.dumps(body).encode()
        return lad(url, headers)

    r = ladder_riot(fetch)
    s = C.collect(r, tmp_path / "d", tmp_path / "s.json", league="emerald_plus", players=3,
                  now=lambda: 1_795_100_000, log=lambda *a: None)  # fmt: skip
    assert s["league"] == "emerald_plus" and s["counted"] == 2 and s["players"] == 3
    doc = dataset.load_file(tmp_path / "d" / "16.23" / "euw1" / "emerald_plus.json.gz")
    assert doc["league"] == "emerald_plus" and dataset.validate(doc) == []
    st = json.loads((tmp_path / "s.json").read_text(encoding="utf-8"))
    assert set(st["leagues"]["emerald_plus"]["seen"]) == {"EUW1_1", "EUW1_2"}
    assert st["leagues"]["emerald_plus"]["sources"]["EMERALD/IV"] == {"page": 1, "skip": 3}
    assert not (tmp_path / "d" / "16.23" / "euw1" / "master_plus.json.gz").exists()


def test_cada_liga_cuenta_sus_partidas(tmp_path):
    """Con el mismo estado, una partida ya contada en Master+ cuenta también en Esmeralda+ (otra muestra)."""
    kw = {"now": lambda: 1_795_100_000, "log": lambda *a: None}
    r, _ = riot(routes(2))
    C.collect(r, tmp_path / "d", tmp_path / "s.json", **kw)
    r, _ = riot(routes(2))
    assert C.collect(r, tmp_path / "d", tmp_path / "s.json", league="emerald_plus", **kw)["counted"] == 2
    with pytest.raises(ValueError):
        C.collect(r, tmp_path / "d", tmp_path / "s.json", league="hierro_plus", **kw)


def test_el_estado_antiguo_se_conserva(tmp_path):
    """El estado de antes (solo Master+, con "cursor") pasa al nuevo sin perder ids ni rotación."""
    old = {"cursor": 210, "seen": {"EUW1_1": 1_795_000_000}, "last_run": 1_795_000_000}
    (tmp_path / "s.json").write_text(json.dumps(old), encoding="utf-8")
    league = {"entries": [{"puuid": f"p{i:03d}"} for i in range(300)]}
    r, api = riot({"challengerleagues": league, "/ids": ["EUW1_1"]})
    s = C.collect(r, tmp_path / "d", tmp_path / "s.json", players=2, now=lambda: 1_795_100_000, log=lambda *a: None)
    assert s["new"] == 0  # EUW1_1 ya estaba contada
    pedidos = [u.split("/by-puuid/")[1].split("/")[0] for u in api.urls if "/by-puuid/" in u]
    assert pedidos == ["p210", "p211"]  # sigue por donde iba
    st = json.loads((tmp_path / "s.json").read_text(encoding="utf-8"))
    assert "cursor" not in st and "seen" not in st and "EUW1_1" in st["leagues"]["master_plus"]["seen"]


def test_olvida_ids_que_ya_no_pueden_volver():
    """Un id contado hace más del LOOKBACK (más un margen) ya no sale en las listas: se olvida."""
    assert C.LOOKBACK < C.KEEP_IDS <= C.LOOKBACK + 2 * 86400


def test_partidas_por_rol_son_las_reales():
    """Una partida pone dos campeones en cada rol: son 5 partidas por rol, no 1 (antes, `// 10`)."""
    doc = A.new_doc("16.23", "euw1", "emerald_plus", "test")
    for _ in range(5):
        A.add_match(doc, MATCH)
    doc["generated"] = "2026-11-19T00:00:00Z"
    d = dataset.derive(doc)
    assert {r: t["games"] for r, t in d["roles"].items()} == dict.fromkeys(
        ("top", "jungle", "middle", "bottom", "utility"), 5
    )


def test_la_app_lee_los_datos_propios_de_la_liga_de_build_tier(tmp_path, monkeypatch):
    out = tmp_path / "data"
    for league in ("master_plus", "emerald_plus"):
        doc = A.new_doc("16.23", "euw1", league, "test")
        for _ in range(1 if league == "master_plus" else 3):
            A.add_match(doc, MATCH)
        doc["generated"] = doc["cutoff"] = "2026-11-19T00:00:00Z"
        C.write_doc(C.out_file(out, "16.23", "euw1", league), doc)
    monkeypatch.setitem(CFG, "build_tier", "emerald_plus")
    assert worker.own_league() == "emerald_plus"
    p = LocalStats(out, region="euw1", league=worker.own_league())
    assert p.refresh_tiers("16.23") == 5 and p.stats()["games"] == 3
    st = worker.data_status(p, "16.23")
    assert st["tier"] == "Esmeralda+" and st["games"] == 3
    monkeypatch.setitem(CFG, "build_tier", "raro")
    assert worker.own_league() == "emerald_plus"
    monkeypatch.setitem(CFG, "build_tier", "master_plus")
    assert LocalStats(out, league=worker.own_league()).stats()["games"] == 1


def test_la_linea_de_ordenes_solo_acepta_ligas_conocidas(monkeypatch):
    monkeypatch.setenv("RIOT_API_KEY", "RGAPI-test")
    with pytest.raises(SystemExit):
        main(["recoger", "--league", "hierro_plus"])


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
