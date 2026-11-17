"""Ventana de escritorio (pywebview con WebView2) y lo que necesita de Windows: cuadros de
diálogo, la consola del terminal, la instancia única y la posición de la ventana.

La ventana muestra el mismo panel que el navegador, servido por el servidor local (127.0.0.1).
Las llamadas a Windows (ctypes) no hacen nada en otros sistemas; lo demás se prueba sin ventana.
"""

import contextlib
import ctypes
import json
import os
import sys
import urllib.request
from collections.abc import Sequence
from ctypes import wintypes
from pathlib import Path
from typing import Any

from nachero import paths
from nachero.jsonio import read_json, write_json

TITLE = "Nachero"
SIZE = (1280, 860)  # tamaño de la primera vez (píxeles lógicos)
MIN_SIZE = (960, 600)
BACKGROUND = "#0c0c0e"  # el fondo del panel (--bg): sin destello blanco al abrir
WEBVIEW2_URL = "https://developer.microsoft.com/microsoft-edge/webview2/"
# Opciones que escriben en el terminal: el ejecutable con ventana no tiene consola propia
CLI_FLAGS = ("-h", "--help", "--version", "--profile")
# Icono de la ventana y de la barra de tareas (#45). En el ejecutable pywebview usa el suyo
# (--icon en scripts/build_exe.py); este, al ejecutar desde el código. Solo si existe.
ICON = paths.UI_DIR / "icon.ico"

WIN = sys.platform == "win32"
MB_ICONS = {"error": 0x10, "warn": 0x30, "info": 0x40}
MB_SETFOREGROUND = 0x10000
SW_HIDE, SW_SHOWMINIMIZED, SW_SHOWMAXIMIZED, SW_RESTORE = 0, 2, 3, 9
WPF_RESTORETOMAXIMIZED = 0x2


# ------------------------------------------------------------------ consola y diálogos


def message_box(text: str, kind: str = "error", title: str = TITLE) -> None:
    """Cuadro de diálogo de Windows; bloquea hasta que se cierra. Fuera de Windows, a stderr."""
    if WIN:
        try:
            ctypes.windll.user32.MessageBoxW(None, text, title, MB_ICONS.get(kind, 0) | MB_SETFOREGROUND)
            return
        except Exception:
            pass
    with contextlib.suppress(Exception):
        print(f"{title}: {text}", file=sys.stderr)


def has_console() -> bool:
    """Si el proceso tiene consola (python run.py en un terminal). El ejecutable no la tiene."""
    if not WIN:
        return True
    try:
        return bool(ctypes.windll.kernel32.GetConsoleWindow())
    except Exception:
        return True


def wants_console(argv: Sequence[str]) -> bool:
    return any(a in CLI_FLAGS for a in argv)


def setup_streams(argv: Sequence[str]) -> None:
    """Sin consola (el ejecutable con ventana) sys.stdout y sys.stderr son None.

    Con una opción que escribe (--version, --help, --profile) lanzada desde un terminal, se usa la
    consola de ese terminal. Si no, la salida se descarta: el registro sigue en Actividad y en
    logs/, y así ningún print ni librería falla por no tener dónde escribir."""
    if sys.stdout is not None and sys.stderr is not None:
        return
    if WIN and wants_console(argv) and attach_parent_console():
        for name in ("stdout", "stderr"):
            if getattr(sys, name) is None:
                with contextlib.suppress(OSError):
                    setattr(sys, name, open("CONOUT$", "w", encoding="utf-8", errors="replace"))  # noqa: SIM115
    for name in ("stdout", "stderr"):
        if getattr(sys, name) is None:
            setattr(sys, name, open(os.devnull, "w", encoding="utf-8"))  # noqa: SIM115


def attach_parent_console() -> bool:
    try:
        return bool(ctypes.windll.kernel32.AttachConsole(-1))  # ATTACH_PARENT_PROCESS
    except Exception:
        return False


# ------------------------------------------------------------------ instancia única


