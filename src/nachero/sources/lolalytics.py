"""Datos de campeones (cliente) y estadisticas Master+ (Lolalytics).

Lolalytics no tiene API publica. Su robots.txt permite el acceso general (Allow: /),
asi que Nachero lee pocas paginas, con cache de varias horas y una peticion cada ~1,5 s.
"""

import json
import os
import queue
import re
import threading
import time
import urllib.request

from nachero.jsonio import read_json
from nachero.sources.health import FormatChanged, Health

LOLA_LANE = {"top": "top", "jungle": "jungle", "middle": "middle", "bottom": "bottom", "utility": "support"}
ARAM = "aram"  # «rol» de las builds de ARAM en la caché (cid:aram): solo runas, sin matchups
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) nachero/2.0 (uso personal)"


class Lolalytics:
    """Fuente de estadísticas (`domain.stats.StatsProvider`) que lee la web de Lolalytics."""

    name = "Lolalytics"
    TIER_TTL = 6 * 3600
    COUNTER_TTL = 24 * 3600
    RETRY_AFTER = 30 * 60

    def __init__(self, cache_dir, log, tier="master_plus", build_tier=None):
        self.path = os.path.join(cache_dir, "lolalytics_cache.json")
        self.log, self.tier_name = log, tier
        # liga de las páginas de build (matchups y runas): más amplia = más partidas por matchup (#70)
        self.build_tier = build_tier or tier
        self.lock = threading.RLock()
        self.save_lock = threading.Lock()  # una escritura del archivo a la vez
        self.cache = {"tiers": {}, "builds": {}, "slugs": {}}
        if os.path.exists(self.path):
            try:
                saved = read_json(self.path, {})
                saved.pop("counters", None)  # formato antiguo (solo tu linea)
                self.cache.update(saved)
            except Exception:
                pass
        self.failed, self.pending = {}, set()
        # tier lists: aviso al segundo rol vacío; builds: al tercer campeón seguido sin datos
        self.health = Health("Lolalytics", log, {"tiers": 2, "builds": 3})
        self.slug_fallback = None  # funcion cid -> slug, hasta tener el mapa real de Lolalytics
        self.q, self.last_req, self.patch = queue.Queue(), 0.0, None
        threading.Thread(target=self._worker, daemon=True).start()

    # -- red
    def _fetch(self, url):
        wait = 1.5 - (time.time() - self.last_req)
        if wait > 0:
            time.sleep(wait)
        self.last_req = time.time()
        req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept-Language": "en"})
        with urllib.request.urlopen(req, timeout=25) as r:
            return r.read().decode("utf-8", "replace")

    def _save(self):
        # serializar con el lock (rápido) y escribir sin él: con la caché grande (más de 10 MB)
        # escribir tarda ~2 s y el motor, que lee la caché en cada tick, no debe esperar
        with self.lock:
            text = json.dumps(self.cache, ensure_ascii=False)
        with self.save_lock:
            tmp = f"{self.path}.tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                f.write(text)
            os.replace(tmp, self.path)

    # -- tier list por linea
    def refresh_tiers(self, patch, force=False, progress=None):
        """Descarga la tier list de cada línea (las que no estén frescas en caché). `progress(n, total)`
        se llama tras cada línea. Devuelve cuántas líneas tienen datos de este parche."""
        self.patch = patch
        total = len(LOLA_LANE)
        for i, (role, lane) in enumerate(LOLA_LANE.items()):
            t = self.cache["tiers"].get(role)
            if not force and t and t.get("patch") == patch and time.time() - t["t"] < self.TIER_TTL:
                if progress:
                    progress(i + 1, total)
                continue
            url = (
                f"https://a1.lolalytics.com/mega/?ep=list&p=d&v=1&patch={patch}&lane={lane}"
                f"&tier={self.tier_name}&queue=ranked&region=all"
            )
            try:
                d = json.loads(self._fetch(url))
                champs = parse_tier(d)  # si ya no trae campeones, no se pisa la caché buena
                with self.lock:
                    self.cache["tiers"][role] = {
                        "t": time.time(),
                        "patch": patch,
                        "avg": d.get("avgWr", 50.0),
                        "games": role_games(champs),
                        "champs": champs,
                    }
                self.health.ok("tiers")
            except Exception as e:
                self.health.fail("tiers", e)
                self.log(f"Lolalytics: no pude leer la tier list de {role} ({e.__class__.__name__})", "warn")
            if progress:
                progress(i + 1, total)
        self._save()
        return self.roles_ready(patch)

    def roles_ready(self, patch):
        """Líneas con tier list de este parche."""
        with self.lock:
            return sum(1 for t in self.cache["tiers"].values() if t.get("patch") == patch)

    def tier(self, role):
        with self.lock:
            return self.cache["tiers"].get(role)

    def updated_at(self):
        ts = [t["t"] for t in self.cache["tiers"].values()]
        return min(ts) if ts else None

    def stats(self):
        """Partidas analizadas por rol y builds en caché (para el panel)."""
        with self.lock:
            tiers = self.cache.get("tiers", {})
            return {
                # cada partida sale en las cinco líneas: el total es el de la línea con más (se
                # calcula de los campeones: la caché anterior a 0.30 guardaba 1/10 por línea)
                "games": max((role_games(v.get("champs") or {}) for v in tiers.values()), default=0),
                "builds": len(self.cache.get("builds", {})),
            }

    # -- matchups por campeon contra las 5 lineas (pagina de build)
    def matchups(self, cid, role, fetch=True):
        """{rol_enemigo: {vs_cid: {wr, d1, d2, pr, n}}} si esta en cache; si no, lo pide en segundo plano
        (con `fetch=False`, solo mira la cache)."""
        key = f"{cid}:{role}"
        with self.lock:
            c = self.cache["builds"].get(key)
        if fetch and not self._fresh(c):
            self.request(cid, role)
        return c["lanes"] if c else None

    def runes(self, cid, role):
        """Paginas de runas recomendadas {"pick": {...}, "win": {...}} (puede estar vacio si hay pocos datos).
        None si aun no esta descargado: lo pide en segundo plano. `role` "aram": las de ARAM."""
        with self.lock:
            c = self.cache["builds"].get(f"{cid}:{role}")
        if not self._fresh(c):
            self.request(cid, role)
        return c.get("runes") if c and "runes" in c else None

    def build(self, cid, role):
        """Builds recomendadas {"pick": {...}, "win": {...}} (objetos, botas, habilidades y hechizos;
        puede estar vacío) de la misma página que los matchups. None si aún no está: la pide en
        segundo plano (también si la entrada es de antes de guardar las builds)."""
        with self.lock:
            c = self.cache["builds"].get(f"{cid}:{role}")
        if not self._fresh(c) or "build" not in c:
            self.request(cid, role)
        return c.get("build") if c and "build" in c else None

    def _fresh(self, c):
        # las entradas antiguas (sin runas) se vuelven a descargar
        return (
            bool(c)
            and "runes" in c
            and c.get("patch") == self.patch
            and c.get("tier", self.tier_name) == self.build_tier
            and time.time() - c["t"] < self.COUNTER_TTL
        )

    def counters(self, cid, role):
        """Solo los matchups contra tu misma linea (compatibilidad)."""
        m = self.matchups(cid, role)
        return None if m is None else m.get(role, {})

    def request(self, cid, role, slug=None):
        key = f"{cid}:{role}"
        if key in self.pending or time.time() - self.failed.get(key, 0) < self.RETRY_AFTER:
            return
        self.pending.add(key)
        self.q.put((cid, role, slug))

    def _worker(self):
        while True:
            cid, role, slug = self.q.get()
            key = f"{cid}:{role}"
            try:
                slug = (
                    self.cache["slugs"].get(str(cid))
                    or slug
                    or (self.slug_fallback(cid) if self.slug_fallback else None)
                )
                if not slug:
                    raise ValueError("sin slug")
                if role == ARAM:  # build de ARAM: mismo estado qwik, sin tablas por línea
                    page = {"lanes": {}, "slugs": {}, "build": {}}
                    page["runes"] = parse_runes(self._fetch(f"https://lolalytics.com/lol/{slug}/aram/build/"))
                else:
                    url = f"https://lolalytics.com/lol/{slug}/build/?lane={LOLA_LANE[role]}&tier={self.build_tier}"
                    page = parse_page(self._fetch(url))
                with self.lock:
                    if page["slugs"]:
                        self.cache["slugs"].update(page["slugs"])
                    self.cache["builds"][key] = {
                        "t": time.time(),
                        "patch": self.patch,
                        "tier": self.build_tier,
                        "lanes": page["lanes"],
                        "runes": page["runes"],
                        "build": page["build"],
                    }
                self._save()
                self.health.ok("builds")
            except Exception as e:
                self.health.fail("builds", e)
                self.failed[key] = time.time()
                self.log(f"Lolalytics: sin matchups para {slug or cid} ({e.__class__.__name__})", "warn")
            finally:
                self.pending.discard(key)


