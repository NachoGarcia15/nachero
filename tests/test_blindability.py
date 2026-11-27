"""Blindability y orden de picks (issues #68–#77): spread, encogimiento, riesgo de counter, bans,
intercambios, Tu pool, calibración, sinergias y simulador pro. Sin cliente ni red."""

import math
import random

import pytest

from conftest import FakeLola, all_roles
from nachero import config
from nachero.app import server
from nachero.domain import blind as BL
from nachero.domain import calibration as C
from nachero.domain import pool as POOL
from nachero.domain import swaps as SW
from nachero.domain.common import ROLES
from nachero.domain.engine import Engine, ban_context, role_probs
from nachero.domain.player import Player
from nachero.domain.pro import ProEngine


# ------------------------------------------------------------------ dobles
class RowsLola(FakeLola):
    """Como FakeLola, pero con filas de matchup completas: {(cid, rol): {rol_rival: {e: (d2, n, pr)}}}."""

    def __init__(self, tiers=None, rows=None, syn=None, avg=50.0):
        super().__init__(tiers, {}, avg)
        self.rows = rows or {}
        self.syn = syn or {}

    def matchups(self, cid, role, fetch=True):
        lanes = self.rows.get((cid, role))
        if lanes is None:
            if fetch:
                self.requested.append((cid, role))
            return None
        if not hasattr(self, "_cache"):
            self._cache = {}
        key = (cid, role)
        if key not in self._cache:  # el mismo objeto en cada llamada, como la caché real
            self._cache[key] = {
                r: {str(e): {"wr": 50 + d2, "d1": d2, "d2": d2, "pr": pr, "n": n} for e, (d2, n, pr) in rows.items()}
                for r, rows in lanes.items()
            }
        return self._cache[key]


def table(sigma, k=60, n=20000, seed=1, start=100):
    """Matchups normales con spread `sigma` (sin ruido apreciable): {e: (d2, n, pr)}."""
    rnd = random.Random(seed)
    return {start + i: (rnd.gauss(0, sigma), n, 1.0) for i in range(k)}


def player():
    g = {"gameId": 1, "t": 0, "patch": "16.22", "champ": 1, "role": "jungle", "win": True,
         "k": 5, "d": 2, "a": 7, "gpm": 400, "dpm": 600, "cspm": 6}  # fmt: skip
    return Player([g] * 3, [])


def eng(champs, rows, tiers=None, cfg=None, syn=None):
    tiers = tiers or all_roles(jungle={c: (52, 9000, 8, 90) for c in champs.data})
    cfg = {"pick_mode": "meta", "weights": {}, "main_role": "jungle", **(cfg or {})}
    return Engine(champs, RowsLola(tiers, rows, syn), player(), cfg)


# ------------------------------------------------------------------ base estadística (#69)
def test_con_poca_muestra_manda_el_spread_de_la_pareja(champs):
    # Master+ de un parche: ~20 partidas por matchup; el ruido (~11 pp) tapa cualquier spread
    rnd = random.Random(2)
    thin = {"jungle": {100 + i: (rnd.gauss(0, 11), 20, 1.0) for i in range(100)}}
    rich = {"jungle": {100 + i: (rnd.gauss(0, 2.5), 50000, 1.0) for i in range(100)}}
    e = eng(champs, {(1, "jungle"): thin, (2, "jungle"): rich})
    assert e.sigma(1, "jungle", "jungle") == pytest.approx(BL.PAIR_PRIOR["jungle"]["jungle"], abs=0.35)
    assert e.sigma(2, "jungle", "jungle") == pytest.approx(2.5, abs=0.4)


def test_spread_quita_el_ruido():
    rnd = random.Random(3)
    true = {i: rnd.gauss(0, 2.0) for i in range(200)}

    def observed(n):
        rows = {}
        for i, t in true.items():
            wins = sum(rnd.random() < 0.5 + t / 100 for _ in range(n))
            rows[str(i)] = {"d2": 100 * wins / n - 50, "n": n, "pr": 1.0, "wr": 100 * wins / n}
        return BL.spread(rows)

    few, many = observed(400), observed(4000)
    assert few["obs"] > many["obs"] + 0.5  # con pocas partidas la dispersión observada se infla
    assert few["spread"] == pytest.approx(2.0, abs=0.4) and many["spread"] == pytest.approx(2.0, abs=0.3)


