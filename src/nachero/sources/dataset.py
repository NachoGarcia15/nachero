"""Formato de datos propio, esquema 1 (docs/FORMATO_DATOS.md): lector, validación y cálculo.

El recolector (fase 2) publica conteos agregados (partidas y victorias), nunca jugadores. Aquí se
validan y se convierten a lo que usa el motor (`domain/stats.py`): WR, pick y ban rate, reparto
por roles, «delta 1/2» de los matchups y páginas de runas. Con pocas partidas (principio de
parche) se mezclan con el parche anterior usando el mismo encogimiento del motor: el parche
anterior pesa k / (n + k), con n las partidas de este parche.
"""

import gzip
import json
import math
from pathlib import Path

from nachero.domain.blind import expected_wr
from nachero.domain.common import ROLES

SCHEMA = 1
MERGE_K = {"champ": 1000, "matchup": 150, "rune": 300}  # partidas a las que el parche anterior pesa la mitad
RUNE_MIN_SHARE = 0.05  # la página de mayor WR necesita al menos el 5 % de las partidas (y 30)
RUNE_MIN_GAMES = 30
BUILD_OPTIONS = 3  # objetos alternativos tras el núcleo (#90)


def load_file(path) -> dict:
    """Lee un archivo del esquema (.json o .json.gz)."""
    p = Path(path)
    raw = p.read_bytes()
    if p.suffix == ".gz" or raw[:2] == b"\x1f\x8b":
        raw = gzip.decompress(raw)
    return json.loads(raw.decode("utf-8"))


def _count(v) -> bool:
    return isinstance(v, int) and not isinstance(v, bool) and v >= 0


def _page_ok(page) -> bool:
    sizes = {"pri": 4, "sec": 2, "mod": 3}
    return isinstance(page, dict) and all(
        isinstance(page.get(k), list) and len(page[k]) == n and all(isinstance(x, int) for x in page[k])
        for k, n in sizes.items()
    )


def _counts_ok(row) -> bool:
    if not isinstance(row, dict) or not _count(row.get("games")) or not _count(row.get("wins")):
        return False
    return row["wins"] <= row["games"]


def _build_ok(r: dict) -> bool:
    """Objetos completos y botas ({"<id>": conteos}) y parejas de hechizos (opcionales, #90)."""
    for key in ("items", "boots"):
        block = r.get(key, {})
        if not isinstance(block, dict) or not all(str(i).isdigit() and _counts_ok(v) for i, v in block.items()):
            return False
    spells = r.get("spells", [])
    if not isinstance(spells, list):
        return False
    return all(
        _counts_ok(s) and isinstance(s.get("ids"), list) and len(s["ids"]) == 2
        and all(isinstance(x, int) and not isinstance(x, bool) for x in s["ids"])
        for s in spells
    )  # fmt: skip


def _key(k) -> tuple[str, str] | None:
    """ "163:jungle" -> ("163", "jungle"), o None si no vale."""
    if not isinstance(k, str) or ":" not in k:
        return None
    cid, role = k.split(":", 1)
    return (cid, role) if cid.isdigit() and role in ROLES else None


