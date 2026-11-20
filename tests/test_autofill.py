"""Autofill y rol secundario: recomendar distinto si no es tu rol (issue #16)."""

import pytest

from conftest import CHAMPS, FakeChamps, FakeLola, all_roles
from nachero.app.draft import Draft
from nachero.config import CFG
from nachero.domain.engine import AUTOFILL_GAMES, Engine
from nachero.domain.player import Player
from test_roles_conexion import _game, session


class Champs(FakeChamps):
    """Como los de conftest, con la dificultad del cliente (1 fácil, 3 difícil)."""

    DIFFICULTY = {3: 3, 4: 1, 10: 3}  # Assassin difícil, Marksman fácil, Shooter difícil

    def info(self, cid):
        return {**super().info(cid), "difficulty": self.DIFFICULTY.get(cid, 2)}


def games(**per_role):
    out = []
    for role, n in per_role.items():
        out += [{**_game(role), "gameId": len(out) + i} for i in range(n)]
    return out


def engine(champs, played, **cfg):
    # bottom: Marksman (fácil) y Shooter (difícil) igual de fuertes; top: Bruiser
    lola = FakeLola(all_roles(bottom={4: (52, 9000, 8, 90), 10: (52, 9000, 8, 90)}, top={5: (52, 9000, 8, 90)}))
    return Engine(champs, lola, Player(played, []), {"pick_mode": "pool", "weights": {}, "main_role": "auto", **cfg})


@pytest.fixture
def ch():
    return Champs(CHAMPS)


# ------------------------------------------------------------------ detectar autofill
def test_rol_principal_no_es_autofill(ch):
    assert engine(ch, games(jungle=50)).role_fit("jungle")["kind"] == "main"


def test_rol_casi_sin_partidas_es_autofill(ch):
    fit = engine(ch, games(jungle=50, bottom=2)).role_fit("bottom")
    assert fit == {"kind": "autofill", "kind_es": "autofill", "games": 2, "main": "jungle"}


def test_rol_secundario_no_es_autofill(ch):
    eng = engine(ch, games(jungle=50), secondary_role="bottom")
    assert eng.role_fit("bottom")["kind"] == "secondary"


def test_rol_que_juegas_a_menudo_no_es_autofill(ch):
    eng = engine(ch, games(jungle=60, top=AUTOFILL_GAMES))
    assert eng.role_fit("top")["kind"] == "familiar"


def test_muchas_partidas_pero_poca_parte_es_autofill(ch):
    # 15 partidas de top entre 400: el 4 %, no es un rol tuyo
    assert engine(ch, games(jungle=385, top=15)).role_fit("top")["kind"] == "autofill"


def test_sin_historial_no_se_sabe(ch):
    assert engine(ch, []).role_fit("top")["kind"] == "unknown"


def test_rol_principal_fijado_en_ajustes(ch):
    eng = engine(ch, games(jungle=50), main_role="bottom")
    assert eng.role_fit("bottom")["kind"] == "main"
    assert eng.role_fit("jungle")["kind"] == "familiar"  # el que más juegas sigue siendo tuyo


# ------------------------------------------------------------------ cómo cambia la recomendación
def _rows(eng, role):
    picks, ctx = eng.picks(role, set(), set(), [], [])
    return {p["id"]: p for p in picks}, ctx


def test_en_autofill_prioriza_campeones_faciles(ch):
    rows, ctx = _rows(engine(ch, games(jungle=50)), "bottom")
    assert ctx["role_fit"]["kind"] == "autofill"
    assert rows[4]["parts"]["ease"] > 0 > rows[10]["parts"]["ease"]
    assert rows[4]["est"] > rows[10]["est"]
    assert rows[4]["why"][0]["text"].startswith("fácil de jugar")


def test_en_tu_rol_la_dificultad_no_cuenta(ch):
    rows, ctx = _rows(engine(ch, games(bottom=50)), "bottom")
    assert ctx["role_fit"]["kind"] == "main"
    assert "ease" not in rows[4]["parts"]
    assert rows[4]["est"] == rows[10]["est"]


def test_en_autofill_pesa_mas_la_fuerza_en_el_parche(ch):
    tuyo, _ = _rows(engine(ch, games(bottom=50)), "bottom")
    autofill, _ = _rows(engine(ch, games(jungle=50)), "bottom")
    assert autofill[4]["parts"]["meta"] >= tuyo[4]["parts"]["meta"]


def test_evaluar_un_campeon_tambien_tiene_en_cuenta_el_autofill(ch):
    row = engine(ch, games(jungle=50)).evaluate(4, "bottom")
    assert row["parts"]["ease"] > 0


# ------------------------------------------------------------------ champ select
def test_la_champ_select_dice_si_vas_de_autofill(ch, monkeypatch):
    for k, v in {"auto_spells": False, "spells_by_role": {}, "auto_hover_pick": False, "import_runes": False}.items():
        monkeypatch.setitem(CFG, k, v)
    out = Draft(None, ch, engine(ch, games(jungle=50))).tick(session("bottom"), False, pickable=set(), bannable=set())
    assert out["role_fit"]["kind"] == "autofill" and out["role_fit"]["games"] == 0
    assert out["hero"]["id"] == 4  # el fácil
