"""Icono y logo (#45): los archivos generados por scripts/make_icons.py están y son válidos."""

import struct
import xml.etree.ElementTree as ET
from pathlib import Path

from nachero import paths
from nachero.app.server import Handler

ROOT = Path(__file__).resolve().parent.parent
ASSETS = ROOT / "assets"
UI = paths.UI_DIR
ICO_SIZES = [16, 24, 32, 48, 64, 128, 256]


def png_size(data: bytes) -> tuple[int, int]:
    assert data[:8] == b"\x89PNG\r\n\x1a\n", "no es un PNG"
    return struct.unpack(">II", data[16:24])


def ico_images(data: bytes) -> dict[int, bytes]:
    """Imágenes del .ico por tamaño (lado en px)."""
    reserved, kind, count = struct.unpack("<HHH", data[:6])
    assert (reserved, kind) == (0, 1), "no es un .ico"
    out = {}
    for i in range(count):
        w, h, _, _, _, _, size, offset = struct.unpack("<BBBBHHII", data[6 + 16 * i : 22 + 16 * i])
        out[w or 256] = data[offset : offset + size]
        assert (w or 256) == (h or 256)
    return out


def test_ico_tiene_todos_los_tamanos():
    raw = (UI / "icon.ico").read_bytes()
    assert raw[:4] == b"\x00\x00\x01\x00", "la cabecera debe ser 00 00 01 00 (formato ICO)"
    images = ico_images(raw)
    assert sorted(images) == ICO_SIZES
    for required in (16, 32, 48, 256):
        assert required in images, f"falta resolución {required}x{required} requerida para Win32"
    for side, data in images.items():
        assert png_size(data) == (side, side)


def test_resolve_icon_modo_normal_y_meipass(tmp_path, monkeypatch):
    import sys

    from nachero.app import desktop

    # En modo normal devuelve el del paquete
    monkeypatch.setattr(paths, "FROZEN", False)
    assert desktop.resolve_icon() == desktop.ICON

    # En modo empaquetado (PyInstaller) usa sys._MEIPASS
    fake_meipass = tmp_path / "meipass"
    fake_icon = fake_meipass / "nachero" / "ui" / "icon.ico"
    fake_icon.parent.mkdir(parents=True, exist_ok=True)
    fake_icon.write_bytes(b"ico")
    monkeypatch.setattr(paths, "FROZEN", True)
    monkeypatch.setattr(sys, "_MEIPASS", str(fake_meipass), raising=False)
    assert desktop.resolve_icon() == fake_icon


def test_png_de_la_bandeja():
    assert png_size((UI / "icon.png").read_bytes()) == (256, 256)


def test_svgs_validos_y_al_dia():
    for f in (ASSETS / "icon.svg", ASSETS / "logo-dark.svg", ASSETS / "logo-light.svg", UI / "logo.svg"):
        root = ET.fromstring(f.read_text(encoding="utf-8"))
        assert root.tag.endswith("svg") and root.get("viewBox"), f.name
    # Las copias del panel salen del original: si no coinciden, falta pasar scripts/make_icons.py
    assert (UI / "icon.svg").read_bytes() == (ASSETS / "icon.svg").read_bytes()
    assert (UI / "logo.svg").read_bytes() == (ASSETS / "logo-dark.svg").read_bytes()


def test_logo_sin_fuentes_externas():
    # El texto va en trazos: se ve igual en GitHub o en el panel sin la fuente instalada
    for f in (ASSETS / "logo-dark.svg", ASSETS / "logo-light.svg"):
        assert "<text" not in f.read_text(encoding="utf-8")


def test_el_panel_sirve_y_enlaza_el_icono():
    for name in ("icon.svg", "icon.ico", "icon.png", "logo.svg"):
        assert Handler.static_file(f"/{name}").name == name
    html = (UI / "index.html").read_text(encoding="utf-8")
    assert 'rel="icon" href="/icon.svg"' in html
    assert 'rel="icon" href="/icon.ico"' in html
    assert '<span class="brand"><img src="/icon.svg"' in html
