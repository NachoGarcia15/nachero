"""Servidor HTTP local del panel (solo escucha en 127.0.0.1)."""

import contextlib
import getpass
import json
import mimetypes
import os
import platform
import re
import threading
import urllib.parse
from collections import deque
from http.server import BaseHTTPRequestHandler
from pathlib import Path

from nachero import __version__, config, paths
from nachero.app import desktop
from nachero.app.state import APP, CTX, LOCK, OPTS, PHASE_ES, TASKS, log, set_demo
from nachero.app.status import diagnostics, empty_states
from nachero.app.worker import evaluate, gol, load_tournament, refresh_tiers
from nachero.config import CFG, TOGGLES
from nachero.domain import calibration
from nachero.domain.common import ROLES
from nachero.domain.policy import GAME_DECISIONS, mode_help
from nachero.domain.tasks import summary as task_summary
from nachero.jsonio import read_json


def snapshot() -> dict:
    """Copia del estado de la app para el panel (las colas pasan a listas)."""
    with LOCK:
        st: dict = {k: (list(v) if isinstance(v, deque) else v) for k, v in APP.items()}
    st["tasks"] = TASKS.items()
    st["progress"] = task_summary(st["tasks"])
    st["phase_es"] = PHASE_ES.get(st["phase"], st["phase"])
    st["empty"] = empty_states(st)
    return st


def evaluate_request(query: str) -> tuple[int, dict]:
    """`/api/evaluate?id=17&role=jungle&view=draft|pool`: cualquier campeón en cualquier rol."""
    q = urllib.parse.parse_qs(query)
    engine, champs = CTX.get("engine"), CTX.get("champs")
    if not engine or not champs:
        return 503, {"error": "cargando"}
    try:
        cid = int((q.get("id") or [""])[0])
    except ValueError:
        return 400, {"error": "campeón no válido"}
    role, view = (q.get("role") or [""])[0], (q.get("view") or ["draft"])[0]
    if cid not in champs.by_id or role not in ROLES:
        return 400, {"error": "campeón o rol no válido"}
    with LOCK:
        d = APP.get("draft") or {}
    in_select = bool(d) and not d.get("unsupported")
    draft = CTX.get("draft")
    ctx = draft.context if in_select and draft is not None else None
    row = evaluate(engine, champs, cid, role, "pool" if view == "pool" else "draft", ctx)
    row["in_draft"] = bool(ctx) and view != "pool"
    return 200, row


def choose_request(body: dict) -> tuple[int, dict]:
    """`POST /api/draft/choose {"kind": "pick"|"ban", "id": 17}`: marca un campeón en tu turno
    desde el panel. Cuenta como elección del jugador: Nachero no lo vuelve a cambiar."""
    kind, cid = body.get("kind"), body.get("id")
    champs, draft = CTX.get("champs"), CTX.get("draft")
    valid_id = isinstance(cid, int) and not isinstance(cid, bool) and champs is not None and cid in champs.by_id
    if kind not in ("pick", "ban") or not valid_id:
        return 400, {"error": "campeón o turno no válido"}
    with LOCK:
        mode, phase = APP.get("mode"), APP.get("phase")
    if mode != "active" or OPTS["demo"]:
        return 409, {"error": "Pasa a modo Activo para marcar desde el panel"}
    if phase != "ChampSelect" or draft is None:
        return 409, {"error": "No estás en la selección de campeón"}
    ok, msg = draft.choose(kind, cid)
    return (200, {"ok": True, "name": msg}) if ok else (409, {"error": msg})


def welcome_request(body: dict) -> tuple[int, dict]:
    """`POST /api/welcome {"seen": true}`: bienvenida vista; `false` la vuelve a mostrar."""
    seen = body.get("seen", True)
    if not isinstance(seen, bool):
        return 400, {"error": "seen"}
    if CFG.get("welcome_seen") != seen:
        CFG["welcome_seen"] = seen
        config.save(CFG)
    return 200, {"ok": True}


def demo_request(body: dict) -> tuple[int, dict]:
    """`POST /api/demo {"on": true}`: champ select de demo sin reiniciar y sin tocar el cliente."""
    on = body.get("on")
    if not isinstance(on, bool):
        return 400, {"error": "on"}
    if on != bool(OPTS["demo"]):
        set_demo(on)
        log("Demo abierta: champ select simulada, no toca el cliente" if on else "Demo cerrada", "ok")
    return 200, {"ok": True}


def autostart_change(body: dict) -> str | None:
    """Aplica «Abrir al iniciar Windows» en el registro antes de guardarlo. Devuelve el error."""
    on = body.get("start_with_windows")
    if not isinstance(on, bool) or on == bool(CFG.get("start_with_windows")):
        return None
    problem = desktop.set_autostart(on)
    return f"No se ha podido cambiar el inicio con Windows: {problem}" if problem else None


