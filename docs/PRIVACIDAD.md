# Privacidad (borrador, #27)

Borrador de la política de privacidad de Nachero para la versión pública. Describe lo que hace la
app **hoy** (0.32.0). Cuando cambie algo de lo que se guarda o se envía, se actualiza aquí y en el
CHANGELOG.

## Resumen

- **Todo lo tuyo se queda en tu PC.** Nachero no tiene servidor propio ni cuentas, y no envía
  nada tuyo a ningún sitio.
- Lo que descarga son **estadísticas públicas y agregadas** (partidas y victorias por campeón),
  nunca datos de jugadores concretos.
- No identifica a jugadores ocultos por el juego ni guarda datos de otros jugadores.
- No hay telemetría ni informes automáticos de errores. Si algún día los hay, serán opcionales,
  desactivados por defecto y con tu permiso explícito.

## Qué guarda la app en tu PC

En `%APPDATA%\nachero` (en Windows; botón «Abrir carpeta» en Ajustes → Datos):

| Archivo o carpeta | Qué es | De dónde sale |
|---|---|---|
| `config.json` | Tus ajustes | Lo que cambias en el panel |
| `profiles/<puuid>/history_cache.json` | Tus partidas: campeón, rol, resultado, KDA y oro, daño y súbditos por minuto | Historial del cliente de LoL (tus últimas 200 partidas) |
| `profiles/<puuid>/player_cache.json` | Tu maestría y tu rango, para usar la app con el cliente cerrado | Cliente de LoL |
| `profiles/<puuid>/predictions.json` | «¿Acierta Nachero?»: el WR estimado de lo que confirmaste y el resultado | La app, al confirmar un pick |
| `profiles/<puuid>/history_import.json` | Opcional: tu temporada completa, si la importas con el recolector | Tú (`docs/RECOLECTOR.md`) |
| `profiles/last.json` | Qué perfil usar con el cliente cerrado | La app |
| `cache/` | Estadísticas públicas descargadas (Lolalytics, gol.gg, datos propios, parche actual) | Internet |
| `logs/nachero.log` | Registro de la app (sin nombres ni puuid) | La app |
| `logs/selecciones/` | Lo que pasó en tus 10 últimas selecciones de campeón: acciones, campeones, roles y tiempos, **sin nombres ni ids de cuenta** | La app |
| `window.json`, `webview/` | Tamaño de la ventana y datos del navegador interno (WebView2) | La app |

El `puuid` (id de tu cuenta de Riot) solo se usa como **nombre de carpeta** para separar los datos
de cada cuenta en tu PC. No sale de tu PC.

**Borrar tus datos**: cierra Nachero y borra la carpeta `%APPDATA%\nachero` (o solo `profiles/`
para tus partidas, maestría y calibración). Nachero vuelve a empezar desde cero la próxima vez.

## Qué se descarga (peticiones GET sin datos tuyos)

| Sitio | Para qué | Cuándo |
|---|---|---|
| API local del cliente de LoL (`127.0.0.1`) | Tu selección de campeón, historial, maestría, runas | Con el cliente abierto |
| lolalytics.com | Estadísticas de soloq (uso personal; la versión pública usará datos propios) | Al arrancar y por campeón |
| gol.gg | Competitivo para el simulador pro (uso personal; la versión pública usará Leaguepedia) | Al abrir el simulador |
| raw.communitydragon.org, ddragon.leagueoflegends.com | Datos de campeones y el parche actual con el cliente cerrado | Sin cliente |
| `stats_url` (si la configuras) | Tus datos propios publicados | Al arrancar y cada hora |
| `update_url` (si la configuras) | Aviso de versión nueva (`latest.json`) | Al arrancar |
| coachless.gg | Solo se **abre** la página de la build en tu navegador, si lo activas | Al confirmar |

El panel no carga nada de fuera: sus fuentes van dentro de la app.

## El recolector (datos propios)

El recolector (`src/nachero_collector`) lee partidas públicas con la API de Riot y publica **solo
conteos agregados** por campeón, rol, runas, objetos y hechizos: ningún identificador de jugador ni
de partida (el lector de la app rechaza un archivo que los lleve). En su estado privado guarda los
ids de las partidas ya contadas, unos días, para no contarlas dos veces; nunca se publica.

**Peticiones de borrado de Riot (GDPR)**: como lo publicado no lleva identificadores, no hay datos
de una persona que borrar en los archivos publicados. Si Riot pide borrar los datos de un jugador,
se borra el estado privado del recolector (los ids de partidas contadas) y se deja de leer su
historial.

## Pendiente para la versión pública

- Telemetría e informes de errores, solo con consentimiento explícito (#27).
- Calibración compartida (opcional, desactivada por defecto): enviar registros de drafts
  terminados sin cuenta ni jugadores para ajustar las constantes del draft (#27).
- Publicar esta política en la web de Nachero (#26) y enlazarla desde la app.
