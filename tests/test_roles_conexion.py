"""Rol del jugador (historial, ajuste y champ select) y conexion con el cliente."""

import pytest

from conftest import FakeLola, all_roles
from draftbot import config
from draftbot.app.draft import Draft
from draftbot.clients.lcu import install_dirs, parse_lockfile
from draftbot.config import CFG
from draftbot.domain.common import ROLES
from draftbot.domain.engine import Engine
from draftbot.domain.player import Player
from draftbot.sources.history import role_of


# ------------------------------------------------------------------ rol de cada partida del historial
@pytest.mark.parametrize(
    ("lane", "role", "smite", "esperado"),
    [
        ("JUNGLE", "NONE", True, "jungle"),
        ("NONE", "SOLO", True, "jungle"),  # sin linea pero con Smite
        ("JUNGLE", "NONE", False, "jungle"),
        ("TOP", "SOLO", False, "top"),
        ("MIDDLE", "SOLO", False, "middle"),
        ("BOTTOM", "CARRY", False, "bottom"),
        ("BOTTOM", "SUPPORT", False, "utility"),
        ("NONE", "SUPPORT", False, "utility"),  # antes se descartaba
        ("BOTTOM", "SOLO", False, "bottom"),
        ("NONE", "NONE", False, ""),
    ],
)
def test_rol_de_una_partida(lane, role, smite, esperado):
    p = {"spell1Id": 11 if smite else 4, "spell2Id": 4 if smite else 14, "timeline": {"lane": lane, "role": role}}
    assert role_of(p) == esperado


# ------------------------------------------------------------------ conexion por lockfile
def test_lockfile():
    assert parse_lockfile("LeagueClient:21444:63973:abc-XYZ_1:https\n") == ("63973", "abc-XYZ_1")
    assert parse_lockfile("") is None
    assert parse_lockfile("LeagueClient:1:puerto:tok:https") is None


def test_carpeta_del_juego_desde_el_instalador():
    meta = 'product_install_full_path: "D:\\\\Juegos\\\\Riot Games\\\\League of Legends"\nproduct_install_root: "D:/"'
    dirs = install_dirs(meta)
    assert dirs[0] == r"D:\Juegos\Riot Games\League of Legends"
    assert r"C:\Riot Games\League of Legends" in dirs
    assert install_dirs("") == [r"C:\Riot Games\League of Legends"]


# ------------------------------------------------------------------ ajustes
def test_colas_antiguas_se_actualizan():
    defaults = {"history_queues": [420, 440, 400, 490]}
    assert config.migrate({"history_queues": [420]}, defaults)["history_queues"] == [420, 440, 400, 490]
    assert config.migrate({"history_queues": [420, 440]}, defaults)["history_queues"] == [420, 440]  # elegido


def test_ajuste_de_rol_principal():
    cfg: dict = {}
    assert config.apply_settings(cfg, {"main_role": "utility"}) == ["rol principal utility"]
    assert config.apply_settings(cfg, {"main_role": "auto"}) == ["rol principal automático"]
    assert config.apply_settings(cfg, {"main_role": "fill"}) == []


def _engine(champs, games, main_role="auto"):
    lola = FakeLola(
        all_roles(top={5: (52, 9000, 8, 90)}, utility={6: (52, 9000, 8, 90)}, jungle={7: (51, 9000, 8, 90)})
    )
    cfg = {"pick_mode": "pool", "weights": {}, "main_role": main_role}
    return Engine(champs, lola, Player(games, []), cfg)


def _game(role):
    return {"gameId": 1, "t": 0, "patch": "16.22", "champ": 6, "role": role, "win": True,
            "k": 1, "d": 1, "a": 1, "gpm": 1, "dpm": 1, "cspm": 1}  # fmt: skip


def test_rol_principal_automatico_o_fijado(champs):
    assert _engine(champs, [_game("utility")] * 3).main_role() == "utility"
    assert _engine(champs, [_game("utility")] * 3, "top").main_role() == "top"


# ------------------------------------------------------------------ champ select con cualquier rol
def session(assigned):
    me = {"cellId": 0, "assignedPosition": assigned, "championId": 0, "championPickIntent": 0}
    allies = [{"cellId": i, "assignedPosition": "", "championId": 0, "championPickIntent": 0} for i in range(1, 5)]
    pick = {"id": 1, "actorCellId": 0, "championId": 0, "completed": False, "isAllyAction": True,
            "isInProgress": True, "type": "pick"}  # fmt: skip
    return {
        "localPlayerCellId": 0,
        "myTeam": [me, *allies],
        "theirTeam": [{"cellId": 5 + i, "championId": 0} for i in range(5)],
        "actions": [[pick]],
        "bans": {"myTeamBans": [], "theirTeamBans": []},
        "timer": {"phase": "BAN_PICK", "adjustedTimeLeftInPhase": 20000},
    }


@pytest.fixture
def quiet(monkeypatch):
    """Sin hechizos, marcado ni runas: solo la recomendacion."""
    for k, v in {"auto_spells": False, "spells_by_role": {}, "auto_hover_pick": False, "import_runes": False}.items():
        monkeypatch.setitem(CFG, k, v)


@pytest.mark.parametrize("role", ROLES)
def test_recomienda_para_el_rol_asignado(champs, quiet, role):
    d = Draft(None, champs, _engine(champs, [_game("jungle")] * 5))
    out = d.tick(session(role), acting=False, pickable=set(), bannable=set())
    assert out["role"] == role


def test_sin_rol_asignado_usa_tu_rol_principal(champs, quiet):
    d = Draft(None, champs, _engine(champs, [_game("utility")] * 5))
    out = d.tick(session(""), acting=False, pickable=set(), bannable=set())
    assert out["role"] == "utility" and out["hero"]["id"] == 6
