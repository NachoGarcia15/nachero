"""python -m nachero_collector [recoger|historial] … (ver docs/RECOLECTOR.md)."""

import argparse
import os
import sys

from nachero_collector import __version__
from nachero_collector.collect import collect, publish_index
from nachero_collector.history import import_history, season_start
from nachero_collector.riot import LEAGUES, Riot, RiotError


def parse_args(argv=None):
    p = argparse.ArgumentParser(prog="nachero_collector", description="Recolector de partidas (API de Riot).")
    p.add_argument("--version", action="version", version=f"nachero-collector {__version__}")
    sub = p.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("recoger", help="una pasada: partidas nuevas de la liga y conteos por parche")
    c.add_argument("--out", default="data", help="carpeta de los archivos publicados (<parche>/<región>/<liga>)")
    c.add_argument("--state", default="state/collector.json", help="estado privado del recolector")
    c.add_argument("--region", default="euw1")
    c.add_argument(
        "--league", default="master_plus", choices=list(LEAGUES), help="liga de la muestra (ver docs/RECOLECTOR.md)"
    )
    c.add_argument("--players", type=int, default=500, help="jugadores por pasada (rotan por divisiones y páginas)")
    c.add_argument("--matches", type=int, default=2000, help="partidas nuevas como mucho por pasada")
    pu = sub.add_parser("publicar", help="escribe index.json para publicar la carpeta en un sitio estático")
    pu.add_argument("--out", default="data")
    h = sub.add_parser("historial", help="tu historial completo de la temporada para «Tu pool»")
    h.add_argument("riot_id", help="tu Riot ID, p. ej. Nacho#EUW")
    h.add_argument("--out", default="history_import.json")
    h.add_argument("--region", default="euw1")
    return p.parse_args(argv)


def main(argv=None) -> int:
    args = parse_args(argv)
    if args.cmd == "publicar":  # no necesita la clave
        index = publish_index(args.out)
        print(f"index.json con {len(index['files'])} archivos en {args.out}: súbelo con la carpeta")
        return 0
    key = os.environ.get("RIOT_API_KEY", "")
    if not key:
        print("Falta la clave: export RIOT_API_KEY=RGAPI-… (nunca la guardes en el repositorio)", file=sys.stderr)
        return 2
    riot = Riot(key, args.region)
    try:
        if args.cmd == "recoger":
            collect(riot, args.out, args.state, args.region, args.league, args.players, args.matches)
        else:
            n = import_history(riot, args.riot_id, args.out, season_start())
            print(f"{n} partidas en {args.out}: cópialo a la carpeta de tu perfil de Nachero")
    except RiotError as e:
        print(f"La API de Riot ha fallado: {e}. ¿Ha caducado la clave? (las de desarrollo duran 24 h)", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
