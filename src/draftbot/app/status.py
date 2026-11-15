"""Qué le falta al panel y diagnóstico para informes: plataforma, estados vacíos y texto sin datos
personales. Todo es lógica pura sobre el estado de la app (sin red ni disco)."""

import platform
import re
import sys


def platform_info(sys_platform: str | None = None, release: str | None = None) -> dict:
    """Sistema en el que corre draftbot. Solo Windows puede hablar con el cliente de LoL."""
    sys_platform = sys.platform if sys_platform is None else sys_platform
    release = platform.release() if release is None else release
    if sys_platform == "win32":
        return {"supported": True, "name": "Windows"}
    if sys_platform.startswith("linux"):
        # WSL corre un kernel de Linux con "microsoft" en la versión (p. ej. 5.15.90.1-microsoft-standard-WSL2)
        name = "WSL" if "microsoft" in release.lower() else "Linux"
    elif sys_platform == "darwin":
        name = "macOS"
    else:
        name = sys_platform
    return {"supported": False, "name": name}


def platform_warning(info: dict) -> str | None:
    if info.get("supported", True):
        return None
    return (
        f"draftbot necesita Windows con el cliente de LoL abierto y estás en {info.get('name')}: "
        "descarga draftbot.exe y ábrelo en Windows."
    )


def empty_states(app: dict) -> dict:
    """Por qué cada parte del panel está vacía, o None si no falta nada (o solo falta un momento).

    Códigos: platform, no_champions, loading, no_client, no_games, no_patch, no_data."""
    connected = bool(app.get("connected"))
    base = None
    if not (app.get("platform") or {}).get("supported", True) and not connected:
        base = "platform"
    elif app.get("issue") == "no_champions":
        base = "no_champions"
    elif app.get("loading"):
        base = "loading"

    pool = None
    if not app.get("pool"):
        if base:
            pool = base
        elif not app.get("games"):
            pool = "no_games" if connected else "no_client"

    data = None
    if not (app.get("data") or {}).get("games"):
        if base:
            data = base
        elif not app.get("patch"):
            data = "no_patch"
        elif (app.get("data") or {}).get("patch"):
            data = "no_data"

    return {"draft": base, "pool": pool, "data": data}


# ---------------------------------------------------------------- diagnóstico
_UUID = re.compile(r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b", re.I)
_PUUID = re.compile(r"\b[A-Za-z0-9_-]{70,}\b")  # el puuid de Riot tiene 78 caracteres
# el nombre de usuario puede tener espacios: llega hasta la siguiente barra
_HOME = re.compile(r"([A-Za-z]:[\\/]+Users[\\/]+|/home/|/Users/)[^\\/:'\"\n]+", re.I)


def scrub(text: str, secrets: tuple[str, ...] = ()) -> str:
    """Quita del texto rutas de usuario, identificadores y los textos de `secrets` (p. ej. el
    nombre de usuario del sistema o de invocador)."""
    for s in sorted({s for s in secrets if s and len(s) >= 3}, key=len, reverse=True):
        text = re.sub(re.escape(s), "<oculto>", text, flags=re.I)
    text = _HOME.sub(lambda m: m.group(1) + "<usuario>", text)
    text = _UUID.sub("<id>", text)
    return _PUUID.sub("<id>", text)


def diagnostics(app: dict, version: str, system: str, frozen: bool, secrets: tuple[str, ...] = (), lines=40) -> str:
    """Informe para pegar en un mensaje: versión, sistema, fase, conexión, parche y log reciente."""
    data = app.get("data") or {}
    plat = app.get("platform") or {}
    if app.get("connected"):
        conn = "conectado al cliente"
    elif app.get("offline"):
        conn = "sin cliente (datos guardados y CommunityDragon)"
    else:
        conn = "esperando al cliente"
    empty = {k: v for k, v in empty_states(app).items() if v}
    log = list(app.get("log") or [])[:lines]
    rows = [
        f"draftbot {version} ({'draftbot.exe' if frozen else 'código fuente'})",
        f"Sistema: {system}" + ("" if plat.get("supported", True) else f" · no compatible ({plat.get('name')})"),
        f"Conexión: {conn}{' · cargando' if app.get('loading') else ''}",
        f"Fase: {app.get('phase_es') or app.get('phase') or '—'} · modo {app.get('mode')}"
        + (" · demo" if app.get("demo") else ""),
        f"Parche: {app.get('patch') or '—'} · Lolalytics {data.get('games', 0)} partidas, "
        f"{data.get('counters', 0)} matchups en caché",
        f"Partidas en el historial: {app.get('games', 0)}",
    ]
    if empty:
        rows.append("Falta: " + ", ".join(f"{k}={v}" for k, v in empty.items()))
    rows.append("")
    rows.append(f"Últimas {len(log)} líneas de Actividad:")
    rows += [f"[{e.get('t', '')}] {e.get('kind', 'info')}: {e.get('msg', '')}" for e in reversed(log)]
    return scrub("\n".join(rows), secrets)
