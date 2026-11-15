"""Estadisticas de competitivo de gol.gg (prioridad, picks, bans, WR y reparto por rol por torneo).

Su robots.txt permite /champion/; Nachero pide pocas paginas, con cache de 12 h y 1,5 s entre peticiones.
"""

import html
import http.cookiejar
import os
import re
import threading
import time
import urllib.parse
import urllib.request

from nachero.domain.common import norm
from nachero.jsonio import read_json, write_json

GOL_ROLE = {"top": "TOP", "jungle": "JUNGLE", "middle": "MID", "bottom": "ADC", "utility": "SUPPORT"}
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) nachero/2.0 (uso personal)"
MAJOR = re.compile(r"Worlds|MSI|First Stand|LCK 20|LPL 20|LEC 20|LCS 20|LTA 20|LCP 20|EWC|Esports World Cup", re.I)


class GolGG:
    TTL = 12 * 3600

    def __init__(self, cache_dir, log):
        self.path = os.path.join(cache_dir, "gol_cache.json")
        self.log, self.lock, self.last = log, threading.Lock(), 0.0
        try:
            self.cache = read_json(self.path) or {"tournaments": None, "data": {}}
        except Exception:
            self.cache = {"tournaments": None, "data": {}}
        self.loading = set()

    def _opener(self):
        jar = http.cookiejar.CookieJar()
        return urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))

    def _get(self, opener, url, data=None):
        wait = 1.5 - (time.time() - self.last)
        if wait > 0:
            time.sleep(wait)
        self.last = time.time()
        body = urllib.parse.urlencode(data).encode() if data else None
        req = urllib.request.Request(url, data=body, headers={"User-Agent": UA})
        with opener.open(req, timeout=30) as r:
            return r.read().decode("utf-8", "replace")

    def _save(self):
        write_json(self.path, self.cache)

    # -- torneos
    def tournaments(self):
        t = self.cache.get("tournaments")
        if t and time.time() - t["t"] < self.TTL:
            return t
        with self.lock:
            h = self._get(self._opener(), "https://gol.gg/champion/list/season-ALL/split-ALL/tournament-ALL/")
            season = (re.findall(r"season-(S\d+)/split", h) or ["S16"])[0]
            h = self._get(self._opener(), f"https://gol.gg/champion/list/season-{season}/split-ALL/tournament-ALL/")
            sel = re.search(r"<select[^>]*name='cbtournament'[^>]*>(.*?)</select>", h, re.S)
            names = (
                [html.unescape(v) for _, v in re.findall(r"<option[^>]*value=(['\"])(.*?)\1", sel.group(1))]
                if sel
                else []
            )
            names = [n for n in names if n != "ALL"]
            majors = [n for n in names if MAJOR.search(n)]
            self.cache["tournaments"] = {"t": time.time(), "season": season, "majors": majors[:25], "all": names}
            self._save()
            return self.cache["tournaments"]

    # -- estadisticas de un torneo
    def dataset(self, tournament):
        d = self.cache["data"].get(tournament)
        if d and time.time() - d["t"] < self.TTL:
            return d
        return None

    def load(self, tournament):
        """Descarga (bloqueante) la tabla general y las 5 por rol de un torneo."""
        if tournament in self.loading:
            return
        self.loading.add(tournament)
        try:
            season = (self.tournaments() or {}).get("season", "S16")
            url = f"https://gol.gg/champion/list/season-{season}/split-ALL/tournament-{urllib.parse.quote(tournament)}/"
            op = self._opener()
            allrows = parse_gol(self._get(op, url))
            roles = {}
            for r, gr in GOL_ROLE.items():
                rows = parse_gol(self._get(op, url, {"role": gr, "leaguePost": "true"}))
                roles[r] = {k: v["picks"] for k, v in rows.items() if v["picks"] > 0}
            games = round(sum(v["picks"] for v in allrows.values()) / 10)
            with self.lock:
                self.cache["data"][tournament] = {"t": time.time(), "games": games, "all": allrows, "roles": roles}
                self._save()
            self.log(f"gol.gg: {tournament} · {games} partidas", "ok")
        except Exception as e:
            self.log(f"gol.gg: no pude leer {tournament} ({e.__class__.__name__})", "warn")
        finally:
            self.loading.discard(tournament)


def _num(s):
    """Numero de una celda de gol.gg ("54%", "3.1"…), o 0."""
    return float(s.replace("%", "")) if re.fullmatch(r"-?[\d.]+%?", s or "") else 0.0


def parse_gol(h):
    out = {}
    for tr in re.findall(r"<tr>(.*?)</tr>", h, re.S):
        if "champion-stats/" not in tr:
            continue
        tds = [html.unescape(re.sub(r"<[^>]+>", "", x)).strip() for x in re.findall(r"<td[^>]*>(.*?)</td>", tr, re.S)]
        if len(tds) < 11:
            continue
        out[norm(tds[0])] = {
            "name": tds[0],
            "picks": int(_num(tds[1])),
            "bans": int(_num(tds[2])),
            "prio": _num(tds[3]),
            "wins": int(_num(tds[4])),
            "losses": int(_num(tds[5])),
            "wr": _num(tds[6]),
            "avg_bt": _num(tds[8]),
            "avg_rp": _num(tds[9]),
            "bp": _num(tds[10]),
        }
    return out
