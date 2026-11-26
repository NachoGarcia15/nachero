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