def test_solo_ruido_da_spread_casi_cero():
    rnd = random.Random(5)
    rows = {}
    for i in range(150):
        wins = sum(rnd.random() < 0.5 for _ in range(300))
        rows[str(i)] = {"d2": 100 * wins / 300 - 50, "n": 300, "pr": 1.0, "wr": 100 * wins / 300}
    sp = BL.spread(rows)
    assert sp["obs"] > 2.0 and sp["spread"] < 0.8


def test_posterior_encoge_con_pocas_partidas():
    assert BL.posterior(-5.0, 50, 1.5)[0] == pytest.approx(-5.0 * 2.25 / (2.25 + 50), rel=1e-6)
    assert BL.posterior(-5.0, 1_000_000, 1.5)[0] == pytest.approx(-5.0, abs=0.01)
    assert BL.shrink_k(1.5) == pytest.approx(2500 / 2.25)
    assert BL.ci95(1000) == pytest.approx(3.1, abs=0.01) and BL.ci95(10000) == pytest.approx(0.98, abs=0.01)


def test_probabilidad_de_counter_y_perdida_esperada():
    safe = BL.available_dist({str(e): {"d2": d, "n": n, "pr": p} for e, (d, n, p) in table(1.1).items()}, 1.1)
    risky = BL.available_dist({str(e): {"d2": d, "n": n, "pr": p} for e, (d, n, p) in table(2.4).items()}, 2.4)
    p_safe, p_risky = BL.p_pool(BL.q_of(safe), 7), BL.p_pool(BL.q_of(risky), 7)
    assert p_safe < 0.35 < 0.6 < p_risky
    assert [round(BL.e_max(n), 3) for n in (1, 2, 3, 7)] == [0.0, 0.564, 0.846, 1.352]
    assert BL.expected_loss(2.4, 7) == pytest.approx(2.4 * 1.352, abs=0.01)
    assert BL.expected_loss(2.4, 7, avail=0.5) == pytest.approx(1.2 * 1.352, abs=0.01)


def test_banear_el_unico_counter_lo_quita():
    rows = {str(100 + i): {"d2": 0.0, "n": 50000, "pr": 1.0} for i in range(30)}
    rows["7"] = {"d2": -6.0, "n": 50000, "pr": 3.0}
    with_c = BL.available_dist(rows, 1.0)
    without = BL.available_dist(rows, 1.0, unavailable={7})
    assert BL.q_of(with_c) > 0.08 and BL.q_of(without) < 0.001


def test_wr_esperado_por_odds():
    assert BL.expected_wr(50.9, 45.5) == pytest.approx(55.5, abs=0.2)  # Ahri contra Mel (vídeo)
    assert BL.expected_wr(50, 50) == pytest.approx(50)
    assert BL.expected_duo(52, 52) == pytest.approx(54.0, abs=0.05)


def test_pool_del_80_por_ciento():
    assert BL.pool_size_80([50, 25, 10, 10, 5]) == 3
    assert BL.pool_size_80([100]) == 1 and BL.pool_size_80([]) == 0


def test_ajustes_de_blindability():
    th = BL.settings({"blind": {"counter_rate": 0.7, "pool_size": {"top": 4, "mid": 9}, "matchup_model": "x"}})
    assert th["counter_rate"] == 0.7 and th["pool_size"]["top"] == 4 and "mid" not in th["pool_size"]
    assert th["matchup_model"] == "measured" and BL.eta(th, "top") == 0.7


# ------------------------------------------------------------------ roles con probabilidades (#70)
def test_roles_con_probabilidades_para_un_flex():
    tiers = all_roles()
    tiers["top"] = {1: (50, 5000, 3, 55)}
    tiers["middle"] = {1: (50, 4000, 3, 45), 2: (50, 9000, 5, 99)}
    lola = FakeLola(tiers)
    solo = role_probs([1], lola)[1]
    assert solo["top"] == pytest.approx(0.55, abs=0.03) and solo["middle"] == pytest.approx(0.45, abs=0.03)
    con_mid = role_probs([1, 2], lola)
    assert con_mid[1]["top"] > 0.9 and con_mid[2]["middle"] > 0.9