ROLE_OF_LANE = {v: k for k, v in LOLA_LANE.items()}


def role_games(champs: dict) -> int:
    """Partidas con este rol: cada una pone dos campeones en él (uno por equipo)."""
    return sum(c.get("games", 0) for c in champs.values()) // 2


def parse_tier(d):
    """Tier list de la API de Lolalytics: {"<cid>": {wr, pr, br, games, tier, rank, pct}}.
    FormatChanged si no trae campeones (cambio de formato)."""
    rows = d.get("cid") if isinstance(d, dict) else None
    if not isinstance(rows, dict) or not rows:
        raise FormatChanged("la tier list no trae campeones")
    champs = {}
    for cid, v in rows.items():
        champs[cid] = {
            "wr": v["wr"],
            "pr": v["pr"],
            "br": v["br"],
            "games": v["games"],
            "tier": v.get("tier", 0),
            "rank": v.get("rank", 0),
            "pct": v.get("pctLane", 0),
        }
    return champs


def _qwik(html):
    m = re.search(r'<script type="qwik/json">(.*?)</script>', html, re.S)
    if not m:
        raise FormatChanged("sin estado qwik")
    objs = json.loads(m.group(1))["objs"]

    def ref(v, depth=3):
        """Resuelve referencias del estado serializado (base 36, con o sin prefijo de senal)."""
        while depth and isinstance(v, str):
            s = v.lstrip("\x11\x12").split("!")[0].split(" ")[0]
            if not re.fullmatch(r"[0-9a-z]+", s):
                return v
            try:
                nv = objs[int(s, 36)]
            except (IndexError, ValueError):
                return v
            if nv == v:
                return v
            v, depth = nv, depth - 1
        return v

    return objs, ref


