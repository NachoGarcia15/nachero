"""Lectura y escritura de JSON: cierra siempre el archivo y escribe de forma atomica."""

import json
import os
from typing import Any


def read_json(path: "str | os.PathLike[str]", default: Any = None) -> Any:
    """Contenido JSON del archivo, o `default` si no existe o esta corrupto."""
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return default


def write_json(path: "str | os.PathLike[str]", data: Any, indent: "int | None" = None) -> None:
    """Escribe en un archivo temporal y lo renombra: nunca deja un JSON a medias."""
    tmp = f"{os.fspath(path)}.tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=indent)
    os.replace(tmp, path)
