"""Perfil por cuenta y configuración guiada (issue #4)."""

import json

import pytest

from conftest import FakeLola, all_roles
from nachero import config, paths
from nachero.app import worker
from nachero.app.state import APP
from nachero.domain.engine import Engine
from nachero.domain.player import Player

PUUID = "a" * 78
OTRO = "b" * 78


def _legacy(home):
    home.mkdir(parents=True, exist_ok=True)
    (home / "history_cache.json").write_text("[1]", encoding="utf-8")
    (home / "player_cache.json").write_text("{}", encoding="utf-8")


# ------------------------------------------------------------------ carpetas por cuenta
def test_sin_perfil_usa_la_carpeta_de_datos(home):
    assert paths.history_file() == home / "history_cache.json"
    assert paths.player_file() == home / "player_cache.json"


def test_el_primer_perfil_se_queda_con_los_datos_antiguos(home):
    _legacy(home)
    assert paths.use_profile(PUUID) == ["history_cache.json", "player_cache.json"]
    assert paths.history_file() == home / "profiles" / PUUID / "history_cache.json"
    assert paths.history_file().read_text(encoding="utf-8") == "[1]"
    assert not (home / "history_cache.json").exists()


def test_otra_cuenta_empieza_de_cero(home):
    _legacy(home)
    paths.use_profile(PUUID)
    assert paths.use_profile(OTRO) == []
    assert not paths.history_file().exists()
    assert paths.history_file().parent.name == OTRO


def test_si_ya_hay_perfiles_no_adopta_los_datos_antiguos(home):
    paths.use_profile(PUUID)
    _legacy(home)
    assert paths.use_profile(OTRO) == []
    assert (home / "history_cache.json").exists()


def test_recuerda_el_ultimo_perfil(home):
    assert paths.last_profile() is None
    paths.use_profile(PUUID)
    paths.use_profile(None)
    assert paths.profile_id() is None
    assert paths.last_profile() == PUUID


@pytest.mark.parametrize("pid", ["../x", "a/b", "", "a" * 200, "a b"])
def test_ids_raros_no_crean_carpetas(home, pid):
    assert paths.use_profile(pid) == []
    assert paths.profile_id() is None
    assert not (home / "profiles").exists()


class Summoner:
    def __init__(self, me):
        self.me = me

    def get(self, path, timeout=None):
        assert path == "/lol-summoner/v1/current-summoner"
        return self.me


def test_abre_el_perfil_de_la_cuenta_conectada(home, monkeypatch):
    monkeypatch.setitem(APP, "profile", None)
    assert worker.open_profile(Summoner({"puuid": PUUID, "gameName": "Nacho", "tagLine": "EUW"})) == PUUID
    assert APP["profile"] == {"name": "Nacho#EUW", "saved": False}


def test_sin_cliente_abre_el_ultimo_perfil(home, monkeypatch):
    monkeypatch.setitem(APP, "profile", None)
    paths.use_profile(PUUID)
    paths.use_profile(None)
    assert worker.open_profile(None) == PUUID
    assert APP["profile"] == {"name": "", "saved": True}


def test_cliente_sin_cuenta_y_sin_perfiles(home, monkeypatch):
    monkeypatch.setitem(APP, "profile", None)
    assert worker.open_profile(Summoner(None)) is None
    assert APP["profile"] is None and paths.history_file() == home / "history_cache.json"


# ------------------------------------------------------------------ ajustes de la configuración guiada
def test_por_defecto_sin_configurar():
    cfg = json.loads(paths.DEFAULT_CONFIG.read_text(encoding="utf-8"))
    assert cfg["setup_done"] is False and cfg["secondary_role"] == "none"
    assert cfg["pool_bonus"] == {} and cfg["never_pick"] == []


def test_guarda_roles_y_campeones():
    cfg: dict = {}
    cambios = config.apply_settings(
        cfg,
        {
            "main_role": "jungle",
            "secondary_role": "middle",
            "pool_bonus": {"Taliyah": 1.5, " Naafiri ": 1.5, "Teemo": 0},
            "never_pick": ["Yuumi", "Yuumi", "Teemo"],
            "setup_done": True,
        },
    )
    assert cfg == {
        "main_role": "jungle",
        "secondary_role": "middle",
        "pool_bonus": {"Taliyah": 1.5, "Naafiri": 1.5},  # sin puntos no se guarda
        "never_pick": ["Yuumi", "Teemo"],
        "setup_done": True,
    }
    assert len(cambios) == 5


@pytest.mark.parametrize(
    "body",
    [
        {"secondary_role": "fill"},
        {"never_pick": "Yuumi"},
        {"never_pick": [1]},
        {"never_pick": ["x"] * 41},
        {"pool_bonus": {"Taliyah": 9}},
        {"pool_bonus": {"Taliyah": True}},
        {"pool_bonus": ["Taliyah"]},
        {"setup_done": "si"},
    ],
)
def test_rechaza_valores_raros(body):
    cfg: dict = {}
    assert config.apply_settings(cfg, body) == [] and cfg == {}


# ------------------------------------------------------------------ campeones que practicas
def _engine(champs, cfg):
    lola = FakeLola(all_roles(jungle={7: (52, 9000, 8, 90), 5: (50, 3000, 3, 30)}))
    return Engine(champs, lola, Player([], []), {"pick_mode": "pool", "weights": {}, **cfg})


def test_lo_que_practicas_entra_como_candidato_con_sus_puntos(champs):
    base = _engine(champs, {})
    con = _engine(champs, {"pool_bonus": {"Bruiser": 1.5}})
    # Bruiser (5) tiene pocas partidas y no está entre los fuertes ni en tu historial
    sin_bonus = {p["id"]: p["est"] for p in base.picks("jungle", set(), set(), [], [])[0]}
    con_bonus = {p["id"]: p["est"] for p in con.picks("jungle", set(), set(), [], [])[0]}
    assert 5 in con_bonus
    if 5 in sin_bonus:
        assert con_bonus[5] == pytest.approx(sin_bonus[5] + 1.5, abs=0.11)


def test_nunca_jugar_lo_quita(champs):
    eng = _engine(champs, {"never_pick": ["Diver"]})
    assert 7 not in {p["id"] for p in eng.picks("jungle", set(), set(), [], [])[0]}


def test_puntos_raros_en_el_archivo_no_rompen(champs):
    eng = _engine(champs, {"pool_bonus": {"Bruiser": "mucho", "Diver": 1}})
    assert eng.picks("jungle", set(), set(), [], [])[0]


def test_panel_tiene_la_configuracion_guiada():
    html = (paths.UI_DIR / "index.html").read_text(encoding="utf-8")
    js = (paths.UI_DIR / "app.js").read_text(encoding="utf-8")
    assert 'id="setup"' in html and 'id="profile-settings"' in html
    for texto in ("Tus roles", "Lo que practicas", "Lo que nunca juegas", "openSetup()", "setup_done: true"):
        assert texto in js, texto