def test_huecos_rivales_despues_de_ti():
    probs = {9: {"middle": 1.0}}
    ap = BL.after_probs(probs, after=2, open_slots=4)
    assert ap["middle"] == 0 and ap["top"] == pytest.approx(0.5)
    assert BL.after_probs(probs, 0, 4) == dict.fromkeys(ROLES, 0.0)


def test_orden_de_picks_del_cliente():
    acts = [[{"type": "ban"}]] + [
        [{"type": "pick", "actorCellId": c, "isAllyAction": c < 5, "completed": False, "championId": 0} for c in g]
        for g in ([0], [5, 6], [1, 2], [7, 8], [3, 4], [9])
    ]
    order = BL.pick_order(acts)
    assert BL.enemy_after(order, 0) == 5 and BL.enemy_after(order, 1) == 3 and BL.enemy_after(order, 4) == 1
    assert BL.ally_slot(order, 0) == 1 and BL.ally_slot(order, 4) == 5


def test_matchup_contra_un_flex_se_reparte(champs):
    e = eng(champs, {(1, "jungle"): {"jungle": {2: (-4.0, 20000, 5)}, "middle": {2: (2.0, 20000, 5)}}})
    lane, rest, items, _ = e.vs_enemy(1, "jungle", {2: {"jungle": 0.5, "middle": 0.5}})
    assert lane < 0 < rest
    assert items[0]["p_role"] == 0.5


# ------------------------------------------------------------------ riesgo de counter (#72)
def risky_rows(sigma_lane, others=0.6):
    # semilla fija por línea: hash(r) cambia en cada ejecución (PYTHONHASHSEED) y el test era intermitente
    return {r: table(sigma_lane if r == "jungle" else others, seed=i + 1, start=100 + 100 * i)
            for i, r in enumerate(ROLES)}  # fmt: skip


def test_el_campeon_de_spread_bajo_arriesga_menos(champs):
    e = eng(champs, {(1, "jungle"): risky_rows(0.8), (2, "jungle"): risky_rows(2.6)})
    assert e.blind_summary(2, "jungle")["p_pool"] > 65 > e.blind_summary(2, "jungle")["p_blind"]
    ap = dict.fromkeys(ROLES, 1.0)
    low, high = e.blind_risk(1, "jungle", ap), e.blind_risk(2, "jungle", ap)
    assert high["risk"] < low["risk"] <= 0 and high["p"] > low["p"]
    assert e.blind_summary(1, "jungle")["label"] == "safe" and e.blind_summary(2, "jungle")["label"] == "counter"


def test_el_counter_viene_sobre_todo_de_tu_rival_de_linea(champs):
    # en soloq, los rivales de otras líneas eligen para la suya: suman algo (jungla), pero poco
    e = eng(champs, {(1, "jungle"): risky_rows(1.2, others=1.2)})
    solo_lane = e.blind_risk(1, "jungle", {"jungle": 1.0})
    todas = e.blind_risk(1, "jungle", dict.fromkeys(ROLES, 1.0))
    lanes = e.lola.matchups(1, "jungle")
    otras = ("top", "middle", "bottom", "utility")
    medias = {r: e._role_stats(1, "jungle", r, lanes[r], lanes, ())[1] for r in otras}
    # las otras líneas suman pérdida a la tuya (sin su media, que aquí es azar de la tabla)
    assert todas["risk"] - sum(medias.values()) < solo_lane["risk"] < 0 and todas["p"] == solo_lane["p"]
    # cada línea ajena pesa mucho menos que la tuya
    for r in otras:
        otra = e.blind_risk(1, "jungle", {r: 1.0})
        assert abs(otra["risk"] - medias[r]) < abs(solo_lane["risk"]) / 3
    # con η cruzado 1 (simulador pro) las otras líneas pesan como la tuya
    pro = e.blind_risk(1, "jungle", dict.fromkeys(ROLES, 1.0), eta=1.0, eta_cross=1.0)["risk"]
    assert pro < todas["risk"] * 2


