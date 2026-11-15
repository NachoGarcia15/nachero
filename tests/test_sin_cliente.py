"""Sin cliente o fuera de Windows: parche de respaldo, plataforma, estados del panel y diagnóstico."""

from collections import deque

from draftbot.app.status import diagnostics, empty_states, platform_info, platform_warning, scrub
from draftbot.app.worker import current_patch, offline_patch
from draftbot.clients.cdragon import PATCH_TTL, latest_patch, parse_versions, short_patch

DDRAGON = ["16.22.1", "16.21.1", "16.20.1"]
CDRAGON = {"version": "16.22.8348910+branch.releases-16-22.content.release"}


# ---------------------------------------------------------------- parche de respaldo
def test_formato_del_parche():
    assert short_patch("16.22.1") == "16.22"
    assert short_patch("16.22.8348910+branch") == "16.22"
    assert short_patch("") is None and short_patch(None) is None
    assert parse_versions(DDRAGON) == "16.22"
    assert parse_versions(CDRAGON) == "16.22"
    assert parse_versions([]) is None and parse_versions("x") is None


def test_parche_de_data_dragon_con_cache(tmp_path):
    calls = []

    def fetch(url):
        calls.append(url)
        return DDRAGON

    f = tmp_path / "patch.json"
    assert latest_patch(f, fetch, now=lambda: 1000.0) == "16.22"
    assert latest_patch(f, fetch, now=lambda: 1000.0 + PATCH_TTL - 1) == "16.22"
    assert len(calls) == 1  # la segunda sale de la caché


def test_si_falla_data_dragon_usa_communitydragon(tmp_path):
    def fetch(url):
        if "ddragon" in url:
            raise OSError("sin red")
        return CDRAGON

    assert latest_patch(tmp_path / "patch.json", fetch) == "16.22"


def test_sin_red_usa_el_ultimo_conocido_o_none(tmp_path):
    def offline(url):
        raise OSError("sin red")

    f = tmp_path / "patch.json"
    assert latest_patch(f, offline) is None
    latest_patch(f, lambda url: ["16.21.1"], now=lambda: 0.0)
    assert latest_patch(f, offline, now=lambda: PATCH_TTL * 10) == "16.21"  # caducada, pero mejor que nada


class FakeLCU:
    def __init__(self, version=None):
        self.version = version

    def get(self, path, timeout=5):
        if self.version is None:
            raise OSError("cliente cerrado")
        return self.version


def test_parche_con_y_sin_cliente():
    games = [{"patch": "16.20"}]
    assert current_patch(FakeLCU("16.22.725.1234"), games, fallback=lambda: "x") == "16.22"
    assert current_patch(FakeLCU(), games, fallback=lambda: "x") == "16.20"
    assert current_patch(FakeLCU(), [], fallback=lambda: "16.22") == "16.22"
    # sin cliente manda internet: tu última partida puede ser de un parche viejo
    assert offline_patch(games, fallback=lambda: "16.22") == "16.22"
    assert offline_patch(games, fallback=lambda: None) == "16.20"
    assert offline_patch([], fallback=lambda: None) is None  # nunca "30"


# ---------------------------------------------------------------- plataforma
def test_deteccion_de_plataforma():
    assert platform_info("win32", "11") == {"supported": True, "name": "Windows"}
    assert platform_info("linux", "5.15.90.1-microsoft-standard-WSL2")["name"] == "WSL"
    assert platform_info("linux", "6.8.0-45-generic") == {"supported": False, "name": "Linux"}
    assert platform_info("darwin", "24.0.0") == {"supported": False, "name": "macOS"}
    assert platform_warning(platform_info("win32", "11")) is None
    msg = platform_warning(platform_info("linux", "5.15-microsoft-standard-WSL2"))
    assert "Windows" in msg and "WSL" in msg and "draftbot.exe" in msg


# ---------------------------------------------------------------- estados del panel
LISTO = {
    "connected": True,
    "offline": False,
    "loading": False,
    "platform": {"supported": True},
    "pool": [{"id": 1}],
    "games": 50,
    "patch": "16.22",
    "data": {"patch": "16.22", "games": 900000},
}


def estado(**kw):
    return LISTO | kw


def test_nada_falta_con_todo_cargado():
    assert empty_states(LISTO) == {"draft": None, "pool": None, "data": None}


def test_fuera_de_windows_lo_dice_en_todo():
    st = estado(connected=False, offline=True, platform={"supported": False, "name": "WSL"}, pool=[], data={})
    assert empty_states(st) == {"draft": "platform", "pool": "platform", "data": "platform"}


def test_cargando_y_sin_campeones():
    assert empty_states(estado(loading=True, pool=[], data={}))["pool"] == "loading"
    st = estado(connected=False, issue="no_champions", loading=True, pool=[], data={})
    assert empty_states(st) == {"draft": "no_champions", "pool": "no_champions", "data": "no_champions"}


def test_pool_sin_cliente_o_sin_partidas():
    assert empty_states(estado(connected=False, offline=True, pool=[], games=0))["pool"] == "no_client"
    assert empty_states(estado(pool=[], games=0))["pool"] == "no_games"
    assert empty_states(estado(pool=[], games=30))["pool"] is None  # aún calculando


def test_datos_sin_parche_o_sin_lolalytics():
    assert empty_states(estado(patch=None, data={"patch": None, "games": 0}))["data"] == "no_patch"
    assert empty_states(estado(data={"patch": "16.22", "games": 0}))["data"] == "no_data"
    assert empty_states(estado(data={}))["data"] is None  # el bucle aún no ha publicado los datos


# ---------------------------------------------------------------- diagnóstico
def test_scrub_quita_datos_personales():
    txt = (
        r"Datos movidos a C:\Users\Nacho Garcia\AppData\Roaming\draftbot: config.json"
        " · /home/pepe/x · /Users/ana/y · puuid " + "a" * 78 + " · 0f8fad5b-d9cb-469f-a165-70867728950e · Pepito"
    )
    out = scrub(txt, ("Pepito",))
    for secret in ("Nacho", "pepe", "ana/", "a" * 78, "0f8fad5b", "Pepito"):
        assert secret not in out
    assert r"C:\Users\<usuario>\AppData" in out and "config.json" in out


def test_diagnostico_completo_y_limpio():
    log = deque(
        [
            {"t": "10:00:02", "msg": r"Datos movidos a C:\Users\nacho\AppData\Roaming\draftbot", "kind": "ok"},
            {"t": "10:00:01", "msg": "Cliente de LoL cerrado", "kind": "warn"},
        ]
    )
    st = estado(connected=False, offline=True, pool=[], games=0, phase_es="Sin cliente", mode="observe", log=log)
    text = diagnostics(st, "0.6.3", "Windows-11-10.0.26300-SP0", True, ("nacho",))
    assert "draftbot 0.6.3 (draftbot.exe)" in text
    assert "Windows-11" in text and "sin cliente" in text and "Parche: 16.22" in text
    assert "Sin cliente" in text and "pool=no_client" in text
    assert "nacho" not in text
    assert text.index("Cliente de LoL cerrado") < text.index("Datos movidos")  # orden cronológico
