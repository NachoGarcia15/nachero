# Arquitectura

Nachero es una app local: un proceso de Python que habla con el cliente de LoL, descarga
estadísticas públicas y sirve un panel web en `127.0.0.1`. No hay servidor propio.

## Capas

```
src/nachero/
  clients/   Cómo hablamos con el exterior "del juego"
             lcu.py      API local del cliente de LoL (lockfile/puerto + token)
             cdragon.py  CommunityDragon: mismos datos estáticos cuando el cliente está cerrado
  sources/   Fuentes de datos (red, caché en disco, parseo)
             champions.py  metadatos e imágenes de campeones
             history.py    historial del jugador (rol de cada partida)
             lolalytics.py tier list y matchups Master+ (incl. parser del estado qwik)
             local_stats.py estadísticas de un archivo local (datos propios, fase 2)
             dataset.py  esquema 1 de los datos propios: validar, mezclar parches y calcular
             remote_stats.py datos propios publicados: index.json + ETag a la caché
             health.py   salud de una fuente: distingue red de cambio de formato y avisa
             golgg.py      estadísticas de competitivo por torneo
             (lolalytics.py también extrae las páginas de runas recomendadas)
  domain/    Lógica pura: sin red ni disco, testeable con dobles
             common.py   roles, tiers, shrink, normalización de nombres
             player.py   modelo personal (experiencia, forma, residuo de WR)
             tags.py     papel de cada campeón en una composición e identidad de equipo
             roles.py    roles de cada campeón (principal, flex, ocasional, fuera de rol),
                         estimación fuera de rol y confianza
             engine.py   recomendación de picks y bans de soloq
             pro.py      motor del simulador de draft pro
             runes.py    validar una página de runas y pasarla al formato del cliente
             queues.py   tipo de cola: draft, a ciegas o fuera de la Grieta
             tasks.py    registro de tareas: qué hace la app y su progreso (n de m)
             stats.py    interfaz de las fuentes de estadísticas (StatsProvider) y cadena de respaldo
             calibration.py ¿acierta Nachero?: registro de picks, resultado y calibración
  app/       Orquestación
             state.py    estado compartido (APP, TASKS), log
             draft.py    champ select de soloq (lee sesión, recomienda, actúa)
             runes.py    importar la página de runas al cliente
             demo.py     draft simulado
             worker.py   bucle principal y sesión con el cliente
             server.py   API HTTP del panel y archivos estáticos
             desktop.py  ventana de la app (pywebview), diálogos, instancia única
             tray.py     icono en la bandeja del sistema (Win32 con ctypes)
             updates.py  aviso de nueva versión (latest.json público)
             main.py     argumentos y arranque
  ui/        Panel (HTML/CSS/JS sin dependencias)

src/nachero_collector/   Recolector de la fase 2 (API de Riot → esquema 1). No va en la app
                         ni en el .exe; ver docs/RECOLECTOR.md
  defaults/  Ajustes por defecto
  config.py, paths.py, jsonio.py
```

Regla de dependencias: `app → domain ← sources/clients`. El dominio no importa nada de `app`,
`sources` ni `clients`; recibe objetos con la interfaz que necesita (`champs`, `lola`, `gol`).
La de estadísticas está escrita en `domain/stats.py` (`StatsProvider`): Lolalytics, el archivo
local o una cadena de varias (`ChainStats`, según `stats_sources`) valen igual para el motor.
Por eso los tests usan dobles (`tests/conftest.py`) y no necesitan cliente ni internet.

## Flujo de una recomendación (soloq)

1. `worker` lee la fase del cliente cada segundo.
2. Al entrar en champ select, `worker` lee la cola (`/lol-gameflow/v1/session`) y la clasifica
   (`queues.classify`). Fuera de la Grieta solo se muestra un aviso: no se recomienda ni se actúa.
3. En champ select, `draft.Draft.tick` lee la sesión, separa aliados (elegidos y marcados),
   rivales, bans y orden de picks.
4. `engine.Engine.picks` puntúa candidatos: fuerza en el parche + tú + matchups (rival de línea
   y resto, con roles estimados) + encaje con tu equipo + respuesta a su comp + riesgo de counter.
