import json

import pytest

from nachero import config, paths
from nachero.domain.common import norm, shrink, tier_name
from nachero.jsonio import read_json, write_json


def test_shrink_tiende_a_cero_con_poca_muestra():
    assert shrink(4.0, 0, 100) == 0.0
    assert shrink(4.0, 100, 100) == pytest.approx(2.0)
    assert shrink(4.0, 10_000, 100) == pytest.approx(4.0, rel=0.02)


def test_norm_y_tier():
    assert norm("Kai'Sa") == "kaisa"
    assert norm("Nunu & Willump") == "nunuwillump"
    assert tier_name({"tier": 1}) == "S+"
    assert tier_name(None) is None


def test_json_atomico(tmp_path):
    f = tmp_path / "x.json"
    assert read_json(f, {"def": 1}) == {"def": 1}
    write_json(f, {"a": [1, 2]})
    assert read_json(f) == {"a": [1, 2]}
    f.write_text("{roto", encoding="utf-8")
    assert read_json(f, []) == []


def test_deep_merge_conserva_claves_nuevas():
    base = {"a": 1, "w": {"pool": 1.0, "meta": 1.0}}
    over = {"a": 2, "w": {"pool": 1.5}}
    assert config.deep_merge(base, over) == {"a": 2, "w": {"pool": 1.5, "meta": 1.0}}
    assert base["w"]["pool"] == 1.0  # no modifica el original


@pytest.mark.parametrize(
    ("body", "esperado"),
    [
        ({"auto_hover_pick": False}, ["auto_hover_pick"]),
        ({"auto_hover_pick": "no"}, []),
        ({"auto_ban": True}, ["auto_ban"]),
        ({"lock_when_seconds_left": 5}, ["lock_when_seconds_left"]),
        ({"lock_when_seconds_left": 99}, []),
        ({"lock_when_seconds_left": True}, []),
        ({"pick_mode": "meta"}, ["modo solo meta y draft"]),
        ({"pick_mode": "otro"}, []),
        ({"weights": {"pool": 1.5, "hackeo": 9}}, ["peso pool"]),
        ({"weights": {"meta": 3}}, []),
        ({"desconocido": 1}, []),
    ],
)
def test_apply_settings_valida(body, esperado):
    cfg = {"weights": {}}
    assert config.apply_settings(cfg, body) == esperado


def test_config_usuario_sobre_defaults(home):
    cfg = config.load()
    assert cfg["pick_mode"] == "pool"
    cfg["pick_mode"] = "meta"
    config.save(cfg)
    assert json.loads(paths.config_file().read_text(encoding="utf-8"))["pick_mode"] == "meta"
    assert config.load()["pick_mode"] == "meta"
    assert "weights" in config.load()  # sigue teniendo los valores por defecto


@pytest.mark.parametrize("contenido", ["{roto", "[1, 2]", "null"])
def test_ajustes_rotos_no_impiden_arrancar_y_se_guarda_una_copia(home, contenido):
    paths.config_file().write_text(contenido, encoding="utf-8")
    cfg = config.load()  # antes, con una lista: AttributeError y Nachero no arrancaba
    assert cfg["pick_mode"] == "pool" and config.PROBLEM["text"]
    copia = paths.config_file().with_name("config.roto.json")
    assert copia.read_text(encoding="utf-8") == contenido  # el siguiente guardado ya no lo pierde
    paths.config_file().write_text("{}", encoding="utf-8")
    config.load()
    assert config.PROBLEM["text"] is None


def test_valores_con_otro_tipo_no_entran(home):
    paths.config_file().write_text(
        json.dumps({"weights": "x", "auto_accept": "sí", "lock_when_seconds_left": 5.5, "ui_port": "8766",
                    "style": {"carry_weight": "mucho", "utility_weight": 0.5}, "pick_mode": "meta", "extra": [1]}),
        encoding="utf-8",
    )  # fmt: skip
    cfg = config.load()
    assert isinstance(cfg["weights"], dict) and cfg["auto_accept"] is True and cfg["ui_port"] == 8765
    assert cfg["lock_when_seconds_left"] == 5.5 and cfg["pick_mode"] == "meta" and cfg["extra"] == [1]
    assert cfg["style"]["carry_weight"] == 1.0 and cfg["style"]["utility_weight"] == 0.5


def test_migracion_de_datos_antiguos(home, tmp_path):
    proyecto = tmp_path / "proyecto"
    proyecto.mkdir()
    (proyecto / "history_cache.json").write_text("[]", encoding="utf-8")
    (proyecto / "lolalytics_cache.json").write_text("{}", encoding="utf-8")
    movidos = paths.migrate_legacy(proyecto)
    assert sorted(movidos) == ["history_cache.json", "lolalytics_cache.json"]
    assert paths.history_file().exists()
    assert (paths.cache_dir() / "lolalytics_cache.json").exists()
    assert not (proyecto / "history_cache.json").exists()
    # no pisa datos que ya existen
    (proyecto / "history_cache.json").write_text('["viejo"]', encoding="utf-8")
    assert paths.migrate_legacy(proyecto) == []
    assert paths.history_file().read_text(encoding="utf-8") == "[]"


def test_pasa_los_datos_de_la_carpeta_draftbot(tmp_path):
    antigua = tmp_path / "draftbot"
    (antigua / "cache").mkdir(parents=True)
    (antigua / "config.json").write_text('{"pick_mode": "meta"}', encoding="utf-8")
    (antigua / "cache" / "gol_cache.json").write_text("{}", encoding="utf-8")
    (tmp_path / "nachero").mkdir()  # vacia: la crea cualquier arranque previo
    assert paths.migrate_old_name(tmp_path) == antigua
    assert (tmp_path / "nachero" / "config.json").read_text(encoding="utf-8") == '{"pick_mode": "meta"}'
    assert (tmp_path / "nachero" / "cache" / "gol_cache.json").exists()
    assert not antigua.exists()


def test_no_pisa_datos_de_nachero(tmp_path):
    (tmp_path / "draftbot").mkdir()
    (tmp_path / "draftbot" / "config.json").write_text("{}", encoding="utf-8")
    (tmp_path / "nachero").mkdir()
    (tmp_path / "nachero" / "config.json").write_text('{"ya": 1}', encoding="utf-8")
    assert paths.migrate_old_name(tmp_path) is None
    assert (tmp_path / "nachero" / "config.json").read_text(encoding="utf-8") == '{"ya": 1}'
    assert paths.migrate_old_name(tmp_path / "otra") is None  # sin carpeta antigua no hace nada


def test_con_nachero_home_no_migra(home):
    assert paths.migrate_old_name() is None


def test_paginas_de_runas_propias_con_el_nombre_antiguo():
    from nachero.domain import runes as R

    assert R.is_own_page("Nachero · Naafiri JG") and R.is_own_page("draftbot · Taliyah JG")
    assert not R.is_own_page("Mi página")


def test_defaults_del_paquete_son_validos():
    cfg = json.loads(paths.DEFAULT_CONFIG.read_text(encoding="utf-8"))
    for k in config.TOGGLES:
        assert isinstance(cfg[k], bool)
    assert cfg["auto_lock_pick"] is False  # nunca confirmar picks por defecto
    assert set(config.WEIGHT_KEYS) <= set(cfg["weights"])
