"""Leer los datos propios y la caché de Lolalytics para compararlos (#21) y escribir el informe.

No descarga nada: usa lo que ya tiene la app en tu carpeta de datos (el archivo o la caché de los
datos propios y `cache/lolalytics_cache.json`). La comparación en sí está en `domain/validation.py`.
"""

from pathlib import Path

from nachero.config import LEAGUE_NAMES
from nachero.domain import validation as V
from nachero.domain.common import ROLE_ES, ROLES
from nachero.jsonio import read_json
from nachero.sources.local_stats import LocalStats


class LolaCache:
    """La caché de Lolalytics de la app, solo para leer (sin hilos ni red)."""

    def __init__(self, path):
        data = read_json(str(path), {}) if Path(path).is_file() else {}
        self.data = data if isinstance(data, dict) else {}

    def tier(self, role):
        return (self.data.get("tiers") or {}).get(role)

    def builds(self) -> dict:
        return self.data.get("builds") or {}

    def name(self, cid) -> str:
        return (self.data.get("slugs") or {}).get(str(cid)) or str(cid)


def run(own: LocalStats, lola: LolaCache, min_games: int = 100, min_n: int = 30, top: int = 8) -> dict:
    """Comparación por rol (tier lists) y de los matchups de las páginas que tienen las dos fuentes
    en la liga de los datos propios."""
    roles = {}
    for role in ROLES:
        res = V.compare_role(own.tier(role), lola.tier(role), min_games, top)
        res["verdict"] = V.verdict(res)
        res["ref_patch"] = (lola.tier(role) or {}).get("patch")
        roles[role] = res
    pairs = []
    for key, page in lola.builds().items():
        cid, _, role = key.partition(":")
        if role not in ROLES or page.get("tier") not in (None, own.league):
            continue
        mine = own.matchups(cid, role, fetch=False)
        if mine and page.get("lanes"):
            pairs.append((mine, page["lanes"]))
    return {
        "patch": own.patch,
        "league": own.league,
        "roles": roles,
        "matchups": V.compare_matchups(pairs, min_n),
        "problem": own.problem,
    }


def _f(v, nd=2, sign=False, unit="") -> str:
    if v is None:
        return "—"
    s = f"{v:+.{nd}f}" if sign else f"{v:.{nd}f}"
    return s.replace(".", ",") + unit


def _n(v: int) -> str:
    return f"{v:,}".replace(",", ".")


def markdown(res: dict, lola: LolaCache, min_games: int) -> str:
    """Informe para leer (o pegar en la issue #21)."""
    league = LEAGUE_NAMES.get(res["league"] or "", res["league"] or "?")
    out = [
        f"# Datos propios frente a Lolalytics · parche {res['patch'] or '?'}",
        "",
        f"- Datos propios: liga {league}. Tier lists de Lolalytics: Master+ (las de la app), así que el "
        "WR se compara relativo a la media de cada rol. Matchups: páginas de build de la misma liga.",
        f"- Solo cuentan los campeones con {min_games} partidas o más en las dos fuentes. z = diferencia "
        "entre errores típicos: |z| > 3 no se explica por ruido.",
        "",
    ]
    if res.get("problem"):
        out += [f"**Los datos propios no se pueden leer: {res['problem']}.**", ""]
    out += [
        "| Rol | Partidas propias | Campeones (comunes / con pocas) | Corr. WR | Corr. PR | Dif. media | "
        "Sesgo | \\|z\\|>3 | Señal | Veredicto |",
        "|---|---|---|---|---|---|---|---|---|---|",
    ]
    for role, r in res["roles"].items():
        out.append(
            f"| {ROLE_ES.get(role, role)} | {_n(r['own_games'])} | {r['common']} / {r['thin']} | {_f(r['wr_corr'])} | "
            f"{_f(r['pr_corr'])} | {_f(r['mad'], unit=' pp')} | {_f(r['bias'], sign=True, unit=' pp')} | "
            f"{r['outliers']} | {_f(r['signal'])} | {r['verdict'][1]} |"
        )
    m = res["matchups"]
    out += [
        "",
        f"**Matchups** ({m['pages']} {'página' if m['pages'] == 1 else 'páginas'}, {m['rows']} filas con 30+ "
        f"partidas en las dos): corr. d2 {_f(m['d2_corr'])}, dif. media {_f(m['mad'], unit=' pp')}, "
        f"sesgo {_f(m['bias'], sign=True, unit=' pp')}.",
        "",
        "## Campeones con más desviación",
    ]
    for role, r in res["roles"].items():
        if not r["worst"]:
            continue
        out += ["", f"### {ROLE_ES.get(role, role)}", "", "| Campeón | Propio | Lolalytics | Dif. | z | Partidas |",
                "|---|---|---|---|---|---|"]  # fmt: skip
        for w in r["worst"]:
            out.append(
                f"| {lola.name(w['id'])} | {_f(w['own'], 1, True)} | {_f(w['ref'], 1, True)} | "
                f"{_f(w['diff'], 1, True)} | {_f(w['z'], 1, True)} | {_n(w['n_own'])} / {_n(w['n_ref'])} |"
            )
    out += [
        "",
        "Señal: fracción del spread de WR de los datos propios que no es ruido binomial (1 = todo "
        "señal; cerca de 0 = faltan partidas, típico al principio de parche).",
    ]
    return "\n".join(out) + "\n"
