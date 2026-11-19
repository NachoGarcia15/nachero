"""Bienvenida (issue #47): ajuste `welcome_seen`, demo desde el panel y textos del panel."""

import json

import pytest

from nachero import config, paths
from nachero.app import server
from nachero.app.state import APP, OPTS, demo_must_stop, set_demo
from nachero.config import CFG


@pytest.fixture
def cfg(home, monkeypatch):
    home.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(server, "CFG", CFG)
    saved = dict(CFG)
    CFG.clear()
    CFG.update(config.load())
    yield CFG
    CFG.clear()
    CFG.update(saved)


@pytest.fixture
def demo_off():
    yield
    set_demo(False)


def test_bienvenida_sin_ver_por_defecto(cfg):
    assert cfg["welcome_seen"] is False


def test_marcar_bienvenida_vista_la_guarda(cfg):
    assert server.welcome_request({"seen": True}) == (200, {"ok": True})
    assert json.loads(paths.config_file().read_text(encoding="utf-8"))["welcome_seen"] is True
    assert config.load()["welcome_seen"] is True
    assert server.welcome_request({}) == (200, {"ok": True})  # sin cuerpo: vista


def test_ver_la_bienvenida_otra_vez(cfg):
    server.welcome_request({"seen": True})
    server.welcome_request({"seen": False})
    assert config.load()["welcome_seen"] is False


def test_bienvenida_rechaza_valores_raros(cfg):
    assert server.welcome_request({"seen": "si"})[0] == 400
    assert not paths.config_file().exists()


def test_bienvenida_no_es_un_ajuste_del_panel():
    # no pasa por /api/settings: no reinicia Tu pool ni sale como «Ajustes guardados»
    assert config.apply_settings({}, {"welcome_seen": True}) == []


# ------------------------------------------------------------------ demo desde el panel
def test_abrir_y_cerrar_la_demo(demo_off):
    assert server.demo_request({"on": True}) == (200, {"ok": True})
    assert OPTS["demo"] and APP["demo"] and OPTS["demo_ui"] and OPTS["demo_since"] > 0
    assert server.demo_request({"on": False}) == (200, {"ok": True})
    assert not OPTS["demo"] and not APP["demo"] and not OPTS["demo_ui"]
    assert server.demo_request({"on": "si"})[0] == 400


@pytest.mark.parametrize(
    ("phase", "stop"),
    [(None, False), ("None", False), ("Lobby", False), ("Matchmaking", False),
     ("ReadyCheck", True), ("ChampSelect", True), ("InProgress", True)],
)  # fmt: skip
def test_la_demo_del_panel_se_cierra_al_empezar_una_partida(demo_off, phase, stop):
    set_demo(True)
    assert demo_must_stop(phase) is stop


def test_la_demo_de_la_linea_de_comandos_no_se_cierra(demo_off):
    set_demo(True, from_ui=False)
    assert not demo_must_stop("ChampSelect")


def test_sin_demo_no_hay_nada_que_cerrar():
    set_demo(False)
    assert not demo_must_stop("ChampSelect")


# ------------------------------------------------------------------ panel
def test_panel_tiene_bienvenida_y_acerca_de():
    html = (paths.UI_DIR / "index.html").read_text(encoding="utf-8")
    js = (paths.UI_DIR / "app.js").read_text(encoding="utf-8")
    assert 'id="welcome"' in html and 'id="about"' in html and 'id="open-about"' in html
    for texto in ("Qué hace", "Cómo decide", "Qué toca y qué no", "Empezar", "Ver la bienvenida otra vez"):
        assert texto in js or texto in html, texto
    assert "ArrowRight" in js and "ArrowLeft" in js and "Escape" in js
    assert "Probar con una partida de demo" in js
