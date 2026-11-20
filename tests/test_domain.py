"""Motor de soloq: modelo del jugador, etiquetas de composicion y recomendacion."""

import time

import pytest

from conftest import FakeLola, all_roles
from nachero.domain import tags as T
from nachero.domain.engine import Engine, infer_roles
from nachero.domain.player import Player

NOW = time.time() * 1000


def game(cid, role="jungle", win=True, days_ago=1, gpm=400, dpm=600, cspm=6.0):
    return {
        "gameId": hash((cid, role, win, days_ago, gpm)),
        "t": NOW - days_ago * 86400000,
        "patch": "16.22",
        "champ": cid,
        "role": role,
        "win": win,
        "k": 5,
        "d": 3,
        "a": 5,
        "gpm": gpm,
        "dpm": dpm,
        "cspm": cspm,
    }


# ------------------------------------------------------------------ jugador
def test_primera_vez_penaliza_y_la_experiencia_sube():
    p = Player([game(2)], [{"championId": 3, "championPoints": 70_000}])
    novato = p.components(4, "jungle")["experience"]
    medio = Player([game(4)] * 20, []).components(4, "jungle")["experience"]
    veterano = p.components(3, "jungle")["experience"]  # ~100 partidas por maestria
    assert novato == pytest.approx(-6.0, abs=0.01)
    assert novato < medio < veterano
    assert veterano <= 2.0


def test_pocas_victorias_no_disparan_la_estimacion():
    # 4 de 4 dice poco: el residuo de WR debe quedar muy encogido
    games = [game(3, win=True) for _ in range(4)] + [game(4, win=False) for _ in range(30)]
    resid = Player(games, []).components(3, "jungle")["resid"]
    assert 0 < resid < 3


def test_forma_premia_lo_jugado_este_mes():
    reciente = Player([game(3, days_ago=2) for _ in range(5)], []).components(3, "jungle")
    antiguo = Player([game(3, days_ago=60) for _ in range(5)], []).components(3, "jungle")
    assert reciente["form"] > 0 == antiguo["form"]


def test_rol_principal():
    p = Player([game(3, "jungle")] * 5 + [game(4, "bottom")] * 2, [])
    assert p.main_role == "jungle"


# ------------------------------------------------------------------ etiquetas y composicion
def test_identidad_de_equipo(champs):
    engage = T.identity([(1, 1.0), (7, 1.0), (3, 1.0)], champs)[0]  # tanque, diver, asesino
    rango = T.identity([(2, 1.0), (8, 1.0), (4, 1.0)], champs)[0]  # magos y tirador
    assert engage == "engage"
    assert rango == "range"
    assert T.identity([(6, 1.0)], champs)[0] == ""  # muy poco para decidir


def test_cohesion_premia_el_engage_que_falta(champs):
    aliados = [(2, 1.0), (4, 1.0), (8, 1.0)]  # sin engage
    con_engage, why = T.cohesion(1, aliados, champs)
    sin_engage, _ = T.cohesion(4, aliados, champs)
    assert con_engage > sin_engage
    assert any("engage" in t for _, t in why)


def test_counter_comp_anti_dive(champs):
    rival_dive = [1, 7, 3]
    b, why = T.counter_comp(6, rival_dive, champs)  # encantador (peel)
    assert b > 0 and why
    assert T.counter_comp(6, rival_dive[:2], champs) == (0.0, [])  # menos de 3 enemigos: no opina


# ------------------------------------------------------------------ motor
def make_engine(champs, matchups=None, games=(), mode="pool"):
    tiers = all_roles(
        jungle={1: (52.0, 5000, 5.0, 60), 3: (51.0, 8000, 6.0, 80), 7: (50.0, 6000, 4.0, 70)},
        middle={2: (51.0, 6000, 5.0, 90), 8: (50.5, 4000, 3.0, 90)},
        top={5: (50.0, 6000, 5.0, 85)},
        bottom={4: (50.0, 9000, 8.0, 95)},
        utility={6: (51.0, 7000, 6.0, 95)},
    )
    lola = FakeLola(tiers, matchups or {})
    cfg = {"pick_mode": mode, "weights": {"pool": 1, "meta": 1, "matchup": 1, "comp": 1}, "style": {}}
    return Engine(champs, lola, Player(list(games), []), cfg), lola


