"""Cliente mínimo de la API de Riot: league-v4, match-v5 y account-v1, con los límites de la clave.

Clave personal: 20 peticiones por segundo y 100 cada 2 minutos. En un 429 se respeta
`Retry-After`; los 5xx se reintentan con espera creciente. El transporte (`fetch`) se inyecta para
los tests: recibe la URL y las cabeceras y devuelve (código, cabeceras, cuerpo).
"""

import json
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import deque
from collections.abc import Callable

PLATFORM_ROUTING = {"euw1": "europe", "eun1": "europe", "tr1": "europe", "ru": "europe", "me1": "europe",
                    "na1": "americas", "br1": "americas", "la1": "americas", "la2": "americas",
                    "kr": "asia", "jp1": "asia", "oc1": "sea", "sg2": "sea", "tw2": "sea", "vn2": "sea"}  # fmt: skip
PERSONAL_LIMITS = ((20, 1.0), (100, 120.0))
APEX = ("challengerleagues", "grandmasterleagues", "masterleagues")
DIVISIONS = ("I", "II", "III", "IV")
PAGE = 205  # jugadores por página de league-v4 /entries
# Ligas de la muestra: los apex y, por debajo, estas ligas con sus cuatro divisiones
LEAGUES = {"master_plus": (), "diamond_plus": ("DIAMOND",), "emerald_plus": ("DIAMOND", "EMERALD")}


class RiotError(Exception):
    def __init__(self, status: int, url: str):
        super().__init__(f"HTTP {status} en {url}")
        self.status = status


def _http(url: str, headers: dict) -> tuple[int, dict, bytes]:
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            return r.status, dict(r.headers), r.read()
    except urllib.error.HTTPError as e:
        return e.code, dict(e.headers or {}), e.read() or b""


class RateLimiter:
    """Ventanas deslizantes: como mucho `n` peticiones en `secs` segundos, para cada límite."""

    def __init__(self, limits=PERSONAL_LIMITS, clock=time.monotonic, sleep=time.sleep):
        self.limits, self.clock, self.sleep = limits, clock, sleep
        self.sent: deque[float] = deque()

    def wait(self) -> None:
        while True:
            now = self.clock()
            longest = max(secs for _, secs in self.limits)
            while self.sent and now - self.sent[0] >= longest:
                self.sent.popleft()
            delay = 0.0
            for n, secs in self.limits:
                recent = [t for t in self.sent if now - t < secs]
                if len(recent) >= n:
                    delay = max(delay, secs - (now - recent[-n]))
            if delay <= 1e-6:
                self.sent.append(now)
                return
            self.sleep(max(delay, 0.001))  # nunca 0: con relojes de coma flotante no avanzaría


class Riot:
    def __init__(
        self,
        key: str,
        platform: str = "euw1",
        fetch: Callable[[str, dict], tuple[int, dict, bytes]] = _http,
        limiter: RateLimiter | None = None,
        sleep=time.sleep,
        retries: int = 4,
    ):
        if not key:
            raise ValueError("falta la clave de la API (RIOT_API_KEY)")
        self.key, self.platform = key, platform
        self.region = PLATFORM_ROUTING[platform]
        self.fetch, self.limiter, self.sleep, self.retries = fetch, limiter or RateLimiter(), sleep, retries
        self.requests = 0

    def get(self, host: str, path: str, params: dict | None = None):
        url = f"https://{host}.api.riotgames.com{path}"
        if params:
            url += "?" + urllib.parse.urlencode(params)
        for attempt in range(self.retries + 1):
            self.limiter.wait()
            self.requests += 1
            status, headers, body = self.fetch(url, {"X-Riot-Token": self.key, "User-Agent": "nachero-collector"})
            if status == 200:
                return json.loads(body.decode("utf-8"))
            if status == 404:
                return None
            if status == 429 or status >= 500:
                retry = headers.get("Retry-After") or headers.get("retry-after")
                self.sleep(float(retry) if retry else min(60.0, 2.0 ** (attempt + 1)))
                continue
            raise RiotError(status, path)  # 400, 401, 403: clave caducada o petición mal hecha
        raise RiotError(429, path)

    # -- league-v4
    def apex_puuids(self, queue: str = "RANKED_SOLO_5x5") -> list[str]:
        """Jugadores de Challenger, Grandmaster y Master (sus puuid, sin guardar nombres)."""
        out: list[str] = []
        for league in APEX:
            data = self.get(self.platform, f"/lol/league/v4/{league}/by-queue/{queue}") or {}
            out += [e["puuid"] for e in data.get("entries", []) if e.get("puuid")]
        return list(dict.fromkeys(out))

    def entries_puuids(self, tier: str, division: str, page: int = 1, queue: str = "RANKED_SOLO_5x5") -> list[str]:
        """Una página (hasta 205) de jugadores de una división por debajo de Master (sus puuid, sin
        guardar nombres). Pasada la última página, la API devuelve una lista vacía."""
        data = self.get(self.platform, f"/lol/league/v4/entries/{queue}/{tier}/{division}", {"page": page}) or []
        return [e["puuid"] for e in data if isinstance(e, dict) and e.get("puuid")]

    # -- match-v5
    def match_ids(self, puuid: str, queue: int = 420, start_time: int | None = None, count: int = 100) -> list[str]:
        ids: list[str] = []
        start = 0
        while True:
            params = {"queue": queue, "start": start, "count": count}
            if start_time:
                params["startTime"] = int(start_time)
            page = self.get(self.region, f"/lol/match/v5/matches/by-puuid/{puuid}/ids", params) or []
            ids += page
            if len(page) < count:
                return ids
            start += count

    def match(self, match_id: str):
        return self.get(self.region, f"/lol/match/v5/matches/{match_id}")

    def timeline(self, match_id: str):
        """Eventos de la partida (compras y subidas de habilidad): una petición más por partida (#90)."""
        return self.get(self.region, f"/lol/match/v5/matches/{match_id}/timeline")

    # -- account-v1 (solo para tu propio historial)
    def puuid_of(self, game_name: str, tag_line: str) -> str | None:
        path = f"/riot/account/v1/accounts/by-riot-id/{urllib.parse.quote(game_name)}/{urllib.parse.quote(tag_line)}"
        data = self.get(self.region, path)
        return data.get("puuid") if data else None
