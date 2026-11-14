"""Constantes y utilidades compartidas por el dominio."""

import re

ROLES = ["top", "jungle", "middle", "bottom", "utility"]
ROLE_ES = {"top": "Top", "jungle": "Jungla", "middle": "Mid", "bottom": "ADC", "utility": "Support", "": "?"}
ROLE_SHORT = {"top": "TOP", "jungle": "JG", "middle": "MID", "bottom": "ADC", "utility": "SUP", "": ""}
TIER_NAMES = {
    1: "S+",
    2: "S",
    3: "S-",
    4: "A+",
    5: "A",
    6: "A-",
    7: "B+",
    8: "B",
    9: "B-",
    10: "C+",
    11: "C",
    12: "C-",
    13: "D+",
    14: "D",
    15: "D-",
}


def shrink(x, n, k):
    """Encoge un efecto hacia 0 segun el tamano de muestra: x * n / (n + k)."""
    return x * n / (n + k) if n else 0.0


def tier_name(row):
    """Nombre del tier de Lolalytics de una fila de la tier list (o None)."""
    return TIER_NAMES.get(row.get("tier")) if row else None


def norm(name):
    """Normaliza un nombre de campeon para comparar entre fuentes."""
    return re.sub(r"[^a-z0-9]", "", name.lower())
