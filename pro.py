"""Simulador de drafts competitivos.

Datos: gol.gg (estadisticas de campeones por torneo: prioridad, picks, bans, WR y reparto por rol).
Su robots.txt permite /champion/; draftbot pide pocas paginas, con cache de 12 h.

Conceptos aplicados (draft profesional):
  - Prioridad: campeones fuertes y seguros a ciegas (PrioScore de gol.gg).
  - Flex: un campeon que va a varios roles esconde informacion en la primera rotacion.
  - Composicion cohesionada con condicion de victoria (engage/dive, outrange, proteger) y siempre algo de engage.
  - Matchups favorables (datos Master+ de Lolalytics como aproximacion; en pro las muestras son pequenas).
  - Counter a la composicion rival en los ultimos picks, sin sacrificar la linea.
  - Denegar: quitar al rival un pick que le encaja.
  - Bans: no banear lo que vas a coger; en la segunda ronda, banear los roles que le faltan al rival
    y los counters de tus picks.
"""
import html, http.cookiejar, itertools, json, math, os, re, threading, time, urllib.parse, urllib.request

import tags as T

ROLES = ["top", "jungle", "middle", "bottom", "utility"]
GOL_ROLE = {"top": "TOP", "jungle": "JUNGLE", "middle": "MID", "bottom": "ADC", "utility": "SUPPORT"}
ROLE_SHORT = {"top": "TOP", "jungle": "JG", "middle": "MID", "bottom": "ADC", "utility": "SUP"}
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) draftbot/2.0 (uso personal)"
MAJOR = re.compile(r"Worlds|MSI|First Stand|LCK 20|LPL 20|LEC 20|LCS 20|LTA 20|LCP 20|EWC|Esports World Cup", re.I)

# Orden de draft de torneo: 6 bans, 6 picks, 4 bans, 4 picks
DRAFT_ORDER = [("blue", "ban"), ("red", "ban"), ("blue", "ban"), ("red", "ban"), ("blue", "ban"), ("red", "ban"),
               ("blue", "pick"), ("red", "pick"), ("red", "pick"), ("blue", "pick"), ("blue", "pick"), ("red", "pick"),
               ("red", "ban"), ("blue", "ban"), ("red", "ban"), ("blue", "ban"),
               ("red", "pick"), ("blue", "pick"), ("blue", "pick"), ("red", "pick")]


def norm(name):
    return re.sub(r"[^a-z0-9]", "", name.lower())


class GolGG:
    TTL = 12 * 3600

    def __init__(self, cache_dir, log):
        self.path = os.path.join(cache_dir, "gol_cache.json")
        self.log, self.lock, self.last = log, threading.Lock(), 0.0
        try:
            self.cache = json.load(open(self.path, encoding="utf-8"))
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
        tmp = self.path + ".tmp"
        json.dump(self.cache, open(tmp, "w", encoding="utf-8"))
        os.replace(tmp, self.path)

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
            names = [html.unescape(v) for _, v in re.findall(r"<option[^>]*value=(['\"])(.*?)\1", sel.group(1))] if sel else []
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
            url = (f"https://gol.gg/champion/list/season-{season}/split-ALL/tournament-"
                   f"{urllib.parse.quote(tournament)}/")
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


def parse_gol(h):
    out = {}
    for tr in re.findall(r"<tr>(.*?)</tr>", h, re.S):
        if "champion-stats/" not in tr:
            continue
        tds = [html.unescape(re.sub(r"<[^>]+>", "", x)).strip() for x in re.findall(r"<td[^>]*>(.*?)</td>", tr, re.S)]
        if len(tds) < 11:
            continue
        num = lambda s: float(s.replace("%", "")) if re.fullmatch(r"-?[\d.]+%?", s or "") else 0.0
        out[norm(tds[0])] = {"name": tds[0], "picks": int(num(tds[1])), "bans": int(num(tds[2])), "prio": num(tds[3]),
                             "wins": int(num(tds[4])), "losses": int(num(tds[5])), "wr": num(tds[6]),
                             "avg_bt": num(tds[8]), "avg_rp": num(tds[9]), "bp": num(tds[10])}
    return out