def test_sin_rivales_despues_o_eta_cero_no_hay_riesgo(champs):
    e = eng(champs, {(1, "jungle"): risky_rows(2.0)})
    assert e.blind_risk(1, "jungle", dict.fromkeys(ROLES, 0.0))["risk"] == 0
    # con η = 0 el rival coge uno cualquiera de su pool: solo queda la media (la del azar de la tabla)
    azar = e.blind_risk(1, "jungle", dict.fromkeys(ROLES, 1.0), eta=0.0, eta_cross=0.0)["risk"]
    lanes = e.lola.matchups(1, "jungle")
    medias = sum(e._role_stats(1, "jungle", r, lanes[r], lanes, ())[1] for r in ROLES)
    assert (
        azar == pytest.approx(medias) and azar > e.blind_risk(1, "jungle", dict.fromkeys(ROLES, 1.0), eta=1.0)["risk"]
    )
    row = e.score(1, "jungle", [], [], {}, 0)
    assert row["parts"]["risk"] == 0 and row["risk_open"] is False and row["risk_items"] == []


def test_banear_el_counter_baja_el_riesgo(champs):
    rows = {"jungle": {100 + i: (0.0, 50000, 1.0) for i in range(30)}}
    rows["jungle"][7] = (-6.0, 50000, 4.0)
    e = eng(champs, {(1, "jungle"): rows})
    antes = e.blind_risk(1, "jungle", {"jungle": 1.0})
    despues = e.blind_risk(1, "jungle", {"jungle": 1.0}, unavailable={7})
    assert despues["risk"] > antes["risk"] and despues["p"] < antes["p"] and antes["items"][0]["id"] == 7


def test_tarjeta_con_etiqueta_a_ciegas(champs):
    e = eng(champs, {(1, "jungle"): risky_rows(0.8)})
    picks, ctx = e.picks("jungle", set(), set(), [], [], enemy_left_after=5)
    row = next(p for p in picks if p["id"] == 1)
    assert row["blind"]["label"] == "safe" and row["blind"]["p"] is not None and ctx["risk_open"]
    assert any("seguro a ciegas" in w["text"] for w in row["why"])


# ------------------------------------------------------------------ bans según tu hueco (#73)
def test_bans_protegen_mas_si_eliges_antes(champs):
    tiers = all_roles(jungle={c: (52, 9000, 8, 90) for c in champs.data})
    tiers["jungle"][3] = (51, 9000, 3, 90)  # flojo y poco jugado, pero counter de tu pick
    e = eng(champs, {(1, "jungle"): {"jungle": {3: (-9.0, 4000, 3)}}}, tiers=tiers)
    top = [{"id": 1, "name": "Tanky"}]
    primero = e.bans("jungle", top, {1}, my_after=1.0)
    ultimo = e.bans("jungle", top, {1}, my_after=0.0)
    assert primero[0]["id"] == 3 and ultimo[0]["id"] != 3
    assert ban_context(1.0).startswith("eliges antes") and "fuerza" in ban_context(0.0)


# ------------------------------------------------------------------ intercambios (#74)
def test_intercambio_el_campeon_no_el_rol():
    # tú (Nocturne) eliges primero; tu support (Nami) elige después y es mucho más ciega
    losses = {"noc": 2.0, "nami": 0.3}

    def loss(cid, role, after):
        return losses[cid] * after / 5, 0.1 * losses[cid] * after / 5

    me = {"cell": 0, "cid": "noc", "role": "jungle", "after": 5}
    nami = {"cell": 3, "cid": "nami", "role": "utility", "after": 1, "name": "tu Support", "slot": 4}
    adv = SW.advise(me, [nami], loss, [{"cellId": 3, "id": 11, "state": "AVAILABLE"}])
    assert adv["kind"] == "propose" and adv["swap_id"] == 11 and adv["gain"] > 1
    assert "Propón cambiar de turno con tu Support (pick 4)" in SW.message(adv, "Nocturne", "Nami")
    # ella te lo pide: aceptar
    inc = SW.advise(me, [nami], loss, [{"cellId": 3, "id": 11, "state": "RECEIVED"}])
    assert inc["kind"] == "incoming" and inc["verdict"] == "accept"
    # campeones iguales o aliado sin marcar: nada que sugerir
    assert SW.advise(me, [{**nami, "cid": "noc"}], loss) is None
    assert SW.advise(me, [{**nami, "cid": 0}], loss) is None