def validate(doc) -> list[str]:
    """Errores del archivo (vacío si vale). Comprueba también que no lleve datos de jugadores."""
    if not isinstance(doc, dict):
        return ["no es un objeto JSON"]
    errors = []
    if doc.get("schema") != SCHEMA:
        return [f"esquema {doc.get('schema')!r} no soportado (se espera {SCHEMA})"]
    for k in ("patch", "region", "league", "generated", "collector"):
        if not isinstance(doc.get(k), str) or not doc[k]:
            errors.append(f"falta «{k}»")
    totals = doc.get("totals")
    if not isinstance(totals, dict) or not _count(totals.get("games")) or not totals["games"]:
        errors.append("«totals.games» no válido")
    champs = doc.get("champions")
    if not isinstance(champs, dict) or not champs:
        errors.append("sin «champions»")
        champs = {}
    for cid, c in champs.items():
        if not cid.isdigit() or not isinstance(c, dict) or not _count(c.get("bans", 0)):
            errors.append(f"campeón {cid!r} no válido")
            continue
        for role, r in (c.get("roles") or {}).items():
            if role not in ROLES or not isinstance(r, dict) or not _count(r.get("games")) or not _count(r.get("wins")):
                errors.append(f"{cid}:{role} no válido")
            elif r["wins"] > r["games"]:
                errors.append(f"{cid}:{role} con más victorias que partidas")
            for page in r.get("runes", []) if isinstance(r, dict) else []:
                if not _page_ok(page) or not _count(page.get("games")) or not _count(page.get("wins")):
                    errors.append(f"runas de {cid}:{role} no válidas")
                    break
            if isinstance(r, dict) and not _build_ok(r):
                errors.append(f"objetos o hechizos de {cid}:{role} no válidos")
    for section in ("matchups", "synergies"):
        block = doc.get(section, {})
        if not isinstance(block, dict):
            errors.append(f"«{section}» no válido")
            continue
        for k, rows in block.items():
            if _key(k) is None or not isinstance(rows, dict):
                errors.append(f"{section}: clave {k!r} no válida")
                continue
            for ek, row in rows.items():
                if _key(ek) is None or not isinstance(row, dict) or not _count(row.get("games")):
                    errors.append(f"{section}: {k} contra {ek!r} no válido")
                elif not _count(row.get("wins")) or row["wins"] > row["games"]:
                    errors.append(f"{section}: {k} contra {ek} con victorias no válidas")
    banned = {"puuid", "summonerId", "accountId", "gameName", "riotId", "matchId", "summonerName"}
    if banned & set(_all_keys(doc)):
        errors.append("lleva identificadores de jugadores o partidas: solo se publican agregados")
    return errors[:20]


def _all_keys(o, depth=0):
    if depth > 6:
        return
    if isinstance(o, dict):
        for k, v in o.items():
            yield k
            yield from _all_keys(v, depth + 1)
    elif isinstance(o, list):
        for v in o[:50]:
            yield from _all_keys(v, depth + 1)


# ------------------------------------------------------------------ fusión con el parche anterior
def _blend(cur: dict | None, prev: dict | None, k: int) -> dict | None:
    """Conteos de este parche más los del anterior escalados por k / (n + k)."""
    if not prev:
        return cur
    n = (cur or {}).get("games", 0)
    f = k / (n + k)
    out = dict(cur or {})
    out["games"] = n + prev.get("games", 0) * f
    out["wins"] = (cur or {}).get("wins", 0) + prev.get("wins", 0) * f
    out["merged"] = True
    return out


def merge(doc: dict, prev: dict | None) -> dict:
    """El documento con el parche anterior mezclado (si lo hay). Conteos con decimales."""
    if not prev or prev.get("region") != doc.get("region") or prev.get("league") != doc.get("league"):
        return doc
    champs: dict = {}
    for cid in set(doc.get("champions", {})) | set(prev.get("champions", {})):
        cur_c, prev_c = doc["champions"].get(cid, {}), prev.get("champions", {}).get(cid, {})
        roles = {}
        for role in set(cur_c.get("roles", {})) | set(prev_c.get("roles", {})):
            cr, pr = cur_c.get("roles", {}).get(role), prev_c.get("roles", {}).get(role)
            r = _blend(cr, pr, MERGE_K["champ"]) or {}
            pages = {json.dumps([p["pri"], p["sec"], p["mod"]]): p for p in (cr or {}).get("runes", [])}
            for p in (pr or {}).get("runes", []):
                key = json.dumps([p["pri"], p["sec"], p["mod"]])
                pages[key] = {**p, **(_blend(pages.get(key), p, MERGE_K["rune"]) or {})}
            r["runes"] = list(pages.values())
            for key in ("items", "boots"):  # objetos de la build (#90), como las runas
                cb, pb = (cr or {}).get(key) or {}, (pr or {}).get(key) or {}
                if cb or pb:
                    r[key] = {i: _blend(cb.get(i), pb.get(i), MERGE_K["rune"]) for i in set(cb) | set(pb)}
            sp = {json.dumps(s["ids"]): s for s in (cr or {}).get("spells", [])}
            for s in (pr or {}).get("spells", []):
                key = json.dumps(s["ids"])
                sp[key] = {**s, **(_blend(sp.get(key), s, MERGE_K["rune"]) or {})}
            if sp:
                r["spells"] = list(sp.values())
            roles[role] = r
        champs[cid] = {"bans": cur_c.get("bans", 0), "roles": roles}
    out = {**doc, "champions": champs, "merged_with": prev.get("patch")}
    for section in ("matchups", "synergies"):
        block: dict = {}
        cur_b, prev_b = doc.get(section, {}), prev.get(section, {})
        for k in set(cur_b) | set(prev_b):
            rows = {}
            for ek in set(cur_b.get(k, {})) | set(prev_b.get(k, {})):
                rows[ek] = _blend(cur_b.get(k, {}).get(ek), prev_b.get(k, {}).get(ek), MERGE_K["matchup"])
            block[k] = rows
        out[section] = block
    return out


