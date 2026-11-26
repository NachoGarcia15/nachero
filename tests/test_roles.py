"""Roles de campeón (issue #43): principal, flex, ocasional y fuera de rol con los repartos reales
de Master+, y su uso en Draft, Tu pool, el simulador pro y los roles del rival."""

import pytest

from conftest import REAL_AVG, FakeLola, real_tiers
from nachero.app.worker import evaluate, pool_rows
from nachero.domain import blind as BL
from nachero.domain import roles as R
from nachero.domain.common import ROLES
from nachero.domain.engine import Engine, infer_roles
from nachero.domain.player import Player
from nachero.domain.pro import ProEngine, parse_fixed

KATARINA, JAYCE, CASSIOPEIA, TEEMO, TALIYAH = 55, 126, 69, 17, 163
LEE_SIN, ORNN, AHRI, JINX, THRESH = 64, 516, 103, 222, 412
TH = R.settings({})


def split(cid):
    return R.split_of(FakeLola(real_tiers(), avg=REAL_AVG), cid)


def game(cid, role, win=True):
    return {"gameId": hash((cid, role, win)), "t": 0, "patch": "16.22", "champ": cid, "role": role, "win": win,
            "k": 5, "d": 3, "a": 5, "gpm": 400, "dpm": 600, "cspm": 6.0}  # fmt: skip


def engine(real_champs, games=(), mastery=(), mode="pool", mu=None, cfg=None):
    lola = FakeLola(real_tiers(), mu or {}, avg=REAL_AVG)
    base = {"pick_mode": mode, "weights": {}, "style": {}}
    return Engine(real_champs, lola, Player(list(games), list(mastery)), base | (cfg or {})), lola


# ------------------------------------------------------------------ categorías
@pytest.mark.parametrize(
    ("cid", "esperado"),
    [
        (KATARINA, {"middle": "main", "bottom": "flex", "top": "occasional", "utility": "off", "jungle": "off"}),
        (JAYCE, {"top": "main", "jungle": "flex", "middle": "flex", "bottom": "off", "utility": "off"}),
        (CASSIOPEIA, {"middle": "main", "top": "flex", "bottom": "flex", "jungle": "off", "utility": "off"}),
        (TEEMO, {"top": "main", "jungle": "occasional", "utility": "occasional", "middle": "occasional",
                 "bottom": "occasional"}),
        (TALIYAH, {"jungle": "main", "middle": "flex", "bottom": "occasional", "utility": "occasional",
                   "top": "occasional"}),
    ],
)  # fmt: skip
def test_categorias_con_repartos_reales(cid, esperado):
    sp = split(cid)
    assert {r: R.category(sp, r, TH) for r in esperado} == esperado


def test_umbrales_ajustables_en_config():
    sp = split(TEEMO)
    assert R.category(sp, "jungle", TH) == "occasional"
    th = R.settings({"roles": {"flex_pct": 7.5}})
    assert R.category(sp, "jungle", th) == "flex"  # 7,57 % de sus partidas
    assert R.settings({"roles": {"flex_pct": "mucho"}})["flex_pct"] == 10.0  # valores no válidos: por defecto


def test_etiqueta_con_sus_roles():
    assert R.label(split(KATARINA), TH) == "Mid · ADC flex"
    assert R.label(split(JAYCE), TH) == "Top · Jungla flex · Mid flex"
    assert R.label(split(TEEMO), TH) == "Top"


def test_confianza_segun_partidas_en_el_rol():
    assert R.estimate(split(JAYCE), "jungle", TH)["confidence"] == "high"  # 15.466 partidas
    assert R.estimate(split(KATARINA), "bottom", TH)["confidence"] == "medium"  # 4.572
    assert R.estimate(split(TEEMO), "jungle", TH)["confidence"] == "low"  # 989
    assert R.estimate(split(CASSIOPEIA), "jungle", TH)["confidence"] == "none"  # 3 partidas
    assert R.estimate(split(TEEMO), "jungle", TH)["confidence_es"] == "Baja"


# ------------------------------------------------------------------ estimación fuera de rol
def test_rol_principal_sin_penalizacion():
    e = R.estimate(split(KATARINA), "middle", TH)
    assert e["penalty"] == 0
    assert e["delta"] == pytest.approx((54.42 - REAL_AVG) * 28453 / (28453 + 1500))


