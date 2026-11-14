"""Cliente minimo para la API local del cliente de LoL (LCU)."""

import base64
import json
import re
import ssl
import subprocess
import urllib.error
import urllib.request

_CTX = ssl._create_unverified_context()


class LCU:
    def __init__(self):
        self.base = self.auth = None

    def connect(self):
        """Lee puerto y token de la linea de comandos de LeagueClientUx.exe."""
        try:
            out = subprocess.run(
                [
                    "powershell",
                    "-NoProfile",
                    "-Command",
                    "(Get-CimInstance Win32_Process -Filter \"Name='LeagueClientUx.exe'\").CommandLine",
                ],
                capture_output=True,
                text=True,
                timeout=15,
            ).stdout
        except Exception:
            return False
        port = re.search(r'"--app-port=(\d+)"', out)
        tok = re.search(r'"--remoting-auth-token=([^"]+)"', out)
        if not (port and tok):
            return False
        self.base = f"https://127.0.0.1:{port.group(1)}"
        self.auth = "Basic " + base64.b64encode(f"riot:{tok.group(1)}".encode()).decode()
        return True

    def raw(self, method, path, body=None, timeout=5):
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(
            self.base + path,
            data=data,
            method=method,
            headers={"Authorization": self.auth, "Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(req, context=_CTX, timeout=timeout) as resp:
                return resp.read()
        except urllib.error.HTTPError:
            return None

    def req(self, method, path, body=None, timeout=5):
        b = self.raw(method, path, body, timeout)
        return json.loads(b) if b else None

    def get(self, path, timeout=5):
        return self.req("GET", path, timeout=timeout)
