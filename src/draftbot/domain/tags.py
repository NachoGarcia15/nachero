"""Papel de cada campeon en una composicion (conocimiento de draft, no estadistica).

Letras:
  E engage      inicia peleas de forma fiable
  D dive        se mete en la backline
  F followup    remata/encadena tras un engage (AoE, control)
  P poke        dano a distancia / asedio, "outrange"
  K peel        protege, desengancha, anti-dive
  Z zona        controla zonas en peleas (AoE persistente)
  C pick        atrapa objetivos sueltos
  S split       presion en banda 1v1
  L scaling     mejora mucho a partida larga
  T frontline   aguanta dano delante

Campeones que no esten en la tabla reciben etiquetas aproximadas a partir de los datos del cliente.
"""

CHAMP_TAGS = {
    "Aatrox": "TD",
    "Ahri": "CD",
    "Akali": "DS",
    "Akshan": "SC",
    "Alistar": "EKT",
    "Ambessa": "DT",
    "Amumu": "EFT",
    "Anivia": "ZPL",
    "Annie": "EF",
    "Aphelios": "LF",
    "Ashe": "ECP",
    "Aurelion Sol": "LZP",
    "Aurora": "DC",
    "Azir": "ZPL",
    "Bard": "CK",
    "Bel'Veth": "DLS",
    "Blitzcrank": "CE",
    "Brand": "FZP",
    "Braum": "KT",
    "Briar": "DE",
    "Caitlyn": "PZ",
    "Camille": "DSC",
    "Cassiopeia": "ZL",
    "Cho'Gath": "TF",
    "Corki": "PL",
    "Darius": "TD",
    "Diana": "EDF",
    "Dr. Mundo": "TL",
    "Draven": "",
    "Ekko": "DC",
    "Elise": "DC",
    "Evelynn": "DC",
    "Ezreal": "PL",
    "Fiddlesticks": "EF",
    "Fiora": "SL",
    "Fizz": "DC",
    "Galio": "EFTK",
    "Gangplank": "ZPL",
    "Garen": "T",
    "Gnar": "ETF",
    "Gragas": "EKT",
    "Graves": "",
    "Gwen": "DS",
    "Hecarim": "ED",
    "Heimerdinger": "ZP",
    "Hwei": "PZF",
    "Illaoi": "ZTS",
    "Irelia": "DS",
    "Ivern": "K",
    "Janna": "K",
    "Jarvan IV": "EDF",
    "Jax": "DSL",
    "Jayce": "P",
    "Jhin": "PC",
    "Jinx": "LF",
    "K'Sante": "TEK",
    "Kai'Sa": "DL",
    "Kalista": "E",
    "Karma": "PK",
    "Karthus": "ZL",
    "Kassadin": "DL",
    "Katarina": "DF",
    "Kayle": "L",
    "Kayn": "D",
    "Kennen": "EF",
    "Kha'Zix": "DC",
    "Kindred": "L",
    "Kled": "ED",
    "Kog'Maw": "L",
    "LeBlanc": "CD",
    "Lee Sin": "DCE",
    "Leona": "ET",
    "Lillia": "FZ",
    "Lissandra": "EFK",
    "Lucian": "",
    "Lulu": "K",
    "Lux": "PC",
    "Malphite": "EFT",
    "Malzahar": "C",
    "Maokai": "ETKZ",
    "Master Yi": "LD",
    "Mel": "PK",
    "Milio": "K",
    "Miss Fortune": "FZ",
    "Mordekaiser": "TC",
    "Morgana": "KC",
    "Naafiri": "DC",
    "Nami": "KF",
    "Nasus": "SLT",
    "Nautilus": "ECT",
    "Neeko": "EF",
    "Nidalee": "PC",
    "Nilah": "F",
    "Nocturne": "EDC",
    "Nunu & Willump": "EFT",
    "Olaf": "DT",
    "Orianna": "FZK",
    "Ornn": "ETF",
    "Pantheon": "EDC",
    "Poppy": "KET",
    "Pyke": "CE",
    "Qiyana": "EDF",
    "Quinn": "SC",
    "Rakan": "EF",
    "Rammus": "ET",
    "Rek'Sai": "ED",
    "Rell": "ETF",
    "Renata Glasc": "KZ",
    "Renekton": "DT",
    "Rengar": "DC",
    "Riven": "DS",
    "Rumble": "ZF",
    "Ryze": "L",
    "Samira": "FD",
    "Sejuani": "ETF",
    "Senna": "PKL",
    "Seraphine": "ZPFK",
    "Sett": "ETD",
    "Shaco": "CS",
    "Shen": "KETS",
    "Shyvana": "DT",
    "Singed": "ST",
    "Sion": "ETS",
    "Sivir": "E",
    "Skarner": "ECT",
    "Smolder": "LP",
    "Sona": "KFZ",
    "Soraka": "K",
    "Swain": "ZTK",
    "Sylas": "DF",
    "Syndra": "PCZ",
    "Tahm Kench": "KT",
    "Taliyah": "ZPC",
    "Talon": "DC",
    "Taric": "KF",
    "Teemo": "ZPS",
    "Thresh": "CKE",
    "Tristana": "DL",
    "Trundle": "ST",
    "Tryndamere": "SL",
    "Twisted Fate": "CS",
    "Twitch": "LF",
    "Udyr": "TD",
    "Urgot": "TZ",
    "Varus": "PC",
    "Vayne": "LS",
    "Veigar": "ZCL",
    "Vel'Koz": "PZ",
    "Vex": "EFK",
    "Vi": "EDC",
    "Viego": "DL",
    "Viktor": "ZPL",
    "Vladimir": "LF",
    "Volibear": "EDT",
    "Warwick": "DC",
    "Wukong": "EFD",
    "Xayah": "L",
    "Xerath": "P",
    "Xin Zhao": "DE",
    "Yasuo": "FD",
    "Yone": "FD",
    "Yorick": "S",
    "Yuumi": "K",
    "Zac": "ETF",
    "Zed": "DCS",
    "Zeri": "L",
    "Ziggs": "PZ",
    "Zilean": "K",
    "Zoe": "PC",
    "Zyra": "ZFP",
    "Yunara": "L",
}

