"""Conectar con el cliente sin abrir consolas (#93).

La línea de comandos de LeagueClientUx.exe se lee con la API de Windows (`clients/winproc.py`);
PowerShell solo queda de respaldo y sin ventana, igual que el acceso directo del Menú Inicio."""

import os
import subprocess
import sys
from pathlib import Path

import pytest

from nachero.app import desktop
from nachero.clients import lcu as L
from nachero.clients import winproc

LINEA = (
    '"C:/Riot Games/League of Legends/LeagueClientUx.exe" "--riotclient-auth-token=x" '
    '"--riotclient-app-port=1111" "--app-port=63973" "--remoting-auth-token=abc-XYZ_1" "--locale=es_ES"'
)


def test_puerto_y_token_de_la_linea_de_comandos():
    assert L.parse_cmdline(LINEA) == ("63973", "abc-XYZ_1")  # no confunde --riotclient-app-port
    assert L.parse_cmdline("LeagueClientUx.exe --app-port=5 --remoting-auth-token=tok") == ("5", "tok")
    assert L.parse_cmdline("") is None and L.parse_cmdline('"--app-port=1"') is None


@pytest.fixture
def sin_procesos(monkeypatch):
    """Cualquier proceso lanzado queda apuntado (y no se lanza)."""
    calls = []

    def run(args, **kw):
        calls.append((args, kw))
        return subprocess.CompletedProcess(args, 0, stdout=LINEA + "\n", stderr="")

    monkeypatch.setattr(subprocess, "run", run)
    return calls


def test_fuera_de_windows_no_lanza_nada(monkeypatch, sin_procesos):
    monkeypatch.setattr(sys, "platform", "linux")
    assert L.client_cmdlines() == [] and sin_procesos == []


def test_en_windows_lee_con_la_api_sin_powershell(monkeypatch, sin_procesos):
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(winproc, "cmdlines", lambda name: [LINEA] if name == "LeagueClientUx.exe" else [])
    lcu = L.LCU()
    monkeypatch.setattr(L.LCU, "_from_lockfile", staticmethod(lambda: None))
    assert lcu.connect() and lcu.base == "https://127.0.0.1:63973"
    assert sin_procesos == []  # ni una consola


def test_si_la_api_falla_powershell_va_sin_ventana(monkeypatch, sin_procesos):
    monkeypatch.setattr(sys, "platform", "win32")

    def falla(name):
        raise OSError("sin ntdll")

    monkeypatch.setattr(winproc, "cmdlines", falla)
    assert L.client_cmdlines() == [LINEA]
    ((args, kw),) = sin_procesos
    assert args[0] == "powershell" and kw["creationflags"] == winproc.CREATE_NO_WINDOW


def test_cliente_como_administrador_usa_el_lockfile(monkeypatch, sin_procesos):
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(winproc, "cmdlines", lambda name: [])  # Windows no deja leerla
    monkeypatch.setattr(L.LCU, "_from_lockfile", staticmethod(lambda: ("1234", "tok")))
    lcu = L.LCU()
    assert lcu.connect() and lcu.base == "https://127.0.0.1:1234" and sin_procesos == []


def test_acceso_directo_sin_ventana_y_con_comillas_escapadas(monkeypatch, tmp_path, sin_procesos):
    monkeypatch.setattr(sys, "platform", "win32")
    scripts = []
    real_write = os.write

    def write(fd, data):
        scripts.append(data.decode("utf-8"))
        return real_write(fd, data)

    monkeypatch.setattr(os, "write", write)
    lnk = tmp_path / "O'Brien" / "Nachero.lnk"
    desktop._create_lnk(str(lnk), r"C:\Users\O'Brien\nachero.exe", "")
    # PowerShell no crea el .lnk (es un doble): se prueba también el respaldo de VBScript
    assert [a[0] for a, _ in sin_procesos] == ["powershell", "cscript"]
    assert all(kw.get("creationflags") == winproc.CREATE_NO_WINDOW for _, kw in sin_procesos)
    ps, vbs = scripts
    assert "C:\\Users\\O''Brien\\nachero.exe'" in ps and "O'Brien" not in ps.replace("O''Brien", "")
    assert 'lnk.TargetPath = "C:\\Users\\O\'Brien\\nachero.exe"' in vbs


def test_hidden_solo_en_windows(monkeypatch):
    monkeypatch.setattr(sys, "platform", "linux")
    assert winproc.hidden() == {}
    monkeypatch.setattr(sys, "platform", "win32")
    assert winproc.hidden() == {"creationflags": 0x08000000}


# ------------------------------------------------------------------ Windows de verdad (CI)
@pytest.mark.skipif(sys.platform != "win32", reason="API de Windows")
def test_api_de_windows_lee_este_proceso():
    exe = Path(sys.executable).name
    assert os.getpid() in winproc.pids(exe)
    line = winproc.cmdline(os.getpid())
    assert line and "pytest" in line.lower()
    assert winproc.cmdline(0) is None  # el proceso inactivo del sistema no se puede abrir
    assert winproc.pids("no-existe-nachero.exe") == []
