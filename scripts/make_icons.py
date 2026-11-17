"""Genera los iconos y el logo de Nachero a partir de assets/icon.svg (el original).

Uso:  python scripts/make_icons.py      (requiere: pip install -e ".[build]")

Lo generado se sube al repositorio; solo hay que repetirlo si cambia el diseño:

  src/nachero/ui/icon.svg    favicon y cabecera del panel (copia del original)
  src/nachero/ui/icon.ico    icono del .exe, la ventana y la barra de tareas (16 a 256 px)
  src/nachero/ui/icon.png    256 px, para la bandeja del sistema
  src/nachero/ui/logo.svg    logo horizontal para fondo oscuro (panel, bienvenida)
  assets/logo-dark.svg       logo horizontal para tema oscuro (README)
  assets/logo-light.svg      logo horizontal para tema claro (README)

El texto «Nachero» del logo va convertido a trazos con Geist, la fuente del panel (licencia OFL),
para que se vea igual sin tenerla instalada. Se descarga una vez de Google Fonts a build/fonts/.
"""

import re
import struct
import sys
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path

import resvg_py
from fontTools.pens.svgPathPen import SVGPathPen
from fontTools.pens.transformPen import TransformPen
from fontTools.ttLib import TTFont

ROOT = Path(__file__).resolve().parent.parent
ASSETS = ROOT / "assets"
UI = ROOT / "src" / "nachero" / "ui"
FONTS = ROOT / "build" / "fonts"

ICO_SIZES = (16, 24, 32, 48, 64, 128, 256)
TRAY_SIZE = 256

SVG_NS = "http://www.w3.org/2000/svg"
ET.register_namespace("", SVG_NS)

# Logo horizontal: icono de 40 px, hueco y «Nachero» como en la cabecera del panel
LOGO_HEIGHT = 40
LOGO_GAP = 12
FONT_SIZE = 29
FONT_WEIGHT = 650
TRACKING = -0.01  # em, como .brand en style.css
TEXT_DARK_THEME = "#ededef"  # --text del panel
TEXT_LIGHT_THEME = "#0c0c0e"  # --bg del panel


def render_png(svg: str, size: int) -> bytes:
    """PNG cuadrado de `size` px del SVG (resvg, con suavizado)."""
    return bytes(resvg_py.svg_to_bytes(svg_string=svg, width=size, height=size, skip_system_fonts=True))


def png_size(data: bytes) -> tuple[int, int]:
    if data[:8] != b"\x89PNG\r\n\x1a\n":
        raise ValueError("no es un PNG")
    w, h = struct.unpack(">II", data[16:24])
    return w, h


def build_ico(pngs: dict[int, bytes]) -> bytes:
    """Archivo .ico con una imagen PNG por tamaño (Windows Vista o posterior)."""
    sizes = sorted(pngs)
    header = struct.pack("<HHH", 0, 1, len(sizes))
    offset = len(header) + 16 * len(sizes)
    entries, blobs = b"", b""
    for s in sizes:
        data = pngs[s]
        if png_size(data) != (s, s):
            raise ValueError(f"el PNG de {s} px no mide {s}×{s}")
        side = 0 if s >= 256 else s  # 0 significa 256 en el formato ICO
        entries += struct.pack("<BBBBHHII", side, side, 0, 0, 1, 32, len(data), offset)
        blobs += data
        offset += len(data)
    return header + entries + blobs


def icon_inner(svg: str) -> str:
    """Las formas del icono, sin la etiqueta <svg>, el título ni los comentarios."""
    root = ET.fromstring(svg)
    parts = [ET.tostring(el, encoding="unicode").strip() for el in root if el.tag != f"{{{SVG_NS}}}title"]
    return "".join(re.sub(r'\s+xmlns="[^"]+"', "", p) for p in parts)


def geist_font() -> Path:
    """Geist en el grosor del logo; se descarga de Google Fonts la primera vez."""
    dest = FONTS / f"Geist-{FONT_WEIGHT}.ttf"
    if dest.exists():
        return dest
    # Sin cabecera de navegador, Google Fonts sirve TrueType en vez de WOFF2
    css_url = f"https://fonts.googleapis.com/css2?family=Geist:wght@{FONT_WEIGHT}"
    css = urllib.request.urlopen(css_url, timeout=20).read().decode()
    match = re.search(r"url\((https://fonts\.gstatic\.com/[^)]+\.ttf)\)", css)
    if not match:
        raise RuntimeError("Google Fonts no ha devuelto la fuente en TrueType")
    FONTS.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(urllib.request.urlopen(match.group(1), timeout=20).read())
    return dest


def fmt(x: float) -> str:
    return f"{x:.2f}".rstrip("0").rstrip(".")


def text_path(font_path: Path, text: str, x0: float, baseline: float) -> tuple[str, float]:
    """Trazado SVG del texto y su anchura, en unidades del logo."""
    font = TTFont(font_path)
    cmap, glyphs = font.getBestCmap(), font.getGlyphSet()
    scale = FONT_SIZE / font["head"].unitsPerEm
    tracking = TRACKING * font["head"].unitsPerEm
    pen = SVGPathPen(glyphs, ntos=fmt)
    x = 0.0
    for i, ch in enumerate(text):
        glyph = glyphs[cmap[ord(ch)]]
        glyph.draw(TransformPen(pen, (scale, 0, 0, -scale, x0 + x * scale, baseline)))
        x += glyph.width + (tracking if i < len(text) - 1 else 0)
    return pen.getCommands(), x * scale


def cap_height(font_path: Path) -> float:
    font = TTFont(font_path)
    return font["OS/2"].sCapHeight * FONT_SIZE / font["head"].unitsPerEm


def logo_svg(icon: str, font_path: Path, text_color: str) -> str:
    """Logo horizontal: icono + «Nachero» (texto en trazos)."""
    baseline = LOGO_HEIGHT / 2 + cap_height(font_path) / 2
    x0 = LOGO_HEIGHT + LOGO_GAP
    d, width = text_path(font_path, "Nachero", x0, baseline)
    total = int(x0 + width + 1)
    k = LOGO_HEIGHT / 32
    return (
        f'<svg xmlns="{SVG_NS}" width="{total}" height="{LOGO_HEIGHT}" viewBox="0 0 {total} {LOGO_HEIGHT}">'
        f"<title>Nachero</title>"
        f'<g transform="scale({fmt(k)})">{icon_inner(icon)}</g>'
        f'<path fill="{text_color}" d="{d}"/>'
        f"</svg>\n"
    )


def write(path: Path, data: bytes | str) -> None:
    if isinstance(data, str):
        data = data.encode("utf-8")
    path.write_bytes(data)
    print(f"  {path.relative_to(ROOT)}  ({len(data) / 1024:.1f} KB)")


def main() -> int:
    icon = (ASSETS / "icon.svg").read_text(encoding="utf-8")
    print("Generando iconos desde assets/icon.svg:")
    pngs = {s: render_png(icon, s) for s in ICO_SIZES}
    write(UI / "icon.svg", icon)
    write(UI / "icon.ico", build_ico(pngs))
    write(UI / "icon.png", pngs[TRAY_SIZE] if TRAY_SIZE in pngs else render_png(icon, TRAY_SIZE))
    font = geist_font()
    dark = logo_svg(icon, font, TEXT_DARK_THEME)
    write(ASSETS / "logo-dark.svg", dark)
    write(ASSETS / "logo-light.svg", logo_svg(icon, font, TEXT_LIGHT_THEME))
    write(UI / "logo.svg", dark)
    return 0


if __name__ == "__main__":
    sys.exit(main())