IDENTITY_ES = {
    "engage": "Engage / dive",
    "range": "Outrange / poke",
    "protect": "Proteger al carry",
    "": "Sin identidad clara",
}


def tags(champs, cid):
    """Conjunto de letras para un campeon (tabla curada o aproximacion)."""
    name = champs.name(cid)
    if name in CHAMP_TAGS:
        return set(CHAMP_TAGS[name])
    i = champs.info(cid)
    roles, out = set(i.get("roles", [])), set()
    if "tank" in roles:
        out |= {"T"} | ({"E"} if i["cc"] >= 2 else set())
    if "fighter" in roles:
        out |= {"D"} if i["mobility"] >= 2 else {"T"}
    if "assassin" in roles:
        out |= {"D", "C"}
    if "mage" in roles:
        out |= {"Z"} | ({"P"} if i["mobility"] <= 1 else {"C"})
    if "marksman" in roles:
        out |= {"L"}
    if "support" in roles and i["utility"] >= 2:
        out |= {"K"}
    return out


def identity(members, champs):
    """members: [(cid, peso)]. Devuelve (identidad, puntuaciones, conteos de letras)."""
    cnt = {k: 0.0 for k in "EDFPKZCSLT"}
    for cid, w in members:
        if cid and w > 0:
            for t in tags(champs, cid):
                cnt[t] += w
    sc = {
        "engage": cnt["E"] + 0.6 * cnt["D"] + 0.4 * cnt["F"],
        "range": cnt["P"] + 0.5 * cnt["Z"],
        "protect": cnt["K"] + 0.4 * cnt["L"],
    }
    best = max(sc, key=sc.get)
    return (best if sc[best] >= 1.2 else ""), sc, cnt


def cohesion(cid, allies, champs):
    """Encaje por condicion de victoria (concepto del draft competitivo). Devuelve (pp, motivos)."""
    t = tags(champs, cid)
    w = sum(x for c, x in allies if c)
    if w < 1.5:
        return 0.0, []
    ident, sc, cnt = identity(allies, champs)
    known = min(1.0, w / 4)
    b, why = 0.0, []
    if cnt["E"] < 0.5 and "E" in t:
        b += 0.9 * known
        why.append(("+", "tu equipo no tiene engage: este lo da"))
    if ident == "engage":
        if t & {"E", "D", "F"}:
            b += 0.4 * known
            why.append(("+", "encaja con la comp de engage/dive"))
        elif "P" in t and not t & {"E", "F"}:
            b -= 0.3
            why.append(("-", "poke en una comp de engage"))
    elif ident == "range":
        if t & {"P", "Z"}:
            b += 0.4 * known
            why.append(("+", "encaja con la comp de outrange"))
        elif "D" in t and "E" not in t:
            b -= 0.2
            why.append(("-", "dive suelto en una comp de rango"))
    elif ident == "protect" and t & {"L", "K"}:
        b += 0.3 * known
        why.append(("+", "encaja con proteger al carry"))
    if cnt["E"] >= 1 and "F" in t:
        b += 0.3 * known
        why.append(("+", "remata el engage de tus aliados"))
    return b, why


def counter_comp(cid, enemies, champs):
    """Responder a la composicion rival (p. ej. anti-dive contra dive). Pesos pequenos:
    nunca debe compensar perder la linea (ejemplo de Gangplank en el video)."""
    if len([e for e in enemies if e]) < 3:
        return 0.0, []
    t = tags(champs, cid)
    ident, sc, cnt = identity([(e, 1.0) for e in enemies], champs)
    b, why = 0.0, []
    if ident == "engage" and ("K" in t or {"Z", "T"} <= t):
        b += 0.6
        why.append(("+", "anti-dive contra su comp de engage"))
    elif ident == "range" and t & {"E", "D"}:
        b += 0.5
        why.append(("+", "engage para castigar su poke"))
    elif ident == "protect" and t & {"P", "Z"}:
        b += 0.4
        why.append(("+", "poke y zona contra una comp de proteger"))
    if cnt["E"] < 0.5 and "P" in t:
        b += 0.3
        why.append(("+", "el rival no tiene engage para castigar tu poke"))
    return b, why
