"""Bandeja del sistema, abrir al iniciar Windows y aviso de nueva versión (issue #6)."""

import json
from pathlib import Path

import pytest

from nachero import config, paths
from nachero.app import desktop, server, updates
from nachero.app import main as M
from nachero.app.state import APP, OPTS
from nachero.app.tray import CMD_OPEN, CMD_QUIT, TRAY_HINT, Tray, close_action, menu_items
from nachero.config import CFG


# ------------------------------------------------------------------ bandeja
def test_menu_de_la_bandeja_marca_el_modo_actual():
    items = menu_items("observe")
    assert items[0] == (CMD_OPEN, "Abrir Nachero", False)
    assert items[-1] == (CMD_QUIT, "Salir de Nachero", False)
    marcados = [text for cid, text, checked in items if checked]
    assert marcados == ["Observar"]
    assert [i for i in items if i[0] == 0] == [(0, "", False)] * 2  # dos separadores


@pytest.mark.parametrize(
    ("cfg", "tray_ok", "quitting", "esperado"),
    [
        ({}, True, False, "hide"),  # por defecto, a la bandeja
        ({"close_to_tray": False}, True, False, "quit"),  # ajuste: cerrar sale
        ({}, False, False, "quit"),  # sin bandeja no se puede esconder
        ({}, True, True, "quit"),  # «Salir» del menú
    ],
)
def test_que_hace_cerrar_la_ventana(cfg, tray_ok, quitting, esperado):
    assert close_action(cfg, tray_ok, quitting) == esperado


def test_fuera_de_windows_no_hay_bandeja():
    t = Tray(Path("icon.ico"), lambda: "observe", lambda: None, lambda m: None, lambda: None)
    if not desktop.WIN:
        assert t.start() is False
    t.notify(*TRAY_HINT)  # sin icono no hace nada
    t.stop()


def test_cambiar_el_modo_desde_la_bandeja(monkeypatch):
    monkeypatch.setitem(APP, "mode", "observe")
    M.set_mode("active")
    assert APP["mode"] == "active"
    M.set_mode("raro")
    assert APP["mode"] == "active"


def test_por_defecto_cerrar_deja_en_la_bandeja_y_no_arranca_con_windows():
    cfg = json.loads(paths.DEFAULT_CONFIG.read_text(encoding="utf-8"))
    assert cfg["close_to_tray"] is True and cfg["start_with_windows"] is False
    assert cfg["tray_hint_shown"] is False and cfg["update_url"] == ""


def test_ajustes_de_la_app():
    cfg: dict = {}
    assert config.apply_settings(cfg, {"close_to_tray": False, "start_with_windows": True}) == [
        "close_to_tray",
        "start_with_windows",
    ]
    assert config.apply_settings(cfg, {"close_to_tray": "no"}) == []


def test_arrancar_en_la_bandeja():
    assert M.parse_args(["--tray"]).tray is True
    assert M.window_controls(True)["hidden"] is True


# ------------------------------------------------------------------ otro Nachero pide mostrar la ventana
def test_mostrar_la_ventana_desde_otra_instancia(monkeypatch):
    shown = []
    monkeypatch.setitem(OPTS, "show_window", lambda: shown.append(True))
    assert OPTS["show_window"] is not None
    OPTS["show_window"]()
    assert shown == [True]


def test_segunda_instancia_pide_mostrar_la_ventana_escondida(monkeypatch):
    seen = {"allow": [], "show": [], "front": []}
    monkeypatch.setattr(desktop, "probe_instance", lambda url: {"app": "nachero", "pid": 77, "window": True})
    monkeypatch.setattr(desktop, "allow_foreground", lambda pid: seen["allow"].append(pid))
    monkeypatch.setattr(desktop, "request_show", lambda url: seen["show"].append(url) or True)
    monkeypatch.setattr(desktop, "bring_to_front", lambda pid: seen["front"].append(pid))
    M.another_instance("http://127.0.0.1:8765", 8765, "window")
    assert seen == {"allow": [77], "show": ["http://127.0.0.1:8765"], "front": []}