# ------------------------------------------------------------------ Tu pool (#75)
def test_plan_del_pool():
    th = BL.settings({})
    row = lambda n, lab, est=52: {"name": n, "est": est, "blind": {"label": lab}}  # noqa: E731
    sin = POOL.plan([row("Qiyana", "counter"), row("Naafiri", "counter")], "jungle", th,
                    suggest=[{"id": 1, "name": "Lee Sin", "p_pool": 12}])  # fmt: skip
    assert sin["missing"] == ["safe"] and sin["suggest"][0]["name"] == "Lee Sin"
    ok = POOL.plan([row("Graves", "safe"), row("Qiyana", "counter")], "jungle", th, [50, 30, 20], [10, 5])
    assert ok["missing"] == [] and ok["suggest"] == [] and "Graves" in ok["text"]
    assert ok["size_mastery"] == 2 and ok["size_role"] == 2
    assert "seguro a ciegas: Graves" in POOL.slot_line(2, 0.8, 0.0, ok)
    assert "counter: Qiyana" in POOL.slot_line(5, 0.0, 1.0, ok)
    # sin counter: «todos son de elegir pronto» solo si de verdad lo son (sin intermedios)
    solo = POOL.plan([row("Taliyah", "safe"), row("Naafiri", "safe")], "jungle", th)
    assert solo["missing"] == ["counter"] and solo["text"].startswith("Todos tus campeones son de elegir pronto")
    mezcla = POOL.plan([row("Taliyah", "safe"), row("Qiyana", "flex")], "jungle", th)
    assert mezcla["text"] == (
        "Para elegir pronto tienes Taliyah, pero ningún counter: te falta uno para cuando veas a tu rival."
    )


# ------------------------------------------------------------------ calibración (#71)
def test_calibracion_a_ciegas_o_de_counter():
    row = {"id": 1, "name": "Tanky", "est": 52.0, "parts": {}}
    rec = C.make_record(1000, {"id": 420}, "jungle", row, None,
                        order={"slot": 1, "after": 5, "lane_p": 0.0, "p_counter": 0.3, "lane_loss": 2.0})  # fmt: skip
    rec = C.finish_order(rec, [], [7, 8, 9, 10, 11], {7: "jungle", 8: "top"})
    players = [{"team": 100, "champ": 1, "role": "jungle"}, {"team": 200, "champ": 7, "role": "jungle"},
               {"team": 200, "champ": 8, "role": "middle"}]  # fmt: skip
    out = C.enrich({**rec, "win": False, "gameId": 5}, players, lambda c, r, o: -2.5)
    assert out["opp"] == 7 and out["opp_after"] is True and out["countered"] is True
    assert out["roles_ok"] == 0.5
    rep = C.report([out], eta_prior=0.5)
    assert rep["order"]["blind"]["n"] == 1 and rep["order"]["p_counter"]["obs"] == 100.0
    eta = C.estimate_eta([out], 0.5)
    assert eta["raw"] == 1.0 and 0.5 < eta["value"] < 0.6  # 2,5 / 2,0 → 1 (tope), mezclado con 0,5


def test_registro_antiguo_sigue_valiendo():
    old = {"t": 1, "champ": 1, "role": "jungle", "est": 51.0, "parts": {}, "win": True, "gameId": 2}
    rep = C.report([old])
    assert rep["n"] == 1 and rep["order"]["blind"]["n"] == 0 and rep["order"]["eta"]["value"] == 0.5


