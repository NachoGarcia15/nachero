"""Lo que pasó en una selección de campeón, leído de su registro de diagnóstico.

Uso:  python scripts/ver_seleccion.py               la última (logs/selecciones de tu carpeta de datos)
      python scripts/ver_seleccion.py ARCHIVO.jsonl  otra

Cada línea: hora, fase y reloj, tu pick en el cliente (acción e intención), qué recomendaba y
marcaba Nachero (y de quién era la marca) y qué respondió el cliente a cada marca o confirmación.
Los nombres salen de la caché de Lolalytics; si no están, el id del campeón.
"""

import contextlib
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
from nachero import paths  # noqa: E402
from nachero.app.trace import timeline  # noqa: E402
from nachero.sources.compare import LolaCache  # noqa: E402


def main(argv=None) -> int:
    args = sys.argv[1:] if argv is None else list(argv)
    folder = paths.log_dir() / "selecciones"
    path = Path(args[0]) if args else max(folder.glob("*.jsonl"), default=None, key=lambda p: p.name)
    if not path or not path.is_file():
        print(f"No hay registros de selecciones en {folder}", file=sys.stderr)
        return 1
    lines = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        with contextlib.suppress(ValueError):
            lines.append(json.loads(raw))
    lola = LolaCache(paths.cache_dir() / "lolalytics_cache.json")

    def name(cid) -> str:
        n = lola.name(cid)
        return n.capitalize() if n != str(cid) else f"#{cid}"

    with contextlib.suppress(AttributeError, ValueError):
        sys.stdout.reconfigure(encoding="utf-8")
    print(f"{path.name}\n")
    print("\n".join(timeline(lines, name)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
