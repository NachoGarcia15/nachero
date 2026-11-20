"""Ajustes: valores por defecto del paquete + los del usuario (en su carpeta de datos).

Solo se guardan en el archivo del usuario; los valores por defecto nunca se modifican.
"""

import json
from copy import deepcopy
from typing import Any

from nachero import paths
from nachero.domain.common import ROLES

TOGGLES = [
    "auto_accept",
    "auto_hover_pick",
    "auto_lock_pick",
    "auto_spells",
    "import_runes",
    "open_coachless_on_lock",
]
WEIGHT_KEYS = ("pool", "meta", "matchup", "comp")
MAX_CHAMP_LIST = 40  # campeones en pool_bonus y never_pick
PRACTICE_BONUS = 1.5  # puntos de WR de «lo estoy practicando» en la configuración guiada


def _champ_names(v) -> list[str] | None:
    """Lista de nombres de campeón válida (sin repetir), o None."""
    if not isinstance(v, list) or len(v) > MAX_CHAMP_LIST:
        return None
    if not all(isinstance(n, str) and 0 < len(n.strip()) <= 30 for n in v):
        return None
    return list(dict.fromkeys(n.strip() for n in v))


def deep_merge(base: dict, over: dict) -> dict:
    """Mezcla recursiva: lo de `over` gana, pero conserva las claves nuevas de `base`."""
    out = deepcopy(base)
    for k, v in over.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = deep_merge(out[k], v)
        else:
            out[k] = deepcopy(v)
    return out


def migrate(user: dict, defaults: dict) -> dict:
    """Actualiza valores guardados que eran el antiguo valor por defecto."""
    if user.get("history_queues") == [420]:  # antes solo soloq: las demas colas tambien son experiencia
        user["history_queues"] = defaults["history_queues"]
    return user


def load() -> dict:
    defaults = json.loads(paths.DEFAULT_CONFIG.read_text(encoding="utf-8"))
    f = paths.config_file()
    if f.exists():
        try:
            return deep_merge(defaults, migrate(json.loads(f.read_text(encoding="utf-8")), defaults))
        except (OSError, ValueError):
            pass
    return defaults


def save(cfg: dict) -> None:
    f = paths.config_file()
    tmp = f.with_suffix(".tmp")
    tmp.write_text(json.dumps(cfg, indent=2, ensure_ascii=False), encoding="utf-8")
    tmp.replace(f)


def apply_settings(cfg: dict, body: dict[str, Any]) -> list[str]:
    """Valida y aplica cambios del panel. Devuelve la lista de cambios aceptados."""
    changed = []
    for k, v in body.items():
        if k in TOGGLES and isinstance(v, bool):
            cfg[k] = v
            changed.append(k)
        elif k == "lock_when_seconds_left" and isinstance(v, (int, float)) and not isinstance(v, bool) and 1 <= v <= 30:
            cfg[k] = int(v)
            changed.append(k)
        elif k == "runes_source" and v in ("pick", "win"):
            cfg[k] = v
            changed.append("runas " + ("más populares" if v == "pick" else "de mayor WR"))
        elif k == "pick_mode" and v in ("pool", "meta"):
            cfg[k] = v
            changed.append("modo " + ("tu pool" if v == "pool" else "solo meta y draft"))
        elif k == "main_role" and v in ("auto", *ROLES):
            cfg[k] = v
            changed.append("rol principal " + ("automático" if v == "auto" else v))
        elif k == "secondary_role" and v in ("none", *ROLES):
            cfg[k] = v
            changed.append("rol secundario " + ("ninguno" if v == "none" else v))
        elif k == "never_pick" and _champ_names(v) is not None:
            cfg[k] = _champ_names(v)
            changed.append("campeones que nunca juegas")
        elif k == "pool_bonus" and isinstance(v, dict) and _champ_names(list(v)) is not None:
            ok = all(isinstance(b, (int, float)) and not isinstance(b, bool) and -5 <= b <= 5 for b in v.values())
            if ok:
                cfg[k] = {n.strip(): round(float(b), 2) for n, b in v.items() if b}
                changed.append("campeones con puntos extra")
        elif k == "setup_done" and isinstance(v, bool):
            cfg[k] = v
            changed.append("configuración guiada" + (" hecha" if v else " por hacer"))
        elif k == "weights" and isinstance(v, dict):
            for wk, wv in v.items():
                if wk in WEIGHT_KEYS and isinstance(wv, (int, float)) and not isinstance(wv, bool) and 0 <= wv <= 2:
                    cfg.setdefault("weights", {})[wk] = round(float(wv), 2)
                    changed.append(f"peso {wk}")
    return changed


CFG: dict = {}


def init() -> dict:
    """Carga los ajustes en el diccionario compartido CFG (se llama al arrancar)."""
    CFG.clear()
    CFG.update(load())
    return CFG
