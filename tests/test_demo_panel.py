"""La demo (lo primero que ve un usuario nuevo desde la bienvenida) recorre su draft entero sin fallos."""

import time

from conftest import FakeChamps, FakeLola, all_roles
from nachero.app.demo import Demo
from nachero.app.draft import Draft
from nachero.config import CFG
from nachero.domain.engine import Engine
from nachero.domain.player import Player
from test_roles_conexion import _game

NOMBRES = ["Darius", "Zed", "Jinx", "Nautilus", "Aatrox", "Viego", "Talon", "Kai'Sa", "Leona", "Yone", "Kayn",
           "Draven", "Pyke", "Graves", "Qiyana", "Akali", "Ezreal", "Blitzcrank", "Taliyah"]  # fmt: skip


def test_la_demo_recorre_todo_el_draft(monkeypatch):
    for k, v in {"auto_spells": False, "spells_by_role": {}, "import_runes": False}.items():
        monkeypatch.setitem(CFG, k, v)
    data = {100 + i: (n, "AD", 2, 2, 2, 2, 1, ["fighter"]) for i, n in enumerate(NOMBRES)}
    champs = FakeChamps(data)
    jungle = {100 + i: (50 + i % 5, 9000, 5, 90) for i in range(len(NOMBRES))}
    eng = Engine(champs, FakeLola(all_roles(jungle=jungle)), Player([_game("jungle")] * 5, []),
                 {"pick_mode": "meta", "weights": {}})  # fmt: skip
    demo, d = Demo(champs), Draft(None, champs, eng)
    vistos = set()
    for step in range(7):
        demo.t0 = time.time() - step * Demo.STEP_SECONDS - 0.5
        s, got = demo.session(d.last_best or champs.id("Taliyah"))
        out = d.tick(s, False, pickable=set(), bannable=set(), queue={"kind": "draft", "name": "Demo", "demo": True})
        vistos.add(got)
        assert out["hero"] and out["timer_phase"]
        if got == 1:
            assert out["my_turn"] == "ban" and out["ban_suggestions"]
        if got == 4:
            assert out["my_turn"] == "pick"
        if got >= 5:
            assert out["locked"]  # confirmado: la tarjeta es tu campeón
    assert vistos == set(range(7))
