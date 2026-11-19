# Recolector de partidas (fase 2)

`src/nachero_collector/` genera los datos propios del esquema 1 (`docs/FORMATO_DATOS.md`) con la
API oficial de Riot: soloq EUW Master+, con la **clave personal**. No va en la app ni en el `.exe`
(el paquete de la app solo incluye `nachero`), y la clave nunca se guarda en el repositorio: se
lee de la variable de entorno `RIOT_API_KEY`.

> La issue #19 proponía un repositorio aparte (`draftbot-data`). El recolector solo depende del
> lector del esquema (`nachero.sources.dataset`), así que se puede mover tal cual cuando exista.

## Qué hace una pasada

1. `league-v4`: Challenger, Grandmaster y Master de `euw1` → sus `puuid` (solo en memoria).
2. `match-v5` (routing `europe`): ids de soloq (`queue=420`) de los últimos 3 días de un tramo de
   jugadores (500 por pasada, rotando), sin repetir las ya contadas.
3. Detalle de cada partida nueva (como mucho 2000 por pasada). Fuera remakes, otras colas y
   partidas sin posición.
4. Suma campeón, rol, victoria, bans, runas, matchups y sinergias al archivo de su parche
   (`<salida>/<parche>/euw1/master_plus.json.gz`). **La partida en bruto se descarta** en cuanto se
   cuenta; los archivos publicados no llevan jugadores ni ids de partida.
5. Guarda su estado privado (`state/collector.json`: por dónde va la rotación y qué ids ya contó,
   30 días) — no se publica.

Límites de la clave personal: 20 peticiones/s y 100 cada 2 min (~3000 por hora). Con los valores
por defecto, una pasada ronda 2500 peticiones. En un 429 se espera lo que diga `Retry-After`; los
5xx se reintentan con espera creciente; un 401/403 (clave caducada) para con un mensaje claro.

## Uso

```
export RIOT_API_KEY=RGAPI-…            # Windows: set RIOT_API_KEY=RGAPI-…
python -m nachero_collector recoger --out data --state state/collector.json
```

Opciones: `--region euw1`, `--league master_plus`, `--players 500`, `--matches 2000`.

Cada hora en un PC o VPS (cron), mejor que GitHub Actions con el repositorio privado:

```
7 * * * * cd /ruta/nachero && RIOT_API_KEY=… .venv/bin/python -m nachero_collector recoger >> collector.log 2>&1
```

Para que la app los use: `stats_sources: ["local", "lolalytics"]` y `stats_file` apuntando a la
carpeta `data` (o, más adelante, la descarga de #20).

## Tu historial completo para «Tu pool»

El cliente solo da tus últimas 200 partidas. Con la misma clave:

```
python -m nachero_collector historial "TuNombre#EUW" --out history_import.json
```

Busca tu `puuid` por tu Riot ID (solo el tuyo), descarga tus partidas de soloq y flex de la
temporada que falten y las escribe en el formato del historial. Copia `history_import.json` a la
carpeta de tu perfil (`%APPDATA%\nachero\profiles\<tu puuid>\`) y Nachero las une a tu historial
al arrancar. Una temporada son ~250 partidas: unos 5 minutos con el límite de la clave.