# ------------------------------------------------------------------ cálculo para el motor
def _wr(c) -> float:
    return 100 * c["wins"] / c["games"] if c.get("games") else 0.0


def _tiers(rows: dict, avg: float) -> dict:
    """Tier 1 (S+) a 15 (D-) por percentil de fuerza encogida y presencia, como orientación."""
    score = {
        cid: (r["wr"] - avg) * r["games"] / (r["games"] + 1500) + 0.05 * r["pr"]
        for cid, r in rows.items()
        if r["games"]
    }
    ranked = sorted(score, key=lambda c: -score[c])
    out = {}
    for i, cid in enumerate(ranked):
        out[cid] = (i + 1, min(15, 1 + math.floor(15 * i / max(1, len(ranked)))))
    return out


def _rune_pages(pages: list, games: float) -> dict:
    pages = [p for p in pages if p.get("games")]
    if not pages:
        return {}
    pick = max(pages, key=lambda p: p["games"])
    floor = max(RUNE_MIN_GAMES, RUNE_MIN_SHARE * games)
    good = [p for p in pages if p["games"] >= floor] or [pick]
    win = max(good, key=lambda p: (p["wins"] + 25) / (p["games"] + 50))  # WR encogido hacia el 50 %
    page = lambda p: {"pri": list(p["pri"]), "sec": list(p["sec"]), "mod": list(p["mod"])}  # noqa: E731
    return {"pick": page(pick), "win": page(win)}


def _shrunk(row) -> float:
    return (row["wins"] + 25) / (row["games"] + 50)  # WR encogido hacia el 50 %


def _builds(r: dict) -> dict:
    """Builds del formato de `StatsProvider.build` (#90) con lo que hay sin el timeline: objetos
    completos y botas del final de la partida y la pareja de hechizos. «pick»: lo más jugado; «win»:
    lo de mayor WR (encogido) entre lo que tiene el 5 % de las partidas y 30. Sin orden de compra
    ni de habilidades (hace falta el timeline): `start`, `skills` y `order` vacíos."""
    games = r.get("games") or 0
    items = {int(i): v for i, v in (r.get("items") or {}).items() if v and v.get("games")}
    boots = {int(i): v for i, v in (r.get("boots") or {}).items() if v and v.get("games")}
    spells = [s for s in r.get("spells") or [] if s.get("games")]
    if not items and not spells:
        return {}
    floor = max(RUNE_MIN_GAMES, RUNE_MIN_SHARE * games)

    def best(rows: dict | list, key, by_wr: bool):
        rows = list(rows.items()) if isinstance(rows, dict) else [(None, s) for s in rows]
        if by_wr:
            rows = [x for x in rows if x[1]["games"] >= floor] or rows
        return max(rows, key=lambda x: _shrunk(x[1]) if by_wr else x[1]["games"], default=(None, None))

    popular = sorted(items, key=lambda i: -items[i]["games"])
    winning = sorted((i for i in items if items[i]["games"] >= floor), key=lambda i: -_shrunk(items[i]))

    def page(core: list[int], by_wr: bool) -> dict:
        rest = [i for i in popular if i not in core][:BUILD_OPTIONS]
        options = [{"id": i, "wr": round(_wr(items[i]), 1), "n": round(items[i]["games"])} for i in rest]
        sp = best(spells, None, by_wr)[1]
        return {
            "start": [], "core": core, "core_wr": None, "core_n": None, "boots": best(boots, None, by_wr)[0],
            "options": [options, [], []] if options else [], "skills": "", "order": "",
            "spells": list(sp["ids"]) if sp else [],
        }  # fmt: skip

    out = {"pick": page(popular[:3], False)}
    if winning:
        out["win"] = page(winning[:3], True)
    return out