def _slugs(objs, ref):
    for o in objs:
        if isinstance(o, dict) and len(o) > 120 and all(k.isdigit() for k in o):
            slugs = {}
            for k, v in o.items():
                s = ref(v, 1)
                if isinstance(s, str) and re.fullmatch(r"[a-z0-9]+", s):
                    slugs[k] = s
            if len(slugs) > 100:
                return slugs
    return {}


def _runes(objs, ref):
    """Paginas de runas de "Most Common Build" (pick) y "Highest Win Build" (win).
    Cada una: {"pri": [4 runas], "sec": [2 runas], "mod": [3 fragmentos]}. Vacio si la pagina no las trae."""
    for o in objs:
        if not (isinstance(o, dict) and {"pick", "win"} <= o.keys()):
            continue
        out = {}
        for kind in ("pick", "win"):
            summary = ref(o[kind])
            runes = ref(summary.get("runes")) if isinstance(summary, dict) else None
            rset = ref(runes.get("set")) if isinstance(runes, dict) else None
            if not isinstance(rset, dict):
                continue
            page = {}
            for part, size in (("pri", 4), ("sec", 2), ("mod", 3)):
                ids = ref(rset.get(part))
                ids = [ref(x, 1) for x in ids] if isinstance(ids, list) else []
                if len(ids) == size and all(isinstance(x, int) for x in ids):
                    page[part] = ids
            if len(page) == 3:
                out[kind] = page
        if out:
            return out
    return {}


def parse_runes(html):
    """Solo las runas recomendadas de una página de build (la de ARAM no tiene matchups por línea).
    {"pick": {...}, "win": {...}}, o vacío si no las trae."""
    objs, ref = _qwik(html)
    return _runes(objs, ref)


SKILL_KEYS = {"1": "Q", "2": "W", "3": "E", "4": "R"}
NO_BOOTS = {9999, 1001}  # «sin botas» y las botas básicas: solo si no hay otras


def _ints(v, ref):
    v = ref(v)
    v = [ref(x, 1) for x in v] if isinstance(v, list) else []
    return [x for x in v if isinstance(x, int) and not isinstance(x, bool)]


def _num(v, ref):
    v = ref(v, 1)
    return v if isinstance(v, (int, float)) and not isinstance(v, bool) else None


def _boots_table(objs, ref):
    """Botas de la tabla «Boots» de la página, de más a menos jugadas: [(id, wr, partidas)]."""
    for o in objs:
        if not (isinstance(o, dict) and {"data", "type"} <= o.keys() and ref(o["type"]) == "boots"):
            continue
        rows = []
        data = ref(o["data"])
        for r in data if isinstance(data, list) else []:
            r = ref(r, 1)
            if isinstance(r, list) and len(r) >= 4:
                v = [ref(x, 1) for x in r[:4]]
                if isinstance(v[0], int) and all(isinstance(x, (int, float)) for x in v):
                    rows.append((v[0], v[1], v[3]))
        if rows:
            return rows
    return []