# ------------------------------------------------------------------ sinergias (#77)
def test_sinergia_medida_con_datos_propios(champs):
    syn = {(1, "jungle"): {"2:middle": {"wr": 60.0, "n": 20000}, "3:middle": {"wr": 54.0, "n": 50}}}

    class Syn(RowsLola):
        def synergies(self, cid, role):
            return self.syn.get((cid, role))

    tiers = all_roles(jungle={1: (52, 9000, 8, 90)}, middle={2: (52, 9000, 8, 90), 3: (52, 9000, 8, 90)})
    e = Engine(champs, Syn(tiers, {}, syn), player(), {"pick_mode": "meta", "weights": {}})
    good, why, has = e.synergy(1, "jungle", [(2, 1.0)], {2: "middle"})
    few, _, _ = e.synergy(1, "jungle", [(3, 1.0)], {3: "middle"})
    assert has and good > 1.0 and abs(few) < 0.1 and "sinergia con tu Mage" in why[0][1]
    assert eng(champs, {}).synergy(1, "jungle", [(2, 1.0)], {2: "middle"}) == (0.0, [], False)


# ------------------------------------------------------------------ combos de tus aliados en los bans (#85)
class SynLola(RowsLola):
    def synergies(self, cid, role):
        return self.syn.get((cid, role))


def combo_bans(champs, syn, allies):
    """Bans de un ADC: Marksman (4) es el más fuerte de la línea; tu support marca Enchanter (6)."""
    tiers = all_roles(bottom={4: (54, 9000, 12, 90), 10: (51, 9000, 6, 90)}, utility={6: (51, 9000, 8, 90)})
    e = Engine(champs, SynLola(tiers, {}, syn), player(), {"pick_mode": "meta", "weights": {}})
    return e, [b["id"] for b in e.bans("bottom", [], set(), allies)]


def test_no_banea_el_combo_de_lo_que_marca_tu_aliado(champs):
    # Enchanter + Marksman ganan mucho más juntos de lo esperado (20.000 partidas): combo
    syn = {(6, "utility"): {"4:bottom": {"wr": 62.0, "n": 20000}, "10:bottom": {"wr": 51.0, "n": 20000}}}
    _, sin_datos = combo_bans(champs, {}, [(6, "utility", 0.5)])
    assert sin_datos[0] == 4  # sin datos propios, nada cambia: el más fuerte
    e, con = combo_bans(champs, syn, [(6, "utility", 0.5)])
    assert 4 not in con and con[0] == 10
    combo, who = e.ally_combos([(6, "utility", 0.5)])
    assert combo[("bottom", "4")] > e.COMBO_MIN * 0.5 and who["4"] == ["Enchanter"]
    # con tu ADC ya confirmado, ese hueco está cerrado: no hay nada que proteger
    _, cerrado = combo_bans(champs, syn, [(6, "utility", 0.5), (10, "bottom", 1.0)])
    assert cerrado[0] == 4


# ------------------------------------------------------------------ tu pick depende de su pareja (#85)
PAREJAS = {4: 60.0, 10: 42.0, 100: 46.0, 101: 55.0, 102: 48.0, 103: 52.0, 104: 44.0, 105: 50.0, 106: 51.0, 107: 49.0}


def dependiente(champs, wrs=None):
    """Enchanter (6) de support: con Marksman (4) gana mucho y con Shooter (10) pierde mucho."""
    syn = {(6, "utility"): {f"{c}:bottom": {"wr": wr, "n": 30000} for c, wr in (wrs or PAREJAS).items()}}
    tiers = all_roles(bottom={c: (50, 9000, 5, 90) for c in PAREJAS}, utility={6: (51, 9000, 8, 90)})
    return Engine(champs, SynLola(tiers, {}, syn), player(), {"pick_mode": "meta", "weights": {}})


def test_pareja_de_la_que_depende_tu_pick(champs):
    e = dependiente(champs)
    adv = e.combo_advice(6, "utility", ["bottom", "top"])
    assert adv["role"] == "bottom" and adv["partner"] == 4 and adv["gain"] >= e.COMBO_MIN
    assert adv["sigma"] >= e.DEP_SIGMA
    assert e.combo_advice(6, "utility", ["bottom"], gone={4})["partner"] == 101  # la siguiente libre
    assert e.combo_advice(6, "utility", ["top"]) is None  # el ADC ya ha elegido: no hay a quién
    assert e.combo_advice(6, "utility", ["bottom"], planned={"bottom": 4}) is None  # ya la ha marcado
    plano = dependiente(champs, {c: 50.0 for c in PAREJAS})  # le da igual la pareja
    assert plano.combo_advice(6, "utility", ["bottom"]) is None
    assert eng(champs, {}).combo_advice(1, "jungle", ["bottom"]) is None  # sin datos propios