def test_la_penalizacion_crece_cuanto_menos_se_juega_ahi():
    pen = [R.estimate(split(c), r, TH)["penalty"] for c, r in
           [(JAYCE, "jungle"), (KATARINA, "bottom"), (TEEMO, "jungle"), (KATARINA, "jungle"),
            (CASSIOPEIA, "jungle")]]  # fmt: skip
    assert pen == sorted(pen, reverse=True)
    assert pen[0] == pen[1] == 0  # flex (>= 10 %): sin penalización
    assert -1.0 < pen[2] < -0.3  # Teemo jungla: 7,6 % de sus partidas, 989 partidas
    assert pen[-1] == pytest.approx(-4.0, abs=0.02)  # Cassiopeia jungla: 0,02 %, 3 partidas
    assert R.offrole_gap(0, TH) == -4.0 and R.offrole_gap(5, TH) == -2.0 and R.offrole_gap(12, TH) == 0


def test_fuera_de_rol_se_encoge_hacia_su_rol_principal():
    sp = split(CASSIOPEIA)
    base = R.estimate(sp, "middle", TH)["delta"]
    jungla = R.estimate(sp, "jungle", TH)  # 3 partidas al 66,7 %: casi no cuentan
    assert jungla["delta"] == pytest.approx(base, abs=0.2)
    assert jungla["value"] < base - 3.5
    katarina_adc = R.estimate(split(KATARINA), "bottom", TH)  # mucha muestra: manda su WR de ADC
    assert katarina_adc["value"] > 2.5
    # Katarina jungla (0,15 %, 50 partidas) queda muy por debajo de Katarina mid aunque mid sea fuerte
    assert R.estimate(sp := split(KATARINA), "jungle", TH)["value"] < R.estimate(sp, "middle", TH)["value"] - 3.5


def test_sin_datos_del_campeon_no_falla():
    e = R.estimate({}, "jungle", TH)
    assert (e["value"], e["category"], e["confidence"]) == (-4.0, "off", "none")


# ------------------------------------------------------------------ Draft
def test_candidatos_principal_y_flex_entre_los_fuertes(real_champs):
    eng, _ = engine(real_champs, mode="meta")
    assert KATARINA in eng.candidates("bottom")  # ADC flex
    assert JAYCE in eng.candidates("jungle")  # jungla flex
    assert CASSIOPEIA in eng.candidates("top")  # top flex
    assert TEEMO not in eng.candidates("jungle")  # ocasional: solo si lo juegas o tienes maestría


def test_candidatos_por_lo_jugado_y_la_maestria(real_champs):
    maestria = [{"championId": TEEMO, "championPoints": 60_000}, {"championId": KATARINA, "championPoints": 60_000}]
    eng, _ = engine(real_champs, games=[game(AHRI, "jungle")], mastery=maestria)
    cands = eng.candidates("jungle")
    assert TEEMO in cands  # jungla ocasional + maestría
    assert KATARINA not in cands  # jungla fuera de rol: la maestría no basta
    assert AHRI in cands  # una partida tuya en el rol basta


def test_tarjeta_con_rol_y_confianza(real_champs):
    eng, _ = engine(real_champs, mode="meta")
    picks, _ = eng.picks("bottom", set(), set(), [], [])
    kata = next(p for p in picks if p["id"] == KATARINA)
    assert (kata["role_cat"], kata["confidence"], kata["roles_label"]) == ("flex", "medium", "Mid · ADC flex")
    assert kata["meta_games"] == 4572 and kata["role_pct"] == 13.4


def test_evaluar_teemo_jungla_con_confianza_baja(real_champs):
    eng, lola = engine(real_champs)
    row = eng.evaluate(TEEMO, "jungle", enemy_ids=[LEE_SIN, AHRI])
    assert (row["role_cat"], row["confidence"], row["confidence_es"]) == ("occasional", "low", "Baja")
    assert row["parts"]["meta"] < 0
    assert [s["role"] for s in row["split"]][:2] == ["top", "utility"]
    assert (TEEMO, "jungle") in lola.requested  # pide sus matchups en segundo plano


