"""Procesos de Windows con la API del sistema (ctypes), sin abrir consolas (#93).

Para conectar con el cliente hace falta la línea de comandos de `LeagueClientUx.exe` (puerto y
token). Antes se leía con PowerShell, que abre una consola un instante en cada intento: con el
cliente cerrado, cada 10 s. Aquí se busca el proceso con una instantánea de procesos
(`CreateToolhelp32Snapshot`) y se lee su línea de comandos con `NtQueryInformationProcess`
(`ProcessCommandLineInformation`, Windows 8.1 o posterior), como hace psutil.

Si el cliente se abrió como administrador y Nachero no, Windows no deja leerla: el que llama usa
el `lockfile` de la carpeta del juego. Fuera de Windows no hay nada que leer.
"""

import ctypes
import sys
from ctypes import wintypes

WIN = sys.platform == "win32"
CREATE_NO_WINDOW = 0x08000000  # subprocess en Windows sin consola (el .exe va sin ella)
TH32CS_SNAPPROCESS = 0x00000002
PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
PROCESS_COMMAND_LINE_INFORMATION = 60
MAX_PATH = 260
# respuestas de NtQueryInformationProcess que solo piden un búfer mayor
SIZE_STATUS = {0xC0000004, 0x80000005, 0xC0000023}  # INFO_LENGTH_MISMATCH, BUFFER_OVERFLOW, BUFFER_TOO_SMALL
MAX_CMDLINE = 1 << 20  # 1 MiB: una línea de comandos real ocupa unos KB


def hidden() -> dict:
    """Argumentos de `subprocess.run` para no abrir una consola en Windows (#93)."""
    return {"creationflags": CREATE_NO_WINDOW} if sys.platform == "win32" else {}


class ProcessEntry(ctypes.Structure):
    """PROCESSENTRY32W."""

    _fields_ = [
        ("dwSize", wintypes.DWORD),
        ("cntUsage", wintypes.DWORD),
        ("th32ProcessID", wintypes.DWORD),
        ("th32DefaultHeapID", ctypes.c_size_t),  # ULONG_PTR
        ("th32ModuleID", wintypes.DWORD),
        ("cntThreads", wintypes.DWORD),
        ("th32ParentProcessID", wintypes.DWORD),
        ("pcPriClassBase", wintypes.LONG),
        ("dwFlags", wintypes.DWORD),
        ("szExeFile", wintypes.WCHAR * MAX_PATH),
    ]


class UnicodeString(ctypes.Structure):
    """UNICODE_STRING: longitud en bytes y puntero al texto (dentro del mismo búfer)."""

    _fields_ = [("Length", wintypes.USHORT), ("MaximumLength", wintypes.USHORT), ("Buffer", ctypes.c_void_p)]


def _kernel32():
    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    k32.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
    k32.CreateToolhelp32Snapshot.argtypes = [wintypes.DWORD, wintypes.DWORD]
    k32.Process32FirstW.restype = wintypes.BOOL
    k32.Process32FirstW.argtypes = [wintypes.HANDLE, ctypes.POINTER(ProcessEntry)]
    k32.Process32NextW.restype = wintypes.BOOL
    k32.Process32NextW.argtypes = [wintypes.HANDLE, ctypes.POINTER(ProcessEntry)]
    k32.OpenProcess.restype = wintypes.HANDLE
    k32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    k32.CloseHandle.restype = wintypes.BOOL
    k32.CloseHandle.argtypes = [wintypes.HANDLE]
    return k32


def _ntdll():
    nt = ctypes.WinDLL("ntdll")
    nt.NtQueryInformationProcess.restype = ctypes.c_long  # NTSTATUS
    nt.NtQueryInformationProcess.argtypes = [
        wintypes.HANDLE,
        ctypes.c_int,
        ctypes.c_void_p,
        wintypes.ULONG,
        ctypes.POINTER(wintypes.ULONG),
    ]
    return nt


def pids(name: str) -> list[int]:
    """Ids de los procesos cuyo ejecutable se llama `name` (sin distinguir mayúsculas)."""
    if not WIN:
        return []
    k32 = _kernel32()
    snap = k32.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
    if not snap or snap == wintypes.HANDLE(-1).value:
        return []
    out = []
    try:
        entry = ProcessEntry()
        entry.dwSize = ctypes.sizeof(ProcessEntry)
        ok = k32.Process32FirstW(snap, ctypes.byref(entry))
        while ok:
            if entry.szExeFile.lower() == name.lower():
                out.append(int(entry.th32ProcessID))
            ok = k32.Process32NextW(snap, ctypes.byref(entry))
    finally:
        k32.CloseHandle(snap)
    return out


def cmdline(pid: int) -> str | None:
    """Línea de comandos del proceso `pid`, o None si Windows no deja leerla (p. ej. un proceso
    de administrador desde uno que no lo es) o el proceso ya no existe."""
    if not WIN:
        return None
    k32, nt = _kernel32(), _ntdll()
    handle = k32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not handle:
        return None
    try:
        size = wintypes.ULONG(0)
        status = nt.NtQueryInformationProcess(handle, PROCESS_COMMAND_LINE_INFORMATION, None, 0, ctypes.byref(size))
        if (status & 0xFFFFFFFF) not in SIZE_STATUS or not 0 < size.value <= MAX_CMDLINE:
            return None
        buf = ctypes.create_string_buffer(size.value)
        status = nt.NtQueryInformationProcess(
            handle, PROCESS_COMMAND_LINE_INFORMATION, buf, size.value, ctypes.byref(size)
        )
        if status < 0:  # NT_ERROR
            return None
        text = UnicodeString.from_buffer(buf)
        if not text.Buffer or not text.Length:
            return ""
        return ctypes.wstring_at(text.Buffer, text.Length // 2)
    finally:
        k32.CloseHandle(handle)


def cmdlines(name: str) -> list[str]:
    """Líneas de comandos que se pueden leer de los procesos llamados `name`."""
    return [line for line in (cmdline(pid) for pid in pids(name)) if line]
