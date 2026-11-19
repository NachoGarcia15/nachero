"""Punto de entrada: argumentos, servidor del panel, bucle principal y ventana de la app."""

import argparse
import contextlib
import sys
import threading
import webbrowser
from http.server import ThreadingHTTPServer

from nachero import __version__, config, paths
from nachero.app import desktop
from nachero.app.state import APP, OPTS, log, logger, set_demo, setup_logging
from nachero.app.status import platform_info, platform_warning
from nachero.config import CFG


def disable_quick_edit() -> None:
    """En la consola de Windows, hacer clic en la ventana la deja en modo seleccion y congela
    cualquier print(): Nachero dejaria de aceptar partidas y de seguir la champ select."""
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
    p = argparse.ArgumentParser(prog="nachero", description="Asistente de draft para League of Legends.")
    p.add_argument("--observe", action="store_true", help="arranca en modo Observar (no actúa en el cliente)")
    p.add_argument("--demo", action="store_true", help="champ select simulado para ver el panel")
    p.add_argument("--browser", action="store_true", help="abre el panel en el navegador, sin ventana (desarrollo)")
    p.add_argument("--no-browser", action="store_true", help="no abre ventana ni navegador: solo el servidor del panel")
    p.add_argument("--profile", action="store_true", help="muestra tu pool en consola y sale")
    p.add_argument("--install-shortcut", action="store_true", help="crea acceso directo en el Menú Inicio")
    p.add_argument("--port", type=int, default=None, help="puerto del panel (por defecto, el de los ajustes)")
    p.add_argument("--version", action="version", version=f"Nachero {__version__}")
    return p.parse_args(argv)


def ui_mode(args) -> str:
    """Dónde se ve el panel: "window" (la ventana de la app), "browser" o "none" (solo servidor)."""
    if args.no_browser:
        return "none"
    return "browser" if args.browser else "window"


def print_profile():
    from nachero.app.worker import current_patch, open_profile, pool_rows
    from nachero.clients.lcu import LCU
    from nachero.domain.engine import Engine
    from nachero.domain.player import Player
    from nachero.sources.champions import Champs
    from nachero.sources.history import load_history
    from nachero.sources.lolalytics import Lolalytics

    lcu = LCU()
    if not lcu.connect():
        print("No encuentro el cliente de LoL abierto.")
        return
    champs = Champs(lcu)
    open_profile(lcu)
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
    """Arranca Nachero. El ejecutable no tiene consola: si algo falla, lo dice en un cuadro de
    diálogo con la ruta del registro."""
    argv = sys.argv[1:] if argv is None else list(argv)
    desktop.setup_streams(argv)
    try:
        run(argv)
    except (KeyboardInterrupt, SystemExit):
        raise
    except Exception as e:
        if not paths.FROZEN:
            raise
        report_crash(e)


def report_crash(exc: BaseException) -> None:
    where = r"%APPDATA%\nachero\logs"
    with contextlib.suppress(Exception):
        where = str(paths.log_dir())
        setup_logging()
        logger.exception("Nachero se ha cerrado por un error")
    desktop.message_box(
        f"Nachero se ha cerrado por un error:\n\n{type(exc).__name__}: {exc}\n\nEl registro está en {where}", "error"
    )


