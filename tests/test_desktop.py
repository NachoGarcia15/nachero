"""App de escritorio (#44): ventana, instancia única, estado de la ventana y arranque sin consola.

Sin abrir ventanas: lo que toca Windows se sustituye y se prueba la lógica que lo rodea."""

import json
import os
import socket
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from nachero import paths
from nachero.app import desktop
from nachero.app import main as M
from nachero.app.server import Handler
from nachero.app.state import OPTS
from nachero.jsonio import read_json, write_json


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture
def server():
    """Servidor del panel de verdad en un puerto libre; devuelve su URL."""
    srv = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_address[1]}"
    srv.shutdown()
    srv.server_close()


# ------------------------------------------------------------------ argumentos


def test_modo_por_defecto_es_la_ventana():
    assert M.ui_mode(M.parse_args([])) == "window"
    assert M.ui_mode(M.parse_args(["--browser"])) == "browser"
    assert M.ui_mode(M.parse_args(["--no-browser"])) == "none"
    assert M.ui_mode(M.parse_args(["--browser", "--no-browser"])) == "none"


def test_opciones_que_escriben_en_el_terminal():
    assert desktop.wants_console(["--version"]) and desktop.wants_console(["--port", "1", "--profile"])
    assert desktop.wants_console(["-h"])
    assert not desktop.wants_console([]) and not desktop.wants_console(["--demo", "--browser"])


# ------------------------------------------------------------------ sin consola


def test_sin_consola_la_salida_se_descarta_sin_fallar(monkeypatch):
    monkeypatch.setattr(sys, "stdout", None)
    monkeypatch.setattr(sys, "stderr", None)
    desktop.setup_streams([])
    assert sys.stdout is not None and sys.stderr is not None
    print("nadie lo lee")  # no falla
    sys.stdout.close()
    sys.stderr.close()


def test_con_consola_no_se_toca_la_salida(monkeypatch):
    out, err = sys.stdout, sys.stderr
    desktop.setup_streams(["--version"])
    assert sys.stdout is out and sys.stderr is err


def test_version_sin_consola_no_abre_nada(monkeypatch, capsys):
    """La comprobación del CI: --version sale con código 0 aunque no haya consola."""
    monkeypatch.setattr(desktop, "attach_parent_console", lambda: False)
    monkeypatch.setattr(sys, "stdout", None)
    monkeypatch.setattr(sys, "stderr", None)
    with pytest.raises(SystemExit) as e:
        M.main(["--version"])
    assert e.value.code == 0


def test_error_al_arrancar_en_el_ejecutable_sale_en_un_dialogo(home, monkeypatch):
    shown = []
    monkeypatch.setattr(paths, "FROZEN", True)
    monkeypatch.setattr(desktop, "message_box", lambda text, kind="error", title="Nachero": shown.append((text, kind)))

    def boom(argv):
        raise RuntimeError("no hay disco")

    monkeypatch.setattr(M, "run", boom)
    M.main([])
    (text, kind), *_ = shown
    assert kind == "error" and "RuntimeError: no hay disco" in text and str(home / "logs") in text


def test_error_al_arrancar_desde_el_codigo_se_lanza(monkeypatch):
    def boom(argv):
        raise RuntimeError("visible en el terminal")

    monkeypatch.setattr(M, "run", boom)
    with pytest.raises(RuntimeError):
        M.main([])


# ------------------------------------------------------------------ instancia única


def test_el_puerto_ocupado_se_detecta():
    first = M.bind(0, Handler)
    assert first is not None
    try:
        assert M.bind(first.server_address[1], Handler) is None
    finally:
        first.server_close()


def test_el_panel_dice_quien_es(server, monkeypatch):
    monkeypatch.setitem(OPTS, "window", True)
    info = desktop.probe_instance(server)
    assert info is not None
    assert info["app"] == "nachero" and info["pid"] == os.getpid() and info["window"] is True


def test_otro_programa_en_el_puerto_no_es_nachero():
    class Otro(BaseHTTPRequestHandler):
        def do_GET(self):
            body = json.dumps({"app": "otra"}).encode()
            self.send_response(200)
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *a):
            pass

    srv = ThreadingHTTPServer(("127.0.0.1", 0), Otro)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        assert desktop.probe_instance(f"http://127.0.0.1:{srv.server_address[1]}") is None
    finally:
        srv.shutdown()
        srv.server_close()
    assert desktop.probe_instance(f"http://127.0.0.1:{free_port()}", timeout=1) is None  # nadie escucha


@pytest.fixture
def calls(monkeypatch):
    """Sustituye lo que abre cosas (ventanas, navegador, diálogos) y apunta las llamadas."""
    seen: dict[str, list] = {"front": [], "browser": [], "box": []}
    monkeypatch.setattr(desktop, "bring_to_front", lambda pid: seen["front"].append(pid) or True)
    monkeypatch.setattr(M.webbrowser, "open", lambda url: seen["browser"].append(url))
    monkeypatch.setattr(desktop, "message_box", lambda text, kind="error", title="Nachero": seen["box"].append(text))
    monkeypatch.setattr(desktop, "has_console", lambda: False)
    return seen


