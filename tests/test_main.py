"""Arranque: el punto de entrada importa y entiende sus opciones (lo que ejecuta draftbot.exe)."""

import pytest

from draftbot import __version__, paths
from draftbot.app import main as M


def test_opciones():
    args = M.parse_args(["--port", "8766", "--no-browser", "--observe"])
    assert args.port == 8766 and args.no_browser and args.observe


def test_version(capsys):
    with pytest.raises(SystemExit) as e:
        M.main(["--version"])
    assert e.value.code == 0
    assert __version__ in capsys.readouterr().out


def test_fuera_del_ejecutable_no_es_frozen():
    assert paths.FROZEN is False
    assert (paths.UI_DIR / "index.html").is_file() and paths.DEFAULT_CONFIG.is_file()
