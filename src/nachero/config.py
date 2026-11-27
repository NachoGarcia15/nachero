"""Ajustes: valores por defecto del paquete + los del usuario (en su carpeta de datos).

Solo se guardan en el archivo del usuario; los valores por defecto nunca se modifican.
"""

import contextlib
import json
import shutil
from copy import deepcopy
from typing import Any

from nachero import paths
from nachero.domain.common import ROLES

TOGGLES = [
    "auto_accept",
    "auto_ban",
    "auto_hover_pick",
    "auto_lock_pick",
    "auto_spells",
    "import_runes",
    "open_coachless_on_lock",
]
# Interruptores de la app (no de la partida): se cambian en Ajustes → App
APP_TOGGLES = ["close_to_tray", "start_with_windows", "tray_notify"]
WEIGHT_KEYS = ("pool", "meta", "matchup", "comp")
MAX_CHAMP_LIST = 40  # campeones en pool_bonus y never_pick
MAX_BAN_PRIORITY = 10  # bans prioritarios por rol
MODES = ("paused", "observe", "active")
# Hechizos que se pueden poner por rol (los mismos nombres que app.state.SPELL_IDS)
SPELLS = ("Cleanse", "Exhaust", "Flash", "Ghost", "Heal", "Smite", "Teleport", "Ignite", "Barrier")
STYLE_KEYS = ("carry_weight", "utility_weight")
STYLE_DEFAULTS = {"carry_weight": 1.0, "utility_weight": 0.2}
PRACTICE_BONUS = 1.5  # puntos de WR de «lo estoy practicando» en la configuración guiada
# Blindability (#68): lo que se puede cambiar desde el panel (el resto, en config.json)
BLIND_KEYS = ("counter_rate", "pool_size", "matchup_model", "safe_pct", "counter_pct")
# Liga de las páginas de matchups y runas de Lolalytics y de los datos propios (#86)
BUILD_TIERS = ("emerald_plus", "diamond_plus", "master_plus")
LEAGUE_NAMES = {"emerald_plus": "Esmeralda+", "diamond_plus": "Diamante+", "master_plus": "Master+"}


def _number(v, lo: float, hi: float) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool) and lo <= v <= hi


def _spell_pair(v) -> bool:
    """Dos hechizos distintos y conocidos."""
    return isinstance(v, list) and len(v) == 2 and all(s in SPELLS for s in v) and v[0] != v[1]


def _champ_names(v) -> list[str] | None:
    """Lista de nombres de campeón válida (sin repetir), o None."""
    if not isinstance(v, list) or len(v) > MAX_CHAMP_LIST:
        return None
    if not all(isinstance(n, str) and 0 < len(n.strip()) <= 30 for n in v):
        return None
    return list(dict.fromkeys(n.strip() for n in v))


def same_kind(default, value) -> bool:
    """¿`value` tiene el tipo de `default`? Enteros y decimales valen igual; un booleano, no."""
    if isinstance(default, bool) or isinstance(value, bool):
        return isinstance(default, bool) and isinstance(value, bool)
    if isinstance(default, (int, float)) and isinstance(value, (int, float)):
        return True
    return type(default) is type(value)


def deep_merge(base: dict, over: dict) -> dict:
    """Mezcla recursiva: lo de `over` gana, pero conserva las claves nuevas de `base`. Un valor de
    `over` con otro tipo que el de `base` (un archivo editado a mano o roto, p. ej. "weights": "x")
    no entra: rompería el motor en cada vuelta. Las claves que `base` no tiene pasan tal cual."""
    out = deepcopy(base)
    for k, v in over.items():
        cur = out.get(k)
        if isinstance(v, dict) and isinstance(cur, dict):
            out[k] = deep_merge(cur, v)
        elif k in out and cur is not None and not same_kind(cur, v):
            continue
        else:
            out[k] = deepcopy(v)
    return out


def migrate(user: dict, defaults: dict) -> dict:
    """Actualiza valores guardados que eran el antiguo valor por defecto."""
    if user.get("history_queues") == [420]:  # antes solo soloq: las demas colas tambien son experiencia
        user["history_queues"] = defaults["history_queues"]
    return user


PROBLEM: dict = {"text": None}  # por qué no se pudo leer config.json (lo dice el registro al arrancar)