def test_segunda_instancia_trae_la_ventana_al_frente(calls, monkeypatch):
    monkeypatch.setattr(desktop, "probe_instance", lambda url: {"app": "nachero", "pid": 4321, "window": True})
    M.another_instance("http://127.0.0.1:8765", 8765, "window")
    assert calls == {"front": [4321], "browser": [], "box": []}


def test_segunda_instancia_sin_ventana_abre_el_panel(calls, monkeypatch):
    monkeypatch.setattr(desktop, "probe_instance", lambda url: {"app": "nachero", "pid": 4321, "window": False})
    M.another_instance("http://127.0.0.1:8765", 8765, "window")
    assert calls["front"] == [] and calls["browser"][0].startswith("http://127.0.0.1:8765/")


def test_puerto_de_otro_programa_avisa(calls, monkeypatch):
    monkeypatch.setattr(desktop, "probe_instance", lambda url: None)
    M.another_instance("http://127.0.0.1:8765", 8765, "window")
    assert calls["front"] == [] and calls["browser"] == []
    assert "8765" in calls["box"][0]


def test_pick_window_es_la_visible_del_proceso_con_ese_titulo():
    windows = [
        (1, 50, True, "Nachero"),  # otro proceso (p. ej. una carpeta llamada así)
        (2, 99, False, "Nachero"),  # oculta
        (3, 99, True, "WebView2"),
        (4, 99, True, "Nachero"),
    ]
    assert desktop.pick_window(windows, 99) == 4
    assert desktop.pick_window(windows, 7) is None


# ------------------------------------------------------------------ estado de la ventana


def test_estado_de_la_ventana_valido():
    raw = {"left": -1900, "top": 40, "right": -500, "bottom": 900, "maximized": 1}
    assert desktop.clean_placement(raw) == {"left": -1900, "top": 40, "right": -500, "bottom": 900, "maximized": True}
    assert desktop.clean_placement({"left": "10", "top": 10, "right": 1290, "bottom": 870})["maximized"] is False


@pytest.mark.parametrize(
    "raw",
    [
        None,
        [],
        "x",
        {"left": 0, "top": 0, "right": 1280},  # falta bottom
        {"left": 0, "top": 0, "right": 100, "bottom": 900},  # demasiado estrecha
        {"left": 0, "top": 0, "right": 1280, "bottom": 50},  # demasiado baja
        {"left": "a", "top": 0, "right": 1280, "bottom": 800},
        {"left": 0, "top": 0, "right": 10**9, "bottom": 800},  # absurda
    ],
)
def test_estado_de_la_ventana_roto_se_ignora(raw):
    assert desktop.clean_placement(raw) is None


def test_estado_de_la_ventana_se_guarda_en_la_carpeta_del_usuario(home):
    assert paths.window_file().parent == home and paths.webview_dir().parent == home
    write_json(paths.window_file(), {"left": 10, "top": 20, "right": 1290, "bottom": 880, "maximized": False})
    assert desktop.clean_placement(read_json(paths.window_file()))["right"] == 1290


# ------------------------------------------------------------------ sin WebView2


def test_sin_webview2_abre_el_navegador_y_el_aviso_hace_de_ventana(home, calls, monkeypatch):
    """Sin WebView2: el panel en el navegador y, sin consola, un aviso que al cerrarse cierra Nachero."""
    import nachero.app.worker as W

    monkeypatch.setitem(OPTS, "window", True)
    monkeypatch.setattr(W, "worker", lambda: None)  # sin cliente ni red
    monkeypatch.setattr(desktop, "window_problem", lambda: "falta WebView2")
    monkeypatch.setattr(desktop, "open_window", lambda *a: pytest.fail("no debe abrir la ventana"))
    port = free_port()
    M.run(["--port", str(port)])
    assert OPTS["window"] is False
    assert calls["browser"] == [f"http://127.0.0.1:{port}/?v={M.__version__}"]
    (text,) = calls["box"]
    assert "WebView2" in text and "pulsa Aceptar para cerrarlo" in text


def test_con_webview2_abre_la_ventana(home, calls, monkeypatch):
    import nachero.app.worker as W

    opened = []
    monkeypatch.setitem(OPTS, "window", False)
    monkeypatch.setattr(W, "worker", lambda: None)
    monkeypatch.setattr(desktop, "window_problem", lambda: None)
    monkeypatch.setattr(desktop, "open_window", lambda url, state, storage: opened.append((url, state, storage)))
    port = free_port()
    M.run(["--port", str(port)])
    assert OPTS["window"] is True
    assert opened == [(f"http://127.0.0.1:{port}/?v={M.__version__}", paths.window_file(), paths.webview_dir())]
    assert calls["browser"] == [] and calls["box"] == []
