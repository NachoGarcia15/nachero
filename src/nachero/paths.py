"""Rutas de la app.

El codigo y los recursos viven dentro del paquete. Los datos del usuario (ajustes, historial,
caches, logs) viven fuera, en una carpeta propia:

  Windows:  %APPDATA%\\nachero
  otros:    ~/.local/share/nachero

Se puede cambiar con la variable de entorno NACHERO_HOME (util para pruebas).
"""

import os
import shutil
import sys
from pathlib import Path

# Dentro de nachero.exe (PyInstaller) los recursos se extraen junto al paquete
FROZEN = bool(getattr(sys, "frozen", False))
PACKAGE_DIR = Path(__file__).resolve().parent
UI_DIR = PACKAGE_DIR / "ui"
DEFAULT_CONFIG = PACKAGE_DIR / "defaults" / "config.json"

# Carpeta del proyecto (para migrar datos de versiones antiguas que los guardaban junto al codigo)
PROJECT_DIR = PACKAGE_DIR.parent.parent


APP_DIR_NAME = "nachero"
OLD_DIR_NAME = "draftbot"  # nombre de la app hasta la 0.7.0


def data_parent() -> Path:
    """Carpeta que contiene la de datos de la app (sin NACHERO_HOME)."""
    if sys.platform == "win32" and os.environ.get("APPDATA"):
        return Path(os.environ["APPDATA"])
    return Path.home() / ".local" / "share"


def user_dir() -> Path:
    env = os.environ.get("NACHERO_HOME")
    base = Path(env) if env else data_parent() / APP_DIR_NAME
    base.mkdir(parents=True, exist_ok=True)
    return base


def migrate_old_name(parent: Path | None = None) -> Path | None:
    """Pasa los datos de la carpeta del nombre antiguo (draftbot) a la nueva.

    Se llama antes de abrir el registro. Si la app antigua sigue abierta y no deja mover la
    carpeta, se copian los datos (sin los logs) y la antigua se queda. Devuelve la carpeta
    antigua si se ha pasado algo.
    """
    if parent is None:
        if os.environ.get("NACHERO_HOME"):
            return None
        parent = data_parent()
    old, new = parent / OLD_DIR_NAME, parent / APP_DIR_NAME
    if not old.is_dir() or (new.is_dir() and any(new.iterdir())):
        return None
    try:
        if new.is_dir():
            new.rmdir()
        old.rename(new)
    except OSError:
        try:
            shutil.copytree(old, new, dirs_exist_ok=True, ignore=shutil.ignore_patterns("logs"))
        except (OSError, shutil.Error):
            return None
    return old


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
