"""Una pasada del recolector: jugadores de Master+, partidas nuevas de soloq y conteos por parche.

Presupuesto de la clave personal: ~3000 peticiones por hora. Cada pasada mira un tramo de
jugadores (`players`, rotando entre pasadas) y como mucho `matches` partidas nuevas. El estado
(qué partidas ya se han contado y por dónde va la rotación) vive en un archivo privado del
recolector, nunca en los datos publicados.
"""

import gzip
import hashlib
import json
import time
from pathlib import Path

from nachero.sources import dataset
from nachero_collector import __version__
from nachero_collector import aggregate as A

LOOKBACK = 3 * 86400  # partidas de los últimos 3 días de cada jugador
KEEP_IDS = 30 * 86400  # ids contados que se recuerdan (más viejos ya no salen en el LOOKBACK)


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


def collect(riot, out_dir, state_path, region="euw1", league="master_plus", players=500, matches=2000,
            now=time.time, log=print) -> dict:  # fmt: skip
    """Una pasada. Devuelve un resumen: jugadores mirados, partidas nuevas, contadas y parches."""
    state_path = Path(state_path)
    state = load_state(state_path)
    seen: dict[str, float] = state.get("seen", {})
    t0 = now()
    seen = {k: v for k, v in seen.items() if t0 - v < KEEP_IDS}

    puuids = sorted(riot.apex_puuids())
    cursor = state.get("cursor", 0) % max(1, len(puuids))
    batch = (puuids[cursor:] + puuids[:cursor])[:players]
    ids: list[str] = []
    for puuid in batch:
        ids += riot.match_ids(puuid, 420, start_time=t0 - LOOKBACK)
    new = [m for m in dict.fromkeys(ids) if m not in seen][:matches]
    log(f"{len(batch)} jugadores · {len(new)} partidas nuevas")

    docs: dict[str, dict] = {}
    counted = 0
    for mid in new:
        m = riot.match(mid)
        seen[mid] = t0
        if not m or not A.usable(m):
            continue
        patch = A.patch_of(m["info"]["gameVersion"])
        if patch not in docs:
            docs[patch] = load_doc(out_file(out_dir, patch, region, league)) or A.new_doc(
                patch, region, league, f"nachero-collector {__version__}"
            )
        A.add_match(docs[patch], m)
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
    save_state(state_path, {"cursor": (cursor + len(batch)) % max(1, len(puuids)), "seen": seen, "last_run": t0})
    summary = {"players": len(batch), "new": len(new), "counted": counted, "patches": sorted(docs),
               "requests": riot.requests}  # fmt: skip
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
