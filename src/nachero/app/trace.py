"""Registro de diagnóstico de cada champ select: `logs/selecciones/<fecha>.jsonl`.

Para saber qué ha pasado de verdad en una partida real cuando marcar o confirmar no va como debe:
qué daba el cliente (acciones, intenciones de pick, reloj) y qué ha hecho Nachero (qué marca, qué
confirma y qué le responde el cliente). Sin datos de jugadores: celdas, roles, campeones y tiempos;
ni nombres ni ids de cuenta. Una línea solo cuando algo cambia, y se guardan las últimas `KEEP`
selecciones. Escribir nunca para la selección: si falla, se calla.
"""

import json
import time
from pathlib import Path

KEEP = 10
ACTION_KEYS = ("id", "actorCellId", "type", "championId", "completed", "isInProgress", "isAllyAction")
TEAM_KEYS = ("cellId", "assignedPosition", "championId", "championPickIntent")


def session_view(s: dict) -> dict:
    """Lo que interesa de la sesión de la champ select, sin datos de jugadores."""
    return {
        "me": s.get("localPlayerCellId"),
        "actions": [[{k: a.get(k) for k in ACTION_KEYS} for a in grp] for grp in s.get("actions") or []],
        "my_team": [{k: m.get(k) for k in TEAM_KEYS} for m in s.get("myTeam") or []],
        "their_team": [{k: m.get(k) for k in ("cellId", "championId")} for m in s.get("theirTeam") or []],
        "bans": {k: v for k, v in (s.get("bans") or {}).items() if k in ("myTeamBans", "theirTeamBans")},
    }


class Trace:
    """Sin carpeta (`folder=None`) no apunta nada: así va en los tests y en la demo."""

    def __init__(self, folder: Path | None = None, clock=time.time):
        self.folder, self.clock = folder, clock
        self.path: Path | None = None
        self.last: dict = {}

    def start(self) -> None:
        """Champ select nueva: el próximo apunte abre un archivo nuevo."""
        self.path, self.last = None, {}

    def write(self, kind: str, data: dict, key: str | None = None, **extra) -> None:
        """Apunta `data` (y `extra`). Con `key`, solo si `data` ha cambiado desde el último apunte
        con esa clave (`extra` no cuenta: p. ej. el reloj, que cambia en cada vuelta)."""
        if self.folder is None:
            return
        if key is not None:
            if self.last.get(key) == data:
                return
            self.last[key] = data
        now = self.clock()
        try:
            if self.path is None:
                self.folder.mkdir(parents=True, exist_ok=True)
                for old in sorted(self.folder.glob("*.jsonl"))[: -(KEEP - 1) or None]:
                    old.unlink(missing_ok=True)
                self.path = self.folder / time.strftime("%Y-%m-%d_%H-%M-%S.jsonl", time.localtime(now))
            line = json.dumps({"t": round(now, 3), "kind": kind, **data, **extra}, ensure_ascii=False, default=str)
            with self.path.open("a", encoding="utf-8") as f:
                f.write(line + "\n")
        except OSError:
            pass


def _hms(t) -> str:
    return time.strftime("%H:%M:%S", time.localtime(t)) if isinstance(t, (int, float)) else "--:--:--"


def _my_pick(view: dict) -> dict:
    """Tu acción de pick en una sesión del registro (o {})."""
    me = view.get("me")
    return next((a for grp in view.get("actions") or [] for a in grp
                 if a.get("actorCellId") == me and a.get("type") == "pick"), {})  # fmt: skip


def timeline(lines: list[dict], name=str) -> list[str]:
    """Cronología legible de un registro de selección: fase y reloj, tu pick en el cliente, qué
    recomendaba y marcaba Nachero, de quién era la marca y qué respondió el cliente a cada PATCH.
    `name(cid)`: nombre de un campeón (por defecto, su id)."""

    def champ(cid) -> str:
        return name(cid) if cid else "nada"

    out: list[str] = []
    phase, mine, decided, ban = None, None, None, None
    for ln in lines:
        kind, at = ln.get("kind"), _hms(ln.get("t"))
        if kind == "timer" and ln.get("phase") != phase:
            phase = ln.get("phase")
            left = ln.get("left")
            clock = f" · quedan {left:.0f} s" if isinstance(left, (int, float)) else ""
            out.append(f"{at}  Fase {phase or '?'}{clock}")
        elif kind == "session":
            a = _my_pick(ln)
            me = ln.get("me")
            intent = next((m.get("championPickIntent") for m in ln.get("my_team") or [] if m.get("cellId") == me), 0)
            now = (a.get("championId") or 0, bool(a.get("isInProgress")), bool(a.get("completed")), intent or 0)
            if a and now != mine:
                state = "confirmado" if now[2] else ("es tu turno" if now[1] else "aún no es tu turno")
                shown = f"en la acción {champ(now[0])} · intención {champ(now[3])}"
                out.append(f"{at}  Cliente: tu pick, {state} · {shown}")
                mine = now
        elif kind == "pick":
            seen = (ln.get("target"), ln.get("marked"), ln.get("by"))
            if seen != decided:
                left = ln.get("left")
                clock = f" · quedan {left:.0f} s" if isinstance(left, (int, float)) else ""
                by = {"nachero": "de Nachero", "player": "tuyo"}.get(ln.get("by") or "", "de nadie")
                out.append(f"{at}  Nachero recomienda {champ(seen[0])} · marcado {champ(seen[1])} ({by}){clock}")
                decided = seen
        elif kind == "player":
            out.append(f"{at}  Marcado por ti: {champ(ln.get('cur'))} (Nachero ya no lo cambia en este turno)")
        elif kind == "patch":
            body = ln.get("body") or {}
            what = "Confirmar" if body.get("completed") or ln.get("method") == "POST" else "Marcar"
            ok = ln.get("ok")
            res = "aceptado" if ok else ("sin respuesta a tiempo" if ok is None else f"rechazado ({ln.get('error')})")
            out.append(f"{at}  {what} {champ(body.get('championId'))} → {res} en {ln.get('ms', '?')} ms")
        elif kind == "ban" and (ln.get("target"), ln.get("cur"), ln.get("choice")) != ban:
            ban = (ln.get("target"), ln.get("cur"), ln.get("choice"))
            ours = ln.get("cur") and ln.get("cur") == ln.get("hovered")
            who = " (tuyo)" if ln.get("choice") else (" (de Nachero)" if ours else "")
            out.append(f"{at}  Ban: recomienda {champ(ban[0])} · marcado {champ(ban[1])}{who}")
    return out