def test_matchups_del_rol_principal_con_menos_peso(real_champs):
    # Teemo jungla sin datos de matchups en jungla: usa los de Teemo top contra Lee Sin, a la mitad
    mu = {(TEEMO, "top"): {"jungle": {LEE_SIN: 4.0}}}
    eng, lola = engine(real_champs, mu=mu)
    lane, rest, items, loaded = eng.vs_enemy(TEEMO, "jungle", {LEE_SIN: "jungle"})
    assert loaded and items[0]["other_role"] and items[0]["lane"]
    # a la mitad del mismo matchup encogido con el spread de su rol principal contra la jungla
    propio = BL.posterior(4.0, 1000, eng.sigma(TEEMO, "top", "jungle"), 54.0)[0]
    assert lane == pytest.approx(propio * 0.5)
    row = eng.evaluate(TEEMO, "jungle", enemy_ids=[LEE_SIN])
    assert row["matchups_other_role"] is True


def test_flex_no_pide_la_pagina_de_su_rol_principal(real_champs):
    eng, lola = engine(real_champs)
    eng.vs_enemy(KATARINA, "bottom", {JINX: "bottom"})
    assert (KATARINA, "bottom") in lola.requested
    assert (KATARINA, "middle") not in lola.requested  # flex: solo si ya estaba en caché


# ------------------------------------------------------------------ roles del rival
def test_teemo_jungla_no_rompe_la_asignacion():
    lola = FakeLola(real_tiers(), avg=REAL_AVG)
    roles = infer_roles([TEEMO, ORNN, AHRI, JINX, THRESH], lola)
    assert roles == {TEEMO: "jungle", ORNN: "top", AHRI: "middle", JINX: "bottom", THRESH: "utility"}
    assert infer_roles([TEEMO, LEE_SIN], lola) == {TEEMO: "top", LEE_SIN: "jungle"}


def test_roles_sin_partidas_no_fallan():
    lola = FakeLola({"middle": {AHRI: (53.5, 48818, 10.5, 94.15), KATARINA: (54.4, 28453, 6.1, 83.25)}})
    roles = infer_roles([AHRI, KATARINA], lola, {"roles": {"assign_floor_pct": 0}})
    assert roles[AHRI] == "middle" and roles[KATARINA] != "middle"


# ------------------------------------------------------------------ Tu pool
def test_pool_maestria_en_roles_principal_y_flex(real_champs):
    maestria = [{"championId": KATARINA, "championPoints": 120_000}]
    eng, _ = engine(real_champs, games=[game(LEE_SIN, "jungle")] * 3, mastery=maestria)
    rows = pool_rows(eng, real_champs)
    kata = {r["role_key"]: r for r in rows if r["id"] == KATARINA}
    assert set(kata) == {"middle", "bottom"}  # no top (ocasional) ni tu rol principal (jungla)
    assert kata["bottom"]["role_cat"] == "flex" and kata["bottom"]["roles_label"] == "Mid · ADC flex"
    assert {r["role_key"] for r in rows if r["id"] == LEE_SIN} == {"jungle"}


def test_tu_pool_y_la_pantalla_de_espera_dan_el_mismo_estimado(real_champs):
    """Antes Tu pool sumaba solo tú + parche: el mismo campeón salía con otro WR que en la pantalla
    de espera (que cuenta el riesgo de counter a ciegas, tus puntos extra y tu estilo)."""
    juegos = [game(LEE_SIN, "jungle")] * 6 + [game(TALIYAH, "jungle", win=False)] * 4
    eng, _ = engine(real_champs, games=juegos, cfg={"pool_bonus": {"Taliyah": 1.5}})
    rows = {r["id"]: r for r in pool_rows(eng, real_champs) if r["role_key"] == "jungle"}
    idle = {p["id"]: p for p in eng.picks("jungle", set(), set(), [], [])[0]}
    for cid in (LEE_SIN, TALIYAH):
        assert rows[cid]["est"] == idle[cid]["est"]
    sin, _ = engine(real_champs, games=juegos)
    sin_rows = {r["id"]: r for r in pool_rows(sin, real_champs) if r["role_key"] == "jungle"}
    assert round(rows[TALIYAH]["est"] - sin_rows[TALIYAH]["est"], 1) == 1.5  # «practicando» cuenta


def test_buscador_en_tu_pool(real_champs):
    eng, _ = engine(real_champs)
    row = evaluate(eng, real_champs, TEEMO, "jungle", view="pool")
    assert row["confidence"] == "low" and row["role_key"] == "jungle" and row["split"]


# ------------------------------------------------------------------ simulador pro
class FakeGol:
    loading: set = set()

    def __init__(self, ds):
        self.ds = ds

    def dataset(self, t):
        return self.ds


def pro_engine(real_champs, ds=None):
    eng, lola = engine(real_champs, mode="meta")
    return ProEngine(real_champs, lola, eng, FakeGol(ds))


