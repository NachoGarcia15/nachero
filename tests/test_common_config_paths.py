import json

import pytest

from draftbot import config, paths
from draftbot.domain.common import norm, shrink, tier_name
from draftbot.jsonio import read_json, write_json


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
        ({"auto_ban": False}, ["auto_ban"]),
        ({"auto_ban": "no"}, []),
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


def test_defaults_del_paquete_son_validos():
    cfg = json.loads(paths.DEFAULT_CONFIG.read_text(encoding="utf-8"))
    for k in config.TOGGLES:
        assert isinstance(cfg[k], bool)
    assert cfg["auto_lock_pick"] is False  # nunca confirmar picks por defecto
    assert set(config.WEIGHT_KEYS) <= set(cfg["weights"])