5. `Engine.bans` puntúa bans: presencia × (fuerza × 0,4 + cuánto countea a tu pick y a tus
   aliados, con los matchups en caché). Con `auto_ban`, `Draft.ban_turn` marca el primero en
   `BAN_PICK` (nunca lo confirma) y no pisa el que marque el jugador.
6. En modo Activo, `Draft.turn` marca la recomendación de pick una vez por acción y confirma lo
   que esté marcado a falta de `lock_when_seconds_left` s. Si lo marcado no es lo que marcó Nachero (o
   se eligió en el panel con `POST /api/draft/choose`), es la elección del jugador: no se vuelve
   a marcar en ese turno.
7. El panel consulta `/api/state` cada segundo y pinta.

## Arranque y carga visible

`worker.run_session` va marcando en `state.TASKS` (`domain/tasks.py`) cada paso real: buscar el
cliente, historial, maestría y rango, campeones y parche, tier lists de Lolalytics (n/5 roles) y
las recomendaciones. En segundo plano, la cola de matchups (`TASKS.queue`) y los torneos de
gol.gg (n/6 páginas). `/api/state` publica la lista (`tasks`) y un resumen (`progress`): el panel
pinta la pantalla de arranque mientras `loading`, la tarea en curso en la barra superior y los
skeletons de Tu pool y el simulador. Si un paso falla, la tarea guarda el error y, si se puede,
cuándo se reintenta (`retry_in`); las tier lists que fallan se vuelven a pedir solas.

## Bienvenida y demo

La bienvenida (pasos en `ui/index.html`, lógica en `ui/app.js`) sale mientras `welcome_seen` sea
`false` y se marca con `POST /api/welcome`. La demo se abre y se cierra en caliente con
`POST /api/demo` (`state.set_demo`): el bucle sustituye la fase real por una champ select
simulada (`app/demo.py`) y nunca actúa. La abierta desde el panel se cierra sola si el cliente
entra en una partida (`state.demo_must_stop`).

## Datos y privacidad

- Los datos del usuario (ajustes, historial, maestría, cachés, logs) viven en
  `%APPDATA%\nachero` (o `NACHERO_HOME`), nunca en el repositorio.
- Historial, maestría y rango van por cuenta en `profiles/<puuid>` (`paths.use_profile`, al
  conectar con `/lol-summoner/v1/current-summoner`); sin cliente, el último perfil (`last.json`).
  Los ajustes son comunes a todas las cuentas.
- No se envía nada del usuario a ningún sitio. Solo se descargan estadísticas públicas.
- Las fuentes externas se piden con caché y ~1,5 s entre peticiones.

## Decisiones

| Decisión | Motivo |
|---|---|
| Solo biblioteca estándar en tiempo de ejecución (salvo pywebview) | Instalar y empaquetar sin fricción. |
| Panel web local, mostrado en una ventana propia (pywebview con WebView2) | La misma interfaz HTML/JS en la app y, para desarrollo, en el navegador (`--browser`). WebView2 viene con Windows 10 y 11; Electron o Tauri obligarían a reescribir el backend. |
| Bandeja con ctypes, sin pystray | Sin dependencias nuevas y sin los choques conocidos de pystray con pywebview: una ventana oculta propia, en su hilo, recibe los mensajes del icono. Cerrar la ventana la esconde (`closing` devuelve False). |
| Instancia única por puerto | Abrir Nachero otra vez trae al frente la ventana del que ya usa el puerto (`/api/instance`); en otro puerto se puede probar una segunda copia. |
| Todo en puntos de winrate | Las partes se pueden sumar, comparar y explicar al usuario. |
| *Delta 2* para matchups | Mide solo la interacción; no cuenta dos veces la fuerza del campeón. |
| Encogimiento por muestra (`shrink`) | Pocas partidas dicen poco: evita recomendaciones por suerte. |
| No usar APIs ofuscadas ni saltarse protecciones | Respetar a las fuentes de datos. |
| Decisiones de juego automáticas: opcionales y sin pisar la elección del jugador | Normas de Riot (ver ROADMAP): Nachero marca, el jugador decide y se confirma lo marcado. |
