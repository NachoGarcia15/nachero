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
APP_MODEL_ID = "Nachero.Desktop.App"
SIZE = (1280, 860)  # tamaño de la primera vez (píxeles lógicos)
MIN_SIZE = (960, 600)
BACKGROUND = "#0c0c0e"  # el fondo del panel (--bg): sin destello blanco al abrir
WEBVIEW2_URL = "https://developer.microsoft.com/microsoft-edge/webview2/"
# Opciones que escriben en el terminal: el ejecutable con ventana no tiene consola propia
CLI_FLAGS = ("-h", "--help", "--version", "--profile", "--install-shortcut")
# Icono de la ventana y de la barra de tareas (#45), también al ejecutar desde el código. El del
# .exe en el Explorador lo pone --icon en scripts/build_exe.py.
ICON = paths.UI_DIR / "icon.ico"

WIN = sys.platform == "win32"
MB_ICONS = {"error": 0x10, "warn": 0x30, "info": 0x40}
MB_SETFOREGROUND = 0x10000
SW_HIDE, SW_SHOWMINIMIZED, SW_SHOWMAXIMIZED, SW_RESTORE = 0, 2, 3, 9
WPF_RESTORETOMAXIMIZED = 0x2
# Win32: WM_SETICON para poner el icono a la ventana ya abierta
WM_SETICON = 0x0080
ICON_SMALL, ICON_BIG = 0, 1
IMAGE_ICON = 1
LR_LOADFROMFILE = 0x0010

# ------------------------------------------------------------------ identidad Win32


def resolve_icon() -> Path:
    """Ruta al .ico que funciona tanto en ejecución local como empaquetada (sys._MEIPASS / importlib.resources)."""
    if paths.FROZEN:
        meipass = getattr(sys, "_MEIPASS", "")
        if meipass:
            p = Path(meipass) / "nachero" / "ui" / "icon.ico"
            if p.is_file():
                return p
    with contextlib.suppress(Exception):
        import importlib.resources as pkg_resources

        ref = pkg_resources.files("nachero").joinpath("ui").joinpath("icon.ico")
        p = Path(str(ref))
        if p.is_file():
            return p
    return ICON


def set_app_model_id() -> None:
    """Registra un AppUserModelID para que Windows agrupe la ventana bajo el icono y nombre de
    Nachero en la barra de tareas, Alt+Tab y el Menú Inicio, en vez de usar los del intérprete."""
    if not WIN:
        return
    with contextlib.suppress(Exception):
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(APP_MODEL_ID)


def set_window_icon(hwnd: int, icon_path: Path) -> None:
    """Pone el icono de la ventana (barra de título y Alt+Tab) vía WM_SETICON + LoadImageW."""
    if not WIN or not hwnd or not icon_path.is_file():
        return
    with contextlib.suppress(Exception):
        u = ctypes.WinDLL("user32", use_last_error=True)
        u.LoadImageW.restype = wintypes.HANDLE
        u.LoadImageW.argtypes = [
            wintypes.HINSTANCE,
            wintypes.LPCWSTR,
            wintypes.UINT,
            ctypes.c_int,
            ctypes.c_int,
            wintypes.UINT,
        ]
        u.SendMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
        path_str = str(icon_path)
        # ICON_SMALL (16x16) para la barra de título
        small = u.LoadImageW(None, path_str, IMAGE_ICON, 16, 16, LR_LOADFROMFILE)
        if small:
            u.SendMessageW(hwnd, WM_SETICON, ICON_SMALL, small)
        # ICON_BIG (32x32) para Alt+Tab y la barra de tareas
        big = u.LoadImageW(None, path_str, IMAGE_ICON, 32, 32, LR_LOADFROMFILE)
        if big:
            u.SendMessageW(hwnd, WM_SETICON, ICON_BIG, big)


def _start_menu_dir() -> Path:
    """Carpeta de accesos directos del Menú Inicio del usuario."""
    appdata = os.environ.get("APPDATA", "")
    return Path(appdata) / "Microsoft" / "Windows" / "Start Menu" / "Programs"