# ---------------------------------------------------------------- motor
class ProEngine:
    def __init__(self, champs, lola, engine, gol):
        self.champs, self.lola, self.engine, self.gol = champs, lola, engine, gol

    # -- datos por campeon
    def pro(self, ds, cid):
        return ds["all"].get(norm(self.champs.name(cid))) if ds else None

    def role_share(self, ds, cid, role):
        """Fraccion de partidas pro del campeon en ese rol; si no hay datos pro, % de Master+."""
        key = norm(self.champs.name(cid))
        if ds:
            tot = sum(ds["roles"][r].get(key, 0) for r in ROLES)
            if tot >= 2:
                return ds["roles"][role].get(key, 0) / tot
        t = self.lola.tier(role)
        c = (t or {}).get("champs", {}).get(str(cid))
        return (c["pct"] / 100) if c and c["games"] >= 1500 else 0.0

    def assign(self, ds, picks):
        """Roles mas probables de un equipo (maximiza el producto de reparto por rol)."""
        ids = [c for c in picks if c][:5]
        if not ids:
            return {}
        best, bs = None, -1e9
        for perm in itertools.permutations(ROLES, len(ids)):
            sc = sum(math.log(self.role_share(ds, c, r) + 0.02) for c, r in zip(ids, perm))
            if sc > bs:
                best, bs = perm, sc
        return dict(zip(ids, best))

    def priority(self, ds, cid):
        p = self.pro(ds, cid)
        if not p:
            meta = max((self.engine.meta(cid, r)[0] for r in ROLES), default=0.0)
            return 0.4 * max(-2.0, meta), None
        games = p["wins"] + p["losses"]
        wr_part = (p["wins"] - games * 0.5) / (games + 20) * 100 * 0.15
        return 4.0 * p["prio"] / 100 + wr_part, p

    # -- estado del draft
    def state(self, st):
        side_lists = {s: {"bans": [c for c in st.get(s, {}).get("bans", []) if c],
                          "picks": [c for c in st.get(s, {}).get("picks", []) if c]} for s in ("blue", "red")}
        counts = {("blue", "ban"): 0, ("red", "ban"): 0, ("blue", "pick"): 0, ("red", "pick"): 0}
        step = 0
        for side, kind in DRAFT_ORDER:
            have = len(side_lists[side]["bans" if kind == "ban" else "picks"])
            if counts[(side, kind)] < have:
                counts[(side, kind)] += 1
                step += 1
            else:
                break
        return side_lists, step

    def suggest(self, st):
        tour = st.get("tournament")
        ds = self.gol.dataset(tour) if tour else None
        teams, step = self.state(st)
        fearless = set(c for c in st.get("fearless", []) if c)
        used = fearless | {c for s in teams.values() for k in ("bans", "picks") for c in s[k]}
        roles = {s: self.assign(ds, teams[s]["picks"]) for s in teams}
        open_roles = {s: [r for r in ROLES if r not in roles[s].values()] for s in teams}
        done = step >= len(DRAFT_ORDER)
        side, kind = DRAFT_ORDER[step] if not done else (None, None)
        res = {"step": step, "side": side, "kind": kind, "done": done, "roles": roles,
               "open_roles": open_roles, "teams": {}, "data": self.data_info(ds, tour)}
        for s in ("blue", "red"):
            other = "red" if s == "blue" else "blue"
            res["teams"][s] = self.team_summary(teams[s]["picks"], teams[other]["picks"], roles[s], roles[other])
        if done:
            res["verdict"] = self.verdict(res["teams"])
            return res
        other = "red" if side == "blue" else "blue"
        cands = self.candidates(ds, used)
        if kind == "pick":
            res["suggestions"] = self.picks(ds, cands, side, other, teams, roles, open_roles, step)[:8]
        else:
            res["suggestions"] = self.bans(ds, cands, side, other, teams, roles, open_roles, step)[:8]
        return res

    def data_info(self, ds, tour):
        if not ds:
            return {"tournament": tour, "loaded": False, "loading": tour in self.gol.loading}
        return {"tournament": tour, "loaded": True, "games": ds["games"], "updated": ds["t"]}

    def candidates(self, ds, used):
        ids = set()
        if ds:
            for key, p in ds["all"].items():
                if p["picks"] + p["bans"] > 0:
                    cid = self.champs.by_name.get(p["name"].lower()) or self._by_norm(key)
                    if cid:
                        ids.add(cid)
        for r in ROLES:
            t = self.lola.tier(r)
            if t:
                ranked = sorted(t["champs"].items(), key=lambda kv: -kv[1]["pr"])[:12]
                ids |= {int(c) for c, v in ranked if v["games"] >= 3000}
        return [c for c in ids if c not in used and c in self.champs.by_id]

    def _by_norm(self, key):
        if not hasattr(self, "_norm_map"):
            self._norm_map = {norm(c["name"]): cid for cid, c in self.champs.by_id.items()}
            self._norm_map.update({"nunu": self.champs.id("Nunu & Willump"), "wukong": self.champs.id("Wukong"),
                                   "renata": self.champs.id("Renata Glasc")})
        return self._norm_map.get(key)

    def _feasible(self, ds, cid, open_r, thr=0.12):
        return [(r, self.role_share(ds, cid, r)) for r in open_r if self.role_share(ds, cid, r) >= thr]

    def enemy_left_in_role(self, step, other):
        """Picks que le quedan al rival despues de este paso."""
        return sum(1 for s, k in DRAFT_ORDER[step + 1:] if s == other and k == "pick")

    # -- picks
    def picks(self, ds, cands, side, other, teams, roles, open_roles, step):
        mine, theirs = teams[side]["picks"], teams[other]["picks"]
        enemy_roles = {c: r for c, r in roles[other].items()}
        first_rotation = step < 12
        left_after = self.enemy_left_in_role(step, other)
        out = []
        for cid in cands:
            feas = self._feasible(ds, cid, open_roles[side])
            if not feas:
                continue
            role, share = max(feas, key=lambda x: x[1])
            prio, p = self.priority(ds, cid)
            parts = {"prio": prio}
            why = []
            if p and p["prio"] >= 50:
                why.append(("+", f"prioridad alta ({p['prio']:.0f}%)"))
            nflex = len(self._feasible(ds, cid, ROLES, 0.15))
            parts["flex"] = 0.6 if (first_rotation and nflex >= 2 and len(open_roles[side]) >= 3) else 0.0
            if parts["flex"]:
                why.append(("+", "flex: esconde a qué rol va"))
            fit, fit_why = self.engine.ally_fit(cid, [(c, 1.0) for c in mine])
            parts["comp"] = fit
            why += fit_why
            vc, vc_why = self.engine.vs_comp(cid, theirs)   # incluye el counter a la composicion rival
            parts["counter"] = vc
            why += vc_why
            lane_v, rest_v, items, loaded = self.engine.vs_enemy(cid, role, enemy_roles)
            parts["matchup"] = 0.6 * lane_v + 0.4 * rest_v      # Master+ como aproximacion
            opp_known = role in enemy_roles.values()
            risk, risk_items = (0.0, [])
            if not opp_known and left_after > 0:
                risk, risk_items = self.engine.counter_risk(cid, role, False, left_after)
                risk *= 0.8
            parts["risk"] = risk
            deny = 0.0
            if any(self.role_share(ds, cid, r) >= 0.15 for r in open_roles[other]) and p:
                deny = 0.3 * 4.0 * p["prio"] / 100
            parts["deny"] = deny if step < 12 else deny * 0.5
            if parts["deny"] >= 0.5:
                why.append(("+", "se lo quitas al rival"))
            if not loaded:
                self.lola.request(cid, role, self.champs.slug(cid))
            total = sum(parts.values())
            out.append({"id": cid, "name": self.champs.name(cid), "role": role, "role_short": ROLE_SHORT[role],
                        "score": round(total, 2), "parts": {k: round(v, 2) for k, v in parts.items()},
                        "why": [{"sign": a, "text": b} for a, b in why][:5],
                        "matchups": items[:3], "risk_items": risk_items, "pro": p, "loaded": loaded,
                        "tags": "".join(sorted(T.tags(self.champs, cid)))})
        out.sort(key=lambda x: -x["score"])
        return out

    # -- bans
    def bans(self, ds, cands, side, other, teams, roles, open_roles, step):
        mine, theirs = teams[side]["picks"], teams[other]["picks"]
        second_phase = step >= 12
        # no banear lo que vas a coger tu antes de que elija el rival
        next_pick = next(((s, i) for i, (s, k) in enumerate(DRAFT_ORDER[step:]) if k == "pick"), (None, 0))
        my_plan = set()
        if next_pick[0] == side:
            my_top = self.picks(ds, cands, side, other, teams, roles, open_roles, step)[:2]
            my_plan = {p["id"] for p in my_top}
        my_roles = roles[side]
        out = []
        for cid in cands:
            if cid in my_plan:
                continue
            feas = self._feasible(ds, cid, open_roles[other])
            if not feas:
                continue
            role, share = max(feas, key=lambda x: x[1])
            prio, p = self.priority(ds, cid)
            parts, why = {"prio": prio * (0.7 if second_phase else 1.0)}, []
            if p and p["prio"] >= 50:
                why.append(("+", f"prioridad alta ({p['prio']:.0f}%)"))
            fit, _ = self.engine.ally_fit(cid, [(c, 1.0) for c in theirs])
            parts["their_comp"] = 0.6 * fit
            if fit >= 0.8:
                why.append(("+", "encaja en la comp rival"))
            # cuanto counterea a tus picks (desde las paginas de tus campeones)
            counter = 0.0
            for my_c, my_r in my_roles.items():
                rows = (self.lola.matchups(my_c, my_r) or {}).get(role, {})
                row = rows.get(str(cid))
                if row and row["d2"] < 0:
                    wgt = 1.0 if my_r == role else 0.4
                    counter += -row["d2"] * row["n"] / (row["n"] + 250) * wgt
                    if row["d2"] <= -2:
                        why.append(("+", f"counterea a tu {self.champs.name(my_c)} ({row['d2']:+.1f})"))
            parts["counter"] = 0.5 * counter
            if second_phase and role in open_roles[other]:
                parts["role_need"] = 0.4
                why.append(("+", f"al rival le falta {ROLE_SHORT[role]}"))
            total = sum(parts.values())
            out.append({"id": cid, "name": self.champs.name(cid), "role": role, "role_short": ROLE_SHORT[role],
                        "score": round(total, 2), "parts": {k: round(v, 2) for k, v in parts.items()},
                        "why": [{"sign": a, "text": b} for a, b in why][:4], "pro": p})
        out.sort(key=lambda x: -x["score"])
        return out

    # -- resumen de equipos
    def team_summary(self, picks, enemy_picks, roles, enemy_roles):
        ident, sc, cnt = T.identity([(c, 1.0) for c in picks], self.champs)
        notes = []
        if len(picks) >= 3 and cnt["E"] < 0.5:
            notes.append("Sin engage: le costará forzar peleas.")
        if len(picks) >= 4 and cnt["T"] < 0.5:
            notes.append("Sin frontline.")
        prof = {"AP": 0.0, "AD": 0.0}
        for c in picks:
            i = self.champs.info(c)
            if i["dmg"] in prof:
                prof[i["dmg"]] += i["damage"]
        tot = prof["AP"] + prof["AD"]
        if len(picks) >= 4 and tot and min(prof.values()) / tot < 0.2:
            notes.append("Daño casi todo " + ("físico." if prof["AD"] > prof["AP"] else "mágico."))
        if ident == "" and len(picks) >= 4:
            notes.append("Sin condición de victoria clara.")
        lanes = []
        for c, r in roles.items():
            opp = next((e for e, er in enemy_roles.items() if er == r), None)
            if opp:
                row = ((self.lola.matchups(c, r) or {}).get(r, {})).get(str(opp))
                lanes.append({"role": ROLE_SHORT[r], "me": self.champs.name(c), "vs": self.champs.name(opp),
                              "d2": round(row["d2"], 1) if row else None})
        return {"identity": ident, "identity_es": T.IDENTITY_ES[ident], "scores": {k: round(v, 1) for k, v in sc.items()},
                "notes": notes, "lanes": lanes,
                "picks": [{"id": c, "name": self.champs.name(c), "role": roles.get(c, ""),
                           "role_short": ROLE_SHORT.get(roles.get(c, ""), "")} for c in picks]}

    def verdict(self, teams):
        def score(t):
            s = {"engage": 1.0, "range": 1.0, "protect": 0.8, "": 0.0}[t["identity"]]
            s -= 0.6 * len(t["notes"])
            s += 0.15 * sum(l["d2"] for l in t["lanes"] if l["d2"] is not None)
            return s
        b, r = score(teams["blue"]), score(teams["red"])
        lean = "blue" if b - r > 0.3 else "red" if r - b > 0.3 else ""
        return {"blue": round(b, 2), "red": round(r, 2), "lean": lean}
