"""Registro de tareas (#46): lo que la app está haciendo, con su progreso real."""

from nachero.domain.tasks import BOOT_STEPS, Tasks, label, summary


class Clock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


def _tasks():
    clock = Clock()
    return Tasks(now=clock), clock


def test_plan_deja_los_pasos_del_arranque_pendientes_y_en_orden():
    tk, _ = _tasks()
    tk.plan()
    items = tk.items()
    assert [t["id"] for t in items] == [tid for tid, _ in BOOT_STEPS]
    assert all(t["state"] == "pending" and t["boot"] for t in items)
    s = summary(items)
    assert s["booting"] and s["step"] == 1 and s["steps"] == len(BOOT_STEPS)
    assert s["current"] == "client" and not s["busy"]


def test_progreso_n_de_m_y_fin():
    tk, clock = _tasks()
    tk.plan()
    tk.finish("client", "Conectado")
    tk.start("tiers", total=5, detail="Parche 16.22")
    tk.step("tiers", 3)
    clock.t += 4.5
    t = tk.get("tiers")
    assert (t["state"], t["done"], t["total"], t["detail"]) == ("running", 3, 5, "Parche 16.22")
    assert t["text"] == "Estadísticas Master+"  # conserva el texto del plan
    row = next(r for r in tk.items() if r["id"] == "tiers")
    assert row["elapsed"] == 4.5
    assert label(row) == "Estadísticas Master+ 3/5"
    s = summary(tk.items())
    assert s["busy"] and s["label"] == "Estadísticas Master+ 3/5"
    tk.finish("tiers", "5 roles")
    assert tk.get("tiers")["done"] == 5  # al terminar, completo


def test_arranque_terminado_con_pasos_saltados():
    tk, _ = _tasks()
    tk.plan()
    tk.skip("client", "Cerrado: uso tus datos guardados")
    for tid in ("history", "mastery", "champions", "tiers", "picks"):
        tk.finish(tid)
    s = summary(tk.items())
    assert not s["booting"] and s["current"] is None and not s["busy"]
    assert s["step"] == s["steps"]


def test_un_fallo_dice_cual_y_cuando_se_reintenta():
    tk, clock = _tasks()
    tk.plan()
    tk.start("tiers", total=5)
    tk.fail("tiers", "Lolalytics no responde: 2/5 roles", retry_in=60)
    s = summary(tk.items())
    assert s["errors"] == ["tiers"] and s["booting"]
    row = next(r for r in tk.items() if r["id"] == "tiers")
    assert row["error"].startswith("Lolalytics") and row["retry_in"] == 60
    assert not tk.retry_due("tiers")
    clock.t += 61
    assert tk.retry_due("tiers")
    tk.start("tiers", total=5)  # el reintento limpia el error
    assert tk.get("tiers")["error"] is None and not tk.retry_due("tiers")


def test_fallo_sin_reintento():
    tk, clock = _tasks()
    tk.fail("golgg", "gol.gg no responde")
    clock.t += 10_000
    assert not tk.retry_due("golgg")
    assert tk.items()[0]["retry_in"] is None


def test_cola_en_segundo_plano_cuenta_lo_hecho_sobre_el_maximo():
    tk, _ = _tasks()
    tk.queue("matchups", "Matchups", 0)
    assert tk.get("matchups") is None  # nada en cola: no aparece
    tk.queue("matchups", "Matchups", 4)
    tk.queue("matchups", "Matchups", 6)  # entran más: el total crece
    tk.queue("matchups", "Matchups", 2)
    t = tk.get("matchups")
    assert (t["state"], t["done"], t["total"]) == ("running", 4, 6)
    assert not t["boot"]
    tk.queue("matchups", "Matchups", 0)
    t = tk.get("matchups")
    assert (t["state"], t["done"], t["total"]) == ("done", 6, 6)
    tk.queue("matchups", "Matchups", 3)  # una cola nueva empieza de cero
    t = tk.get("matchups")
    assert (t["done"], t["total"]) == (0, 3)