def install_shortcut() -> str:
    """Crea un acceso directo «Nachero» en el Menú Inicio de Windows.

    Apunta al ejecutable instalado (nachero-gui.exe de gui-scripts, nachero.exe si es PyInstaller
    o pythonw.exe como último recurso), con el icono, la descripción y el AppUserModelID de Nachero.
    Devuelve la ruta del .lnk creado o un mensaje de error."""
    if not WIN:
        return "los accesos directos solo funcionan en Windows"

    exe = _find_shortcut_target()
    if exe is None:
        return "no encuentro el ejecutable de Nachero para el acceso directo"

    icon_path = resolve_icon()
    lnk = _start_menu_dir() / "Nachero.lnk"
    try:
        lnk.parent.mkdir(parents=True, exist_ok=True)
        _create_lnk(str(lnk), str(exe), str(icon_path) if icon_path.is_file() else "")
    except Exception as e:
        return f"no se ha podido crear el acceso directo: {e}"
    return str(lnk)


def _find_shortcut_target() -> Path | None:
    """Ejecutable al que debe apuntar el acceso directo del Menú Inicio."""
    if paths.FROZEN:
        return Path(sys.executable)
    # gui-scripts: nachero.exe (pythonw, sin consola)
    scripts_dir = Path(sys.prefix) / "Scripts"
    for name in ("nachero.exe", "Nachero.exe", "nachero-gui.exe"):
        candidate = scripts_dir / name
        if candidate.is_file():
            return candidate
    # Último recurso: pythonw + run.py
    pythonw = scripts_dir / "pythonw.exe"
    if pythonw.is_file():
        return pythonw
    return Path(sys.executable)