# ------------------------------------------------------------------ abrir al iniciar Windows
@pytest.mark.parametrize(
    ("target", "esperado"),
    [
        (Path(r"C:\Apps\Nachero.exe"), '"C:\\Apps\\Nachero.exe" --tray'),
        (Path(r"C:\Py\pythonw.exe"), '"C:\\Py\\pythonw.exe" -m nachero --tray'),
    ],
)
def test_orden_de_inicio_con_windows(target, esperado):
    assert desktop.autostart_command(target) == esperado


def test_inicio_con_windows_fuera_de_windows(monkeypatch):
    monkeypatch.setattr(desktop, "WIN", False)
    assert desktop.set_autostart(True) == "solo en Windows"
    assert desktop.autostart_enabled() is False


def test_el_panel_cambia_el_inicio_con_windows(monkeypatch):
    calls = []
    monkeypatch.setitem(CFG, "start_with_windows", False)
    monkeypatch.setattr(desktop, "set_autostart", lambda on: calls.append(on) or None)
    assert server.autostart_change({"start_with_windows": True}) is None
    assert server.autostart_change({"start_with_windows": False}) is None  # ya estaba así
    assert server.autostart_change({"pick_mode": "meta"}) is None
    assert calls == [True]


def test_si_windows_no_deja_no_se_guarda(monkeypatch):
    monkeypatch.setitem(CFG, "start_with_windows", False)
    monkeypatch.setattr(desktop, "set_autostart", lambda on: "acceso denegado")
    assert "acceso denegado" in server.autostart_change({"start_with_windows": True})


# ------------------------------------------------------------------ aviso de nueva versión
@pytest.mark.parametrize(
    ("latest", "current", "esperado"),
    [("0.17.0", "0.16.0", True), ("v1.0.0", "0.16.3", True), ("0.16.0", "0.16.0", False),
     ("0.9.0", "0.16.0", False), ("raro", "0.16.0", False), ("0.16.10", "0.16.9", True)],
)  # fmt: skip
def test_compara_versiones(latest, current, esperado):
    assert updates.newer(latest, current) is esperado


def test_lee_el_latest_json():
    data = {"version": "0.17.0", "url": "https://example.com/Nachero.exe", "notes": "  Bandeja  "}
    assert updates.read_latest(data, "0.16.0") == {
        "version": "0.17.0",
        "url": "https://example.com/Nachero.exe",
        "notes": "Bandeja",
    }
    assert updates.read_latest(data, "0.17.0") is None
    assert updates.read_latest({**data, "url": "http://inseguro"}, "0.16.0") is None
    assert updates.read_latest({**data, "url": "javascript:alert(1)"}, "0.16.0") is None
    assert updates.read_latest([], "0.16.0") is None


def test_comprobar_sin_url_no_pide_nada():
    def fetch(url, timeout):
        raise AssertionError("no debe pedir nada")

    assert updates.check("", "0.16.0", fetch) is None
    assert updates.check("http://sin-https", "0.16.0", fetch) is None


def test_comprobar_con_fallos_no_avisa():
    def falla(url, timeout):
        raise OSError("sin red")

    assert updates.check("https://x/latest.json", "0.16.0", falla) is None
    assert updates.check("https://x/latest.json", "0.16.0", lambda u, t: b"no es json") is None
    ok = json.dumps({"version": "9.0.0", "url": "https://x/N.exe"}).encode()
    assert updates.check("https://x/latest.json", "0.16.0", lambda u, t: ok)["version"] == "9.0.0"


def test_al_arrancar_guarda_el_aviso(monkeypatch):
    monkeypatch.setitem(CFG, "update_url", "https://x/latest.json")
    monkeypatch.setitem(APP, "update", None)
    monkeypatch.setattr(updates, "check", lambda url, current: {"version": "9.0.0", "url": "https://x", "notes": ""})
    M.check_update()
    assert APP["update"]["version"] == "9.0.0"


def test_panel_tiene_aviso_y_ajustes_de_la_app():
    js = (paths.UI_DIR / "app.js").read_text(encoding="utf-8")
    html = (paths.UI_DIR / "index.html").read_text(encoding="utf-8")
    assert 'id="update"' in html and 'id="app-settings"' in html
    assert "close_to_tray" in js and "start_with_windows" in js
