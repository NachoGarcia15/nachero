"""Normas de Riot: aviso legal, decisiones de juego desactivadas por defecto y explicación de modos."""

import json

import pytest

from nachero import config, paths
from nachero.app.draft import Draft
from nachero.config import CFG
from nachero.domain.policy import GAME_DECISIONS, RIOT_NOTICE, client_actions, mode_help, summary
from test_queues import FakeLCU
from test_roles_conexion import _engine, _game, session


def _defaults():
    return json.loads(paths.DEFAULT_CONFIG.read_text(encoding="utf-8"))


# ------------------------------------------------------------------ aviso legal
def test_aviso_legal_con_el_texto_de_riot():
    # https://developer.riotgames.com/policies/general, con «[Your product]» → Nachero
    assert RIOT_NOTICE == (
        "Nachero isn't endorsed by Riot Games and doesn't reflect the views or opinions of Riot Games or "
        "anyone officially involved in producing or managing Riot Games properties. Riot Games, and all "
        "associated properties are trademarks or registered trademarks of Riot Games, Inc."
    )


def test_aviso_legal_visible_en_el_panel():
    html = (paths.UI_DIR / "index.html").read_text(encoding="utf-8")
    assert f'<footer class="legal" id="legal">{RIOT_NOTICE}</footer>' in html


# ------------------------------------------------------------------ valores por defecto
def test_decisiones_de_juego_desactivadas_por_defecto():
    cfg = _defaults()
    for k in GAME_DECISIONS:
        assert cfg[k] is False, k
    assert set(GAME_DECISIONS) <= set(config.TOGGLES)


def test_aceptar_partida_y_runas_siguen_activadas():
    cfg = _defaults()
    assert cfg["auto_accept"] is True
    assert cfg["import_runes"] is True
    assert cfg["start_mode"] == "observe"


def test_sin_ajustes_guardados_usa_los_nuevos_valores(home):
    home.mkdir(parents=True, exist_ok=True)
    paths.config_file().write_text(json.dumps({"pick_mode": "meta"}), encoding="utf-8")
    cfg = config.load()
    assert cfg["pick_mode"] == "meta"
    assert [cfg[k] for k in GAME_DECISIONS] == [False, False, False]


def test_respeta_lo_que_el_usuario_ya_tenia_guardado(home):
    home.mkdir(parents=True, exist_ok=True)
    guardado = {"auto_ban": True, "auto_hover_pick": True, "auto_lock_pick": True, "auto_accept": False}
    paths.config_file().write_text(json.dumps(guardado), encoding="utf-8")
    cfg = config.load()
    assert {k: cfg[k] for k in guardado} == guardado
    assert json.loads(paths.config_file().read_text(encoding="utf-8")) == guardado  # no reescribe el archivo


# ------------------------------------------------------------------ en la champ select
@pytest.fixture
def por_defecto(monkeypatch):
    """Ajustes por defecto del paquete, sin hechizos ni runas para aislar ban y pick."""
    for k, v in _defaults().items():
        monkeypatch.setitem(CFG, k, v)
    monkeypatch.setitem(CFG, "auto_spells", False)
    monkeypatch.setitem(CFG, "import_runes", False)
    monkeypatch.setitem(CFG, "open_coachless_on_lock", False)


def test_modo_activo_por_defecto_no_marca_ni_confirma(champs, por_defecto):
    lcu = FakeLCU()
    s = session("jungle")
    s["timer"]["adjustedTimeLeftInPhase"] = 2000  # a falta de 2 s: con auto_lock_pick confirmaria
    out = Draft(lcu, champs, _engine(champs, [_game("jungle")] * 5)).tick(s, True, pickable=set(), bannable=set())
    assert lcu.calls == []
    assert out["status"][0]["kind"] == "turn"  # el panel dice «hazlo tú»


def test_confirmar_activado_avisa_de_que_lo_hara_nachero(champs, por_defecto, monkeypatch):
    monkeypatch.setitem(CFG, "auto_lock_pick", True)
    lcu = FakeLCU()
    out = Draft(lcu, champs, _engine(champs, [_game("jungle")] * 5)).tick(
        session("jungle"), True, pickable=set(), bannable=set()
    )
    assert lcu.calls == []  # quedan 20 s: aun no confirma
    assert out["status"][0]["kind"] == "turn_auto"


def test_en_observar_nunca_es_automatico(champs, por_defecto, monkeypatch):
    monkeypatch.setitem(CFG, "auto_lock_pick", True)
    out = Draft(FakeLCU(), champs, _engine(champs, [_game("jungle")] * 5)).tick(
        session("jungle"), False, pickable=set(), bannable=set()
    )
    assert out["status"][0]["kind"] == "turn"


# ------------------------------------------------------------------ explicacion de modos
def test_que_toca_el_modo_activo_con_los_valores_por_defecto():
    assert client_actions(_defaults()) == [
        "acepta la partida",
        "pone los hechizos de tu rol",
        "crea la página de runas «Nachero»",
    ]


def test_que_toca_con_todo_activado():
    cfg = {k: True for k in config.TOGGLES} | {"lock_when_seconds_left": 5}
    acciones = client_actions(cfg)
    assert "marca tu ban y lo confirma a falta de 5 s" in acciones and "marca tu pick" in acciones
    assert "confirma el pick marcado a falta de 5 s" in acciones


def test_observar_y_pausa_no_tocan_el_cliente():
    help_ = mode_help({k: True for k in config.TOGGLES})
    assert list(help_) == ["paused", "observe", "active"]
    for mode in ("paused", "observe"):
        assert help_[mode]["touches"] == []
        assert help_[mode]["summary"] == "No toca el cliente."
    assert help_["active"]["touches"]


@pytest.mark.parametrize(
    ("touches", "esperado"),
    [
        ([], "Con tus ajustes no toca el cliente: solo recomienda."),
        (["acepta la partida"], "En el cliente acepta la partida."),
        (["a", "b", "c"], "En el cliente a, b y c."),
    ],
)
def test_resumen_del_modo_activo(touches, esperado):
    assert summary("active", touches) == esperado
