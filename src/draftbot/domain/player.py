"""Modelo personal: cuanto rindes con cada campeon, en puntos de winrate."""

import math
import time
from collections import defaultdict


class Player:
    """Cuanto rindes tu con cada campeon, en pp sobre lo esperado."""

    def __init__(self, games, mastery):
        games = [g for g in games if g.get("role")]
        self.games = games
        self.mastery = {m["championId"]: m for m in (mastery or [])}
        n = len(games)
        self.base_wr = (sum(g["win"] for g in games) + 10 * 0.5) / (n + 10) if n else 0.5
        role_count = defaultdict(int)
        for g in games:
            role_count[g["role"]] += 1
        self.main_role = max(role_count, key=role_count.get) if role_count else "jungle"
        self.role_games = dict(role_count)
        by_role = defaultdict(list)
        for g in games:
            by_role[g["role"]].append(g)
        self.role_mean = {
            r: {k: max(1e-6, sum(g[k] for g in gs) / len(gs)) for k in ("gpm", "dpm", "cspm")}
            for r, gs in by_role.items()
        }
        self.by_cr = defaultdict(list)
        self.by_c = defaultdict(list)
        for g in games:
            self.by_cr[(g["champ"], g["role"])].append(g)
            self.by_c[g["champ"]].append(g)
        self.now_ms = time.time() * 1000

    def exp_games(self, cid):
        """Partidas equivalentes de experiencia: recientes + maestria historica (~700 puntos por partida)."""
        pts = self.mastery.get(cid, {}).get("championPoints", 0)
        return len(self.by_c.get(cid, [])) + pts / 700

    def components(self, cid, role):
        g = self.exp_games(cid)
        # Penaliza mucho las primeras partidas y sigue premiando la soltura hasta ~100-150 partidas
        experience = -6.0 * math.exp(-g / 8) + 2.0 * (1 - math.exp(-g / 80))
        # Forma: campeones que estas jugando ahora (ultimos 30 dias, cualquier rol)
        recent30 = sum(1 for x in self.by_c.get(cid, []) if self.now_ms - x["t"] < 30 * 86400000)
        form = min(1.5, 0.3 * recent30)
        gs = self.by_cr.get((cid, role), [])
        n, w = len(gs), sum(x["win"] for x in gs)
        resid = 0.0
        perf = 0.0
        if n:
            # Varianza de una partida (0,25) frente a la de tu ventaja real por campeon (~3 pp)^2 -> k ~ 120
            resid = (w - n * self.base_wr) / (n + 120) * 100
            mean = self.role_mean.get(role)
            if mean:
                raw = sum(sum(x[m] for x in gs) / n / mean[m] - 1 for m in mean) / 3
                perf = max(-2.0, min(2.0, 8 * raw * n / (n + 8)))
        last = self.mastery.get(cid, {}).get("lastPlayTime", 0)
        days = (self.now_ms - last) / 86400000 if last else 999
        rust = -0.6 if days > 90 and g > 0 else 0.0
        total = max(-8.0, min(6.0, experience + resid + perf + rust + form))
        return {
            "total": total,
            "experience": experience,
            "resid": resid,
            "perf": perf,
            "rust": rust,
            "form": form,
            "recent30": recent30,
            "games": n,
            "wins": w,
            "exp_games": g,
            "mastery": self.mastery.get(cid, {}).get("championPoints", 0),
        }