def _build_page(summary, ref, boots_rows):
    """Una build («pick» o «win») del resumen de la página: objetos, botas, habilidades y hechizos."""
    summary = ref(summary)
    if not isinstance(summary, dict):
        return None
    items = ref(summary.get("items"))
    items = items if isinstance(items, dict) else {}
    start, core = ref(items.get("start")), ref(items.get("core"))
    page: dict = {
        "start": _ints(start.get("set"), ref) if isinstance(start, dict) else [],
        "core": _ints(core.get("set"), ref) if isinstance(core, dict) else [],
    }
    if isinstance(core, dict):
        page["core_wr"], page["core_n"] = _num(core.get("wr"), ref), _num(core.get("n"), ref)
    options = []
    for k in ("item4", "item5", "item6"):
        rows = ref(items.get(k))
        opts = []
        for r in rows if isinstance(rows, list) else []:
            r = ref(r, 1)
            if isinstance(r, dict) and isinstance(ref(r.get("id"), 1), int):
                opts.append({"id": ref(r["id"], 1), "wr": _num(r.get("wr"), ref), "n": _num(r.get("n"), ref)})
        options.append(opts[:3])
    page["options"] = options
    # botas: las del núcleo si las lleva; si no, las más jugadas de la tabla
    boot_ids = [b for b, _, _ in boots_rows]
    page["boots"] = next((c for c in page["core"] if c in boot_ids), None) or next(
        (b for b in boot_ids if b not in NO_BOOTS), boot_ids[0] if boot_ids else None
    )
    prio = ref(summary.get("skillpriority"))
    prio = ref(prio.get("id"), 1) if isinstance(prio, dict) else None
    page["skills"] = prio if isinstance(prio, str) and set(prio) <= set("QWER") else ""
    order = ref(summary.get("skillorder"))
    order = ref(order.get("id"), 1) if isinstance(order, dict) else None
    digits = str(order) if isinstance(order, (int, str)) else ""
    page["order"] = "".join(SKILL_KEYS[d] for d in digits) if digits and set(digits) <= set(SKILL_KEYS) else ""
    sums = ref(summary.get("sums"))
    page["spells"] = _ints(sums.get("ids"), ref) if isinstance(sums, dict) else []
    return page if page["core"] or page["start"] else None


def _build(objs, ref):
    """Builds recomendadas de "Most Common Build" (pick) y "Highest Win Build" (win), del mismo
    resumen que las runas. Vacío si la página no las trae."""
    boots_rows = _boots_table(objs, ref)
    for o in objs:
        if not (isinstance(o, dict) and {"pick", "win"} <= o.keys()):
            continue
        out = {}
        for kind in ("pick", "win"):
            page = _build_page(o[kind], ref, boots_rows)
            if page:
                out[kind] = page
        if out:
            return out
    return {}


def parse_page(html):
    """Todo lo que Nachero usa de una página de build: matchups, slugs, runas y build (#88)."""
    objs, ref = _qwik(html)
    lanes = _lanes(objs, ref)
    return {"lanes": lanes, "slugs": _slugs(objs, ref), "runes": _runes(objs, ref), "build": _build(objs, ref)}


def parse_build(html):
    """Pagina de build de Lolalytics: matchups contra cada linea enemiga, mapa de slugs y runas recomendadas.
    Fila de matchup = [campeon, WR contra el, delta1, delta2, % de partidas, partidas]."""
    page = parse_page(html)
    return page["lanes"], page["slugs"], page["runes"]


def _lanes(objs, ref):
    lanes = {}
    for o in objs:
        if not (isinstance(o, dict) and {"data", "lane"} <= o.keys() and ("$$type" in o or "type" in o)):
            continue
        t = ref(o.get("$$type") or o.get("type"))
        if isinstance(t, dict):
            t = ref(t.get("type"))
        if isinstance(t, str) and t not in ("counter",) and not t.startswith("\x11"):
            continue
        lane = ROLE_OF_LANE.get(ref(o["lane"]))
        data = ref(o["data"])
        if not lane or not isinstance(data, list):
            continue
        rows = {}
        for r in data:
            r = ref(r, 1)
            if isinstance(r, list) and len(r) >= 6:
                v = [ref(x, 1) for x in r[:6]]
                if all(isinstance(x, (int, float)) for x in v):
                    rows[str(int(v[0]))] = {"wr": v[1], "d1": v[2], "d2": v[3], "pr": v[4], "n": v[5]}
        if rows and lane not in lanes:
            lanes[lane] = rows
    if not lanes:
        raise ValueError("sin tablas de matchups")
    return lanes
