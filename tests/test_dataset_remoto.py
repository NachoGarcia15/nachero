"""Publicar el dataset propio y que la app lo descargue (issue #20), con un servidor local falso."""

import hashlib
import shutil
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from nachero.app import worker
from nachero.config import CFG, apply_settings
from nachero.domain.stats import ChainStats
from nachero.sources.lolalytics import Lolalytics
from nachero.sources.remote_stats import RemoteStats, pick_files
from nachero_collector.collect import publish_index

DATA = Path(__file__).parent / "data" / "stats"


@pytest.fixture
def site(tmp_path):
    """Carpeta publicada (con su index.json del recolector) servida en 127.0.0.1 con ETag."""
    root = tmp_path / "site"
    shutil.copytree(DATA, root)
    # el recolector publica .json.gz: el 16.22 de ejemplo está sin comprimir, se comprime aquí
    import gzip

    src = root / "16.22" / "euw1" / "master_plus.json"
    (root / "16.22" / "euw1" / "master_plus.json.gz").write_bytes(gzip.compress(src.read_bytes()))
    src.unlink()
    publish_index(root, now=lambda: 1_795_000_000)
    hits: list[tuple[str, int]] = []

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def do_GET(self):
            f = root / self.path.lstrip("/")
            if not f.is_file():
                hits.append((self.path, 404))
                self.send_response(404)
                self.end_headers()
                return
            body = f.read_bytes()
            etag = '"' + hashlib.md5(body).hexdigest() + '"'
            if self.headers.get("If-None-Match") == etag:
                hits.append((self.path, 304))
                self.send_response(304)
                self.end_headers()
                return
            hits.append((self.path, 200))
            self.send_response(200)
            self.send_header("ETag", etag)
            self.end_headers()
            self.wfile.write(body)

    srv = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_address[1]}", root, hits
    srv.shutdown()
    srv.server_close()


def remote(url, tmp_path, now=None):
    clock = now or (lambda: 1000.0)
    return RemoteStats(url, tmp_path / "cache", lambda *a, **k: None, clock=clock)


# ------------------------------------------------------------------ manifiesto
def test_el_recolector_publica_un_indice(site):
    _, root, _ = site
    index = publish_index(root, now=lambda: 1_795_000_000)
    assert [f["patch"] for f in index["files"]] == ["16.22", "16.23"]
    f = index["files"][1]
    assert f["path"] == "16.23/euw1/master_plus.json.gz" and f["games"] == 2000 and len(f["sha256"]) == 64


def test_elige_este_parche_y_el_anterior():
    index = {"files": [{"patch": p, "region": "euw1", "league": "master_plus", "path": f"{p}/x"} for p in
                       ("16.20", "16.21", "16.23", "16.24")] + [{"patch": "16.22", "region": "kr", "league": "master_plus", "path": "k"}]}  # fmt: skip
    assert [f["patch"] for f in pick_files(index, "16.23", "euw1", "master_plus")] == ["16.23", "16.21"]
    assert pick_files(index, "16.19", "euw1", "master_plus") == []


# ------------------------------------------------------------------ descarga
def test_descarga_y_lee_los_datos_propios(site, tmp_path):
    url, _, hits = site
    s = remote(url, tmp_path)
    assert s.refresh_tiers("16.23") == 5
    assert s.name == "Datos propios" and s.data["merged_with"] == "16.22"
    assert [h for h, _ in hits] == ["/index.json", "/16.23/euw1/master_plus.json.gz", "/16.22/euw1/master_plus.json.gz"]
    assert (tmp_path / "cache" / "16.23" / "euw1" / "master_plus.json.gz").is_file()