def sesion_support(monkeypatch):
    """Tú de support (sin elegir) y tu ADC sin elegir; sin hechizos, runas ni marcar."""
    from nachero.config import CFG

    for k, v in {"auto_spells": False, "spells_by_role": {}, "import_runes": False, "auto_hover_pick": False}.items():
        monkeypatch.setitem(CFG, k, v)
    me = {"cellId": 0, "assignedPosition": "utility", "championId": 0, "championPickIntent": 0}
    adc = {"cellId": 1, "assignedPosition": "bottom", "championId": 0, "championPickIntent": 0}
    return {"localPlayerCellId": 0, "myTeam": [me, adc], "theirTeam": [],
            "actions": [[{"id": 1, "actorCellId": 0, "championId": 0, "completed": False, "isAllyAction": True,
                          "isInProgress": True, "type": "pick"}]],
            "bans": {"myTeamBans": [], "theirTeamBans": []}, "timer": {}}  # fmt: skip


def test_ancla_con_combos_para_copiar(champs, monkeypatch):
    from nachero.app.draft import Draft

    # Enchanter casi no depende de su ADC (spread bajo), pero con Marksman gana bastante más
    wrs = {4: 53.0, 10: 50.5, 100: 49.5, 101: 50.2, 102: 49.8, 103: 50.0, 104: 50.3, 105: 49.7, 106: 50.1, 107: 49.9}
    e = dependiente(champs, wrs)
    assert e.combo_advice(6, "utility", ["bottom"]) is None and e.combo_partners(6, "utility", "bottom")[0][0] == 4
    out = Draft(None, champs, e).tick(sesion_support(monkeypatch), False, pickable=set(), bannable=set())
    c = out["combo"]
    assert c["kind"] == "anchor" and c["role"] == "bottom" and c["partners"][0]["id"] == 4
    assert c["text"].startswith("Combos de Enchanter para tu ADC: Marksman (+")
    assert c["chat"].startswith("Tengo Enchanter: hace combo con Marksman +")


def test_linea_de_combo_en_la_champ_select(champs, monkeypatch):
    from nachero.app.draft import Draft

    s = sesion_support(monkeypatch)
    adc = s["myTeam"][1]
    out = Draft(None, champs, dependiente(champs)).tick(s, False, pickable=set(), bannable=set())
    assert out["hero"]["id"] == 6 and out["combo"]["partner"] == 4
    assert out["combo"]["text"].startswith("Enchanter rinde mucho más con Marksman (+")
    assert out["combo"]["text"].endswith("propónselo a tu ADC.")
    assert out["combo"]["chat"] == "Si te va bien, coge Marksman: hace combo con mi Enchanter."
    adc["championId"] = 10  # tu ADC ya ha elegido: nada que proponer
    assert Draft(None, champs, dependiente(champs)).tick(s, False, pickable=set(), bannable=set())["combo"] is None


