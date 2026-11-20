"""Icono de Nachero en la bandeja del sistema (Windows), con ctypes y sin dependencias.

Clic en el icono: abre la ventana. Clic derecho: menú con Abrir, los modos y Salir. Va en su
propio hilo, con una ventana oculta que recibe los mensajes del icono. Fuera de Windows no hace
nada; el menú (`menu_items`) y las decisiones (`close_action`) se prueban sin Windows.
"""

import ctypes
import sys
import threading
from collections.abc import Callable
from ctypes import wintypes
from pathlib import Path

WIN = sys.platform == "win32"

# ids de las órdenes del menú
CMD_OPEN, CMD_ACTIVE, CMD_OBSERVE, CMD_PAUSED, CMD_QUIT = 1, 2, 3, 4, 5
MODE_CMDS = {CMD_ACTIVE: "active", CMD_OBSERVE: "observe", CMD_PAUSED: "paused"}
SEPARATOR = (0, "", False)


def menu_items(mode: str) -> list[tuple[int, str, bool]]:
    """(id, texto, marcado) del menú del icono; id 0 es un separador."""
    return [
        (CMD_OPEN, "Abrir Nachero", False),
        SEPARATOR,
        (CMD_ACTIVE, "Activo", mode == "active"),
        (CMD_OBSERVE, "Observar", mode == "observe"),
        (CMD_PAUSED, "Pausado", mode == "paused"),
        SEPARATOR,
        (CMD_QUIT, "Salir de Nachero", False),
    ]


def close_action(cfg: dict, tray_ok: bool, quitting: bool) -> str:
    """Qué hacer al cerrar la ventana: "hide" (a la bandeja) o "quit"."""
    if quitting or not tray_ok or not cfg.get("close_to_tray", True):
        return "quit"
    return "hide"


TRAY_HINT = (
    "Nachero sigue en la bandeja",
    "Sigue aceptando partidas y leyendo la selección. Clic en el icono para abrirlo.",
)

# ------------------------------------------------------------------ Win32
WM_DESTROY, WM_CLOSE, WM_NULL, WM_COMMAND = 0x0002, 0x0010, 0x0000, 0x0111
WM_LBUTTONUP, WM_LBUTTONDBLCLK, WM_RBUTTONUP, WM_CONTEXTMENU = 0x0202, 0x0203, 0x0205, 0x007B
WM_APP = 0x8000
WM_TRAY = WM_APP + 1
NIM_ADD, NIM_MODIFY, NIM_DELETE = 0, 1, 2
NIF_MESSAGE, NIF_ICON, NIF_TIP, NIF_INFO = 0x1, 0x2, 0x4, 0x10
NIIF_INFO = 0x1
MF_STRING, MF_SEPARATOR, MF_CHECKED = 0x0, 0x800, 0x8
TPM_RIGHTBUTTON, TPM_RETURNCMD, TPM_NONOTIFY = 0x2, 0x100, 0x80
IMAGE_ICON, LR_LOADFROMFILE = 1, 0x10
SM_CXSMICON, SM_CYSMICON = 49, 50

if WIN:
    LRESULT = ctypes.c_ssize_t
    WNDPROC = ctypes.WINFUNCTYPE(LRESULT, wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM)

    class WNDCLASSW(ctypes.Structure):
        _fields_ = [
            ("style", wintypes.UINT),
            ("lpfnWndProc", WNDPROC),
            ("cbClsExtra", ctypes.c_int),
            ("cbWndExtra", ctypes.c_int),
            ("hInstance", wintypes.HINSTANCE),
            ("hIcon", wintypes.HICON),
            ("hCursor", wintypes.HANDLE),
            ("hbrBackground", wintypes.HBRUSH),
            ("lpszMenuName", wintypes.LPCWSTR),
            ("lpszClassName", wintypes.LPCWSTR),
        ]

    class NOTIFYICONDATAW(ctypes.Structure):
        _fields_ = [
            ("cbSize", wintypes.DWORD),
            ("hWnd", wintypes.HWND),
            ("uID", wintypes.UINT),
            ("uFlags", wintypes.UINT),
            ("uCallbackMessage", wintypes.UINT),
            ("hIcon", wintypes.HICON),
            ("szTip", wintypes.WCHAR * 128),
            ("dwState", wintypes.DWORD),
            ("dwStateMask", wintypes.DWORD),
            ("szInfo", wintypes.WCHAR * 256),
            ("uVersion", wintypes.UINT),
            ("szInfoTitle", wintypes.WCHAR * 64),
            ("dwInfoFlags", wintypes.DWORD),
            ("guidItem", ctypes.c_byte * 16),
            ("hBalloonIcon", wintypes.HICON),
        ]


