"""Registro de tareas: qué está haciendo la app ahora mismo, para enseñarlo en el panel (#46).

Cada tarea corresponde a algo real (conectar con el cliente, leer el historial, descargar una tier
list…) y lleva su progreso: `done` de `total` cuando se sabe el total, o solo el estado cuando no.
Lógica pura: el bucle principal y las fuentes de datos la alimentan y `/api/state` la publica.
"""

import threading
import time
from collections.abc import Callable, Iterable

# Estados de una tarea
PENDING, RUNNING, DONE, ERROR, SKIPPED = "pending", "running", "done", "error", "skipped"

# Pasos del arranque, en el orden en que se ven en la pantalla de carga
BOOT_STEPS = (
    ("client", "Cliente de LoL"),
    ("history", "Tu historial"),
    ("mastery", "Maestría y rango"),
    ("champions", "Campeones y parche"),
    ("tiers", "Estadísticas Master+"),
    ("picks", "Tus recomendaciones"),
)


class Tasks:
    """Tareas en curso y terminadas, seguras entre hilos.

    `boot` marca los pasos del arranque: mientras alguno no ha terminado, la app está «cargando».
    El resto (matchups en cola, torneos de gol.gg…) son trabajo en segundo plano."""

    def __init__(self, now: Callable[[], float] = time.time):
        self._now = now
        self._lock = threading.Lock()
        self._items: dict[str, dict] = {}

    # -- altas y cambios
    def plan(self, steps: Iterable[tuple[str, str]] = BOOT_STEPS) -> None:
        """Deja los pasos del arranque pendientes, en orden (al empezar cada sesión con el cliente)."""
        with self._lock:
            for tid, text in steps:
                self._items.pop(tid, None)
                self._items[tid] = self._new(tid, text, boot=True)

    def start(self, tid: str, text: str | None = None, total: int | None = None, detail: str = "") -> None:
        with self._lock:
            t = self._items.get(tid)
            if t is None:
                t = self._items[tid] = self._new(tid, text or tid, boot=False)
            t.update(state=RUNNING, done=0, total=total, detail=detail, error=None, retry_at=None)
            if text:
                t["text"] = text
            t["started"] = t["updated"] = self._now()

    def step(self, tid: str, done: int, total: int | None = None, detail: str | None = None) -> None:
        """Progreso de una tarea en curso: `done` de `total` (n de m)."""
        with self._lock:
            t = self._items.get(tid)
            if t is None:
                return
            t["state"], t["done"] = RUNNING, max(0, done)
            if total is not None:
                t["total"] = total
            if detail is not None:
                t["detail"] = detail
            t["updated"] = self._now()

    def finish(self, tid: str, detail: str = "") -> None:
        self._end(tid, DONE, detail)

    def skip(self, tid: str, detail: str = "") -> None:
        """La tarea no hace falta (p. ej. maestría sin cliente: se usa la guardada)."""
        self._end(tid, SKIPPED, detail)

    def fail(self, tid: str, error: str, retry_in: float | None = None) -> None:
        """La tarea ha fallado; con `retry_in` (segundos), se reintenta sola pasado ese tiempo."""
        with self._lock:
            t = self._items.get(tid)
            if t is None:
                t = self._items[tid] = self._new(tid, tid, boot=False)
            t.update(state=ERROR, error=error, updated=self._now())
            t["retry_at"] = self._now() + retry_in if retry_in is not None else None

    def queue(self, tid: str, text: str, pending: int) -> None:
        """Cola en segundo plano (p. ej. matchups por descargar): el total es el máximo de
        pendientes desde que la cola dejó de estar vacía, y lo hecho, ese máximo menos lo que queda."""
        with self._lock:
            t = self._items.get(tid)
            running = t is not None and t["state"] == RUNNING
            if pending <= 0:
                if running and t is not None:
                    t.update(state=DONE, done=t["total"] or 0, updated=self._now())
                return
            if not running or t is None:
                t = self._items[tid] = self._new(tid, text, boot=False)
                t.update(state=RUNNING, total=pending, started=self._now())
            t["total"] = max(t["total"] or 0, pending)
            t["done"] = t["total"] - pending
            t["text"], t["updated"] = text, self._now()

    def _end(self, tid: str, state: str, detail: str) -> None:
        with self._lock:
            t = self._items.get(tid)
            if t is None:
                t = self._items[tid] = self._new(tid, tid, boot=False)
            t.update(state=state, detail=detail, error=None, retry_at=None, updated=self._now())
            if state == DONE and t["total"]:
                t["done"] = t["total"]

    def _new(self, tid: str, text: str, boot: bool) -> dict:
        return {
            "id": tid,
            "text": text,
            "state": PENDING,
            "done": 0,
            "total": None,
            "detail": "",
            "error": None,
            "boot": boot,
            "started": None,
            "updated": self._now(),
            "retry_at": None,
        }

    # -- consultas
    def get(self, tid: str) -> dict | None:
        with self._lock:
            t = self._items.get(tid)
            return dict(t) if t else None

    def retry_due(self, tid: str) -> bool:
        """Si la tarea falló y ya toca reintentarla."""
        with self._lock:
            t = self._items.get(tid)
            return bool(t and t["state"] == ERROR and t["retry_at"] is not None and self._now() >= t["retry_at"])

    def items(self) -> list[dict]:
        """Copia de las tareas para el panel, en orden de alta, con los segundos que faltan para
        reintentar las que han fallado."""
        now = self._now()
        with self._lock:
            out = []
            for t in self._items.values():
                row = {k: v for k, v in t.items() if k not in ("retry_at", "updated", "started")}
                row["retry_in"] = max(0, round(t["retry_at"] - now)) if t["retry_at"] is not None else None
                row["elapsed"] = round(now - t["started"], 1) if t["started"] and t["state"] == RUNNING else None
                out.append(row)
            return out


def label(t: dict) -> str:
    """Texto corto de una tarea para la barra superior, p. ej. «Estadísticas Master+ 3/5»."""
    if t.get("total") and t.get("state") == RUNNING:
        return f"{t['text']} {t.get('done', 0)}/{t['total']}"
    return t.get("text", "")


def summary(items: list[dict]) -> dict:
    """Resumen para el panel: si el arranque sigue en marcha, el paso actual (n de m) y qué hay
    trabajando en segundo plano."""
    boot = [t for t in items if t.get("boot")]
    finished = [t for t in boot if t["state"] in (DONE, SKIPPED)]
    current = next((t for t in boot if t["state"] in (RUNNING, ERROR)), None)
    if current is None:
        current = next((t for t in boot if t["state"] == PENDING), None)
    running = [t for t in items if t["state"] == RUNNING]
    errors = [t for t in items if t["state"] == ERROR]
    return {
        "booting": bool(boot) and len(finished) < len(boot),
        "step": min(len(finished) + 1, len(boot)) if boot else 0,
        "steps": len(boot),
        "current": current["id"] if current and len(finished) < len(boot) else None,
        "busy": bool(running),
        "label": label(running[0]) if running else "",
        "errors": [t["id"] for t in errors],
    }
