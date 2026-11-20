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

LOLA_LANE = {"top": "top", "jungle": "jungle", "middle": "middle", "bottom": "bottom", "utility": "support"}
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) nachero/2.0 (uso personal)"


class Lolalytics:
    TIER_TTL = 6 * 3600
    COUNTER_TTL = 24 * 3600
    RETRY_AFTER = 30 * 60

    def __init__(self, cache_dir, log, tier="master_plus"):
        self.path = os.path.join(cache_dir, "lolalytics_cache.json")
        self.log, self.tier_name = log, tier
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
                champs = {}
                for cid, v in d.get("cid", {}).items():
                    champs[cid] = {
                        "wr": v["wr"],
                        "pr": v["pr"],
                        "br": v["br"],
                        "games": v["games"],
                        "tier": v.get("tier", 0),
                        "rank": v.get("rank", 0),
                        "pct": v.get("pctLane", 0),
                    }
                with self.lock:
                    self.cache["tiers"][role] = {
                        "t": time.time(),
                        "patch": patch,
                        "avg": d.get("avgWr", 50.0),
                        "games": sum(c["games"] for c in champs.values()) // 10,
                        "champs": champs,
                    }
            except Exception as e:
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
        None si aun no esta descargado: lo pide en segundo plano."""
        with self.lock:
            c = self.cache["builds"].get(f"{cid}:{role}")
        if not self._fresh(c):
            self.request(cid, role)
        return c.get("runes") if c and "runes" in c else None

    def _fresh(self, c):
        # las entradas antiguas (sin runas) se vuelven a descargar
        return bool(c) and "runes" in c and c.get("patch") == self.patch and time.time() - c["t"] < self.COUNTER_TTL

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
                url = f"https://lolalytics.com/lol/{slug}/build/?lane={LOLA_LANE[role]}&tier={self.tier_name}"
                lanes, slugs, runes = parse_build(self._fetch(url))
                with self.lock:
                    if slugs:
                        self.cache["slugs"].update(slugs)
                    self.cache["builds"][key] = {"t": time.time(), "patch": self.patch, "lanes": lanes, "runes": runes}
                self._save()
            except Exception as e:
                self.failed[key] = time.time()
                self.log(f"Lolalytics: sin matchups para {slug or cid} ({e.__class__.__name__})", "warn")
            finally:
                self.pending.discard(key)


ROLE_OF_LANE = {v: k for k, v in LOLA_LANE.items()}


def _qwik(html):
    m = re.search(r'<script type="qwik/json">(.*?)</script>', html, re.S)
    if not m:
        raise ValueError("sin estado qwik")
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


def parse_build(html):
    """Pagina de build de Lolalytics: matchups contra cada linea enemiga, mapa de slugs y runas recomendadas.
    Fila de matchup = [campeon, WR contra el, delta1, delta2, % de partidas, partidas]."""
    objs, ref = _qwik(html)
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
    return lanes, _slugs(objs, ref), _runes(objs, ref)
