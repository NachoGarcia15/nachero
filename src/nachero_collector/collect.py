"""Una pasada del recolector: jugadores de la liga, partidas nuevas de soloq y conteos por parche.

Ligas (`riot.LEAGUES`): `master_plus` (Challenger, Grandmaster y Master), `diamond_plus` (además
Diamante I–IV) y `emerald_plus` (además Esmeralda I–IV). Cada división es una «fuente» que se lee
por páginas de 205 jugadores; los apex, una más. Cada pasada coge `players` jugadores de la fuente
que lleve menos recorrido (en fracción de su tamaño), así que con el tiempo cada división aporta en
proporción a sus jugadores. Una partida cuenta en la liga de la muestra (la del archivo), sea cual
sea la división del jugador que la trajo.

Presupuesto de la clave personal: ~3000 peticiones por hora. Cada pasada mira `players` jugadores
(una petición de ids cada uno, más una por página de la liga) y como mucho `matches` partidas
nuevas (una petición cada una). El estado (qué partidas ya se han contado y por dónde va la
rotación de cada liga) vive en un archivo privado del recolector, nunca en los datos publicados.
"""

import gzip
import hashlib
import json
import random
import time
from pathlib import Path

from nachero.sources import dataset
from nachero_collector import __version__
from nachero_collector import aggregate as A
from nachero_collector import items as I
from nachero_collector.riot import DIVISIONS, LEAGUES, PAGE

DAY = 86400
# Días de partidas que se piden a cada jugador. En Master+ (~11.000 jugadores en EUW) se recorre la
# lista en ~1 día: 3 días bastan. En Diamante+ y Esmeralda+ (~700.000, muchos inactivos) a cada
# jugador se le vuelve a mirar tras semanas y muchos juegan poco (medido en noviembre de 2026: ~0,7
# partidas en 3 días en Esmeralda, ~10 en los apex): con 3 días, buena parte de las peticiones de ids
# volverían vacías. Más de 7 días ya no compensa: las partidas extra son sobre todo del parche anterior.
LOOKBACK = {"master_plus": 3 * DAY, "diamond_plus": 7 * DAY, "emerald_plus": 7 * DAY}
SIZE_GUESS = 50  # páginas que se le suponen a una división hasta haberla recorrido entera


def keep_ids(league: str) -> float:
    """Cuánto se recuerda un id contado: uno contado hace más ya no sale en los ids que se piden."""
    return LOOKBACK[league] + DAY


def out_file(out_dir, patch: str, region: str, league: str) -> Path:
    return Path(out_dir) / patch / region / f"{league}.json.gz"


def load_doc(path: Path) -> dict | None:
    if not path.is_file():
        return None
    doc = dataset.load_file(path)
    return doc if not dataset.validate(doc) else None


def write_doc(path: Path, doc: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_bytes(gzip.compress(json.dumps(doc, separators=(",", ":")).encode("utf-8")))
    tmp.replace(path)


def load_state(path: Path) -> dict:
    try:
        st = json.loads(path.read_text(encoding="utf-8"))
        return st if isinstance(st, dict) else {}
    except (OSError, ValueError):
        return {}


def save_state(path: Path, state: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(state), encoding="utf-8")
    tmp.replace(path)


def iso(ts: float) -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(ts))


def sources_of(league: str) -> list[str]:
    """Fuentes de jugadores de una liga: "APEX" y "TIER/DIVISIÓN" (p. ej. "DIAMOND/II")."""
    return ["APEX"] + [f"{tier}/{div}" for tier in LEAGUES[league] for div in DIVISIONS]


def _progress(s: dict) -> float:
    """Vueltas dadas a una fuente, con decimales (0,5 = media fuente recorrida)."""
    page = s.get("page", 1)
    size = max(s.get("size") or SIZE_GUESS, page)
    return s.get("lap", 0) + (page - 1 + s.get("skip", 0) / PAGE) / size


