"""Todos los ajustes editables desde el panel (issue #5)."""

import json

import pytest

from nachero import config, paths
from nachero.app.state import SPELL_IDS


def test_los_hechizos_del_panel_son_los_que_conoce_la_app():
    assert set(config.SPELLS) == set(SPELL_IDS)


def test_modo_al_abrir():
    cfg: dict = {}
    assert config.apply_settings(cfg, {"start_mode": "active"}) == ["modo al abrir activo"]
    assert cfg["start_mode"] == "active"
    assert config.apply_settings(cfg, {"start_mode": "turbo"}) == [] and cfg["start_mode"] == "active"


def test_hechizos_por_rol_cambia_solo_ese_rol():
    cfg = {"spells_by_role": {"jungle": ["Smite", "Flash"], "top": ["Teleport", "Flash"]}}
    assert config.apply_settings(cfg, {"spells_by_role": {"top": ["Ghost", "Teleport"]}}) == ["hechizos de top"]
    assert cfg["spells_by_role"] == {"jungle": ["Smite", "Flash"], "top": ["Ghost", "Teleport"]}


@pytest.mark.parametrize(
    "pair",
    [["Flash", "Flash"], ["Flash"], ["Flash", "Mark"], "Flash", ["Flash", "Heal", "Ignite"], [4, 7]],
)
def test_hechizos_no_validos(pair):
    cfg: dict = {}
    assert config.apply_settings(cfg, {"spells_by_role": {"top": pair}}) == [] and cfg == {}


def test_rol_raro_en_hechizos():
    cfg: dict = {}
    assert config.apply_settings(cfg, {"spells_by_role": {"fill": ["Flash", "Heal"]}}) == []


def test_estilo():
    cfg = {"style": {"_info": "x", "carry_weight": 1.0, "utility_weight": 0.2}}
    assert config.apply_settings(cfg, {"style": {"carry_weight": 1.6}}) == ["estilo carry_weight"]
    assert cfg["style"] == {"_info": "x", "carry_weight": 1.6, "utility_weight": 0.2}
    for malo in ({"carry_weight": 3}, {"carry_weight": -1}, {"carry_weight": True}, {"otra": 1}):
        assert config.apply_settings(cfg, {"style": malo}) == []


def test_bans_prioritarios_por_rol():
    cfg = {"ban_priority": {"jungle": [], "top": ["Teemo"]}}
    assert config.apply_settings(cfg, {"ban_priority": {"jungle": ["Lee Sin", "Lee Sin", "Kindred"]}}) == [
        "bans prioritarios de jungle"
    ]
    assert cfg["ban_priority"] == {"jungle": ["Lee Sin", "Kindred"], "top": ["Teemo"]}
    assert config.apply_settings(cfg, {"ban_priority": {"jungle": [f"C{i}" for i in range(11)]}}) == []
    assert config.apply_settings(cfg, {"ban_priority": {"fill": ["Teemo"]}}) == []
    assert config.apply_settings(cfg, {"ban_priority": {"top": []}}) == ["bans prioritarios de top"]
    assert cfg["ban_priority"]["top"] == []


def test_puntos_extra_y_nunca_jugar():
    cfg: dict = {}
    assert config.apply_settings(cfg, {"pool_bonus": {"Taliyah": 2.5, "Yuumi": -3}, "never_pick": ["Teemo"]})
    assert cfg == {"pool_bonus": {"Taliyah": 2.5, "Yuumi": -3.0}, "never_pick": ["Teemo"]}
    assert config.apply_settings(cfg, {"pool_bonus": {}})  # quitar todos
    assert cfg["pool_bonus"] == {}


def test_se_guarda_y_se_vuelve_a_cargar(home):
    home.mkdir(parents=True, exist_ok=True)
    cfg = config.load()
    config.apply_settings(cfg, {"start_mode": "paused", "spells_by_role": {"utility": ["Exhaust", "Flash"]}})
    config.save(cfg)
    again = config.load()
    assert again["start_mode"] == "paused" and again["spells_by_role"]["utility"] == ["Exhaust", "Flash"]
    assert again["spells_by_role"]["jungle"] == ["Smite", "Flash"]  # lo demás, como estaba


def test_el_panel_puede_editarlos_todos():
    js = (paths.UI_DIR / "app.js").read_text(encoding="utf-8")
    for key in ("start_mode", "spells_by_role", "style", "ban_priority", "pool_bonus", "never_pick"):
        assert f"{key}:" in js or f'"{key}"' in js, key
    defaults = json.loads(paths.DEFAULT_CONFIG.read_text(encoding="utf-8"))
    assert set(defaults["spells_by_role"]) <= {"top", "jungle", "middle", "bottom", "utility"}
