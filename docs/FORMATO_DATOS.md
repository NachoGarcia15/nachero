# Formato de datos propio · esquema 1

Contrato entre el recolector de la fase 2 (#19) y la app: qué se publica y cómo. Lo lee
`sources/dataset.py` (validación y cálculo) a través de `sources/local_stats.py`, que es una
fuente más (`StatsProvider`, ver `docs/DATOS.md`).

## Archivos

Un archivo por **parche, región y liga**:

```
<parche>/<región>/<liga>.json.gz        p. ej. 16.22/euw1/master_plus.json.gz
```

- `región`: la plataforma de Riot (`euw1`, `kr`, `na1`…).
- `liga`: `master_plus`, `diamond_plus`, `emerald`… (las de Lolalytics, para poder compararlas, #21).
- Comprimido con gzip. La app también lee `.json` sin comprimir (para pruebas).

## Contenido

Solo **conteos agregados**: partidas y victorias. La app calcula WR, pick y ban rate, reparto por
roles y deltas. **Ningún identificador** de jugador ni de partida (`puuid`, `summonerId`,
`gameName`, `matchId`…): las normas de Riot permiten estadísticas agregadas, no jugadores
concretos, y el lector rechaza el archivo si los encuentra.

```json
{
  "schema": 1,
  "patch": "16.22",
  "region": "euw1",
  "league": "master_plus",
  "generated": "2026-11-19T08:00:00Z",
  "cutoff": "2026-11-19T07:00:00Z",
  "collector": "nachero-collector 0.1.0",
  "totals": {"games": 18234},
  "champions": {
    "163": {
      "bans": 410,
      "roles": {
        "jungle": {
          "games": 900, "wins": 480,
          "runes": [
            {"pri": [8112, 8139, 8140, 8105], "sec": [8347, 8304], "mod": [5008, 5008, 5007], "games": 600, "wins": 318}
          ]
        },
        "middle": {"games": 640, "wins": 330}
      }
    }
  },
  "matchups": {
    "163:jungle": {"64:jungle": {"games": 120, "wins": 66, "gold15": 230}}
  },
  "synergies": {
    "163:jungle": {"103:middle": {"games": 80, "wins": 45}}
  }
}
```

| Campo | Qué es |
|---|---|
| `schema` | Versión del esquema (1). Un cambio incompatible sube el número; la app rechaza los que no conoce. |
| `patch`, `region`, `league` | Lo mismo que la ruta del archivo. |
| `generated`, `cutoff` | Cuándo se generó y hasta qué partida entra (ISO 8601, UTC). |
| `collector` | Nombre y versión del recolector. |
| `totals.games` | Partidas del archivo (base del pick y ban rate). |
| `champions.<cid>.bans` | Partidas en las que se baneó. |
| `champions.<cid>.roles.<rol>` | Partidas y victorias del campeón en ese rol (`top`, `jungle`, `middle`, `bottom`, `utility`). |
| `…roles.<rol>.runes` | Páginas de runas jugadas (4 + 2 + 3 ids) con sus partidas y victorias. Basta con las más jugadas. |
| `matchups.<cid>:<rol>.<cid>:<rol>` | Partidas y victorias del primero contra el segundo, por pareja de líneas. `gold15`: diferencia media de oro a los 15 min, si se recoge (opcional). |
| `synergies.<cid>:<rol>.<cid>:<rol>` | Lo mismo para dúos del mismo equipo (jungla con mid, ADC con support…). |

## Lo que calcula la app

- **WR** = victorias / partidas. **Pick rate** = partidas del campeón en el rol / `totals.games`.
  **Ban rate** = `bans` / `totals.games`. **Reparto** (`pct`) = partidas en el rol / partidas del
  campeón en todos los roles.
- **Tier** (1 = S+ … 15 = D−): percentil de fuerza encogida y presencia. Es orientativo.
- **Matchups**: `d1` = WR del enfrentamiento − WR del campeón; `d2` = WR del enfrentamiento − el
  esperado por la fuerza de los dos (50 + fuerza propia − fuerza rival). Igual que en Lolalytics:
  `d2` mide solo la interacción.
- **Runas**: «más popular» (más partidas) y «mayor WR» (WR encogido hacia el 50 %, entre las que
  tienen al menos el 5 % de las partidas y 30).

## Principio de parche

Con pocas partidas, cada conteo se mezcla con el del parche anterior (misma región y liga) con el
mismo encogimiento que usa el motor: el anterior pesa **k / (n + k)**, con *n* las partidas de este
parche. k = 1000 para campeón y rol, 150 para matchups y sinergias, 300 para runas. Con 0 partidas
manda el parche anterior; con 9000, apenas pesa un 10 %. La app marca esos datos (`merged`).

En una carpeta con la estructura publicada, la app usa el archivo del parche actual y el del
parche anterior más reciente que encuentre.

## Ejemplo

`tests/data/stats/` tiene un ejemplo pequeño de dos parches (16.22 sin comprimir y 16.23 en gzip)
que usan los tests.
