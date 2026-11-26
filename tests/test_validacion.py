"""¿Valen los datos propios? Comparación con Lolalytics (#21), sin red."""

import json
import random
import sys
from pathlib import Path

from nachero.domain import validation as V
from nachero.sources.compare import LolaCache, markdown, run
from nachero.sources.local_stats import LocalStats

ROOT = Path(__file__).resolve().parent.parent


def tier(rows, avg=50.0):
    """{cid: (wr, partidas, pr)} -> tier list del motor."""
    champs = {str(c): {"wr": wr, "games": n, "pr": pr} for c, (wr, n, pr) in rows.items()}
    return {"avg": avg, "games": sum(n for _, n, _ in rows.values()) // 2, "champs": champs}


def spread(n=20, games=20000, seed=3):
    rnd = random.Random(seed)
    return {c: (50 + rnd.gauss(0, 2), games, rnd.uniform(1, 10)) for c in range(1, n + 1)}


def test_iguales_coinciden_aunque_cambie_la_media_de_la_liga():
    rows = spread()
    own = tier({c: (wr + 1.5, n, pr) for c, (wr, n, pr) in rows.items()}, avg=51.5)  # otra liga: +1,5
    res = V.compare_role(own, tier(rows))
    assert res["common"] == 20 and res["wr_corr"] == 1.0 and res["pr_corr"] == 1.0
    assert res["mad"] == 0.0 and res["bias"] == 0.0 and res["outliers"] == 0
    assert res["signal"] > 0.9 and V.verdict(res)[0] == "good"


def test_un_campeon_desviado_sale_el_primero():
    rows = spread()
    own = dict(rows)
    own[7] = (rows[7][0] + 4, 20000, rows[7][2])  # 4 pp con 20.000 partidas: no es ruido
    res = V.compare_role(tier(own), tier(rows), top=3)
    assert res["worst"][0]["id"] == "7" and res["worst"][0]["z"] > 3 and res["outliers"] == 1


def test_al_principio_de_parche_casi_todo_es_ruido():
    rnd = random.Random(5)
    ref = spread(30)
    own = {c: (50 + rnd.gauss(0, 5), 150, pr) for c, (_, _, pr) in ref.items()}  # 150 partidas: ±4 pp de ruido
    res = V.compare_role(tier(own), tier(ref))
    assert res["signal"] is not None and res["signal"] < V.MIN_SIGNAL
    assert V.verdict(res)[0] in ("fair", "poor")


def test_sin_partidas_no_se_juzga():
    ref = spread()
    own = {c: (wr, 40, pr) for c, (wr, _, pr) in ref.items()}
    res = V.compare_role(tier(own), tier(ref), min_games=100)
    assert res["common"] == 0 and res["thin"] == 20 and V.verdict(res)[0] == "thin"
    assert V.compare_role(None, tier(ref))["common"] == 0


def test_matchups():
    own = {"jungle": {"64": {"d2": 1.0, "n": 300}, "11": {"d2": -2.0, "n": 300}, "5": {"d2": 0.5, "n": 10}},
           "middle": {"103": {"d2": 3.0, "n": 200}}}  # fmt: skip
    ref = {"jungle": {"64": {"d2": 1.5, "n": 900}, "11": {"d2": -1.0, "n": 900}, "5": {"d2": 9.0, "n": 900}},
           "middle": {"103": {"d2": 2.0, "n": 900}}}  # fmt: skip
    res = V.compare_matchups([(own, ref)], min_n=30)
    assert res["rows"] == 3 and res["pages"] == 1  # la de 10 partidas no cuenta
    assert res["d2_corr"] > 0.9 and res["mad"] == round((0.5 + 1.0 + 1.0) / 3, 2)


def escribir(tmp_path):
    rows = spread()
    own_file = tmp_path / "propios.json"
    matchups = {"7:jungle": {"jungle": {"1": {"wr": 51, "d1": 1, "d2": 1.0, "pr": 5, "n": 300},
                                        "2": {"wr": 49, "d1": -1, "d2": -1.0, "pr": 5, "n": 300},
                                        "3": {"wr": 50, "d1": 0, "d2": 0.2, "pr": 5, "n": 300}}}}  # fmt: skip
    own_file.write_text(json.dumps({
        "format": "nachero-stats", "version": 1, "patch": "16.23", "region": "euw1", "tier": "emerald_plus",
        "roles": {"jungle": tier(rows)}, "matchups": matchups,
    }))  # fmt: skip
    lola_file = tmp_path / "lolalytics_cache.json"
    lanes = {"jungle": {"1": {"d2": 1.2, "n": 900}, "2": {"d2": -0.8, "n": 900}, "3": {"d2": 0.1, "n": 900}}}
    lola_file.write_text(json.dumps({
        "tiers": {"jungle": {**tier(rows), "patch": "16.23"}},
        "builds": {"7:jungle": {"tier": "emerald_plus", "lanes": lanes}, "8:jungle": {"tier": "master_plus", "lanes": lanes}},
        "slugs": {"7": "taliyah"},
    }))  # fmt: skip
    return own_file, lola_file


def test_informe(tmp_path):
    own_file, lola_file = escribir(tmp_path)
    own = LocalStats(own_file, region="euw1", league="emerald_plus")
    lola = LolaCache(lola_file)
    res = run(own, lola)
    assert res["roles"]["jungle"]["wr_corr"] == 1.0 and res["roles"]["top"]["verdict"][0] == "thin"
    assert res["matchups"]["pages"] == 1 and res["matchups"]["rows"] == 3  # la página de otra liga no cuenta
    text = markdown(res, lola, 100)
    assert "| Jungla | " in text and "coinciden" in text and "parche 16.23" in text


def test_script(tmp_path, monkeypatch, home, capsys):
    own_file, lola_file = escribir(tmp_path)
    sys.path.insert(0, str(ROOT / "scripts"))
    try:
        import validar_datos
    finally:
        sys.path.pop(0)
    out = tmp_path / "informe.md"
    assert validar_datos.main(["--own", str(own_file), "--lola", str(lola_file), "--salida", str(out)]) == 0
    assert "Datos propios frente a Lolalytics" in out.read_text(encoding="utf-8")
    assert validar_datos.main(["--own", str(tmp_path / "no-existe"), "--lola", str(lola_file)]) == 1