def test_pro_flex_entra_en_sus_roles(real_champs):
    # En el torneo Katarina solo se ha jugado en mid, pero en Master+ es ADC flex
    ds = {"t": 0, "games": 10, "all": {}, "roles": {r: {} for r in ("top", "jungle", "middle", "bottom", "utility")}}
    ds["roles"]["middle"]["katarina"] = 4
    pe = pro_engine(real_champs, ds)
    assert pe.roles_of(ds, KATARINA) == ["middle", "bottom"]
    assert pe.roles_of(None, JAYCE) == ["top", "jungle", "middle"]
    assert pe.roles_of(None, CASSIOPEIA) == ["top", "middle", "bottom"]
    assert "jungle" not in pe.roles_of(None, TEEMO)  # ocasional: no basta en pro
    assert KATARINA in pe.candidates(None, set())


def test_pro_sugiere_katarina_adc_si_mid_esta_ocupado(real_champs):
    pe = pro_engine(real_champs)
    teams = {"blue": {"picks": [AHRI]}, "red": {"picks": []}}
    roles = {"blue": {AHRI: "middle"}, "red": {}}
    libres = {"blue": ["top", "jungle", "bottom", "utility"], "red": list(ROLES)}
    sug = pe.picks(None, [KATARINA], "blue", "red", teams, roles, libres, 9)
    assert [(s["id"], s["role"]) for s in sug] == [(KATARINA, "bottom")]


def test_pro_rol_elegido_a_mano(real_champs):
    pe = pro_engine(real_champs)
    assert pe.assign(None, [JAYCE, LEE_SIN]) == {JAYCE: "top", LEE_SIN: "jungle"}
    assert pe.assign(None, [JAYCE, LEE_SIN], {JAYCE: "jungle"}) == {JAYCE: "jungle", LEE_SIN: "top"}
    # dos picks al mismo rol: gana el primero y el otro se reparte
    assert pe.assign(None, [JAYCE, LEE_SIN], {JAYCE: "jungle", LEE_SIN: "jungle"})[LEE_SIN] != "jungle"
    st = {
        "blue": {"bans": [], "picks": [JAYCE]},
        "red": {"bans": [], "picks": []},
        "roles": {"blue": {"126": "middle"}},
    }
    res = pe.suggest(st)
    assert res["roles"]["blue"] == {JAYCE: "middle"}
    assert res["teams"]["blue"]["picks"][0]["fixed"] is True
    assert parse_fixed({"x": "top", "17": "fill", "64": "jungle"}) == {64: "jungle"}
    assert parse_fixed(None) == {} and parse_fixed(["top"]) == {}


# ------------------------------------------------------------------ servidor: /api/evaluate
def test_api_evaluar(real_champs, monkeypatch):
    from nachero.app import server
    from nachero.app.state import APP, CTX

    eng, _ = engine(real_champs)
    monkeypatch.setitem(CTX, "engine", eng)
    monkeypatch.setitem(CTX, "champs", real_champs)
    monkeypatch.setitem(APP, "draft", None)
    code, row = server.evaluate_request("id=17&role=jungle&view=draft")
    assert code == 200 and row["confidence"] == "low" and row["in_draft"] is False
    code, row = server.evaluate_request("id=17&role=jungle&view=pool")
    assert code == 200 and row["role_key"] == "jungle"
    assert server.evaluate_request("id=17&role=fill")[0] == 400
    assert server.evaluate_request("id=abc&role=top")[0] == 400
    assert server.evaluate_request("id=99999&role=top")[0] == 400


def test_api_evaluar_con_el_draft_actual(real_champs, monkeypatch):
    from nachero.app import server
    from nachero.app.state import APP, CTX

    class Draft:
        context = {"role": "jungle", "allies": [], "enemy_ids": [LEE_SIN], "enemy_left_after": 0}

    mu = {(TEEMO, "jungle"): {"jungle": {LEE_SIN: -3.0}}}
    eng, _ = engine(real_champs, mu=mu)
    monkeypatch.setitem(CTX, "engine", eng)
    monkeypatch.setitem(CTX, "champs", real_champs)
    monkeypatch.setitem(CTX, "draft", Draft())
    monkeypatch.setitem(APP, "draft", {"role": "jungle"})
    code, row = server.evaluate_request("id=17&role=jungle")
    assert code == 200 and row["in_draft"] is True
    assert row["parts"]["lane"] < 0 and row["ctx"]["lane_known"] is True
