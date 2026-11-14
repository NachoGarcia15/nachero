"""Servidor HTTP local del panel (solo escucha en 127.0.0.1)."""

import json
import mimetypes
import re
import threading
import urllib.parse
from collections import deque
from http.server import BaseHTTPRequestHandler

from draftbot import config, paths
from draftbot.app.state import APP, CTX, LOCK, PHASE_ES, log
from draftbot.app.worker import gol
from draftbot.config import CFG, TOGGLES


class Handler(BaseHTTPRequestHandler):
    img_cache: dict[tuple[str, int], bytes] = {}

    def log_message(self, *a):
        pass

    @staticmethod
    def static_file(path):
        """Archivo del panel para una ruta, o None. Nunca sale de la carpeta ui/."""
        name = "index.html" if path in ("/", "/index.html") else path.lstrip("/")
        if not re.fullmatch(r"[a-z0-9_-]+\.(html|css|js|svg|png|ico)", name):
            return None
        f = (paths.UI_DIR / name).resolve()
        return f if f.parent == paths.UI_DIR.resolve() and f.is_file() else None

    def send(self, code, body, ctype="application/json", cache=False):
        if isinstance(body, (dict, list)):
            body = json.dumps(body, ensure_ascii=False).encode()
        elif isinstance(body, str):
            body = body.encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Cache-Control", "max-age=86400" if cache else "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        path = self.path.split("?")[0]
        static = self.static_file(path)
        if static:
            ctype = mimetypes.guess_type(static.name)[0] or "text/plain"
            return self.send(200, static.read_bytes(), ctype + "; charset=utf-8")
        if path == "/api/state":
            with LOCK:
                st = {k: (list(v) if isinstance(v, deque) else v) for k, v in APP.items()}
            st["phase_es"] = PHASE_ES.get(st["phase"], st["phase"])
            st["settings"] = {k: CFG[k] for k in TOGGLES} | {
                "lock_when_seconds_left": CFG["lock_when_seconds_left"],
                "weights": CFG.get("weights", {}),
                "pick_mode": CFG.get("pick_mode", "pool"),
            }
            return self.send(200, st)
        if path == "/api/pro/tournaments":
            try:
                return self.send(200, gol().tournaments())
            except Exception as e:
                return self.send(502, {"error": f"gol.gg no responde ({e.__class__.__name__})"})
        if path == "/api/pro/champions":
            champs, pe = CTX.get("champs"), CTX.get("pro")
            if not champs:
                return self.send(503, {"error": "cargando"})
            q = urllib.parse.parse_qs(self.path.split("?", 1)[1] if "?" in self.path else "")
            ds = gol().dataset((q.get("t") or [""])[0])
            out = []
            for cid in sorted(champs.by_id, key=champs.name):
                p = pe.pro(ds, cid) if pe else None
                shares = (
                    {r: round(pe.role_share(ds, cid, r), 2) for r in ("top", "jungle", "middle", "bottom", "utility")}
                    if pe
                    else {}
                )
                out.append(
                    {
                        "id": cid,
                        "name": champs.name(cid),
                        "prio": p["prio"] if p else 0,
                        "presence": round(100 * (p["picks"] + p["bans"]) / max(1, ds["games"])) if p else 0,
                        "roles": [r for r, v in shares.items() if v >= 0.12],
                    }
                )
            return self.send(200, out)
        m = re.match(r"^/api/img/(tile|splash|icon)/(\d+)$", path)
        if m:
            kind, cid = m.group(1), int(m.group(2))
            key = (kind, cid)
            if key not in self.img_cache:
                champs, lcu = CTX.get("champs"), CTX.get("src")
                data = None
                if champs and lcu:
                    try:
                        p = champs.info(cid)["img"].get(kind)
                        data = lcu.raw("GET", p, timeout=20) if p else None
                    except Exception:
                        data = None
                if data is None:
                    return self.send(404, {"error": "no image"})
                self.img_cache[key] = data
            data = self.img_cache[key]
            return self.send(200, data, "image/png" if kind == "icon" else "image/jpeg", cache=True)
        self.send(404, {"error": "not found"})

    def do_POST(self):
        n = int(self.headers.get("Content-Length", 0) or 0)
        try:
            body = json.loads(self.rfile.read(n) or b"{}")
        except Exception:
            return self.send(400, {"error": "json"})
        if self.path == "/api/mode" and body.get("mode") in ("paused", "observe", "active"):
            with LOCK:
                APP["mode"] = body["mode"]
            log("Modo " + {"paused": "pausado", "observe": "observar", "active": "activo"}[body["mode"]], "ok")
            return self.send(200, {"ok": True})
        if self.path == "/api/settings":
            changed = config.apply_settings(CFG, body)
            if changed:
                config.save(CFG)
                with LOCK:
                    APP["pool"] = []
                    APP["refresh_idle"] = True
                log("Ajustes guardados: " + ", ".join(changed), "ok")
            return self.send(200, {"ok": True})
        if self.path == "/api/pro/suggest":
            pe = CTX.get("pro")
            if not pe:
                return self.send(503, {"error": "cargando"})
            tour = body.get("tournament")
            if tour and not gol().dataset(tour) and tour not in gol().loading:
                threading.Thread(target=gol().load, args=(tour,), daemon=True).start()
            try:
                return self.send(200, pe.suggest(body))
            except Exception as e:
                log(f"Simulador: fallo ({e.__class__.__name__}: {e})", "warn")
                return self.send(500, {"error": str(e)})
        if self.path == "/api/refresh":
            lola, patch = CTX.get("lola"), CTX.get("patch")
            if lola:
                threading.Thread(
                    target=lambda: (
                        lola.refresh_tiers(patch, force=True),
                        log("Estadísticas Master+ actualizadas", "ok"),
                    ),
                    daemon=True,
                ).start()
            return self.send(200, {"ok": True})
        self.send(404, {"error": "not found"})