def _create_lnk(lnk_path: str, target_path: str, icon: str, app_id: str = APP_MODEL_ID) -> None:
    """Crea un .lnk y asigna System.AppUserModel.ID usando PowerShell (con fallback a WScript.Shell)."""
    import subprocess
    import tempfile

    args = ""
    if Path(target_path).stem.lower() in ("python", "pythonw"):
        args = "-m nachero"

    # 1. Intentar PowerShell (crea el .lnk y añade AppUserModelID via IPropertyStore)
    ps_code = f"""$wsh = New-Object -ComObject WScript.Shell
$shortcut = $wsh.CreateShortcut('{lnk_path}')
$shortcut.TargetPath = '{target_path}'
$shortcut.Arguments = '{args}'
$shortcut.Description = 'Nachero'
if ('{icon}') {{ $shortcut.IconLocation = '{icon},0' }}
$shortcut.Save()

$source = @"
using System;
using System.Runtime.InteropServices;
public class LnkHelper {{
    [ComImport, Guid("00021401-0000-0000-C000-000000000046")]
    public class ShellLink {{}}
    [ComImport, InterfaceType(ComInterfaceType.InterfaceIsIUnknown), Guid("000214F9-0000-0000-C000-000000000046")]
    public interface IShellLinkW {{
        void GetPath(IntPtr p, int c, IntPtr f, uint fl); void GetIDList(out IntPtr p); void SetIDList(IntPtr p);
        void GetDescription(IntPtr p, int c); void SetDescription([MarshalAs(UnmanagedType.LPWStr)] string s);
        void GetWorkingDirectory(IntPtr p, int c);
        void SetWorkingDirectory([MarshalAs(UnmanagedType.LPWStr)] string s);
        void GetArguments(IntPtr p, int c); void SetArguments([MarshalAs(UnmanagedType.LPWStr)] string s);
        void GetHotkey(out short h); void SetHotkey(short h); void GetShowCmd(out int s); void SetShowCmd(int s);
        void GetIconLocation(IntPtr p, int c, out int i);
        void SetIconLocation([MarshalAs(UnmanagedType.LPWStr)] string s, int i);
        void SetRelativePath([MarshalAs(UnmanagedType.LPWStr)] string s, uint r); void Resolve(IntPtr h, uint f);
        void SetPath([MarshalAs(UnmanagedType.LPWStr)] string s);
    }}
    [ComImport, InterfaceType(ComInterfaceType.InterfaceIsIUnknown), Guid("886d8eeb-8cf2-4446-8d02-cdba1dbdcf99")]
    public interface IPropertyStore {{
        void GetCount(out uint c); void GetAt(uint i, out PROPERTYKEY k);
        void GetValue(ref PROPERTYKEY k, [In, Out] PROPVARIANT v);
        void SetValue(ref PROPERTYKEY k, [In] PROPVARIANT v); void Commit();
    }}
    [ComImport, InterfaceType(ComInterfaceType.InterfaceIsIUnknown), Guid("0000010b-0000-0000-C000-000000000046")]
    public interface IPersistFile {{
        void GetClassID(out Guid c); int IsDirty(); void Load([MarshalAs(UnmanagedType.LPWStr)] string f, uint m);
        void Save([MarshalAs(UnmanagedType.LPWStr)] string f, [MarshalAs(UnmanagedType.Bool)] bool r);
        void SaveCompleted([MarshalAs(UnmanagedType.LPWStr)] string f); void GetCurFile(out string f);
    }}
    [StructLayout(LayoutKind.Sequential, Pack = 4)]
    public struct PROPERTYKEY {{
        public Guid fmtid; public uint pid;
        public PROPERTYKEY(Guid f, uint p) {{ fmtid = f; pid = p; }}
    }}
    [StructLayout(LayoutKind.Explicit)]
    public class PROPVARIANT : IDisposable {{
        [FieldOffset(0)] public ushort vt; [FieldOffset(8)] public IntPtr pwszVal;
        public static PROPVARIANT FromString(string val) {{
            return new PROPVARIANT {{ vt = 31, pwszVal = Marshal.StringToCoTaskMemUni(val) }};
        }}
        public void Dispose() {{
            if (pwszVal != IntPtr.Zero) {{ Marshal.FreeCoTaskMem(pwszVal); pwszVal = IntPtr.Zero; }}
        }}
    }}
    public static void SetAppId(string file, string appId) {{
        var link = (IShellLinkW)new ShellLink(); var persist = (IPersistFile)link;
        persist.Load(file, 2); var store = (IPropertyStore)link;
        var pkey = new PROPERTYKEY(new Guid("{{9F4C2855-9F79-4BDE-9E31-411D00424FFE}}"), 5);
        using (var pv = PROPVARIANT.FromString(appId)) {{ store.SetValue(ref pkey, pv); }}
        store.Commit(); persist.Save(file, true);
    }}
}}
"@
try {{
    Add-Type -TypeDefinition $source
    [LnkHelper]::SetAppId('{lnk_path}', '{app_id}')
}} catch {{}}
"""
    fd, ps_path = tempfile.mkstemp(suffix=".ps1")
    try:
        os.write(fd, ps_code.encode("utf-8"))
        os.close(fd)
        res = subprocess.run(
            ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", ps_path],
            capture_output=True,
            timeout=15,
        )
        if res.returncode == 0 and Path(lnk_path).is_file():
            return
    except Exception:
        pass
    finally:
        with contextlib.suppress(OSError):
            os.unlink(ps_path)

    # 2. Fallback VBScript
    vbs = (
        'Set sh = CreateObject("WScript.Shell")\n'
        f'Set lnk = sh.CreateShortcut("{lnk_path}")\n'
        f'lnk.TargetPath = "{target_path}"\n'
        f'lnk.Arguments = "{args}"\n'
        f'lnk.Description = "Nachero"\n'
        f'lnk.WorkingDirectory = ""\n'
    )
    if icon:
        vbs += f'lnk.IconLocation = "{icon},0"\n'
    vbs += "lnk.Save\n"
    fd_vbs, vbs_path = tempfile.mkstemp(suffix=".vbs")
    try:
        os.write(fd_vbs, vbs.encode("utf-8"))
        os.close(fd_vbs)
        subprocess.run(["cscript", "//Nologo", vbs_path], check=True, capture_output=True, timeout=15)
    finally:
        with contextlib.suppress(OSError):
            os.unlink(vbs_path)


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
    (o un Nachero anterior a la 0.11, que no tiene /api/instance)."""
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
    u.FindWindowW.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR]
    u.FindWindowW.restype = wintypes.HWND
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
    """HWND de la ventana de pywebview con fallback a FindWindowW(None, TITLE)."""
    with contextlib.suppress(Exception):
        if hasattr(window, "native") and hasattr(window.native, "Handle"):
            return int(window.native.Handle.ToInt64())
    if WIN:
        with contextlib.suppress(Exception):
            hwnd = _user32().FindWindowW(None, TITLE)
            if hwnd:
                return int(hwnd)
    return 0


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

    set_app_model_id()
    icon_path = resolve_icon()
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
        with contextlib.suppress(Exception):
            set_window_icon(native_hwnd(window), icon_path)
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
    webview.start(private_mode=False, storage_path=str(storage), icon=str(icon_path) if icon_path.is_file() else None)
