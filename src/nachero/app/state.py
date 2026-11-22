"""Estado compartido entre el bucle principal y el servidor del panel."""

import contextlib
import logging
import threading
import time
from collections import deque
from logging.handlers import RotatingFileHandler

from nachero import paths
from nachero.domain.tasks import Tasks

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
TASKS = Tasks()  # qué está haciendo la app (pantalla de carga e indicador de la barra)
# window: el panel está en la ventana de la app. demo_ui: la demo se abrió desde el panel (se
# cierra sola al empezar una champ select de verdad); demo_since: cuándo, para empezarla de cero.
# show_window: muestra la ventana (la pone desktop.open_window; la usa /api/show).
OPTS: dict = {"demo": False, "window": False, "demo_ui": False, "demo_since": 0.0, "show_window": None}
APP: dict = {
    "mode": "observe",
    "connected": False,
    "offline": False,
    "loading": True,
    "phase": None,
    "draft": None,
    "game": None,  # vista «En partida» (#88): drafts, ventaja de draft y tu build
    "idle": None,
    "rank": None,
    "pool": [],
    "pool_plans": {},  # plan de Tu pool por rol: seguros a ciegas y de counter (#75)
    "history": None,
    "log": deque(maxlen=200),
    "demo": False,
    "data": {},
    "platform": {"supported": True, "name": "Windows"},
    "issue": None,  # problema que impide cargar (p. ej. "no_champions")
    "games": 0,  # partidas del historial analizadas
    "patch": None,
    "tasks": TASKS,  # en /api/state sale como lista (server.snapshot)
}
CTX: dict = {}  # objetos de la sesion actual (cliente, motor, fuentes de datos)

logger = logging.getLogger("nachero")


def setup_logging() -> None:
    """Registro en consola y en un archivo rotativo de la carpeta de datos del usuario."""
    if logger.handlers:
        return
    logger.setLevel(logging.INFO)
    fh = RotatingFileHandler(paths.log_dir() / "nachero.log", maxBytes=1_000_000, backupCount=3, encoding="utf-8")
    fh.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    logger.addHandler(fh)


def log(msg: str, kind: str = "info") -> None:
    """Mensaje para el panel (pestana Actividad), la consola y el archivo de log."""
    with LOCK:
        APP["log"].appendleft({"t": time.strftime("%H:%M:%S"), "msg": msg, "kind": kind})
    # sin consola (pythonw) o con una consola rota, el registro sigue en el panel y el archivo
    with contextlib.suppress(OSError, ValueError, AttributeError):
        print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)
    logger.log(logging.WARNING if kind == "warn" else logging.INFO, "%s", msg)


def set_demo(on: bool, from_ui: bool = True) -> None:
    """Abre o cierra la champ select de demo sin reiniciar. Nunca toca el cliente."""
    with LOCK:
        OPTS["demo"] = APP["demo"] = on
        OPTS["demo_ui"] = on and from_ui
        if on:
            OPTS["demo_since"] = time.time()


def demo_must_stop(real_phase) -> bool:
    """La demo abierta desde el panel se cierra si empieza una partida de verdad."""
    return bool(OPTS["demo"] and OPTS["demo_ui"] and real_phase in ("ReadyCheck", "ChampSelect", "InProgress"))
