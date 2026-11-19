"""Salud de una fuente externa: si su lector deja de encontrar datos (cambio de HTML o de formato),
se sigue con la última caché y se avisa en Actividad y en el panel (issue #8).

Un fallo de red (sin conexión, tiempo agotado, 5xx) no es un cambio de formato: se reintenta como
siempre. Un error al leer la respuesta (no hay estado qwik, la tabla viene vacía, falta un campo)
sí lo es, pero solo se avisa tras `threshold` fallos seguidos, porque un campeón sin datos en un
rol también da una página vacía.
"""

import time


class FormatChanged(ValueError):
    """La respuesta llegó, pero no tiene lo que el lector busca."""


# json.JSONDecodeError y UnicodeDecodeError son ValueError
FORMAT_ERRORS = (ValueError, KeyError, TypeError, IndexError, AttributeError)


def is_format_error(e: BaseException) -> bool:
    return isinstance(e, FORMAT_ERRORS) and not isinstance(e, OSError)


class Health:
    def __init__(self, name: str, log=None, thresholds: dict | None = None):
        self.name, self.log = name, log or (lambda *a, **k: None)
        self.thresholds = thresholds or {}
        self.state: dict[str, dict] = {}

    def _get(self, kind: str) -> dict:
        return self.state.setdefault(kind, {"ok": None, "fails": 0, "error": None, "warned": False})

    def ok(self, kind: str, now: float | None = None) -> None:
        s = self._get(kind)
        if s["warned"]:
            self.log(f"{self.name} vuelve a leerse bien ({kind})", "ok")
        s.update(ok=time.time() if now is None else now, fails=0, error=None, warned=False)

    def fail(self, kind: str, e: BaseException) -> bool:
        """Apunta un fallo. True si es (ya) un cambio de formato que hay que avisar."""
        s = self._get(kind)
        if not is_format_error(e):
            return False
        s["fails"] += 1
        s["error"] = f"{e.__class__.__name__}: {e}"[:160]
        changed = s["fails"] >= self.thresholds.get(kind, 1)
        if changed and not s["warned"]:
            s["warned"] = True
            self.log(
                f"{self.name} ha cambiado su página ({kind}): no encuentro los datos y sigo con los guardados. "
                "Copia el diagnóstico de Actividad y avísanos.",
                "warn",
            )
        return changed

    def warnings(self) -> list[dict]:
        """Avisos para el panel: fuentes cuyo lector ya no encuentra datos."""
        return [
            {"source": self.name, "kind": kind, "error": s["error"], "last_ok": s["ok"]}
            for kind, s in self.state.items()
            if s["warned"]
        ]