def _api():
    """Copias propias de user32 y shell32 con sus tipos (no tocan las de pywebview)."""
    u = ctypes.WinDLL("user32", use_last_error=True)
    s = ctypes.WinDLL("shell32", use_last_error=True)
    k = ctypes.WinDLL("kernel32", use_last_error=True)
    u.DefWindowProcW.restype = LRESULT
    u.DefWindowProcW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
    u.RegisterClassW.argtypes = [ctypes.POINTER(WNDCLASSW)]
    u.RegisterClassW.restype = wintypes.ATOM
    u.CreateWindowExW.restype = wintypes.HWND
    u.CreateWindowExW.argtypes = [wintypes.DWORD, wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.DWORD,
                                  ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
                                  wintypes.HWND, wintypes.HMENU, wintypes.HINSTANCE, wintypes.LPVOID]  # fmt: skip
    u.LoadImageW.restype = wintypes.HANDLE
    u.LoadImageW.argtypes = [wintypes.HINSTANCE, wintypes.LPCWSTR, wintypes.UINT, ctypes.c_int, ctypes.c_int,
                             wintypes.UINT]  # fmt: skip
    u.CreatePopupMenu.restype = wintypes.HMENU
    u.AppendMenuW.argtypes = [wintypes.HMENU, wintypes.UINT, ctypes.c_size_t, wintypes.LPCWSTR]
    u.TrackPopupMenu.argtypes = [wintypes.HMENU, wintypes.UINT, ctypes.c_int, ctypes.c_int, ctypes.c_int,
                                 wintypes.HWND, wintypes.LPVOID]  # fmt: skip
    u.DestroyMenu.argtypes = [wintypes.HMENU]
    u.SetForegroundWindow.argtypes = [wintypes.HWND]
    u.PostMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
    u.GetCursorPos.argtypes = [ctypes.POINTER(wintypes.POINT)]
    u.RegisterWindowMessageW.argtypes = [wintypes.LPCWSTR]
    u.RegisterWindowMessageW.restype = wintypes.UINT
    u.DestroyWindow.argtypes = [wintypes.HWND]
    u.GetMessageW.argtypes = [ctypes.POINTER(wintypes.MSG), wintypes.HWND, wintypes.UINT, wintypes.UINT]
    u.TranslateMessage.argtypes = u.DispatchMessageW.argtypes = [ctypes.POINTER(wintypes.MSG)]
    s.Shell_NotifyIconW.argtypes = [wintypes.DWORD, ctypes.POINTER(NOTIFYICONDATAW)]
    s.Shell_NotifyIconW.restype = wintypes.BOOL
    k.GetModuleHandleW.restype = wintypes.HMODULE
    k.GetModuleHandleW.argtypes = [wintypes.LPCWSTR]
    return u, s, k