def probe_instance(url: str, timeout: float = 3.0) -> dict | None:
    """Quién usa el puerto del panel: la respuesta del otro Nachero, o None si es otro programa
    (o un Nachero anterior a la 0.9, que no tiene /api/instance)."""
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))  # sin proxy del sistema
    try:
        with opener.open(f"{url}/api/instance", timeout=timeout) as r:
            data = json.loads(r.read().decode("utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) and data.get("app") == "nachero" else None


def pick_window(windows: Sequence[tuple[int, int, bool, str]], pid: int, title: str = TITLE) -> int | None:
    """De (hwnd, pid, visible, título), la ventana visible de ese proceso con ese título."""
    for hwnd, owner, visible, text in windows:
        if owner == pid and visible and text == title:
            return hwnd
    return None


def _user32() -> Any:
    # Una copia propia de user32: fijar argtypes en ctypes.windll.user32 afectaría a pywebview
    u = ctypes.WinDLL("user32", use_last_error=True)
    u.EnumWindows.argtypes = [ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM), wintypes.LPARAM]
    u.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
    u.IsWindowVisible.argtypes = u.IsIconic.argtypes = u.SetForegroundWindow.argtypes = [wintypes.HWND]
    u.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
    u.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
    u.GetWindowPlacement.argtypes = u.SetWindowPlacement.argtypes = [wintypes.HWND, ctypes.c_void_p]
    return u


def top_windows() -> list[tuple[int, int, bool, str]]:
    """Ventanas de nivel superior: (hwnd, pid, visible, título)."""
    u = _user32()
    found: list[tuple[int, int, bool, str]] = []

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def visit(hwnd, _):
        pid = wintypes.DWORD()
        u.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        buf = ctypes.create_unicode_buffer(256)
        u.GetWindowTextW(hwnd, buf, 256)
        found.append((hwnd or 0, pid.value, bool(u.IsWindowVisible(hwnd)), buf.value))
        return True

    u.EnumWindows(visit, 0)
    return found


def bring_to_front(pid: int) -> bool:
    """Trae al frente la ventana de Nachero del proceso pid (restaurándola si está minimizada).

    La llama el segundo Nachero, recién abierto por el usuario: Windows le deja pasar el foco."""
    if not WIN or not pid:
        return False
    try:
        hwnd = pick_window(top_windows(), pid)
        if not hwnd:
            return False
        u = _user32()
        if u.IsIconic(hwnd):
            u.ShowWindow(hwnd, SW_RESTORE)
        u.SetForegroundWindow(hwnd)
        return True
    except Exception:
        return False


# ------------------------------------------------------------------ posición de la ventana


class WINDOWPLACEMENT(ctypes.Structure):
    _fields_ = [
        ("length", wintypes.UINT),
        ("flags", wintypes.UINT),
        ("showCmd", wintypes.UINT),
        ("ptMinPosition", wintypes.POINT),
        ("ptMaxPosition", wintypes.POINT),
        ("rcNormalPosition", wintypes.RECT),
    ]


def clean_placement(data: Any) -> dict | None:
    """El estado guardado de la ventana, validado; None si falta o no tiene sentido.

    Rectángulo de la ventana sin maximizar, en píxeles de pantalla (como lo da Windows), y si
    estaba maximizada. Si ese rectángulo ya no cae en ningún monitor, Windows lo recoloca."""
    if not isinstance(data, dict):
        return None
    try:
        left, top, right, bottom = (int(data[k]) for k in ("left", "top", "right", "bottom"))
    except (KeyError, TypeError, ValueError):
        return None
    if right - left < 200 or bottom - top < 150 or max(abs(left), abs(top), abs(right), abs(bottom)) > 100_000:
        return None
    return {"left": left, "top": top, "right": right, "bottom": bottom, "maximized": bool(data.get("maximized"))}


def get_placement(hwnd: int) -> dict | None:
    wp = WINDOWPLACEMENT()
    wp.length = ctypes.sizeof(wp)
    if not _user32().GetWindowPlacement(hwnd, ctypes.byref(wp)):
        return None
    r = wp.rcNormalPosition
    maximized = wp.showCmd == SW_SHOWMAXIMIZED or (
        wp.showCmd == SW_SHOWMINIMIZED and bool(wp.flags & WPF_RESTORETOMAXIMIZED)
    )
    return clean_placement({"left": r.left, "top": r.top, "right": r.right, "bottom": r.bottom, "maximized": maximized})


def set_placement(hwnd: int, p: dict) -> None:
    """Coloca la ventana (aún oculta) donde estaba. Maximizarla lo hace pywebview al mostrarla."""
    wp = WINDOWPLACEMENT()
    wp.length = ctypes.sizeof(wp)
    wp.showCmd = SW_HIDE
    wp.rcNormalPosition = wintypes.RECT(p["left"], p["top"], p["right"], p["bottom"])
    _user32().SetWindowPlacement(hwnd, ctypes.byref(wp))


def native_hwnd(window: Any) -> int:
    """HWND de la ventana de pywebview (en Windows, window.native es el Form de WinForms)."""
    return int(window.native.Handle.ToInt64())


# ------------------------------------------------------------------ ventana


def window_problem() -> str | None:
    """Por qué no se puede abrir la ventana, o None si se puede.

    Sin WebView2, pywebview usaría el motor de Internet Explorer, que no puede con el panel."""
    if not WIN:
        return "la ventana propia solo funciona en Windows"
    try:
        import webview  # noqa: F401
    except ImportError:
        return "falta pywebview (pip install -e .)"
    try:
        from webview.platforms import winforms
    except Exception as e:  # pythonnet o .NET Framework
        return f"no se puede cargar .NET Framework ({e})"
    if getattr(winforms, "renderer", None) != "edgechromium":
        return "falta WebView2"
    return None


def open_window(url: str, state_file: Path, storage: Path) -> None:
    """Abre la ventana con el panel y espera a que se cierre. Va en el hilo principal."""
    import webview

    saved = clean_placement(read_json(state_file))
    corner = 0 if saved else None  # con estado guardado, posición manual: la pone set_placement
    win = webview.create_window(
        TITLE,
        url,
        width=SIZE[0],
        height=SIZE[1],
        min_size=MIN_SIZE,
        maximized=bool(saved and saved["maximized"]),
        background_color=BACKGROUND,
        text_select=True,  # como en el navegador: se puede copiar texto del panel
        zoomable=True,
        x=corner,
        y=corner,
    )
    if win is None:
        raise RuntimeError("pywebview no ha creado la ventana")

    def before_show(window):  # hilo de la ventana, antes de mostrarla
        if not saved:
            return
        with contextlib.suppress(Exception):
            set_placement(native_hwnd(window), saved)
            if saved["maximized"]:
                # SetWindowPlacement deja a WinForms en Normal: se vuelve a pedir maximizada
                from System.Windows.Forms import FormWindowState

                window.native.WindowState = FormWindowState.Maximized

    def closing(window):  # hilo de la ventana, antes de cerrarla
        with contextlib.suppress(Exception):
            placement = get_placement(native_hwnd(window))
            if placement:
                write_json(state_file, placement)

    win.events.before_show += before_show
    win.events.closing += closing
    # private_mode=False: el panel guarda en localStorage la pestaña y el simulador pro
    webview.start(private_mode=False, storage_path=str(storage), icon=str(ICON) if ICON.is_file() else None)
