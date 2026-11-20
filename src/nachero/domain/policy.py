"""Normas de Riot: aviso legal y qué toca Nachero en el cliente según el modo y los ajustes.

Texto del aviso copiado de https://developer.riotgames.com/policies/general («legal boilerplate»,
actualizado el 29 de mayo de 2025) con el nombre del producto en lugar de «[Your product]».
"""

RIOT_NOTICE = (
    "Nachero isn't endorsed by Riot Games and doesn't reflect the views or opinions of Riot Games "
    "or anyone officially involved in producing or managing Riot Games properties. Riot Games, and "
    "all associated properties are trademarks or registered trademarks of Riot Games, Inc."
)

# Decisiones de juego: opcionales y desactivadas por defecto (las normas no aceptan apps que decidan
# por el jugador). Siguen la recomendación de Nachero, pero nunca pisan lo que marque el jugador:
# Nachero marca su recomendación; el pick confirma lo que esté marcado al final del turno y el ban
# no se confirma nunca: lo hace el cliente al acabar el tiempo (issue #30).
GAME_DECISIONS = ("auto_ban", "auto_hover_pick", "auto_lock_pick")

# Qué hace en el cliente cada interruptor en modo Activo, en el orden de la partida.
CLIENT_ACTIONS = (
    ("auto_accept", "acepta la partida"),
    ("auto_spells", "pone los hechizos de tu rol"),
    ("auto_ban", "marca tu ban (lo confirma el cliente al acabar el tiempo)"),
    ("auto_hover_pick", "marca tu pick"),
    ("auto_lock_pick", "confirma el pick marcado"),
    ("import_runes", "crea la página de runas «Nachero»"),
)

MODES = {
    "paused": ("Pausado", "No analiza ni actúa: ni recomienda ni toca el cliente."),
    "observe": (
        "Observar",
        "Recomienda y dice qué haría, pero no toca el cliente: solo lee la selección de campeón y tu historial.",
    ),
    "active": ("Activo", "Recomienda y hace en el cliente lo que tengas activado en Ajustes."),
}


def client_actions(cfg: dict) -> list[str]:
    """Lo que Nachero hará en el cliente en modo Activo con estos ajustes."""
    out = []
    for key, text in CLIENT_ACTIONS:
        if cfg.get(key, False):
            if key == "auto_lock_pick":
                text += f" a falta de {cfg.get('lock_when_seconds_left', 8)} s"
            out.append(text)
    return out


def mode_help(cfg: dict) -> dict[str, dict]:
    """Explicación de cada modo para el panel: qué hace y qué toca en el cliente."""
    active = client_actions(cfg)
    out = {}
    for mode, (label, text) in MODES.items():
        touches = active if mode == "active" else []
        out[mode] = {"label": label, "text": text, "touches": touches, "summary": summary(mode, touches)}
    return out


def summary(mode: str, touches: list[str]) -> str:
    """Frase corta para el panel con lo que toca el modo."""
    if mode != "active":
        return "No toca el cliente."
    if not touches:
        return "Con tus ajustes no toca el cliente: solo recomienda."
    head = ", ".join(touches[:-1])
    return "En el cliente " + (f"{head} y {touches[-1]}" if head else touches[-1]) + "."