class Tray:
    """El icono de la bandeja. `on_open()`, `on_mode(modo)` y `on_quit()` se llaman desde su hilo."""

    def __init__(
        self,
        icon: Path,
        get_mode: Callable[[], str],
        on_open: Callable[[], None],
        on_mode: Callable[[str], None],
        on_quit: Callable[[], None],
        tip: str = "Nachero",
    ):
        self.icon, self.tip = icon, tip
        self.get_mode, self.on_open, self.on_mode, self.on_quit = get_mode, on_open, on_mode, on_quit
        self.hwnd = 0
        self.ready = threading.Event()
        self.ok = False

    # -- ciclo de vida
    def start(self, timeout: float = 5.0) -> bool:
        """Crea el icono en su hilo. True si está en la bandeja."""
        if not WIN:
            return False
        threading.Thread(target=self._run, name="bandeja", daemon=True).start()
        self.ready.wait(timeout)
        return self.ok

    def stop(self) -> None:
        if self.hwnd:
            self._u.PostMessageW(self.hwnd, WM_CLOSE, 0, 0)

    def notify(self, title: str, text: str) -> None:
        """Bocadillo de Windows junto al icono."""
        if not self.ok:
            return
        nid = self._nid(NIF_INFO)
        nid.szInfoTitle, nid.szInfo, nid.dwInfoFlags = title[:63], text[:255], NIIF_INFO
        self._s.Shell_NotifyIconW(NIM_MODIFY, ctypes.byref(nid))

    # -- hilo del icono
    def _run(self) -> None:
        try:
            self._u, self._s, k = _api()
            hinst = k.GetModuleHandleW(None)
            self._proc = WNDPROC(self._wndproc)  # referencia viva: si se libera, Windows llama a basura
            wc = WNDCLASSW()
            wc.lpfnWndProc, wc.hInstance, wc.lpszClassName = self._proc, hinst, "NacheroTray"
            self._u.RegisterClassW(ctypes.byref(wc))
            self.hwnd = self._u.CreateWindowExW(0, "NacheroTray", "Nachero bandeja", 0, 0, 0, 0, 0,
                                                None, None, hinst, None)  # fmt: skip
            cx, cy = self._u.GetSystemMetrics(SM_CXSMICON), self._u.GetSystemMetrics(SM_CYSMICON)
            self._hicon = self._u.LoadImageW(None, str(self.icon), IMAGE_ICON, cx, cy, LR_LOADFROMFILE)
            self._taskbar_created = self._u.RegisterWindowMessageW("TaskbarCreated")
            self.ok = bool(self.hwnd) and self._add()
        except Exception:
            self.ok = False
        finally:
            self.ready.set()
        if not self.ok:
            return
        msg = wintypes.MSG()
        while self._u.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
            self._u.TranslateMessage(ctypes.byref(msg))
            self._u.DispatchMessageW(ctypes.byref(msg))

    def _nid(self, flags: int):
        nid = NOTIFYICONDATAW()
        nid.cbSize, nid.hWnd, nid.uID, nid.uFlags = ctypes.sizeof(NOTIFYICONDATAW), self.hwnd, 1, flags
        return nid

    def _add(self) -> bool:
        nid = self._nid(NIF_MESSAGE | NIF_ICON | NIF_TIP)
        nid.uCallbackMessage, nid.hIcon, nid.szTip = WM_TRAY, self._hicon, self.tip
        return bool(self._s.Shell_NotifyIconW(NIM_ADD, ctypes.byref(nid)))

    def _wndproc(self, hwnd, msg, wparam, lparam):
        try:
            if msg == WM_TRAY:
                if lparam in (WM_LBUTTONUP, WM_LBUTTONDBLCLK):
                    self.on_open()
                elif lparam in (WM_RBUTTONUP, WM_CONTEXTMENU):
                    self._menu(hwnd)
                return 0
            if msg == self._taskbar_created:  # el Explorador se ha reiniciado: el icono se pierde
                self._add()
                return 0
            if msg == WM_DESTROY:
                self._s.Shell_NotifyIconW(NIM_DELETE, ctypes.byref(self._nid(0)))
                self._u.PostQuitMessage(0)
                return 0
        except Exception:
            return 0
        return self._u.DefWindowProcW(hwnd, msg, wparam, lparam)

    def _menu(self, hwnd) -> None:
        menu = self._u.CreatePopupMenu()
        for cid, text, checked in menu_items(self.get_mode()):
            if not cid:
                self._u.AppendMenuW(menu, MF_SEPARATOR, 0, None)
            else:
                self._u.AppendMenuW(menu, MF_STRING | (MF_CHECKED if checked else 0), cid, text)
        pt = wintypes.POINT()
        self._u.GetCursorPos(ctypes.byref(pt))
        self._u.SetForegroundWindow(hwnd)  # sin esto el menú no se cierra al hacer clic fuera
        cmd = self._u.TrackPopupMenu(menu, TPM_RIGHTBUTTON | TPM_RETURNCMD | TPM_NONOTIFY, pt.x, pt.y, 0, hwnd, None)
        self._u.PostMessageW(hwnd, WM_NULL, 0, 0)
        self._u.DestroyMenu(menu)
        if cmd == CMD_OPEN:
            self.on_open()
        elif cmd in MODE_CMDS:
            self.on_mode(MODE_CMDS[cmd])
        elif cmd == CMD_QUIT:
            self.on_quit()
