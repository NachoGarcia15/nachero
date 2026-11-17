"""Construye dist/nachero.exe (Windows) con PyInstaller: la app con su ventana, sin consola.

Uso:  python scripts/build_exe.py            un solo archivo: dist/nachero.exe
      python scripts/build_exe.py --onedir   una carpeta: dist/nachero/nachero.exe (arranca
                                             ~1 s antes: no se descomprime en cada arranque)
Requiere: pip install -e ".[build]"
"""

import argparse
import shutil
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
      StringStruct('FileDescription', 'Nachero'),
      StringStruct('FileVersion', '{v}'),
      StringStruct('InternalName', 'Nachero'),
      StringStruct('OriginalFilename', 'Nachero.exe'),
      StringStruct('ProductName', 'Nachero'),
      StringStruct('ProductVersion', '{v}')])]),
    VarFileInfo([VarStruct('Translation', [0x040a, 1200])])
  ]
)
"""


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Construye nachero.exe con PyInstaller.")
    p.add_argument("--onedir", action="store_true", help="una carpeta en vez de un solo archivo")
    args = p.parse_args(argv)
    if sys.platform != "win32":
        print("El ejecutable solo se construye en Windows.")
        return 1
    parts = [int(x) for x in __version__.split(".")[:3]]
    BUILD.mkdir(exist_ok=True)
    version_file = BUILD / "version_info.txt"
    version_file.write_text(VERSION_FILE.format(t=tuple(parts + [0]), v=__version__), encoding="utf-8")
    (DIST / "Nachero.exe").unlink(missing_ok=True)
    (DIST / "nachero.exe").unlink(missing_ok=True)  # limpia nombre antiguo sin mayúscula
    shutil.rmtree(DIST / "Nachero", ignore_errors=True)
    shutil.rmtree(DIST / "nachero", ignore_errors=True)
    sep = ";"  # separador de --add-data en Windows
    cmd = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--noconfirm",
        "--clean",
        "--onedir" if args.onedir else "--onefile",
        "--windowed",  # sin consola: la app es su ventana (pywebview); cerrarla cierra Nachero
        "--name",
        "Nachero",
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
    exe = DIST / "Nachero" / "Nachero.exe" if args.onedir else DIST / "Nachero.exe"
    files = [f for f in exe.parent.rglob("*") if f.is_file()] if args.onedir else [exe]
    size = sum(f.stat().st_size for f in files)
    print(f"\nListo: {exe} ({size / 1e6:.1f} MB) · versión {__version__}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
