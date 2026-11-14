"""Rutas de la app.

El codigo y los recursos viven dentro del paquete. Los datos del usuario (ajustes, historial,
caches, logs) viven fuera, en una carpeta propia:

  Windows:  %APPDATA%\\draftbot
  otros:    ~/.local/share/draftbot

Se puede cambiar con la variable de entorno DRAFTBOT_HOME (util para pruebas).
"""

import os
import shutil
import sys
from pathlib import Path

# Dentro de draftbot.exe (PyInstaller) los recursos se extraen junto al paquete
FROZEN = bool(getattr(sys, "frozen", False))
PACKAGE_DIR = Path(__file__).resolve().parent
UI_DIR = PACKAGE_DIR / "ui"
DEFAULT_CONFIG = PACKAGE_DIR / "defaults" / "config.json"

# Carpeta del proyecto (para migrar datos de versiones antiguas que los guardaban junto al codigo)
PROJECT_DIR = PACKAGE_DIR.parent.parent


def user_dir() -> Path:
    env = os.environ.get("DRAFTBOT_HOME")
    if env:
        base = Path(env)
    elif sys.platform == "win32" and os.environ.get("APPDATA"):
        base = Path(os.environ["APPDATA"]) / "draftbot"
    else:
        base = Path.home() / ".local" / "share" / "draftbot"
    base.mkdir(parents=True, exist_ok=True)
    return base


def config_file() -> Path:
    return user_dir() / "config.json"


def history_file() -> Path:
    return user_dir() / "history_cache.json"


def player_file() -> Path:
    return user_dir() / "player_cache.json"


def cache_dir() -> Path:
    d = user_dir() / "cache"
    d.mkdir(exist_ok=True)
    return d


def log_dir() -> Path:
    d = user_dir() / "logs"
    d.mkdir(exist_ok=True)
    return d


LEGACY = {
    "config.json": config_file,
    "history_cache.json": history_file,
    "player_cache.json": player_file,
    "lolalytics_cache.json": lambda: cache_dir() / "lolalytics_cache.json",
    "gol_cache.json": lambda: cache_dir() / "gol_cache.json",
}


def migrate_legacy(project_dir: Path = PROJECT_DIR) -> list[str]:
    """Mueve los datos que versiones anteriores guardaban junto al codigo. Devuelve lo movido."""
    moved: list[str] = []
    if FROZEN:  # el ejecutable no tiene carpeta de proyecto
        return moved
    for name, target in LEGACY.items():
        old, new = project_dir / name, target()
        if old.is_file() and not new.exists():
            shutil.move(str(old), str(new))
            moved.append(name)
    return moved
