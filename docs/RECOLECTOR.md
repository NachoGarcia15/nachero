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
2. `match-v5` (routing `europe`): ids de soloq (`queue=420`) de cada jugador, en orden aleatorio
   (500 como mucho por pasada), sin repetir las ya contadas: 3 días en Master+ y 7 en Diamante+ y
   Esmeralda+ (ver abajo). Deja de pedir ids cuando ya tiene las partidas nuevas de la pasada.
3. Detalle de cada partida nueva (como mucho 2000 por pasada). Fuera remakes, otras colas y
   partidas sin posición.
4. Suma campeón, rol, victoria, bans, runas, matchups y sinergias al archivo de su parche
   (`<salida>/<parche>/euw1/<liga>.json.gz`). **La partida en bruto se descarta** en cuanto se
   cuenta; los archivos publicados no llevan jugadores ni ids de partida.
5. Guarda su estado privado (`state/collector.json`, por liga: por dónde va la rotación de cada
   fuente y qué ids ya contó, un día más de los que se piden: uno más viejo ya no puede salir) —
   no se publica. El estado de versiones anteriores (solo Master+) se convierte sin perder nada.
6. **Builds** (#90): cuenta la pareja de hechizos y, con el catálogo de objetos del parche, los
   objetos completos y las botas que llevaba cada uno al final. El catálogo sale de **Data Dragon**
   (público, sin clave: la de Riot nunca va en esa petición), una vez por parche, y se guarda junto
   al estado (`state/items-<parche>.json`). Si no se puede leer, esa pasada no cuenta objetos y el
   resto sigue igual. El orden de compra y el de habilidades necesitan el *timeline* (una petición
   más por partida): de momento no se piden.

Límites de la clave personal: 20 peticiones/s y 100 cada 2 min (~3000 por hora). Con los valores
por defecto, una pasada ronda 2500 peticiones. En un 429 se espera lo que diga `Retry-After`; los
5xx se reintentan con espera creciente; un 401/403 (clave caducada) para con un mensaje claro.

## Presupuesto y volumen (clave personal)

Medido en EUW el 22-nov-2026 con la clave personal (pasada real de Esmeralda+ y sondas de
`league-v4` y `match-v5`; 1.100 peticiones en total):

| | Apex | Diamante I–IV | Esmeralda I–IV |
|---|---|---|---|
| Jugadores en la escalera | ~11.000 (54 páginas) | ~156.000 (764) | ~531.000 (2.591) |
| Partidas de soloq en 14 días por jugador (media; muchos con 0) | ~41 | ~13 | ~11 |

- De 400 partidas pedidas, 386 valen (96,5 %: el resto son remakes o sin posición).
- Presupuesto: 100 peticiones cada 2 min = **72.000 al día**. Cada partida cuesta 1 petición de
  detalle más la parte de la petición de ids de su jugador: con 7 días de ids, ~6–7 partidas por
  jugador en Diamante+ y Esmeralda+, ~1,15 peticiones por partida.
- Con los valores por defecto (`--matches 2000`, una pasada por hora de ~2.300 peticiones y
  ~46 min): **~46.000 partidas al día**. Con `--matches 2400` (~2.750 peticiones, ~55 min),
  ~55.000, el máximo práctico.
- **Diamante+ da el mismo volumen que Esmeralda+**: lo que limita son las peticiones, no los
  jugadores. Diamante+ ya tiene de sobra (a ~8.000 jugadores al día, tarda ~3 semanas en dar la
  vuelta) y su muestra es de más nivel. Esmeralda+ solo suma volumen con la clave de producción.
- Master+ no llega: los apex juegan unas 6.000 partidas al día en EUW, y una pasada por hora ya
  las coge casi todas.

Partidas del parche y muestra (parche de 14 días; con 7 días de ids, las de los primeros días de
cada parche se reparten con el anterior). Mediana por pareja, entre campeones con al menos un 1 %
de pick rate en su rol, según los pick rates de Lolalytics (con el volumen de Lolalytics Master+
el modelo da 82 y Lolalytics, 83):

| Muestra | Partidas del parche | Matchup de misma línea | Pareja de sinergia | Sinergias con ≥ 200 |
|---|---|---|---|---|
| Master+ EUW (propio) | ~90.000 | ~50 | ~50 | ~8 % |
| Diamante+ o Esmeralda+ EUW, por defecto | ~480.000 | ~260 | ~270 | ~60 % |
| Ídem con `--matches 2400` | ~580.000 | ~320 | ~330 | ~70 % |
| Lolalytics Esmeralda+, todas las regiones (16.23, a mitad de parche) | — | ~520 | — | — |

Es decir: con la clave personal, la muestra propia de un parche queda a ~½ de la de Lolalytics
Esmeralda+ (que junta todas las regiones), y unas 5 veces la de Master+. La clave de producción
(#23) escala esto a todas las regiones.

La clave es una sola: si corren dos recolectores con ella (p. ej. Master+ cada hora y otro de
Esmeralda+), se reparten las 72.000 peticiones. Para la app por defecto, mejor uno solo con
`--league diamond_plus` o `emerald_plus` (lo que diga `build_tier`).

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
