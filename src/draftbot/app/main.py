"""Punto de entrada: argumentos, arranque del servidor del panel y del bucle principal."""

import argparse
import contextlib
import sys
import threading
import webbrowser
from http.server import ThreadingHTTPServer

from draftbot import __version__, config, paths
from draftbot.app.state import APP, OPTS, log, setup_logging
from draftbot.config import CFG


def disable_quick_edit() -> None:
    """En la consola de Windows, hacer clic en la ventana la deja en modo seleccion y congela
    cualquier print(): draftbot dejaria de aceptar partidas y de seguir la champ select."""
    if sys.platform != "win32":
        return
    try:
        import ctypes

        k32 = ctypes.windll.kernel32
        handle = k32.GetStdHandle(-10)  # STD_INPUT_HANDLE
        mode = ctypes.c_uint32()
        if k32.GetConsoleMode(handle, ctypes.byref(mode)):
            # sin ENABLE_QUICK_EDIT_MODE (0x40); ENABLE_EXTENDED_FLAGS (0x80) hace que se aplique
            k32.SetConsoleMode(handle, (mode.value & ~0x40) | 0x80)
    except Exception:
        pass


def parse_args(argv=None):
    p = argparse.ArgumentParser(prog="draftbot", description="Asistente de draft para League of Legends.")
    p.add_argument("--observe", action="store_true", help="arranca en modo Observar (no actúa en el cliente)")
    p.add_argument("--demo", action="store_true", help="champ select simulado para ver el panel")
    p.add_argument("--no-browser", action="store_true", help="no abre el navegador al arrancar")
    p.add_argument("--profile", action="store_true", help="muestra tu pool en consola y sale")
    p.add_argument("--port", type=int, default=None, help="puerto del panel (por defecto, el de los ajustes)")
    p.add_argument("--version", action="version", version=f"draftbot {__version__}")
    return p.parse_args(argv)


def print_profile():
    from draftbot.app.worker import current_patch, pool_rows
    from draftbot.clients.lcu import LCU
    from draftbot.domain.engine import Engine
    from draftbot.domain.player import Player
    from draftbot.sources.champions import Champs
    from draftbot.sources.history import load_history
    from draftbot.sources.lolalytics import Lolalytics

    lcu = LCU()
    if not lcu.connect():
        print("No encuentro el cliente de LoL abierto.")
        return
    champs = Champs(lcu)
    games = load_history(lcu, str(paths.history_file()), CFG["history_queues"], log)
    player = Player(games, lcu.get("/lol-champion-mastery/v1/local-player/champion-mastery", timeout=20))
    lola = Lolalytics(str(paths.cache_dir()), log)
    lola.refresh_tiers(current_patch(lcu, games))
    eng = Engine(champs, lola, player, CFG)
    for r in pool_rows(eng, champs)[:25]:
        wr = "-" if r["wr"] is None else r["wr"]
        print(
            f"{r['name']:13s} {r['role']:8s} {r['games']:3d}p  WR {wr:>3}%  exp {r['exp']:4d}  "
            f"tú {r['you']:+5.1f}  meta {r['meta']:+5.1f} ({r['tier'] or '-':2s})  est {r['est']:.1f}%"
        )


def main(argv=None):
    with contextlib.suppress(AttributeError, ValueError):
        sys.stdout.reconfigure(encoding="utf-8")
    args = parse_args(argv)
    disable_quick_edit()
    setup_logging()
    moved = paths.migrate_legacy()
    config.init()
    if moved:
        log(f"Datos movidos a {paths.user_dir()}: {', '.join(moved)}", "ok")
    OPTS["demo"] = APP["demo"] = args.demo
    APP["mode"] = "observe" if (args.observe or args.demo) else CFG.get("start_mode", "observe")

    if args.profile:
        print_profile()
        return

    from draftbot.app.server import Handler
    from draftbot.app.worker import worker

    port = args.port or CFG.get("ui_port", 8765)
    url = f"http://127.0.0.1:{port}"
    # En Windows, SO_REUSEADDR deja que dos procesos escuchen en el mismo puerto: lo desactivamos
    # para que un segundo draftbot detecte al primero en vez de quedarse "en sombra".
    ThreadingHTTPServer.allow_reuse_address = False
    try:
        srv = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    except OSError:
        print(f"draftbot ya está abierto en {url}; abro el panel.")
        if not args.no_browser:
            webbrowser.open(f"{url}/?v={__version__}")
        return
    threading.Thread(target=worker, daemon=True).start()
    log(f"draftbot {__version__} · panel en {url}", "ok")
    if not args.no_browser:
        webbrowser.open(f"{url}/?v={__version__}")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\nSaliendo.")
