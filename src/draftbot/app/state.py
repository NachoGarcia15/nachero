"""Estado compartido entre el bucle principal y el servidor del panel."""

import logging
import threading
import time
from collections import deque
from logging.handlers import RotatingFileHandler

from draftbot import paths

SPELL_IDS = {
    "Cleanse": 1,
    "Exhaust": 3,
    "Flash": 4,
    "Ghost": 6,
    "Heal": 7,
    "Smite": 11,
    "Teleport": 12,
    "Ignite": 14,
    "Barrier": 21,
}
PHASE_ES = {
    None: "Sin cliente",
    "None": "Menú principal",
    "Lobby": "En la sala",
    "Matchmaking": "Buscando partida",
    "ReadyCheck": "Partida encontrada",
    "ChampSelect": "Selección de campeón",
    "GameStart": "Cargando partida",
    "InProgress": "En partida",
    "WaitingForStats": "Esperando estadísticas",
    "PreEndOfGame": "Fin de partida",
    "EndOfGame": "Fin de partida",
    "Reconnect": "Reconectar",
}
TIMER_ES = {
    "PLANNING": "Planificación",
    "BAN_PICK": "Bans y picks",
    "FINALIZATION": "Finalización",
    "GAME_STARTING": "Empezando",
}

LOCK = threading.RLock()
OPTS = {"demo": False}
APP: dict = {
    "mode": "observe",
    "connected": False,
    "offline": False,
    "loading": True,
    "phase": None,
    "draft": None,
    "idle": None,
    "rank": None,
    "pool": [],
    "log": deque(maxlen=200),
    "demo": False,
    "data": {},
}
CTX: dict = {}  # objetos de la sesion actual (cliente, motor, fuentes de datos)

logger = logging.getLogger("draftbot")


def setup_logging() -> None:
    """Registro en consola y en un archivo rotativo de la carpeta de datos del usuario."""
    if logger.handlers:
        return
    logger.setLevel(logging.INFO)
    fh = RotatingFileHandler(paths.log_dir() / "draftbot.log", maxBytes=1_000_000, backupCount=3, encoding="utf-8")
    fh.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    logger.addHandler(fh)


def log(msg: str, kind: str = "info") -> None:
    """Mensaje para el panel (pestana Actividad), la consola y el archivo de log."""
    with LOCK:
        APP["log"].appendleft({"t": time.strftime("%H:%M:%S"), "msg": msg, "kind": kind})
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)
    logger.log(logging.WARNING if kind == "warn" else logging.INFO, "%s", msg)
