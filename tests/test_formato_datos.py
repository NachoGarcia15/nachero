"""Formato de datos propio, esquema 1 (issue #18): validación, cálculo, fusión y lectura."""

import copy
from pathlib import Path

import pytest

from nachero.sources import dataset as D
from nachero.sources.local_stats import LocalStats

DATA = Path(__file__).parent / "data" / "stats"
CUR = DATA / "16.23" / "euw1" / "master_plus.json.gz"
PREV = DATA / "16.22" / "euw1" / "master_plus.json"


@pytest.fixture
def doc():
    return D.load_file(CUR)


@pytest.fixture
def prev():
    return D.load_file(PREV)


# ------------------------------------------------------------------ lectura y validación
def test_lee_json_y_json_gz(doc, prev):
    assert doc["schema"] == 1 and doc["patch"] == "16.23"
    assert prev["patch"] == "16.22"


def test_los_ejemplos_son_validos(doc, prev):
    assert D.validate(doc) == [] and D.validate(prev) == []


@pytest.mark.parametrize(
    ("cambio", "error"),
    [
        (lambda d: d.update(schema=2), "esquema 2"),
        (lambda d: d.pop("region"), "falta «region»"),
        (lambda d: d["totals"].update(games=0), "totals.games"),
        (lambda d: d["champions"]["163"]["roles"]["jungle"].update(wins=999), "más victorias que partidas"),
        (lambda d: d["champions"]["163"]["roles"].update(jungla={"games": 1, "wins": 0}), "163:jungla no válido"),
        (lambda d: d["champions"]["163"]["roles"]["jungle"]["runes"][0].update(pri=[1]), "runas de 163:jungle"),
        (lambda d: d["matchups"].update({"163-jungle": {}}), "clave '163-jungle'"),
        (lambda d: d["matchups"]["163:jungle"].update({"64:jungle": {"games": 5, "wins": 9}}), "victorias no válidas"),
        (lambda d: d["champions"]["163"].update(puuid="abc"), "identificadores de jugadores"),
    ],
)
def test_detecta_errores(doc, cambio, error):
    cambio(doc)
    assert any(error in e for e in D.validate(doc)), D.validate(doc)


def test_no_es_un_objeto():
    assert D.validate([]) == ["no es un objeto JSON"]


# ------------------------------------------------------------------ cálculo para el motor
def test_tier_list_por_rol(doc):
    out = D.derive(doc)
    tali = out["roles"]["jungle"]["champs"]["163"]
    assert tali["games"] == 300 and tali["wr"] == 55.0
    assert tali["pr"] == 15.0 and tali["br"] == 2.0  # 300 y 40 de 2000 partidas
    assert tali["pct"] == 75.0  # 300 de sus 400 partidas
    assert 1 <= tali["tier"] <= 15 and tali["rank"] >= 1
    assert out["roles"]["jungle"]["avg"] == pytest.approx((165 + 196) / 700 * 100, abs=0.01)


def test_matchups_con_delta_1_y_2(doc):
    out = D.derive(doc)
    row = out["matchups"]["163:jungle"]["jungle"]["64"]
    tali, lee = out["roles"]["jungle"]["champs"]["163"], out["roles"]["jungle"]["champs"]["64"]
    avg = out["roles"]["jungle"]["avg"]
    assert row["n"] == 90 and row["wr"] == pytest.approx(57.78, abs=0.01)
    assert row["d1"] == pytest.approx(row["wr"] - tali["wr"], abs=0.01)
    assert row["d2"] == pytest.approx(row["wr"] - (50 + (tali["wr"] - avg) - (lee["wr"] - avg)), abs=0.02)
    assert row["pr"] == 30.0


def test_runas_mas_jugada_y_de_mayor_wr(doc):
    pages = D.derive(doc)["runes"]["163:jungle"]
    assert pages["pick"]["pri"][0] == 8112  # 200 partidas
    assert pages["win"]["pri"][0] == 8128  # 61 % en 100 partidas


def test_sinergias(doc):
    assert D.derive(doc)["synergies"]["163:jungle"]["103:middle"] == {"wr": 62.5, "n": 40}


# ------------------------------------------------------------------ principio de parche
def test_mezcla_con_el_parche_anterior(doc, prev):
    solo = D.derive(doc)["roles"]["jungle"]["champs"]["163"]
    mezcla = D.derive(doc, prev)
    tali = mezcla["roles"]["jungle"]["champs"]["163"]
    # 300 partidas ahora: el anterior (900) pesa 1000 / 1300
    assert tali["games"] == round(300 + 900 * 1000 / 1300)
    assert tali["merged"] is True and mezcla["merged_with"] == "16.22"
    assert tali["wr"] == pytest.approx(55.0, abs=0.01) == solo["wr"]  # mismo WR en los dos parches


def test_con_muchas_partidas_el_anterior_apenas_pesa(doc, prev):
    big = copy.deepcopy(doc)
    big["champions"]["163"]["roles"]["jungle"].update(games=50000, wins=25000)
    tali = D.derive(big, prev)["roles"]["jungle"]["champs"]["163"]
    assert tali["wr"] == pytest.approx(50.0, abs=0.2)


def test_no_mezcla_otra_region(doc, prev):
    prev["region"] = "kr"
    assert D.derive(doc, prev).get("merged_with") is None


# ------------------------------------------------------------------ como fuente de la app
def test_archivo_suelto_del_esquema(tmp_path):
    s = LocalStats(CUR)
    assert s.patch == "16.23" and s.tier("jungle")["champs"]["163"]["wr"] == 55.0
    assert s.matchups(163, "jungle")["jungle"]["64"]["n"] == 90
    assert s.synergies(163, "jungle")["103:middle"]["n"] == 40
    assert s.updated_at() == pytest.approx(1795075200.0)  # 2026-11-19T08:00:00Z


def test_carpeta_publicada_con_mezcla(tmp_path):
    s = LocalStats(DATA)
    assert s.refresh_tiers("16.23") == 5
    assert s.data["merged_with"] == "16.22"
    assert s.tier("jungle")["champs"]["163"]["merged"] is True


def test_carpeta_sin_ese_parche():
    s = LocalStats(DATA)
    assert s.refresh_tiers("16.30") == 0 and s.problem == "no existe"


def test_el_parche_anterior_suelto_no_se_mezcla_con_nada():
    s = LocalStats(DATA)
    assert s.refresh_tiers("16.22") == 5 and s.data.get("merged_with") is None


def test_esquema_roto_avisa(tmp_path):
    f = tmp_path / "x.json"
    f.write_text('{"schema": 1, "patch": "16.23"}', encoding="utf-8")
    s = LocalStats(f)
    assert s.tier("jungle") is None and s.health.warnings()