def test_con_etag_no_vuelve_a_descargar(site, tmp_path):
    url, _, hits = site
    now = [1000.0]
    s = remote(url, tmp_path, lambda: now[0])
    s.refresh_tiers("16.23")
    hits.clear()
    s.refresh_tiers("16.23")  # menos de una hora: ni pregunta
    assert hits == []
    now[0] += 3600
    s.refresh_tiers("16.23")
    assert {code for _, code in hits} == {304}  # pregunta con If-None-Match y no baja nada


def test_sin_red_usa_lo_guardado(site, tmp_path):
    url, _, _ = site
    remote(url, tmp_path).refresh_tiers("16.23")
    caido = remote("http://127.0.0.1:9", tmp_path)  # nadie escucha
    assert caido.refresh_tiers("16.23") == 5 and caido.sync_error


def test_archivo_alterado_no_se_usa(site, tmp_path):
    url, root, _ = site
    (root / "16.23" / "euw1" / "master_plus.json.gz").write_bytes(b"\x1f\x8b roto")
    s = remote(url, tmp_path)
    assert s.refresh_tiers("16.23") == 0 and "sha256" in s.sync_error
    assert s.health.warnings()


def test_sin_direccion_no_pide_nada(tmp_path):
    s = RemoteStats("", tmp_path / "c", lambda *a, **k: None, fetch=lambda u, h: pytest.fail("no debe pedir"))
    assert s.refresh_tiers("16.23") == 0 and s.sync_error == "sin dirección de los datos propios"
    assert RemoteStats("ftp://x", tmp_path / "c", fetch=lambda u, h: pytest.fail("no")).refresh_tiers("16.23") == 0


def test_no_escribe_fuera_de_su_carpeta(tmp_path):
    index = b'{"files": [{"patch": "16.23", "region": "euw1", "league": "master_plus", "path": "../../fuera.json.gz"}]}'

    def fetch(url, headers):
        return (200, {}, index) if url.endswith("index.json") else pytest.fail("no debe bajar rutas raras")

    RemoteStats("https://datos.example", tmp_path / "c", lambda *a, **k: None, fetch=fetch).sync("16.23")
    assert not (tmp_path.parent / "fuera.json.gz").exists()


# ------------------------------------------------------------------ elegir la fuente
@pytest.fixture
def cfg(home, monkeypatch):
    for k, v in {"stats_sources": ["lolalytics"], "stats_mode": "auto", "stats_url": "", "stats_file": ""}.items():
        monkeypatch.setitem(CFG, k, v)
    return CFG


@pytest.mark.parametrize(
    ("mode", "url", "esperado"),
    [
        ("auto", "", ["lolalytics"]),
        ("auto", "https://datos.example", ["remote", "lolalytics"]),
        ("own", "https://datos.example", ["remote"]),
        ("own", "", ["local"]),
        ("lolalytics", "https://datos.example", ["lolalytics"]),
    ],
)
def test_fuentes_segun_el_modo(cfg, mode, url, esperado):
    cfg["stats_mode"], cfg["stats_url"] = mode, url
    assert worker.source_names() == esperado


def test_fuentes_a_mano_mandan(cfg):
    cfg["stats_sources"] = ["local", "lolalytics"]
    assert worker.source_names() == ["local", "lolalytics"]


def test_ajuste_de_modo():
    c: dict = {}
    assert apply_settings(c, {"stats_mode": "own"}) == ["fuente de estadísticas propia"]
    assert apply_settings(c, {"stats_mode": "otra"}) == [] and c["stats_mode"] == "own"


def test_automatica_dice_cuando_usa_el_respaldo(site, tmp_path):
    url, _, _ = site
    own = remote(url, tmp_path)
    lola = Lolalytics(str(tmp_path / "lola"), lambda *a, **k: None)
    chain = ChainStats([own, lola])
    own.refresh_tiers("16.23")
    assert worker.fallback_note(chain, "16.23") is None
    own.refresh_tiers("16.30")  # aún no hay datos propios de este parche
    assert worker.fallback_note(chain, "16.30") == "Sin datos propios del parche 16.30: uso " + chain.source()
