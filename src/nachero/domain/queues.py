"""Tipo de cola de la partida: decide si Nachero recomienda y como.

Entrada: la sesion de `/lol-gameflow/v1/session` (o un dict vacio si no se pudo leer).
- "draft": Grieta con draft (ranked solo/flex, normal draft, Clash): todo como siempre.
- "blind": Grieta sin draft (a ciegas, personalizadas, Practice Tool): sin bans ni rival
  visible; el rol es tu rol principal.
- "other": ARAM, Arena, URF y demas modos: no se recomienda ni se toca el cliente.
- "unknown": no se pudo leer la cola; se recomienda como en la Grieta.
"""

RIFT_MAP = 11
# modos de la Grieta con las reglas normales (URF, Uno para todos… tambien usan el mapa 11)
RIFT_MODES = {"CLASSIC", "PRACTICETOOL", "SWIFTPLAY"}
DRAFT_QUEUES = {400, 420, 440, 700}

QUEUE_ES = {
    400: "Normal (reclutamiento)",
    420: "Clasificatoria solo/dúo",
    430: "Normal (a ciegas)",
    440: "Clasificatoria flexible",
    450: "ARAM",
    480: "Swiftplay",
    490: "Partida rápida",
    700: "Clash",
    720: "Clash de ARAM",
    900: "URF",
    1700: "Arena",
    1710: "Arena",
    1900: "URF",
}
MODE_ES = {
    "ARAM": "ARAM",
    "CHERRY": "Arena",
    "URF": "URF",
    "ARURF": "ARURF",
    "ONEFORALL": "Uno para todos",
    "NEXUSBLITZ": "Asalto al Nexo",
    "ULTBOOK": "Libro de hechizos definitivo",
    "PRACTICETOOL": "Herramienta de práctica",
    "TUTORIAL": "Tutorial",
}


def classify(flow: dict | None) -> dict:
    """{"kind", "id", "name"} para la sesion de gameflow `flow`."""
    flow = flow if isinstance(flow, dict) else {}
    game = flow.get("gameData") or {}
    queue = game.get("queue") or {}
    fmap = flow.get("map") or {}
    qid = queue.get("id")
    qid = qid if isinstance(qid, int) else -1
    # personalizadas (3100) y Practice Tool (3140) traen la cola completa; si llegara casi
    # vacia, el mapa y el modo tambien estan en `map`
    map_id = queue.get("mapId") or fmap.get("id") or 0
    mode = (queue.get("gameMode") or fmap.get("gameMode") or "").upper()
    custom = bool(game.get("isCustomGame"))
    if not map_id and not mode and qid < 0:
        return {"kind": "unknown", "id": qid, "name": ""}

    if mode == "PRACTICETOOL":
        name = MODE_ES[mode]
    elif custom:
        name = "Personalizada" + (f" · {MODE_ES[mode]}" if mode in MODE_ES else "")
    else:
        name = QUEUE_ES.get(qid) or MODE_ES.get(mode) or queue.get("description") or mode.title() or "Desconocida"

    if map_id != RIFT_MAP or mode not in RIFT_MODES:
        kind = "other"
    elif qid in DRAFT_QUEUES:
        kind = "draft"
    else:
        kind = "blind"
    return {"kind": kind, "id": qid, "name": name}


def has_bans(session: dict) -> bool:
    """La champ select tiene fase de bans (p. ej. una personalizada en modo torneo)."""
    return any(a.get("type") == "ban" for grp in session.get("actions") or [] for a in grp)
