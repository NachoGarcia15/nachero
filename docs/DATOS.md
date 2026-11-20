# Estrategia de datos

Nachero necesita, para el parche actual y la liga del jugador, estos datos:
- WR, pick y ban rate por campeón y rol.
- Matchups por pareja de líneas y sinergias.
- Páginas de runas.

Para el simulador, además, picks y bans de competitivo. Este documento recoge de dónde salen
hoy, de dónde deben salir para una versión pública y por qué.

## Opciones

| Fuente | Datos | Para uso personal | Para versión pública |
|---|---|---|---|
| **Lolalytics** (lo actual) | Todo lo de soloq, por liga y parche | Sí: su `robots.txt` lo permite; caché y ~1,5 s entre peticiones | **No**: no tiene API pública y Riot pide usar sus servicios oficiales |
| u.gg, op.gg y similares | Parecido | No: sin API pública; condiciones antiguas o poco claras | No |
| **API de Riot** (`league-v4` + `match-v5`) | Partidas en bruto: hay que agregarlas | Sí, con **clave personal** | Sí, con **clave de producción** |
| Acuerdo con una web de estadísticas | Lo que acuerden | Innecesario | Posible, pero Riot prohíbe hacer de «data broker» entre su API y terceros |
| **gol.gg** (competitivo, lo actual) | Picks, bans y WR de torneos | Sí: `/champion/` permitido | No (lectura de su web) |
| **Leaguepedia** (API Cargo) | Competitivo completo | Sí | Sí: licencia CC BY-SA con atribución |

## Decisión

1. **Ahora (fase 1)**: seguir con Lolalytics y gol.gg, con caché y aviso de frescura (#8).
   Antes, separar la fuente detrás de una interfaz común (#17) para poder cambiarla sin tocar
   el motor.
2. **Fase 2**: recolector propio con la API de Riot y **clave personal**, limitado a soloq
   EUW Master+, que es lo que usamos. Riot permite la clave personal para un proyecto propio o
   un grupo pequeño sin publicar la app.
   - Límite: 100 peticiones / 2 min, unas 72.000 al día. Basta para seguir las partidas de
     Master+ de una región.
   - Se publican archivos agregados por parche, región y liga (#18, #19, #20). Antes de cambiar
     la fuente por defecto se validan frente a Lolalytics (#21).
   - Competitivo desde Leaguepedia (#22).
3. **Fase 3**: con el prototipo funcionando, pedir la **clave de producción** (#23). Empieza en
   500 peticiones / 10 s y 30.000 / 10 min por región, unos 4,3 millones al día.
   - Con eso: todas las partidas de Master+ y una muestra de cada liga inferior en todas las
     regiones.
   - La versión pública deja de leer Lolalytics y gol.gg (#24).

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
