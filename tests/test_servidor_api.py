"""La API del panel de punta a punta, con un motor de prueba: ninguna ruta falla (500) por un error
de cableado. Sin cliente ni red."""

import json
import threading
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer

import pytest

from nachero import config
from nachero.app.draft import Draft
from nachero.app.server import Handler
from nachero.app.state import APP, CTX, OPTS
from nachero.config import CFG
from nachero.domain.engine import Engine
from nachero.domain.player import Player
from nachero.domain.pro import ProEngine
from test_bucle_integracion import Lola
from test_roles_conexion import _game


class Gol:
    loading: set = set()

    def dataset(self, name):
        return None

    def tournaments(self):
        return {"majors": ["Worlds 2026"], "all": ["Worlds 2026"]}

    def updated(self):
        return None


@pytest.fixture
def api(monkeypatch, home, champs):
    config.init()
    lola = Lola()
    eng = Engine(champs, lola, Player([_game("jungle")] * 5, []), CFG)
    draft = Draft(None, champs, eng)
    gol = Gol()
    for k, v in {"champs": champs, "engine": eng, "lola": lola, "draft": draft, "patch": "16.23",
                 "pro": ProEngine(champs, lola, eng, gol)}.items():  # fmt: skip
        monkeypatch.setitem(CTX, k, v)
    monkeypatch.setattr("nachero.app.server.gol", lambda: gol)
    for k, v in {"mode": "observe", "phase": "Lobby", "draft": None, "loading": False, "connected": True}.items():
        monkeypatch.setitem(APP, k, v)
    monkeypatch.setitem(OPTS, "demo", False)
    srv = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    port = srv.server_address[1]
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))

    def call(path, body=None):
        data = None if body is None else json.dumps(body).encode()
        req = urllib.request.Request(f"http://127.0.0.1:{port}{path}", data=data,
                                     headers={"Content-Type": "application/json"} if data else {})  # fmt: skip
        try:
            with opener.open(req, timeout=10) as r:
                raw = r.read()
                return r.status, (json.loads(raw) if r.headers.get_content_type() == "application/json" else raw)
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read() or b"null")

    yield call
    srv.shutdown()
    srv.server_close()


def test_rutas_de_lectura(api):
    code, st = api("/api/state")
    assert code == 200 and st["version"] and st["settings"]["auto_hover_pick"] is False and "modes" in st
    code, text = api("/api/diagnostics")
    assert code == 200 and b"Nachero" in text
    code, champs = api("/api/champions")
    assert code == 200 and {"id": 7, "name": "Diver"} in champs
    for view in ("draft", "pool"):
        code, row = api(f"/api/evaluate?id=7&role=jungle&view={view}")
        assert code == 200 and row["id"] == 7 and row["est"] > 0, view
    assert api("/api/evaluate?id=x&role=jungle")[0] == 400
    assert api("/api/evaluate?id=7&role=nada")[0] == 400
    code, cal = api("/api/calibration")
    assert code == 200 and cal["n"] == 0
    assert api("/api/pro/tournaments") == (200, {"majors": ["Worlds 2026"], "all": ["Worlds 2026"]})
    code, pro = api("/api/pro/champions?t=Worlds%202026")
    assert code == 200 and len(pro) == len(CTX["champs"].by_id)
    assert api("/api/img/tile/7")[0] == 404 and api("/api/no-existe")[0] == 404


def test_rutas_de_escritura(api):
    assert api("/api/mode", {"mode": "paused"}) == (200, {"ok": True}) and APP["mode"] == "paused"
    assert api("/api/mode", {"mode": "nada"})[0] == 404
    assert api("/api/settings", {"auto_hover_pick": True, "weights": {"pool": 1.2}}) == (200, {"ok": True})
    assert (
        CFG["auto_hover_pick"] is True and json.loads(config.paths.config_file().read_text())["weights"]["pool"] == 1.2
    )
    assert api("/api/welcome", {"seen": True}) == (200, {"ok": True}) and CFG["welcome_seen"] is True
    assert api("/api/welcome", {"seen": "sí"})[0] == 400
    assert api("/api/demo", {"on": True}) == (200, {"ok": True}) and OPTS["demo"] is True
    assert api("/api/demo", {"on": False}) == (200, {"ok": True}) and OPTS["demo"] is False
    assert api("/api/refresh", {}) == (200, {"ok": True})
    code, res = api("/api/pro/suggest", {"tournament": "", "blue": {"bans": [], "picks": []},
                                         "red": {"bans": [], "picks": []}})  # fmt: skip
    assert code == 200 and res["step"] == 0 and res["kind"] == "ban" and res["suggestions"]
    assert api("/api/draft/choose", {"kind": "pick", "id": 7})[0] == 409  # no estás en la champ select
    assert api("/api/draft/swap", {"op": "hackear", "id": 1})[0] == 400
