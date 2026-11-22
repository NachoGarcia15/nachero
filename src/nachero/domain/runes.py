"""Paginas de runas: validar una recomendacion y convertirla al formato del cliente.

Una recomendacion es {"pri": [4 runas], "sec": [2 runas], "mod": [3 fragmentos]} con ids del juego.
La rama principal y la secundaria se deducen del catalogo (perkstyles.json).
"""

PAGE_PREFIX = "Nachero"
OLD_PAGE_PREFIXES = ("draftbot",)  # paginas creadas con el nombre antiguo de la app
SOURCE_ES = {"pick": "la más popular", "win": "la de mayor WR"}


def is_shard(perk_id: int) -> bool:
    return 5000 <= perk_id < 6000


def perk_styles(perkstyles: dict) -> dict[int, int]:
    """Rama de cada runa (sin fragmentos, que aparecen en todas las ramas)."""
    out = {}
    for style in perkstyles.get("styles", []):
        for slot in style.get("slots", []):
            for perk in slot.get("perks", []):
                if not is_shard(perk):
                    out[perk] = style["id"]
    return out


def is_own_page(name: str) -> bool:
    """Pagina creada por la app (con su nombre actual o el antiguo): la unica que se puede tocar."""
    return name.startswith((PAGE_PREFIX, *OLD_PAGE_PREFIXES))


def page_name(champion: str, role_short: str) -> str:
    """Nombre corto y reconocible; solo se tocan paginas que empiezan por PAGE_PREFIX."""
    return f"{PAGE_PREFIX} · {champion} {role_short}".strip()[:25]


def build_page(rune_set: dict, styles_of: dict[int, int], name: str) -> dict | None:
    """Cuerpo para POST /lol-perks/v1/pages, o None si la recomendacion no es una pagina valida."""
    pri, sec, mod = rune_set.get("pri") or [], rune_set.get("sec") or [], rune_set.get("mod") or []
    if (len(pri), len(sec), len(mod)) != (4, 2, 3):
        return None
    primary, secondary = styles_of.get(pri[0]), styles_of.get(sec[0])
    if not primary or not secondary or primary == secondary:
        return None
    if any(styles_of.get(p) != primary for p in pri) or any(styles_of.get(p) != secondary for p in sec):
        return None
    if not all(is_shard(m) for m in mod):
        return None
    return {
        "name": name,
        "primaryStyleId": primary,
        "subStyleId": secondary,
        "selectedPerkIds": [*pri, *sec, *mod],
        "current": True,
    }


def describe(
    rune_set: dict, styles_of: dict[int, int], perk_names: dict[int, str], style_names: dict[int, str]
) -> dict | None:
    """Resumen legible para el panel: piedra angular, ramas y runas."""
    pri, sec = rune_set.get("pri") or [], rune_set.get("sec") or []
    if len(pri) != 4 or len(sec) != 2:
        return None
    return {
        "keystone": perk_names.get(pri[0], str(pri[0])),
        "keystone_id": pri[0],
        "primary": style_names.get(styles_of.get(pri[0], 0), ""),
        "secondary": style_names.get(styles_of.get(sec[0], 0), ""),
        "runes": [perk_names.get(p, str(p)) for p in [*pri[1:], *sec]],
    }
