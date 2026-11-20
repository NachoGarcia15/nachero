"""Frescura de los datos y aviso si cambia el formato de una fuente (issue #8)."""

import json
import time
import urllib.error

import pytest

from nachero.app import worker
from nachero.sources import golgg as G
from nachero.sources.health import FormatChanged, Health, is_format_error
from nachero.sources.local_stats import LocalStats
from nachero.sources.lolalytics import Lolalytics, parse_build, parse_tier

# ------------------------------------------------------------------ páginas de ejemplo mínimas
TIER_OK = {"avgWr": 50.6, "cid": {"163": {"wr": 53.4, "pr": 4.7, "br": 1.2, "games": 21896, "tier": 3, "rank": 7,
                                          "pctLane": 51.3}}}  # fmt: skip
GOL_ROW = (
    "<tr><td><a href='../champion-stats/163/'>Taliyah</a></td><td>12</td><td>3</td><td>40%</td><td>7</td>"
    "<td>5</td><td>58%</td><td>x</td><td>1.2</td><td>2.1</td><td>3</td></tr>"
)


def test_tier_list_de_ejemplo():
    assert parse_tier(TIER_OK)["163"] == {"wr": 53.4, "pr": 4.7, "br": 1.2, "games": 21896, "tier": 3, "rank": 7,
                                          "pct": 51.3}  # fmt: skip


@pytest.mark.parametrize("d", [{}, {"cid": {}}, {"cid": []}, [], {"data": {"163": {}}}])
def test_tier_list_con_otro_formato(d):
    with pytest.raises(FormatChanged):
        parse_tier(d)


def test_pagina_de_build_sin_estado_qwik():
    with pytest.raises(FormatChanged):
        parse_build("<html><body>nueva web</body></html>")


def test_tabla_de_gol_de_ejemplo():
    rows = G.parse_gol(f"<table>{GOL_ROW}</table>")
    assert rows["taliyah"]["picks"] == 12 and rows["taliyah"]["wr"] == 58.0
    assert G.parse_gol("<table><tr><td>otra cosa</td></tr></table>") == {}


# ------------------------------------------------------------------ salud de una fuente
def test_red_no_es_cambio_de_formato():
    assert not is_format_error(urllib.error.URLError("sin red"))
    assert not is_format_error(TimeoutError())
    assert is_format_error(FormatChanged("x")) and is_format_error(json.JSONDecodeError("x", "", 0))
    assert is_format_error(KeyError("wr"))


def test_avisa_una_vez_tras_varios_fallos_seguidos():
    avisos = []
    h = Health("Lolalytics", lambda msg, kind="info": avisos.append((kind, msg)), {"builds": 3})
    h.ok("builds", now=1000)
    assert h.fail("builds", FormatChanged("vacía")) is False
    assert h.fail("builds", OSError("red")) is False  # la red no cuenta
    assert h.fail("builds", FormatChanged("vacía")) is False
    assert h.fail("builds", FormatChanged("vacía")) is True
    assert h.fail("builds", FormatChanged("vacía")) is True
    assert [k for k, _ in avisos] == ["warn"]  # un solo aviso en Actividad
    (w,) = h.warnings()
    assert w["source"] == "Lolalytics" and w["kind"] == "builds" and w["last_ok"] == 1000
    h.ok("builds")
    assert h.warnings() == [] and avisos[-1][0] == "ok"


# ------------------------------------------------------------------ seguir con la caché
def test_lolalytics_con_otro_formato_conserva_la_tier_list(tmp_path, monkeypatch):
    avisos = []
    lola = Lolalytics(str(tmp_path), lambda msg, kind="info": avisos.append((kind, msg)))
    lola.cache["tiers"] = {"jungle": {"t": 1.0, "patch": "16.22", "avg": 50, "games": 9, "champs": {"163": {}}}}
    monkeypatch.setattr(lola, "_fetch", lambda url: json.dumps({"nuevo": "formato"}))
    lola.refresh_tiers("16.23")
    assert lola.tier("jungle")["champs"] == {"163": {}}  # la buena sigue ahí
    assert lola.health.warnings()[0]["kind"] == "tiers"
    assert any("ha cambiado su página" in m for _, m in avisos)


def test_lolalytics_sin_red_no_avisa_de_cambio(tmp_path, monkeypatch):
    lola = Lolalytics(str(tmp_path), lambda *a, **k: None)

    def sin_red(url):
        raise urllib.error.URLError("sin red")

    monkeypatch.setattr(lola, "_fetch", sin_red)
    lola.refresh_tiers("16.23")
    assert lola.health.warnings() == []


def test_gol_sin_tabla_usa_los_datos_guardados(tmp_path, monkeypatch):
    gol = G.GolGG(str(tmp_path), lambda *a, **k: None)
    old = {"t": time.time() - 2 * G.GolGG.TTL, "games": 10, "all": {"taliyah": {}}, "roles": {}}
    gol.cache = {"tournaments": {"t": time.time(), "season": "S16", "majors": [], "all": []}, "data": {"Worlds": old}}
    assert gol.dataset("Worlds") is None  # caducado
    monkeypatch.setattr(gol, "_get", lambda op, url, data=None: "<html>gol.gg nuevo</html>")
    gol.load("Worlds")
    assert gol.dataset("Worlds") is old  # sigue con lo guardado
    assert gol.health.warnings()[0]["source"] == "gol.gg"


def test_gol_frescura_del_ultimo_torneo(tmp_path):
    gol = G.GolGG(str(tmp_path), lambda *a, **k: None)
    gol.cache = {"tournaments": None, "data": {"A": {"t": 5, "games": 1}, "B": {"t": 9, "games": 2}}}
    assert gol.updated() == {"tournament": "B", "t": 9, "games": 2}
    gol.cache["data"] = {}
    assert gol.updated() is None


def test_archivo_local_roto_avisa_en_el_panel(tmp_path):
    f = tmp_path / "s.json"
    f.write_text(json.dumps({"format": "otro"}), encoding="utf-8")
    assert worker.source_warnings(LocalStats(f))[0]["source"] == "Archivo local"


# ------------------------------------------------------------------ estado para el panel
class Prov:
    name, pending = "Lolalytics", set()

    def __init__(self, updated, patch="16.23"):
        self.u, self.patch = updated, patch
        self.health = Health("Lolalytics")

    def stats(self):
        return {"games": 10, "builds": 2}

    def updated_at(self):
        return self.u


def test_datos_frescos():
    st = worker.data_status(Prov(1000.0), "16.23", now=1000.0 + 3600)
    assert st["stale"] is False and st["warnings"] == [] and st["source"] == "Lolalytics" and st["pro"] is None


def test_datos_viejos_o_de_otro_parche():
    assert worker.data_status(Prov(0.0 + 1), "16.23", now=2 * 86400)["stale"] is True
    assert worker.data_status(Prov(1000.0, "16.22"), "16.23", now=1000.0)["stale"] is True


def test_avisos_de_formato_llegan_al_panel(tmp_path):
    p = Prov(1000.0)
    p.health.fail("tiers", FormatChanged("vacía"))
    gol = G.GolGG(str(tmp_path), lambda *a, **k: None)
    st = worker.data_status(p, "16.23", gol, now=1000.0)
    assert [w["source"] for w in st["warnings"]] == ["Lolalytics"]