def private_words() -> tuple[str, ...]:
    """Textos que no deben salir en un diagnóstico: el usuario del sistema y su carpeta."""
    words = [Path.home().name]
    with contextlib.suppress(Exception):
        words.append(getpass.getuser())
    return tuple(words)


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
        if path == "/api/instance":  # para que un segundo Nachero en este puerto traiga al frente a este
            info = {"app": "nachero", "version": __version__, "pid": os.getpid(), "window": OPTS["window"]}
            return self.send(200, info)
        if path == "/api/diagnostics":
            text = diagnostics(snapshot(), __version__, platform.platform(), paths.FROZEN, private_words())
            return self.send(200, text, "text/plain; charset=utf-8")
        if path == "/api/state":
            st = snapshot()
            st["settings"] = {k: CFG[k] for k in TOGGLES} | {
                "lock_when_seconds_left": CFG["lock_when_seconds_left"],
                "weights": CFG.get("weights", {}),
                "pick_mode": CFG.get("pick_mode", "pool"),
                "runes_source": CFG.get("runes_source", "pick"),
                "main_role": CFG.get("main_role", "auto"),
                "secondary_role": CFG.get("secondary_role", "none"),
                "setup_done": bool(CFG.get("setup_done", False)),
                "pool_bonus": CFG.get("pool_bonus", {}),
                "never_pick": CFG.get("never_pick", []),
                "practice_bonus": config.PRACTICE_BONUS,
                "start_mode": CFG.get("start_mode", "observe"),
                "spells_by_role": CFG.get("spells_by_role", {}),
                "style": {k: CFG.get("style", {}).get(k, config.STYLE_DEFAULTS[k]) for k in config.STYLE_KEYS},
                "ban_priority": CFG.get("ban_priority", {}),
                "spells": list(config.SPELLS),
                "close_to_tray": bool(CFG.get("close_to_tray", True)),
                "start_with_windows": bool(CFG.get("start_with_windows", False)),
            }
            st["settings"]["welcome_seen"] = bool(CFG.get("welcome_seen", False))
            st["version"] = __version__
            st["demo_ui"] = OPTS["demo_ui"]
            st["modes"] = mode_help(CFG)
            st["game_decisions"] = list(GAME_DECISIONS)
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
                out.append(
                    {
                        "id": cid,
                        "name": champs.name(cid),
                        "prio": p["prio"] if p else 0,
                        "presence": round(100 * (p["picks"] + p["bans"]) / max(1, ds["games"])) if p else 0,
                        "roles": pe.roles_of(ds, cid) if pe else [],
                    }
                )
            return self.send(200, out)
        if path == "/api/calibration":  # ¿acierta Nachero? (#9)
            recs = read_json(paths.predictions_file(), [])
            return self.send(200, calibration.report(recs if isinstance(recs, list) else []))
        if path == "/api/champions":
            champs = CTX.get("champs")
            if not champs:
                return self.send(503, {"error": "cargando"})
            return self.send(200, [{"id": c, "name": champs.name(c)} for c in sorted(champs.by_id, key=champs.name)])
        if path == "/api/evaluate":
            code, body = evaluate_request(self.path.split("?", 1)[1] if "?" in self.path else "")
            return self.send(code, body)
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
        if self.path == "/api/show":  # otro Nachero pide mostrar la ventana (p. ej. desde la bandeja)
            show = OPTS.get("show_window")
            if not show:
                return self.send(409, {"ok": False})
            show()
            return self.send(200, {"ok": True})
        if self.path == "/api/settings":
            problem = autostart_change(body)
            if problem:
                return self.send(409, {"error": problem})
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
                threading.Thread(target=load_tournament, args=(tour,), daemon=True).start()
            try:
                return self.send(200, pe.suggest(body))
            except Exception as e:
                log(f"Simulador: fallo ({e.__class__.__name__}: {e})", "warn")
                return self.send(500, {"error": str(e)})
        if self.path == "/api/welcome":
            return self.send(*welcome_request(body))
        if self.path == "/api/demo":
            return self.send(*demo_request(body))
        if self.path == "/api/draft/choose":
            code, out = choose_request(body)
            return self.send(code, out)
        if self.path == "/api/refresh":
            lola, patch = CTX.get("lola"), CTX.get("patch")
            if lola and patch:
                threading.Thread(target=refresh_tiers, args=(lola, patch, True), daemon=True).start()
            return self.send(200, {"ok": True})
        self.send(404, {"error": "not found"})