def run(argv=None):
    with contextlib.suppress(AttributeError, ValueError):
        sys.stdout.reconfigure(encoding="utf-8")
    args = parse_args(argv)
    disable_quick_edit()
    renamed = paths.migrate_old_name()  # antes de abrir el registro, que vive en esa carpeta
    setup_logging()
    moved = paths.migrate_legacy()
    config.init()
    if renamed:
        log(f"Datos de {renamed} pasados a {paths.user_dir()} (draftbot ahora se llama Nachero)", "ok")
    if moved:
        log(f"Datos movidos a {paths.user_dir()}: {', '.join(moved)}", "ok")
    APP["platform"] = platform_info()
    warning = platform_warning(APP["platform"])
    if warning:
        log(warning, "warn")
    set_demo(args.demo, from_ui=False)
    APP["mode"] = "observe" if (args.observe or args.demo) else CFG.get("start_mode", "observe")

    if args.profile:
        print_profile()
        return

    if args.install_shortcut:
        res = desktop.install_shortcut()
        print(f"Acceso directo: {res}")
        return

    from nachero.app.server import Handler
    from nachero.app.worker import worker

    port = args.port or CFG.get("ui_port", 8765)
    url = f"http://127.0.0.1:{port}"
    ui = ui_mode(args)
    srv = bind(port, Handler)
    if srv is None:
        another_instance(url, port, ui)
        return
    notice = None
    if ui == "window":
        problem = desktop.window_problem()
        if problem:
            log(f"Sin ventana propia ({problem}): abro el panel en el navegador.", "warn")
            ui, notice = "browser", no_window_notice(problem)
    OPTS["window"] = ui == "window"
    threading.Thread(target=worker, daemon=True).start()
    log(f"Nachero {__version__} · panel en {url}", "ok")
    panel = f"{url}/?v={__version__}"
    if ui == "window":
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        try:
            desktop.open_window(panel, paths.window_file(), paths.webview_dir())
        finally:
            stop(srv)
        log("Ventana cerrada: Nachero se cierra.")
        return  # el bucle principal es un hilo daemon: termina con el proceso
    if ui == "browser":
        webbrowser.open(panel)
    serve(srv, keep_open_text(url, notice), "warn" if notice else "info")


def bind(port: int, handler) -> ThreadingHTTPServer | None:
    """Servidor del panel en 127.0.0.1, o None si el puerto ya está en uso."""
    # En Windows, SO_REUSEADDR deja que dos procesos escuchen en el mismo puerto: lo desactivamos
    # para que un segundo Nachero detecte al primero en vez de quedarse "en sombra".
    ThreadingHTTPServer.allow_reuse_address = False
    try:
        return ThreadingHTTPServer(("127.0.0.1", port), handler)
    except OSError:
        return None


def another_instance(url: str, port: int, ui: str) -> None:
    """El puerto ya está en uso. Si es otro Nachero, trae al frente su ventana (o abre su panel
    en el navegador si no tiene); si es otro programa, avisa."""
    info = desktop.probe_instance(url)
    if info is None:
        msg = (
            f"El puerto {port} lo está usando otro programa (o un Nachero anterior a la 0.11). "
            "Ciérralo y vuelve a abrir Nachero."
        )
        log(msg, "warn")
        if not desktop.has_console():
            desktop.message_box(msg, "warn")
        return
    if info.get("window"):
        log("Nachero ya está abierto: traigo su ventana al frente.")
        pid = info.get("pid")
        desktop.bring_to_front(pid if isinstance(pid, int) else 0)  # si aún no tiene ventana, sale enseguida
        return
    log(f"Nachero ya está abierto en {url}; abro el panel.")
    if ui != "none":
        webbrowser.open(f"{url}/?v={__version__}")


def no_window_notice(problem: str) -> str:
    return (
        f"Nachero no puede abrir su ventana ({problem}), así que el panel se abre en el navegador.\n\n"
        f"Para tener la ventana, instala «WebView2 Runtime» de Microsoft: {desktop.WEBVIEW2_URL}"
    )


def keep_open_text(url: str, notice: str | None = None) -> str:
    head = notice or f"Nachero está abierto sin ventana. El panel está en {url}"
    return f"{head}\n\nNachero sigue abierto mientras este aviso esté abierto: pulsa Aceptar para cerrarlo."


def serve(srv: ThreadingHTTPServer, text: str, kind: str = "info") -> None:
    """Sirve el panel hasta que se cierra Nachero: en un terminal, con Ctrl+C. Sin consola (el
    ejecutable con --browser o sin WebView2) no habría nada que cerrar, así que un aviso hace de
    ventana y cerrarlo cierra Nachero."""
    if desktop.has_console():
        try:
            srv.serve_forever()
        except KeyboardInterrupt:
            print("\nSaliendo.")
        return
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        desktop.message_box(text, kind)
    finally:
        stop(srv)
    log("Aviso cerrado: Nachero se cierra.")


def stop(srv: ThreadingHTTPServer) -> None:
    srv.shutdown()  # espera a que serve_forever acabe (aunque aún no hubiera empezado)
    srv.server_close()