def test_el_trabajo_en_segundo_plano_no_es_arranque():
    tk, _ = _tasks()
    tk.plan()
    for tid, _ in BOOT_STEPS:
        tk.finish(tid)
    tk.start("golgg", "Torneo pro", total=6)
    tk.step("golgg", 2)
    s = summary(tk.items())
    assert not s["booting"] and s["busy"] and s["label"] == "Torneo pro 2/6"


def test_plan_otra_vez_reinicia_el_arranque_sin_perder_el_segundo_plano():
    tk, _ = _tasks()
    tk.plan()
    for tid, _ in BOOT_STEPS:
        tk.finish(tid)
    tk.queue("matchups", "Matchups", 2)
    tk.plan()  # el cliente se ha vuelto a abrir
    assert summary(tk.items())["booting"]
    assert tk.get("matchups")["state"] == "running"
    assert tk.get("client")["state"] == "pending"


def test_pasos_sin_total_y_tareas_desconocidas():
    tk, _ = _tasks()
    tk.step("nada", 1)  # no existe: no hace nada
    assert tk.items() == []
    tk.start("history", "Tu historial", detail="Leyendo partidas…")
    row = tk.items()[0]
    assert row["total"] is None and label(row) == "Tu historial"
    tk.finish("history", "131 partidas")
    assert tk.get("history")["detail"] == "131 partidas"


# ------------------------------------------------------------------ fuentes y panel
def test_tier_lists_avisan_de_cada_rol(tmp_path):
    import json

    from nachero.sources.lolalytics import Lolalytics

    lola = Lolalytics(str(tmp_path), lambda *a: None)
    calls = []

    def fetch(url):
        if "lane=middle" in url:
            raise OSError("sin red")
        return json.dumps({"avgWr": 50, "cid": {"1": {"wr": 51, "pr": 2, "br": 1, "games": 100}}})

    lola._fetch = fetch
    ready = lola.refresh_tiers("16.22", progress=lambda n, total: calls.append((n, total)))
    assert calls == [(1, 5), (2, 5), (3, 5), (4, 5), (5, 5)]
    assert ready == 4  # mid ha fallado
    # el reintento solo descarga lo que falta, y lo cacheado también cuenta como hecho
    calls.clear()
    urls = []
    lola._fetch = lambda url: urls.append(url) or fetch(url.replace("middle", "mid-ok"))
    assert lola.refresh_tiers("16.22", progress=lambda n, total: calls.append((n, total))) == 5
    assert len(urls) == 1 and "lane=middle" in urls[0]
    assert calls[-1] == (5, 5)


def test_tarea_de_tier_lists_falla_y_se_reintenta(monkeypatch):
    from nachero.app import worker

    tk = Tasks()
    monkeypatch.setattr(worker, "TASKS", tk)

    class Lola:
        def __init__(self, ready):
            self.ready = ready

        def refresh_tiers(self, patch, force=False, progress=None):
            for n in range(1, 6):
                progress(n, 5)
            return self.ready

    assert worker.refresh_tiers(Lola(3), "16.22") == 3
    t = tk.get("tiers")
    assert t["state"] == "error" and "3 de 5" in t["error"] and t["retry_at"] is not None
    worker.refresh_tiers(Lola(5), "16.22")
    t = tk.get("tiers")
    assert (t["state"], t["done"], t["total"]) == ("done", 5, 5)


def test_api_state_publica_tareas_y_resumen():
    import json

    from nachero.app.server import snapshot
    from nachero.app.state import TASKS

    TASKS.plan()
    TASKS.start("history", detail="Leyendo…")
    st = snapshot()
    json.dumps(st, ensure_ascii=False)  # se puede enviar tal cual
    assert [t["id"] for t in st["tasks"]][:2] == ["client", "history"]
    assert st["progress"]["booting"] and st["progress"]["busy"]