def test_infer_roles_asigna_la_linea_mas_probable(champs):
    lola = FakeLola(all_roles(jungle={3: (50, 5000, 5, 90)}, middle={2: (50, 5000, 5, 90)}))
    assert infer_roles([2, 3], lola) == {2: "middle", 3: "jungle"}


def test_matchup_contra_el_rival_de_linea(champs):
    # El campeon 3 gana mucho al jungla rival (7); el 1 lo pierde
    mu = {(3, "jungle"): {"jungle": {7: 6.0}}, (1, "jungle"): {"jungle": {7: -6.0}}}
    eng, _ = make_engine(champs, mu, mode="meta")
    picks, ctx = eng.picks("jungle", set(), set(), [], [7], enemy_left_after=0)
    by = {p["id"]: p for p in picks}
    assert ctx["lane_known"] is True
    assert by[3]["parts"]["lane"] > 0 > by[1]["parts"]["lane"]
    assert picks[0]["id"] == 3


def test_modo_meta_ignora_tu_pool(champs):
    games = [game(1) for _ in range(40)]
    eng, _ = make_engine(champs, games=games, mode="meta")
    picks, _ = eng.picks("jungle", set(), set(), [], [])
    assert all(p["parts"]["you"] == 0 for p in picks)
    eng.cfg["pick_mode"] = "pool"
    picks, _ = eng.picks("jungle", set(), set(), [], [])
    assert {p["id"]: p for p in picks}[1]["parts"]["you"] != 0


def test_riesgo_de_counter_solo_si_el_rival_aun_puede_elegir(champs):
    mu = {(3, "jungle"): {"jungle": {7: -5.0, 1: -4.0}}}
    eng, _ = make_engine(champs, mu, mode="meta")
    con_picks = {p["id"]: p for p in eng.picks("jungle", set(), set(), [], [], enemy_left_after=3)[0]}
    sin_picks = {p["id"]: p for p in eng.picks("jungle", set(), set(), [], [], enemy_left_after=0)[0]}
    assert con_picks[3]["parts"]["risk"] < 0
    assert sin_picks[3]["parts"]["risk"] == 0


def test_no_recomienda_lo_no_disponible(champs):
    eng, lola = make_engine(champs, mode="meta")
    picks, _ = eng.picks("jungle", {3}, set(), [], [])
    assert 3 not in {p["id"] for p in picks}
    assert lola.requested  # pide los matchups que faltan en segundo plano


def test_resumen_del_historial_frente_a_la_temporada():
    games = [game(3, days_ago=10), game(4, days_ago=2), game(5, role="")]
    h = Player(games, []).history_summary({"tier": "Master", "lp": 558, "w": 135, "l": 116})
    assert h["games"] == 2  # las partidas sin rol no cuentan
    assert h["since"] == min(g["t"] for g in games[:2])
    assert (h["season"], h["missing"], h["client_limit"]) == (251, 249, 200)


def test_resumen_del_historial_sin_ranked_ni_partidas():
    h = Player([], []).history_summary(None)
    assert h == {"games": 0, "since": None, "season": None, "missing": 0, "client_limit": 200}


def test_composicion_cuenta_lo_marcado_como_estimacion(champs):
    from nachero.domain.engine import comp_summary

    solo = comp_summary([4], champs)
    assert solo["est"] == 0 and solo["ad"] == 1 and solo["phys"] == 100
    con = comp_summary([4], champs, hovers=[1, 2, 4, 0])  # repetidos y vacíos no cuentan
    assert con["n"] == 3 and con["est"] == 2 and con["ap"] == 2 and con["front"] == 1
    assert 0 < con["phys"] < 100
    assert comp_summary([], champs)["phys"] is None
