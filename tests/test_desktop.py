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
    monkeypatch.setattr(desktop, "request_show", lambda url: False)  # sin otro Nachero escuchando
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
    monkeypatch.setattr(
        desktop, "open_window", lambda url, state, storage, app: opened.append((url, state, storage, app))
    )
    port = free_port()
    M.run(["--port", str(port)])
    assert OPTS["window"] is True
    (abierta,) = opened
    assert abierta[:3] == (f"http://127.0.0.1:{port}/?v={M.__version__}", paths.window_file(), paths.webview_dir())
    assert abierta[3]["hidden"] is False and abierta[3]["cfg"] is M.CFG
    assert calls["browser"] == [] and calls["box"] == []


# ------------------------------------------------------------------ Win32 identity e icono


def test_set_app_model_id_invoca_shell32_en_win32(monkeypatch):
    called = []

    class FakeShell32:
        def SetCurrentProcessExplicitAppUserModelID(self, app_id):
            called.append(app_id)

    class FakeWinDLL:
        shell32 = FakeShell32()

    monkeypatch.setattr(desktop, "WIN", True)
    monkeypatch.setattr(desktop.ctypes, "windll", FakeWinDLL(), raising=False)
    desktop.set_app_model_id()
    assert called == [desktop.APP_MODEL_ID]


def test_set_app_model_id_no_falla_fuera_de_win32(monkeypatch):
    monkeypatch.setattr(desktop, "WIN", False)
    # Fuera de Windows no debe tocar nada ni fallar
    desktop.set_app_model_id()


def test_set_window_icon_invoca_loadimagew_y_sendmessage(tmp_path, monkeypatch):
    loaded = []
    sent = []

    class FakeFunc:
        def __init__(self, fn):
            self.fn = fn
            self.restype = None
            self.argtypes = None

        def __call__(self, *args, **kwargs):
            return self.fn(*args, **kwargs)

    class FakeUser32:
        def __init__(self):
            self.LoadImageW = FakeFunc(lambda inst, path, kind, w, h, flags: loaded.append((path, w, h)) or (w * 100))
            self.SendMessageW = FakeFunc(lambda hwnd, msg, wp, lp: sent.append((hwnd, msg, wp, lp)))

    monkeypatch.setattr(desktop, "WIN", True)
    monkeypatch.setattr(desktop.ctypes, "WinDLL", lambda name, use_last_error=False: FakeUser32(), raising=False)
    ico = tmp_path / "test.ico"
    ico.write_bytes(b"\x00\x00\x01\x00")
    desktop.set_window_icon(5555, ico)
    assert (str(ico), 16, 16) in loaded
    assert (str(ico), 32, 32) in loaded
    assert (5555, desktop.WM_SETICON, desktop.ICON_SMALL, 1600) in sent
    assert (5555, desktop.WM_SETICON, desktop.ICON_BIG, 3200) in sent


def test_set_window_icon_ignora_archivo_inexistente_o_sin_win32(tmp_path, monkeypatch):
    sent = []

    class FakeUser32:
        def SendMessageW(self, *a):
            sent.append(a)

    monkeypatch.setattr(desktop.ctypes, "WinDLL", lambda name, use_last_error=False: FakeUser32(), raising=False)
    monkeypatch.setattr(desktop, "WIN", False)
    desktop.set_window_icon(1234, tmp_path / "no_existe.ico")
    assert sent == []


def test_native_hwnd_con_form_o_fallback_findwindoww(monkeypatch):
    # Con window.native.Handle
    class FakeHandle:
        def ToInt64(self):
            return 9999

    class FakeNative:
        Handle = FakeHandle()

    class FakeWin:
        native = FakeNative()

    assert desktop.native_hwnd(FakeWin()) == 9999

    # Sin window.native: fallback a FindWindowW
    class EmptyWin:
        pass

    class FakeUser32:
        def FindWindowW(self, cls, title):
            return 8888

    monkeypatch.setattr(desktop, "WIN", True)
    monkeypatch.setattr(desktop, "_user32", lambda: FakeUser32())
    assert desktop.native_hwnd(EmptyWin()) == 8888


