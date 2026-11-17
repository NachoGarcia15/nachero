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
  app/       Orquestación
             state.py    estado compartido (APP, TASKS), log
             draft.py    champ select de soloq (lee sesión, recomienda, actúa)
             runes.py    importar la página de runas al cliente
             demo.py     draft simulado
             worker.py   bucle principal y sesión con el cliente
             server.py   API HTTP del panel y archivos estáticos
             desktop.py  ventana de la app (pywebview), diálogos, instancia única
             main.py     argumentos y arranque
  ui/        Panel (HTML/CSS/JS sin dependencias)
  defaults/  Ajustes por defecto
  config.py, paths.py, jsonio.py
```

Regla de dependencias: `app → domain ← sources/clients`. El dominio no importa nada de `app`,
`sources` ni `clients`; recibe objetos con la interfaz que necesita (`champs`, `lola`, `gol`).
Por eso los tests usan dobles (`tests/conftest.py`) y no necesitan cliente ni internet.

## Flujo de una recomendación (soloq)

1. `worker` lee la fase del cliente cada segundo.
2. Al entrar en champ select, `worker` lee la cola (`/lol-gameflow/v1/session`) y la clasifica
   (`queues.classify`). Fuera de la Grieta solo se muestra un aviso: no se recomienda ni se actúa.
3. En champ select, `draft.Draft.tick` lee la sesión, separa aliados (elegidos y marcados),
   rivales, bans y orden de picks.
4. `engine.Engine.picks` puntúa candidatos: fuerza en el parche + tú + matchups (rival de línea
   y resto, con roles estimados) + encaje con tu equipo + respuesta a su comp + riesgo de counter.
5. `Engine.bans` puntúa bans: presencia × (fuerza × 0,4 + cuánto counterea tus picks).
6. El panel consulta `/api/state` cada segundo y pinta.

## Arranque y carga visible

`worker.run_session` va marcando en `state.TASKS` (`domain/tasks.py`) cada paso real: buscar el
cliente, historial, maestría y rango, campeones y parche, tier lists de Lolalytics (n/5 roles) y
las recomendaciones. En segundo plano, la cola de matchups (`TASKS.queue`) y los torneos de
gol.gg (n/6 páginas). `/api/state` publica la lista (`tasks`) y un resumen (`progress`): el panel
pinta la pantalla de arranque mientras `loading`, la tarea en curso en la barra superior y los
skeletons de Tu pool y el simulador. Si un paso falla, la tarea guarda el error y, si se puede,
cuándo se reintenta (`retry_in`); las tier lists que fallan se vuelven a pedir solas.

## Datos y privacidad

- Los datos del usuario (ajustes, historial, maestría, cachés, logs) viven en
  `%APPDATA%\nachero` (o `NACHERO_HOME`), nunca en el repositorio.
- No se envía nada del usuario a ningún sitio. Solo se descargan estadísticas públicas.
- Las fuentes externas se piden con caché y ~1,5 s entre peticiones.

## Decisiones

| Decisión | Motivo |
|---|---|
| Solo biblioteca estándar en tiempo de ejecución (salvo pywebview) | Instalar y empaquetar sin fricción. |
| Panel web local, mostrado en una ventana propia (pywebview con WebView2) | La misma interfaz HTML/JS en la app y, para desarrollo, en el navegador (`--browser`). WebView2 viene con Windows 10 y 11; Electron o Tauri obligarían a reescribir el backend. |
| Instancia única por puerto | Abrir Nachero otra vez trae al frente la ventana del que ya usa el puerto (`/api/instance`); en otro puerto se puede probar una segunda copia. |
| Todo en puntos de winrate | Las partes se pueden sumar, comparar y explicar al usuario. |
| *Delta 2* para matchups | Mide solo la interacción; no cuenta dos veces la fuerza del campeón. |
| Encogimiento por muestra (`shrink`) | Pocas partidas dicen poco: evita recomendaciones por suerte. |
| No usar APIs ofuscadas ni saltarse protecciones | Respetar a las fuentes de datos. |
| No automatizar decisiones de juego en versiones compartidas | Normas de Riot (ver ROADMAP). |