def pick_players(riot, league: str, sources: dict, players: int) -> list[str]:
    """Los `players` jugadores de esta pasada (sus puuid, solo en memoria). Avanza `sources`, el estado
    de la rotación de la liga: {fuente: {"page", "skip", "lap", "size"}}."""
    names = sources_of(league)
    for n in names:
        sources[n] = dict(sources.get(n) or {})
    apex: list[str] | None = None
    pages: dict[tuple[str, int], list[str]] = {}
    wraps = dict.fromkeys(names, 0)
    out: dict[str, None] = {}

    def page_of(name: str, page: int) -> list[str]:
        nonlocal apex
        if (name, page) not in pages:
            if name == "APEX":
                if apex is None:
                    apex = sorted(riot.apex_puuids())
                    sources[name]["size"] = max(1, -(-len(apex) // PAGE))
                pages[(name, page)] = apex[(page - 1) * PAGE : page * PAGE]
            else:
                tier, div = name.split("/")
                pages[(name, page)] = riot.entries_puuids(tier, div, page)
        return pages[(name, page)]

    while len(out) < players:
        live = [n for n in names if wraps[n] < 2]  # una fuente que ya ha dado dos vueltas no da más
        if not live:
            break
        name = min(live, key=lambda n: _progress(sources[n]))
        s = sources[name]
        page, skip = s.get("page", 1), s.get("skip", 0)
        entries = page_of(name, page)
        if not entries:  # pasada la última página: se sabe su tamaño y vuelve a empezar
            s.update(page=1, skip=0, lap=s.get("lap", 0) + 1, size=max(1, page - 1))
            wraps[name] += 1
            continue
        take = entries[skip : skip + players - len(out)]
        out.update(dict.fromkeys(take))
        skip += len(take)
        if skip >= len(entries):
            page, skip = page + 1, 0
        s.update(page=page, skip=skip)
    return list(out)


def league_state(state: dict, league: str) -> dict:
    """Estado de una liga: {"sources": rotación, "seen": ids contados}. El estado antiguo (solo
    Master+, con "cursor" en la lista de apex) se pasa a este formato sin perder nada."""
    leagues = state.setdefault("leagues", {})
    if "seen" in state or "cursor" in state:
        cursor = state.pop("cursor", 0)
        leagues.setdefault(
            "master_plus",
            {"seen": state.pop("seen", {}), "sources": {"APEX": {"page": cursor // PAGE + 1, "skip": cursor % PAGE}}},
        )
    return leagues.setdefault(league, {})


def collect(riot, out_dir, state_path, region="euw1", league="master_plus", players=500, matches=2000,
            now=time.time, log=print, items=None, timeline=False) -> dict:  # fmt: skip
    """Una pasada. Devuelve un resumen: jugadores mirados, partidas nuevas, contadas y parches.
    `items(patch, carpeta)`: objetos completos y botas del parche (Data Dragon, en caché junto al
    estado); si no se puede leer, esa pasada no cuenta objetos (#90). Con `timeline`, pide también
    los eventos de cada partida (una petición más): orden de habilidades, objetos iniciales y núcleo."""
    if league not in LEAGUES:
        raise ValueError(f"liga {league!r} desconocida: {', '.join(LEAGUES)}")
    items = items or I.catalog
    state_path = Path(state_path)
    state = load_state(state_path)
    st = league_state(state, league)
    t0 = now()
    seen: dict[str, float] = {k: v for k, v in st.get("seen", {}).items() if t0 - v < keep_ids(league)}

    sources = st.setdefault("sources", {})
    r0 = riot.requests
    batch = pick_players(riot, league, sources, players)
    listing = riot.requests - r0  # peticiones de las listas de jugadores
    # en orden aleatorio, y sin pedir más ids cuando ya hay `matches` partidas nuevas: los que se
    # quedan sin mirar no sesgan la muestra (cuentan como recorridos y no gastan peticiones)
    random.Random(t0).shuffle(batch)
    ids: list[str] = []
    new: dict[str, None] = {}
    asked = 0
    for puuid in batch:
        if len(new) >= matches:
            break
        got = riot.match_ids(puuid, 420, start_time=t0 - LOOKBACK[league])
        asked += 1
        ids += got
        new.update((m, None) for m in got if m not in seen)
    new_ids = list(new)[:matches]
    log(f"{league}: {asked} jugadores · {len(ids)} ids · {len(new_ids)} partidas nuevas")

    docs: dict[str, dict] = {}
    catalogs: dict[str, dict | None] = {}
    counted = 0
    for mid in new_ids:
        m = riot.match(mid)
        seen[mid] = t0
        if not m or not A.usable(m):
            continue
        patch = A.patch_of(m["info"]["gameVersion"])
        if patch not in docs:
            docs[patch] = load_doc(out_file(out_dir, patch, region, league)) or A.new_doc(
                patch, region, league, f"nachero-collector {__version__}"
            )
        if patch not in catalogs:
            catalogs[patch] = items(patch, state_path.parent)
            if catalogs[patch] is None:
                log(f"Sin catálogo de objetos de {patch} (Data Dragon): esta pasada no cuenta builds")
        tl = riot.timeline(mid) if timeline else None
        A.add_match(docs[patch], m, catalogs[patch], tl if isinstance(tl, dict) else None)
        end = m["info"].get("gameEndTimestamp") or m["info"].get("gameCreation") or 0
        docs[patch]["cutoff"] = max(docs[patch].get("cutoff") or "", iso(end / 1000)) if end else docs[patch]["cutoff"]
        counted += 1  # la partida en bruto no se guarda: solo los conteos

    for patch, doc in docs.items():
        A.trim_runes(doc)
        doc["generated"] = iso(now())
        doc["cutoff"] = doc.get("cutoff") or doc["generated"]
        doc["collector"] = f"nachero-collector {__version__}"
        errors = dataset.validate(doc)
        if errors:
            raise ValueError(f"el archivo de {patch} no cumple el esquema: {errors[:3]}")
        write_doc(out_file(out_dir, patch, region, league), doc)
    st["seen"] = seen
    state["last_run"] = t0
    save_state(state_path, state)
    summary = {"league": league, "players": asked, "ids": len(ids), "new": len(new_ids), "counted": counted,
               "patches": sorted(docs), "requests": riot.requests, "listing": listing}  # fmt: skip
    log(f"Contadas {counted} partidas · parches {', '.join(sorted(docs)) or '—'} · {riot.requests} peticiones")
    return summary


def publish_index(out_dir, now=time.time) -> dict:
    """Escribe `index.json` con los archivos publicados (lo que lee la app, ver
    sources/remote_stats.py). Devuelve el manifiesto."""
    root = Path(out_dir)
    files = []
    for f in sorted(root.glob("*/*/*.json.gz")):
        doc = dataset.load_file(f)
        if dataset.validate(doc):
            continue
        files.append(
            {
                "patch": doc["patch"],
                "region": doc["region"],
                "league": doc["league"],
                "path": f.relative_to(root).as_posix(),
                "games": doc["totals"]["games"],
                "generated": doc["generated"],
                "sha256": hashlib.sha256(f.read_bytes()).hexdigest(),
            }
        )
    index = {"schema": dataset.SCHEMA, "generated": iso(now()), "files": files}
    (root / "index.json").write_text(json.dumps(index, indent=1), encoding="utf-8")
    return index