def test_open_window_registra_app_model_id_y_asigna_icono(tmp_path, monkeypatch):
    app_id_registered = []
    icons_passed = []
    window_icons_set = []

    monkeypatch.setattr(desktop, "set_app_model_id", lambda: app_id_registered.append(True))
    monkeypatch.setattr(desktop, "set_window_icon", lambda hwnd, p: window_icons_set.append((hwnd, p)))
    monkeypatch.setattr(desktop, "native_hwnd", lambda w: 7777)

    class FakeEvents:
        def __init__(self):
            self.before_show = []
            self.closing = []

    class FakeEventList:
        def __init__(self):
            self.callbacks = []

        def __iadd__(self, cb):
            self.callbacks.append(cb)
            return self

    class FakeWindow:
        def __init__(self):
            self.events = FakeEvents()
            self.events.before_show = FakeEventList()
            self.events.closing = FakeEventList()

    fake_win = FakeWindow()

    class FakeWebview:
        def create_window(self, *a, **kw):
            return fake_win

        def start(self, **kw):
            icons_passed.append(kw.get("icon"))
            # Disparar before_show
            for cb in fake_win.events.before_show.callbacks:
                cb(fake_win)

    import sys

    monkeypatch.setitem(sys.modules, "webview", FakeWebview())
    desktop.open_window("http://127.0.0.1:8765", tmp_path / "state.json", tmp_path / "storage")

    assert app_id_registered == [True]
    assert len(icons_passed) == 1
    assert len(window_icons_set) == 1
    assert window_icons_set[0][0] == 7777


def test_install_shortcut_fuera_de_win32(monkeypatch):
    monkeypatch.setattr(desktop, "WIN", False)
    assert "solo funcionan en Windows" in desktop.install_shortcut()


def test_install_shortcut_en_win32(tmp_path, monkeypatch):
    created = []
    monkeypatch.setattr(desktop, "WIN", True)
    monkeypatch.setattr(desktop, "_start_menu_dir", lambda: tmp_path / "StartMenu")
    monkeypatch.setattr(desktop, "_find_shortcut_target", lambda: tmp_path / "Nachero.exe")
    monkeypatch.setattr(
        desktop,
        "_create_lnk",
        lambda lnk, target, icon, app_id=desktop.APP_MODEL_ID: created.append((lnk, target, icon, app_id)),
    )

    res = desktop.install_shortcut()
    assert "Nachero.lnk" in res
    assert len(created) == 1
    assert created[0][1] == str(tmp_path / "Nachero.exe")


def test_install_shortcut_con_el_exe_usa_su_icono(tmp_path, monkeypatch):
    # #100: no el .ico de la carpeta temporal _MEI…, que se borra al cerrar Nachero
    exe = tmp_path / "Nachero.exe"
    exe.write_bytes(b"MZ")
    meipass = tmp_path / "_MEI123"
    (meipass / "nachero" / "ui").mkdir(parents=True)
    (meipass / "nachero" / "ui" / "icon.ico").write_bytes(b"ico")
    created = []
    monkeypatch.setattr(desktop, "WIN", True)
    monkeypatch.setattr(desktop.paths, "FROZEN", True)
    monkeypatch.setattr(desktop.sys, "_MEIPASS", str(meipass), raising=False)
    monkeypatch.setattr(desktop, "_start_menu_dir", lambda: tmp_path / "StartMenu")
    monkeypatch.setattr(desktop, "_find_shortcut_target", lambda: exe)
    monkeypatch.setattr(desktop, "_create_lnk", lambda lnk, target, icon, app_id="": created.append(icon))

    desktop.install_shortcut()
    assert created == [str(exe)]


def test_main_install_shortcut(capsys, monkeypatch):
    monkeypatch.setattr(desktop, "install_shortcut", lambda: r"C:\Start Menu\Nachero.lnk")
    M.main(["--install-shortcut"])
    out = capsys.readouterr().out
    assert "Acceso directo: C:\\Start Menu\\Nachero.lnk" in out
