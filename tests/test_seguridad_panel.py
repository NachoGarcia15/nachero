"""El panel solo atiende al propio panel: otra web abierta en el navegador no puede usarlo.

El servidor escucha en 127.0.0.1, pero el navegador deja que cualquier web le mande peticiones:
sin estas comprobaciones, una página podía activar «Confirmar pick», cambiar la fuente de datos o
el inicio con Windows, marcar un campeón o pedir un intercambio (CSRF), y con un nombre que
apunte a 127.0.0.1 (DNS rebinding), leer tu estado."""

import json
import threading
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer

import pytest

from nachero.app.server import Handler, refusal
from nachero.app.state import APP


@pytest.fixture
def panel(monkeypatch):
    monkeypatch.setitem(APP, "mode", "observe")
    srv = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield srv.server_address[1]
    srv.shutdown()
    srv.server_close()


def call(port, path, body=None, headers=None, method=None):
    """(código, respuesta) de una petición al panel, con las cabeceras que se pidan."""
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    data = body if isinstance(body, bytes) or body is None else json.dumps(body).encode()
    req = urllib.request.Request(f"http://127.0.0.1:{port}{path}", data=data, method=method, headers=headers or {})
    try:
        with opener.open(req, timeout=5) as r:
            return r.status, json.loads(r.read() or b"null")
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read() or b"null")


JSON = {"Content-Type": "application/json"}


def test_el_panel_y_la_otra_instancia_pasan(panel):
    assert call(panel, "/api/instance")[0] == 200
    for origin in (None, f"http://127.0.0.1:{panel}", f"http://localhost:{panel}"):
        headers = {**JSON, **({"Origin": origin} if origin else {})}
        assert call(panel, "/api/mode", {"mode": "paused"}, headers) == (200, {"ok": True})
    assert APP["mode"] == "paused"


@pytest.mark.parametrize(
    "headers",
    [
        {**JSON, "Origin": "https://evil.example"},  # fetch con CORS desde otra web
        {"Content-Type": "text/plain", "Origin": "https://evil.example"},  # fetch no-cors
        {"Content-Type": "text/plain"},  # formulario o no-cors sin Origin
        {**JSON, "Origin": "null"},  # iframe con sandbox o archivo local
        {**JSON, "Host": "evil.example:8765"},  # DNS rebinding
    ],
)
def test_otra_web_no_puede_mandar_ordenes(panel, headers):
    code, out = call(panel, "/api/mode", {"mode": "active"}, headers)
    assert code == 403 and "rechazada" in out["error"]
    assert APP["mode"] == "observe"


def test_dns_rebinding_no_lee_el_estado(panel):
    assert call(panel, "/api/state", headers={"Host": f"evil.example:{panel}"})[0] == 403
    assert call(panel, "/", headers={"Host": f"127.0.0.1.evil.example:{panel}"})[0] == 403


def test_cuerpos_raros(panel):
    assert call(panel, "/api/mode", b"[1, 2]", JSON)[0] == 400
    assert call(panel, "/api/mode", b"{no es json", JSON)[0] == 400
    big = {**JSON, "Content-Length": str(2 << 20)}
    assert call(panel, "/api/mode", b"{}", big)[0] == 413


def test_refusal_sin_servidor():
    ok = {"Host": "127.0.0.1:8765", "Content-Type": "application/json; charset=utf-8"}
    assert refusal(ok, "POST", 8765) is None
    assert refusal({**ok, "Host": "LOCALHOST:8765"}, "POST", 8765) is None
    assert refusal({**ok, "Host": "127.0.0.1:8766"}, "GET", 8765) == "host"  # otro puerto
    assert refusal({"Host": "127.0.0.1:8765"}, "GET", 8765) is None  # un GET no necesita JSON
    assert refusal({}, "GET", 8765) == "host"


def test_el_panel_no_pide_nada_fuera(panel):
    """Fuentes servidas por el propio panel (#27): ni Google Fonts ni otro sitio al abrirlo."""
    import re
    from pathlib import Path

    ui = Path(__file__).resolve().parent.parent / "src" / "nachero" / "ui"
    for name in ("index.html", "style.css"):
        text = (ui / name).read_text(encoding="utf-8")
        assert not re.search(r"(src|href)=[\"']https?://|url\(\s*[\"']?https?://|@import", text), name
    # la licencia OFL va junto a las fuentes
    assert (ui / "geist-ofl.txt").read_text(encoding="utf-8").startswith("Copyright")
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(f"http://127.0.0.1:{panel}/geist.woff2", timeout=5) as r:
        assert r.headers["Content-Type"] == "font/woff2" and r.read(4) == b"wOF2"


def test_abrir_las_carpetas_de_registros_y_de_datos(panel, monkeypatch, home):
    from nachero import paths
    from nachero.app import desktop

    abiertas = []
    monkeypatch.setattr(desktop, "open_folder", lambda p: abiertas.append(p))
    assert call(panel, "/api/open-folder", {"which": "logs"}, JSON) == (200, {"ok": True})
    assert call(panel, "/api/open-folder", {"which": "data"}, JSON) == (200, {"ok": True})
    assert abiertas == [paths.log_dir(), paths.user_dir()]
    assert call(panel, "/api/open-folder", {"which": "C:/Windows"}, JSON)[0] == 400  # solo esas dos
    monkeypatch.setattr(desktop, "open_folder", lambda p: "solo en Windows")
    code, out = call(panel, "/api/open-folder", {"which": "logs"}, JSON)
    assert code == 409 and "solo en Windows" in out["error"]
    assert call(panel, "/api/open-folder", {"which": "logs"}, {"Content-Type": "text/plain"})[0] == 403
