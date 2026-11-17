"""Construye dist/nachero.exe (Windows) con PyInstaller: un solo archivo con Python dentro.

Uso:  python scripts/build_exe.py      (requiere: pip install -e ".[build]")
"""

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src"
BUILD = ROOT / "build"
DIST = ROOT / "dist"
ICON = SRC / "nachero" / "ui" / "icon.ico"  # icono del .exe, la ventana y la barra de tareas (#45)

sys.path.insert(0, str(SRC))
from nachero import __version__  # noqa: E402

VERSION_FILE = """VSVersionInfo(
  ffi=FixedFileInfo(filevers={t}, prodvers={t}, mask=0x3f, flags=0x0, OS=0x40004, fileType=0x1,
                    subtype=0x0, date=(0, 0)),
  kids=[
    StringFileInfo([StringTable('040a04b0', [
      StringStruct('CompanyName', 'Nachero'),
      StringStruct('FileDescription', 'Nachero - asistente de draft para League of Legends'),
      StringStruct('FileVersion', '{v}'),
      StringStruct('InternalName', 'nachero'),
      StringStruct('OriginalFilename', 'nachero.exe'),
      StringStruct('ProductName', 'Nachero'),
      StringStruct('ProductVersion', '{v}')])]),
    VarFileInfo([VarStruct('Translation', [0x040a, 1200])])
  ]
)
"""


def main() -> int:
    if sys.platform != "win32":
        print("El ejecutable solo se construye en Windows.")
        return 1
    parts = [int(x) for x in __version__.split(".")[:3]]
    BUILD.mkdir(exist_ok=True)
    version_file = BUILD / "version_info.txt"
    version_file.write_text(VERSION_FILE.format(t=tuple(parts + [0]), v=__version__), encoding="utf-8")
    (DIST / "nachero.exe").unlink(missing_ok=True)
    sep = ";"  # separador de --add-data en Windows
    cmd = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--noconfirm",
        "--clean",
        "--onefile",
        "--console",  # la ventana muestra la actividad; cerrarla cierra Nachero
        "--name",
        "nachero",
        "--paths",
        str(SRC),
        "--add-data",
        f"{SRC / 'nachero' / 'ui'}{sep}nachero/ui",
        "--add-data",
        f"{SRC / 'nachero' / 'defaults'}{sep}nachero/defaults",
        "--version-file",
        str(version_file),
        "--workpath",
        str(BUILD / "pyinstaller"),
        "--specpath",
        str(BUILD),
        "--distpath",
        str(DIST),
        str(ROOT / "run.py"),
    ]
    if ICON.is_file():
        cmd[-1:-1] = ["--icon", str(ICON)]
    subprocess.run(cmd, check=True)
    exe = DIST / "nachero.exe"
    print(f"\nListo: {exe} ({exe.stat().st_size / 1e6:.1f} MB) · versión {__version__}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
