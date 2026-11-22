# Recolector de partidas (fase 2)

`src/nachero_collector/` genera los datos propios del esquema 1 (`docs/FORMATO_DATOS.md`) con la
API oficial de Riot: soloq EUW de **Master+, Diamante+ o Esmeralda+**, con la **clave personal**.
No va en la app ni en el `.exe` (el paquete de la app solo incluye `nachero`), y la clave nunca se
guarda en el repositorio: se lee de la variable de entorno `RIOT_API_KEY`.

> La issue #19 proponía un repositorio aparte (`draftbot-data`). El recolector solo depende del
> lector del esquema (`nachero.sources.dataset`), así que se puede mover tal cual cuando exista.

## Ligas (`--league`)

| Liga | Jugadores | Para qué |
|---|---|---|
| `master_plus` (por defecto) | Challenger, Grandmaster y Master (`league-v4 …leagues/by-queue`) | Fuerza en el parche en la élite; poca muestra por matchup |
| `diamond_plus` | Además Diamante I–IV (`league-v4 /entries/RANKED_SOLO_5x5/{tier}/{división}?page=`) | Término medio |
| `emerald_plus` | Además Esmeralda I–IV | **Volumen para matchups y sinergias** (#86): lo que usa la app por defecto (`build_tier`) |

Una partida cuenta en la liga de la muestra que la trajo: el archivo `<parche>/<región>/<liga>.json.gz`
lleva `league` = esa liga, como las páginas `tier=emerald_plus` de Lolalytics. Cada liga tiene su
propia muestra: una partida contada en Master+ cuenta también si la trae una pasada de Esmeralda+.

**Rotación.** Cada división es una fuente de jugadores que se lee por páginas de 205; los apex,
una más (su lista ordenada, en tramos de 205). Cada pasada coge jugadores de la fuente con menos
recorrido en fracción de su tamaño (`collect.pick_players`): así cada división aporta en proporción
a sus jugadores y la muestra se parece a la liga, en vez de sobrerrepresentar las divisiones altas.
El tamaño de una división se aprende al pasar su última página (la API devuelve una lista vacía);
hasta entonces se le suponen 50 páginas.

## Qué hace una pasada

1. `league-v4` (`euw1`): las páginas de jugadores que tocan según la rotación → sus `puuid` (solo
   en memoria). Los apex son 3 peticiones; cada página de una división, 1.
2. `match-v5` (routing `europe`): ids de soloq (`queue=420`) de los últimos 3 días de cada jugador
   (500 por pasada), sin repetir las ya contadas.
3. Detalle de cada partida nueva (como mucho 2000 por pasada). Fuera remakes, otras colas y
   partidas sin posición.
4. Suma campeón, rol, victoria, bans, runas, matchups y sinergias al archivo de su parche
   (`<salida>/<parche>/euw1/<liga>.json.gz`). **La partida en bruto se descarta** en cuanto se
   cuenta; los archivos publicados no llevan jugadores ni ids de partida.
5. Guarda su estado privado (`state/collector.json`, por liga: por dónde va la rotación de cada
   fuente y qué ids ya contó, 4 días, porque uno más viejo ya no sale en los 3 días de los ids) —
   no se publica. El estado de versiones anteriores (solo Master+) se convierte sin perder nada.

Límites de la clave personal: 20 peticiones/s y 100 cada 2 min (~3000 por hora). Con los valores
por defecto, una pasada ronda 2500 peticiones. En un 429 se espera lo que diga `Retry-After`; los
5xx se reintentan con espera creciente; un 401/403 (clave caducada) para con un mensaje claro.

## Presupuesto y volumen (clave personal)

PRESUPUESTO_AQUI

## Uso

```
export RIOT_API_KEY=RGAPI-…            # Windows: set RIOT_API_KEY=RGAPI-…
python -m nachero_collector recoger --out data --state state/collector.json
```

Opciones: `--region euw1`, `--league master_plus|diamond_plus|emerald_plus`, `--players 500`,
`--matches 2000`. Para la app por defecto: `--league emerald_plus`.

Cada hora en un PC o VPS (cron), mejor que GitHub Actions con el repositorio privado:

```
7 * * * * cd /ruta/nachero && RIOT_API_KEY=… .venv/bin/python -m nachero_collector recoger >> collector.log 2>&1
```

## Publicar

```
python -m nachero_collector publicar --out data
```

escribe `data/index.json` con cada archivo, su parche, región, liga, partidas y `sha256`. Sube la
carpeta `data` tal cual a un sitio estático (solo son agregados, así que puede ser público):

- **GitHub Pages** de un repositorio de datos (`<usuario>.github.io/nachero-data`): `git push` de la
  carpeta tras cada pasada. Gratis; GitHub sirve `ETag`.
- **Cloudflare R2** u otro almacenamiento S3 con dominio público: `rclone sync data r2:nachero-data`.
- **Releases** de un repositorio público (un recurso por archivo; menos cómodo para cada hora).

Con el repositorio de la app privado, sus Releases y Pages no son públicos: hace falta uno aparte.

En la app: `stats_url` con la dirección de la carpeta (p. ej. `https://usuario.github.io/nachero-data`)
y, en Ajustes → Datos, la fuente **Automática** (propios si los hay del parche; si no, Lolalytics)
o **Propia**. La liga de los datos propios es la de **Liga de los matchups** (`build_tier`, en
Ajustes → A ciegas y counters; Esmeralda+ por defecto): la app usa el archivo de esa liga para todo
(fuerza en el parche, matchups, runas y sinergias). Si no está publicado, en modo automático se usa
Lolalytics. Para probar en local sin publicar: `stats_mode: "own"` y `stats_file` apuntando a la
carpeta `data`.

## Tu historial completo para «Tu pool»

El cliente solo da tus últimas 200 partidas. Con la misma clave:

```
python -m nachero_collector historial "TuNombre#EUW" --out history_import.json
```

Busca tu `puuid` por tu Riot ID (solo el tuyo), descarga tus partidas de soloq y flex de la
temporada que falten y las escribe en el formato del historial. Copia `history_import.json` a la
carpeta de tu perfil (`%APPDATA%\nachero\profiles\<tu puuid>\`) y Nachero las une a tu historial
al arrancar. Una temporada son ~250 partidas: unos 5 minutos con el límite de la clave.