def test_el_combo_del_rival_cuenta_en_tu_linea(champs):
    """El support rival (Enchanter) depende de su ADC y su mejor pareja (Marksman) sigue libre: tu
    rival de línea la coge más a menudo, y Shooter pierde mucho contra ella."""
    syn = {(6, "utility"): {f"{c}:bottom": {"wr": wr, "n": 30000} for c, wr in PAREJAS.items()}}
    rows = {(10, "bottom"): {"bottom": {4: (-5.0, 20000, 10.0), **{c: (0.0, 20000, 10.0) for c in range(100, 108)}}}}
    tiers = all_roles(bottom={c: (50, 9000, 5, 90) for c in PAREJAS}, utility={6: (51, 9000, 8, 90)})
    cfg = {"pick_mode": "meta", "weights": {}}
    con = Engine(champs, SynLola(tiers, rows, syn), player(), cfg)
    sin = Engine(champs, SynLola(tiers, rows, {}), player(), cfg)
    args = ("bottom", [], [6], {6: {"utility": 1.0}}, 4)
    a, b = con.score(10, *args, enemy_open=4), sin.score(10, *args, enemy_open=4)
    assert a["parts"]["risk"] < b["parts"]["risk"] - 0.5
    assert any(w["text"].startswith("su Enchanter pide Marksman: -") for w in a["why"])
    # si ya no puede cogerla (baneada) o tu rival de línea ya ha elegido, nada
    sin_4 = sin.score(10, *args, unavailable={4}, enemy_open=4)["parts"]["risk"]
    assert con.score(10, *args, unavailable={4}, enemy_open=4)["parts"]["risk"] == sin_4
    ya = con.score(10, "bottom", [], [6, 8], {6: {"utility": 1.0}, 8: {"bottom": 1.0}}, 3, enemy_open=3)
    assert not any("pide" in w["text"] for w in ya["why"])


# ------------------------------------------------------------------ simulador pro (#76)
def test_simulador_pro_usa_blindability(champs):
    e = eng(champs, {(1, "jungle"): risky_rows(0.8), (5, "jungle"): risky_rows(2.6)},
            tiers=all_roles(jungle={1: (52, 9000, 8, 90), 5: (52, 9000, 8, 90)}))  # fmt: skip

    class Gol:
        loading: set = set()

        def dataset(self, t):
            return None

    pe = ProEngine(champs, e.lola, e, Gol())
    teams = {"blue": {"picks": [], "bans": []}, "red": {"picks": [], "bans": []}}
    open_r = {"blue": list(ROLES), "red": list(ROLES)}
    sug = pe.picks(None, [1, 5], "blue", "red", teams, {"blue": {}, "red": {}}, open_r, 6)
    by = {s["id"]: s for s in sug}
    assert by[1]["parts"]["risk"] > by[5]["parts"]["risk"] and by[1]["blind"]["label"] == "safe"
    assert sug[0]["id"] == 1


# ------------------------------------------------------------------ ajustes y API
def test_ajustes_de_blindability_desde_el_panel():
    cfg: dict = {}
    changed = config.apply_settings(cfg, {"blind": {"counter_rate": 0.3, "pool_size": 5, "matchup_model": "classic"},
                                          "build_tier": "emerald_plus"})  # fmt: skip
    assert cfg["blind"]["counter_rate"] == 0.3 and cfg["blind"]["pool_size"]["top"] == 5
    assert cfg["blind"]["matchup_model"] == "classic" and cfg["build_tier"] == "emerald_plus" and len(changed) == 4
    assert config.apply_settings(cfg, {"blind": {"counter_rate": 3}, "build_tier": "hierro"}) == []


def test_intercambio_desde_el_panel_solo_en_activo(monkeypatch):
    assert server.swap_request({"op": "x", "id": 1})[0] == 400
    assert server.swap_request({"op": "accept", "id": True})[0] == 400
    monkeypatch.setitem(server.APP, "mode", "observe")
    assert server.swap_request({"op": "accept", "id": 3})[0] == 409


def test_normal_e_max():
    # comprobación de la tabla del docstring: E[máx de 7 normales] ≈ 1,352
    rnd = random.Random(9)
    sims = [max(rnd.gauss(0, 1) for _ in range(7)) for _ in range(20000)]
    assert sum(sims) / len(sims) == pytest.approx(1.352, abs=0.03)
    assert math.isinf(BL.noise_var(0))


def test_sin_pagina_de_matchups_se_usa_el_riesgo_tipico(champs):
    # sin datos del campeón no sale gratis: lo típico de su pareja de roles
    e = eng(champs, {})
    res = e.blind_risk(1, "jungle", {"jungle": 1.0})
    tipico = BL.eta(e.bl, "jungle") * BL.expected_loss(BL.PAIR_PRIOR["jungle"]["jungle"], 7)
    assert res["loaded"] is False and res["risk"] == pytest.approx(-tipico)
    assert e.blind_risk(1, "jungle", dict.fromkeys(ROLES, 0.0))["risk"] == 0
