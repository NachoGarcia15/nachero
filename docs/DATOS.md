# Estrategia de datos

Nachero es de uso personal y con amigos, pero **se diseña para poder publicarse y monetizarse**.
Cada dato debe tener un camino válido para la versión pública (normas de Riot en
`docs/ROADMAP.md`).

Para el parche actual y la liga del jugador, Nachero necesita:
- WR, pick y ban rate por campeón y rol.
- Matchups por pareja de líneas y sinergias.
- Páginas de runas.

Para el simulador, además, los drafts de competitivo, partida a partida: orden de picks y bans,
roles, lado y ganador. Este documento recoge de dónde salen hoy, de dónde deben salir para una
versión pública y por qué.

## Qué usa hoy cada parte

| | Draft de soloq | Simulador pro |
|---|---|---|
| WR, pick rate y roles | Lolalytics | Lolalytics (roles) |
| Matchups y blindability | Lolalytics, páginas de build en Esmeralda+ (`build_tier`) | Lolalytics: datos de soloq como aproximación, porque en pro las muestras son muy pequeñas |
| Sinergias | Solo con datos propios (#77) | — |
| Runas | Lolalytics | — |
| Competitivo (prioridad, picks, bans, WR, roles) | — | gol.gg, hasta que lo sustituya Leaguepedia (#80) |

Los datos propios ya se pueden usar (`stats_mode` automático), pero solo si `stats_url` apunta a
los archivos publicados (#20). Sin eso, todo lo de soloq sale de Lolalytics. Con datos propios, la
liga es la misma `build_tier` (Esmeralda+ por defecto) para todo: fuerza, matchups, runas y
sinergias salen del archivo `<parche>/<región>/<liga>.json.gz` de esa liga (#86).

## Opciones

| Fuente | Datos | Para uso personal | Para versión pública |
|---|---|---|---|
| **Lolalytics** (lo actual) | Todo lo de soloq, por liga y parche | Sí: su `robots.txt` lo permite; caché y ~1,5 s entre peticiones | **No**: no tiene API pública y Riot pide usar sus servicios oficiales |
| u.gg, op.gg y similares | Parecido | No: sin API pública; condiciones antiguas o poco claras | No |
| **API de Riot** (`league-v4` + `match-v5`) | Partidas en bruto: hay que agregarlas | Sí, con **clave personal** | Sí, con **clave de producción** |
| Acuerdo con una web de estadísticas | Lo que acuerden | Innecesario | Posible, pero Riot prohíbe hacer de «data broker» entre su API y terceros |
| **gol.gg** (competitivo, lo actual) | Picks, bans y WR de torneos; drafts por partida en sus páginas de serie | Sí: `/champion/`, `/tournament/` y `/game/stats/` permitidos | No (lectura de su web) |
| **Leaguepedia** (API Cargo) | Competitivo completo: drafts por partida con orden, roles, lado, ganador y parche | Sí | Sí: licencia CC BY-SA con atribución |

### Sinergias de Lolalytics: no

Las pestañas «Synergy» de Lolalytics (Common Teammates, Synergy Delta, Normalised Synergy Delta…)
no vienen en el estado `qwik/json` de la página, donde `$$team` llega vacío. Se cargan al pulsar
desde su API interna (`a1.lolalytics.com/mega/?ep=build-team…`), que no se usa: sería una API no
pública. Tampoco se pide permiso para usarla:
- Riot pide servicios oficiales para obtener datos.
- Riot prohíbe hacer de intermediario de datos entre su API y terceros.
- Lolalytics sería competencia directa de un Nachero de pago.

Las mismas medidas se calculan con los datos propios (#85):
- Common Teammates = partidas juntos / partidas del campeón;
- WR del dúo;
- Normalised Synergy Delta = WR del dúo − `expected_duo`.

### Leaguepedia (comprobado con Worlds 2026 Main Event)

- Una consulta a `PicksAndBansS7` devuelve las 76 partidas con picks y bans en orden
  (`Team1Pick1…5`, `Team1Ban1…5`) y el rol de cada pick (`Team1Role1…5`). Por la web de gol.gg
  fueron 40 peticiones para 66 partidas.
- El `Team1` de `PicksAndBansS7` es el orden del enfrentamiento, **no el lado**. El lado sale de
  `ScoreboardGames` (`Team1` = azul, con `WinTeam` y `Patch`), cruzando por `GameId`.
- Licencia CC BY-SA: atribución visible («Datos de competitivo: Leaguepedia»). Los datos
  derivados que se publiquen, por ejemplo una tabla de combos, van con la misma licencia.

## Decisión

1. **Ahora (fase 1)**:
   - Soloq: seguir con Lolalytics, con caché y aviso de frescura (#8), detrás de una interfaz
     común (#17) para cambiarla sin tocar el motor.
   - Competitivo: pasar a Leaguepedia (#80, que hace también #22), porque el draft pro y los
     combos (#79) necesitan los drafts por partida y así no se hace el trabajo dos veces.
     gol.gg queda de respaldo en uso personal hasta entonces.
2. **Fase 2**: recolector propio con la API de Riot y **clave personal**, limitado a EUW.
   - Riot permite la clave personal para un proyecto propio o un grupo pequeño sin publicar la
     app.
   - Límite: 100 peticiones / 2 min, unas 72.000 al día.
   - Lee Master+, Diamante+ o Esmeralda+ (`--league`, #86). En Master+ y un solo parche, la
     mediana es de 5–50 partidas por matchup: para matchups y sinergias hace falta Esmeralda+.
     Medido en EUW (`docs/RECOLECTOR.md`): ~46.000 partidas al día, ~480.000 por parche, con una
     mediana de ~260 partidas por matchup y ~60 % de parejas de sinergia con 200 o más. Lo que
     limita son las peticiones: Diamante+ da el mismo volumen que Esmeralda+.
   - Se publican archivos agregados por parche, región y liga (#18, #19, #20). Antes de cambiar
     la fuente por defecto se validan frente a Lolalytics (#21).
3. **Fase 3**: con el prototipo funcionando, pedir la **clave de producción** (#23). Empieza en
   500 peticiones / 10 s y 30.000 / 10 min por región, unos 4,3 millones al día.
   - Con eso: todas las partidas de Master+ y una muestra de cada liga inferior en todas las
     regiones.
   - La versión pública deja de leer Lolalytics y gol.gg (#24). Quedan solo la API de Riot y
     Leaguepedia.

## Claves de la API de Riot

Se gestionan en developer.riotgames.com (revisado el 22-nov-2026). Son gratuitas.

| Clave | Cómo | Límite (por región) | Uso |
|---|---|---|---|
| Desarrollo | Automática al entrar al portal; **caduca cada 24 h** | 20 / s y 100 / 2 min | Probar |
| Personal | **Register Product** → proyecto personal: descripción detallada, sin verificación (#7) | 20 / s y 100 / 2 min; no caduca | Tú y un grupo privado pequeño. Nunca uso público, ni en betas abiertas |
| Producción | **Register Product** → producto grande: prototipo funcionando y web completa (#23) | 500 / 10 s y 30.000 / 10 min | Cualquier uso público. Necesaria para monetizar |

La clave solo la usa el recolector (`RIOT_API_KEY`). Nunca va en la app, en el `.exe` ni en el
repositorio: la app descarga los datos ya agregados.

## Fuentes en la app

El motor solo habla con la interfaz `StatsProvider` (`domain/stats.py`). En los ajustes,
`stats_sources` dice qué fuentes usar y en qué orden: la primera manda (con su caché) y las demás
cubren lo que le falte (`ChainStats`). El panel dice de cuál salen los datos.

- `"lolalytics"`: la web de Lolalytics (por defecto).
- `"local"`: datos propios en `stats_file` (por defecto `stats/nachero-stats.json` en la carpeta
  de datos). Puede ser un archivo o una carpeta con la estructura publicada
  `<parche>/<región>/<liga>.json.gz` del **esquema 1** (`docs/FORMATO_DATOS.md`). También lee
  este formato ya calculado, el que usa el motor por dentro:

```json
{
  "format": "nachero-stats", "version": 1,
  "patch": "16.23", "region": "euw", "tier": "master_plus", "generated": 1763500000,
  "roles": {"jungle": {"avg": 50.4, "games": 12345,
            "champs": {"163": {"wr": 53.1, "games": 900, "pr": 4.2, "br": 1.0, "tier": 3, "rank": 12, "pct": 51.0}}}},
  "matchups": {"163:jungle": {"jungle": {"64": {"wr": 51.0, "d1": 1.2, "d2": 0.8, "pr": 9.0, "n": 300}}}},
  "runes": {"163:jungle": {"pick": {"pri": [8112, 8139, 8140, 8105], "sec": [8347, 8304], "mod": [5008, 5008, 5007]}}}
}
```

- `"remote"`: los **datos propios publicados** (#20). La app lee `index.json` de `stats_url`, baja
  el archivo del parche actual y el del anterior (`ETag`, cada hora) a `cache/stats/` y los usa como
  `"local"`. Ver `docs/RECOLECTOR.md` para publicarlos.

En `"local"` y `"remote"`, la región es `stats_region` (`euw1`) y la liga, `build_tier`
(`emerald_plus` por defecto, como las páginas de build de Lolalytics). El antiguo `stats_league`
ya no se usa.

Lo normal es elegir la fuente con `stats_mode` (Ajustes → Datos): **automática** (propios si los
hay del parche y la liga; si no, Lolalytics, y el panel lo dice), **propia** o **Lolalytics**.
`stats_sources` solo hace falta para combinaciones a mano.

Toda fuente nueva pasa los tests de contrato de `tests/test_fuentes.py`.

## Reglas que no cambian
- Solo agregados: ningún identificador de jugador en los datos publicados. Las partidas en bruto
  se borran tras agregarse.
- La clave de la API nunca va en la app ni en el `.exe`: solo en el recolector.
- Datos «frescos»: el recolector corre cada hora y la app descarga los archivos nuevos al
  arrancar y cada hora (`ETag`).
- Pocos datos al principio de parche: mezclar con el parche anterior, con el mismo
  encogimiento que ya usa el motor.
- Respetar `Retry-After` en los 429 de Riot; cachés y ~1,5 s entre peticiones en el resto de
  fuentes.

## Fuentes
- [Políticas generales de Riot](https://developer.riotgames.com/policies/general) y
  [de League of Legends](https://developer.riotgames.com/docs/lol)
- [Tipos de clave y límites](https://developer.riotgames.com/docs/portal)
- [Límites de peticiones](https://developer.riotgames.com/rate-limiting.html)
- [API de Leaguepedia](https://lol.fandom.com/api.php) (`action=cargoquery`; licencia CC BY-SA)
