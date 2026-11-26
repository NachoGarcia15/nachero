"""¿Valen los datos propios? Los compara con Lolalytics, por rol y en los matchups (#21).

Uso:  python scripts/validar_datos.py [--salida informe.md]
      python scripts/validar_datos.py --own RUTA --patch 16.23 --region euw1 --league emerald_plus

Sin argumentos usa lo que ya tiene Nachero en tu carpeta de datos (%APPDATA%\\nachero): el archivo
de datos propios (`stats_file`) o su caché (`cache/stats`, la de `stats_url`) y la caché de
Lolalytics. No descarga nada: abre Nachero antes un rato para que las cachés estén al día.
"""

import argparse
import contextlib
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
from nachero import config, paths  # noqa: E402
from nachero.config import CFG  # noqa: E402
from nachero.sources.compare import LolaCache, markdown, run  # noqa: E402
from nachero.sources.local_stats import LocalStats  # noqa: E402


def default_own() -> Path:
    """Los datos propios que usa la app: `stats_file`, el archivo por defecto o la caché remota."""
    custom = CFG.get("stats_file") or ""
    for p in (Path(custom) if custom else None, paths.user_dir() / "stats" / "nachero-stats.json",
              paths.cache_dir() / "stats"):  # fmt: skip
        if p and p.exists():
            return p
    return paths.cache_dir() / "stats"


def main(argv=None) -> int:
    config.init()
    p = argparse.ArgumentParser(description="Compara los datos propios con Lolalytics (#21).")
    p.add_argument("--own", type=Path, default=None, help="archivo o carpeta de los datos propios")
    p.add_argument("--lola", type=Path, default=None, help="caché de Lolalytics (lolalytics_cache.json)")
    p.add_argument("--patch", default=None, help="parche (por defecto, el último de los datos propios)")
    p.add_argument("--region", default=CFG.get("stats_region", "euw1"))
    p.add_argument("--league", default=CFG.get("build_tier", "emerald_plus"))
    p.add_argument("--min-games", type=int, default=100, help="partidas mínimas por campeón y rol")
    p.add_argument("--top", type=int, default=8, help="campeones con más desviación por rol")
    p.add_argument("--salida", type=Path, default=None, help="guarda el informe en este archivo .md")
    args = p.parse_args(argv)
    own = LocalStats(args.own or default_own(), region=args.region, league=args.league)
    if args.patch:
        own.refresh_tiers(args.patch)
    lola = LolaCache(args.lola or paths.cache_dir() / "lolalytics_cache.json")
    if not own.data:
        print(f"No hay datos propios en {own.path} ({own.problem or 'vacío'}).", file=sys.stderr)
        return 1
    if not lola.data.get("tiers"):
        print("No hay tier lists de Lolalytics en caché: abre Nachero un rato antes.", file=sys.stderr)
        return 1
    text = markdown(run(own, lola, args.min_games, top=args.top), lola, args.min_games)
    if args.salida:
        args.salida.write_text(text, encoding="utf-8")
        print(f"Informe guardado en {args.salida}")
    else:
        with contextlib.suppress(AttributeError, ValueError):
            sys.stdout.reconfigure(encoding="utf-8")
        print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
