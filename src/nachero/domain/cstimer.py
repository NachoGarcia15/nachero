"""Reloj de la champ select: cuánto queda de verdad del turno.

El `timer` de la sesión del cliente es una foto, no un reloj en marcha: `adjustedTimeLeftInPhase`
son los ms que quedaban en el instante `internalNowInEpochMs` (reloj de este PC), y la sesión solo
cambia cuando cambia algo del draft. Si nadie toca nada al final de tu turno, la sesión sigue
diciendo lo que quedaba al empezar (p. ej. 27 s) hasta que se acaba. Lo que queda de verdad es

    adjustedTimeLeftInPhase − (ahora − internalNowInEpochMs)

como lo calcula el propio cliente para su cuenta atrás. Si la marca de tiempo falta o no cuadra
con el reloj de este PC, se descuenta lo que ha pasado desde que Nachero vio esa foto.

Lógica pura: el reloj se pasa como argumento.
"""

SKEW_MS = 2000  # margen para una foto con la marca de tiempo un poco por delante de este PC


def snapshot_key(timer: dict) -> tuple:
    """Identifica una foto del reloj: cambia con cada actualización de la sesión."""
    return tuple(timer.get(k) for k in ("phase", "internalNowInEpochMs", "adjustedTimeLeftInPhase", "totalTimeInPhase"))


def time_left(timer: dict, now_ms: float, seen_ms: float | None = None) -> float | None:
    """Segundos que quedan de la fase en `now_ms` (ms desde 1970, reloj de este PC), o None si la
    sesión no trae reloj (no se confirma nada a ciegas). Con reloj infinito, lo que diga la foto.

    `seen_ms`: cuándo vio Nachero esta foto por primera vez; da un mínimo de tiempo pasado aunque
    la marca de tiempo del cliente falte o no sea creíble."""
    left = timer.get("adjustedTimeLeftInPhase")
    if not isinstance(left, (int, float)) or isinstance(left, bool) or left <= 0:
        return None
    if timer.get("isInfinite"):
        return left / 1000
    elapsed = 0.0 if seen_ms is None else max(0.0, now_ms - seen_ms)
    snap = timer.get("internalNowInEpochMs")
    if isinstance(snap, (int, float)) and not isinstance(snap, bool) and snap > 0:
        age = now_ms - snap
        total = timer.get("totalTimeInPhase")
        span = max(left, total if isinstance(total, (int, float)) else 0)
        if -SKEW_MS <= age <= span + SKEW_MS:  # creíble: la foto es de esta fase
            elapsed = max(elapsed, age)
    return max(0.0, (left - elapsed) / 1000)