def load() -> dict:
    """Ajustes por defecto con los del usuario encima. Si su archivo está roto, se guarda una copia
    (`config.roto.json`) antes de seguir con los de por defecto: el siguiente guardado lo pisaría y
    se perderían sin aviso."""
    defaults = json.loads(paths.DEFAULT_CONFIG.read_text(encoding="utf-8"))
    f = paths.config_file()
    PROBLEM["text"] = None
    if not f.exists():
        return defaults
    try:
        user = json.loads(f.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        user = e
    if isinstance(user, dict):
        return deep_merge(defaults, migrate(user, defaults))
    backup = f.with_name("config.roto.json")
    with contextlib.suppress(OSError):
        shutil.copyfile(f, backup)
    why = "no es JSON válido" if isinstance(user, Exception) else "no es un objeto JSON"
    PROBLEM["text"] = f"Tus ajustes ({f.name}) {why}: uso los de por defecto y guardo una copia en {backup.name}"
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
        if k in (*TOGGLES, *APP_TOGGLES) and isinstance(v, bool):
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
        elif k == "stats_mode" and v in ("auto", "own", "lolalytics"):
            cfg[k] = v
            changed.append(
                "fuente de estadísticas " + {"auto": "automática", "own": "propia", "lolalytics": "Lolalytics"}[v]
            )
        elif k == "start_mode" and v in MODES:
            cfg[k] = v
            changed.append("modo al abrir " + {"paused": "pausado", "observe": "observar", "active": "activo"}[v])
        elif k == "spells_by_role" and isinstance(v, dict):
            for role, pair in v.items():
                if role in ROLES and _spell_pair(pair):
                    cfg.setdefault(k, {})[role] = list(pair)
                    changed.append(f"hechizos de {role}")
        elif k == "style" and isinstance(v, dict):
            for sk, sv in v.items():
                if sk in STYLE_KEYS and _number(sv, 0, 2):
                    cfg.setdefault(k, {})[sk] = round(float(sv), 2)
                    changed.append(f"estilo {sk}")
        elif k == "ban_priority" and isinstance(v, dict):
            for role, names in v.items():
                clean = _champ_names(names)
                if role in ROLES and clean is not None and len(clean) <= MAX_BAN_PRIORITY:
                    cfg.setdefault(k, {})[role] = clean
                    changed.append(f"bans prioritarios de {role}")
        elif k == "setup_done" and isinstance(v, bool):
            cfg[k] = v
            changed.append("configuración guiada" + (" hecha" if v else " por hacer"))
        elif k == "blind" and isinstance(v, dict):
            changed += _apply_blind(cfg, v)
        elif k == "build_tier" and v in BUILD_TIERS:
            cfg[k] = v
            changed.append("liga de los matchups " + v)
        elif k == "weights" and isinstance(v, dict):
            for wk, wv in v.items():
                if wk in WEIGHT_KEYS and isinstance(wv, (int, float)) and not isinstance(wv, bool) and 0 <= wv <= 2:
                    cfg.setdefault("weights", {})[wk] = round(float(wv), 2)
                    changed.append(f"peso {wk}")
    return changed


def _apply_blind(cfg: dict, v: dict) -> list[str]:
    """Ajustes de blindability del panel: η, pool del rival (igual en todos los roles o por rol),
    modelo de matchups y umbrales de las etiquetas."""
    out = []
    b = cfg.setdefault("blind", {})
    if _number(v.get("counter_rate"), 0, 1):
        b["counter_rate"] = round(float(v["counter_rate"]), 2)
        out.append("η (cuánto counterea el rival)")
    size = v.get("pool_size")
    if isinstance(size, (int, float)) and _number(size, 1, 20):
        b["pool_size"] = dict.fromkeys(ROLES, int(size))
        out.append("pool del rival")
    elif isinstance(size, dict) and all(r in ROLES and _number(n, 1, 20) for r, n in size.items()):
        b["pool_size"] = {**b.get("pool_size", {}), **{r: int(n) for r, n in size.items()}}
        out.append("pool del rival")
    if v.get("matchup_model") in ("measured", "classic"):
        b["matchup_model"] = v["matchup_model"]
        out.append("modelo de matchups " + ("medido" if v["matchup_model"] == "measured" else "clásico"))
    for key in ("safe_pct", "counter_pct"):
        if _number(v.get(key), 0, 100):
            b[key] = round(float(v[key]), 1)
            out.append("umbral " + ("seguro a ciegas" if key == "safe_pct" else "de counter"))
    return out


CFG: dict = {}


def init() -> dict:
    """Carga los ajustes en el diccionario compartido CFG (se llama al arrancar)."""
    CFG.clear()
    CFG.update(load())
    return CFG
