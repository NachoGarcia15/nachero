"""Cliente minimo para la API local del cliente de LoL (LCU)."""

import base64
import json
import os
import re
import ssl
import subprocess
import sys
import urllib.error
import urllib.request

from nachero.clients import winproc

_CTX = ssl._create_unverified_context()
CLIENT_EXE = "LeagueClientUx.exe"
METADATA = r"C:\ProgramData\Riot Games\Metadata\league_of_legends.live\league_of_legends.live.product_settings.yaml"
DEFAULT_DIRS = [r"C:\Riot Games\League of Legends"]


def parse_lockfile(text: str) -> tuple[str, str] | None:
    """`LeagueClient:pid:puerto:token:https` -> (puerto, token)."""
    parts = text.strip().split(":")
    if len(parts) == 5 and parts[2].isdigit() and parts[3]:
        return parts[2], parts[3]
    return None


def parse_cmdline(text: str) -> tuple[str, str] | None:
    """Puerto y token de la línea de comandos de LeagueClientUx.exe (`--app-port=…`,
    `--remoting-auth-token=…`, con comillas o sin ellas)."""
    port = re.search(r"--app-port=(\d+)", text or "")
    tok = re.search(r'--remoting-auth-token=([^"\s]+)', text or "")
    return (port.group(1), tok.group(1)) if port and tok else None


def client_cmdlines() -> list[str]:
    """Líneas de comandos de LeagueClientUx.exe: con la API de Windows (sin abrir nada) y, si esa
    falla de forma inesperada, con PowerShell sin ventana. Fuera de Windows, ninguna."""
    if sys.platform != "win32":
        return []
    try:
        return winproc.cmdlines(CLIENT_EXE)
    except Exception:
        pass
    try:
        out = subprocess.run(
            ["powershell", "-NoProfile", "-Command",
             f"(Get-CimInstance Win32_Process -Filter \"Name='{CLIENT_EXE}'\").CommandLine"],
            capture_output=True, text=True, timeout=15, **winproc.hidden(),
        ).stdout  # fmt: skip
    except Exception:
        return []
    return [line for line in (out or "").splitlines() if line.strip()]


def install_dirs(metadata_text: str = "") -> list[str]:
    """Carpetas donde buscar el lockfile: la que indica el instalador de Riot y la de por defecto."""
    m = re.search(r'^product_install_full_path:\s*"(.+?)"\s*$', metadata_text, re.M)
    found = [m.group(1).replace("\\\\", "\\")] if m else []
    return found + [d for d in DEFAULT_DIRS if d not in found]


def http_error_text(e: urllib.error.HTTPError) -> str:
    """«HTTP 500: mensaje», con el mensaje que da el cliente en su respuesta (JSON con `message`)."""
    try:
        body = json.loads(e.read() or b"{}")
    except (ValueError, OSError):
        body = {}
    msg = body.get("message") if isinstance(body, dict) else None
    return f"HTTP {e.code}" + (f": {str(msg)[:160]}" if msg else "")


class LCU:
    def __init__(self):
        self.base = self.auth = None
        self.last_error: str | None = None  # por qué falló la última petición (para el registro)

    def connect(self):
        """Puerto y token del cliente: de la linea de comandos de LeagueClientUx.exe o, si Windows no
        la deja leer (cliente abierto como administrador), del lockfile de la carpeta del juego."""
        found = self._from_cmdline() or self._from_lockfile()
        if not found:
            return False
        port, tok = found
        self.base = f"https://127.0.0.1:{port}"
        self.auth = "Basic " + base64.b64encode(f"riot:{tok}".encode()).decode()
        return True

    @staticmethod
    def _from_cmdline():
        for line in client_cmdlines():
            found = parse_cmdline(line)
            if found:
                return found
        return None

    @staticmethod
    def _from_lockfile():
        try:
            with open(METADATA, encoding="utf-8") as f:
                meta = f.read()
        except OSError:
            meta = ""
        for d in install_dirs(meta):
            try:
                with open(os.path.join(d, "lockfile"), encoding="utf-8") as f:
                    found = parse_lockfile(f.read())
            except OSError:
                continue
            if found:
                return found
        return None

    def raw(self, method, path, body=None, timeout=5):
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(
            self.base + path,
            data=data,
            method=method,
            headers={"Authorization": self.auth, "Content-Type": "application/json"},
        )
        self.last_error = None
        try:
            with urllib.request.urlopen(req, context=_CTX, timeout=timeout) as resp:
                return resp.read()
        except urllib.error.HTTPError as e:
            self.last_error = http_error_text(e)
            return None

    def req(self, method, path, body=None, timeout=5):
        b = self.raw(method, path, body, timeout)
        return json.loads(b) if b else None

    def get(self, path, timeout=5):
        return self.req("GET", path, timeout=timeout)