def derive(doc: dict, prev: dict | None = None) -> dict:
    """Del esquema 1 (con el parche anterior mezclado si se da) al formato del motor:
    {"patch", "generated", "roles": {rol: {"avg", "games", "champs"}}, "matchups", "runes", "synergies"}."""
    doc = merge(doc, prev)
    total = doc["totals"]["games"]
    roles: dict = {r: {} for r in ROLES}
    runes = {}
    builds = {}
    for cid, c in doc["champions"].items():
        champ_games = sum(r.get("games", 0) for r in c.get("roles", {}).values())
        for role, r in c.get("roles", {}).items():
            if not r.get("games"):
                continue
            roles[role][cid] = {
                "wr": round(_wr(r), 2),
                "games": round(r["games"]),
                "pr": round(100 * r["games"] / total, 2),
                "br": round(100 * c.get("bans", 0) / total, 2),
                "pct": round(100 * r["games"] / champ_games, 2) if champ_games else 0.0,
                "merged": bool(r.get("merged")),
            }
            pages = _rune_pages(r.get("runes", []), r["games"])
            if pages:
                runes[f"{cid}:{role}"] = pages
            build = _builds(r)
            if build:
                builds[f"{cid}:{role}"] = build
    out_roles = {}
    for role, rows in roles.items():
        if not rows:
            continue
        games = sum(r["games"] for r in rows.values())
        avg = sum(r["wr"] * r["games"] for r in rows.values()) / games if games else 50.0
        for cid, (rank, tier) in _tiers(rows, avg).items():
            rows[cid]["rank"], rows[cid]["tier"] = rank, tier
        # partidas con este rol: cada una pone dos campeones en él (uno por equipo)
        out_roles[role] = {"avg": round(avg, 2), "games": games // 2, "champs": rows}

    def strength(cid, role):
        r = out_roles.get(role, {}).get("champs", {}).get(cid)
        return (r["wr"] - out_roles[role]["avg"]) if r else 0.0

    matchups: dict = {}
    for k, rows in (doc.get("matchups") or {}).items():
        cid, role = _key(k) or ("", "")
        champ = out_roles.get(role, {}).get("champs", {}).get(cid)
        if not champ:
            continue
        lanes: dict = {}
        for ek, row in rows.items():
            if not row or not row.get("games"):
                continue
            ecid, erole = _key(ek) or ("", "")
            wr = _wr(row)
            # esperado por la fuerza de los dos: cociente de sus odds (blind.expected_wr, vídeo de
            # MachineLoLing); con fuerzas pequeñas es casi 50 + fuerza propia − fuerza rival
            expected = expected_wr(50 + strength(cid, role), 50 + strength(ecid, erole))
            lanes.setdefault(erole, {})[ecid] = {
                "wr": round(wr, 2),
                "d1": round(wr - champ["wr"], 2),
                "d2": round(wr - expected, 2),
                "pr": round(100 * row["games"] / champ["games"], 2) if champ["games"] else 0.0,
                "n": round(row["games"]),
            }
        if lanes:
            matchups[k] = lanes
    synergies = {
        k: {ek: {"wr": round(_wr(r), 2), "n": round(r["games"])} for ek, r in rows.items() if r and r.get("games")}
        for k, rows in (doc.get("synergies") or {}).items()
    }
    return {
        "patch": doc["patch"],
        "region": doc["region"],
        "league": doc["league"],
        "generated": doc["generated"],
        "merged_with": doc.get("merged_with"),
        "roles": out_roles,
        "matchups": matchups,
        "runes": runes,
        "builds": builds,
        "synergies": synergies,
    }
