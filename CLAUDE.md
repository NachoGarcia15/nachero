# Nachero · guía para Claude

Asistente de draft para League of Legends (Windows): lee la champ select del cliente por su API
local (LCU), recomienda picks/bans con datos Master+ y sirve un panel en `http://127.0.0.1:8765`.
Incluye un simulador de draft pro (datos de gol.gg) e importación de runas (Lolalytics).

Lee primero lo que necesites de: `docs/ARCHITECTURE.md` (capas, flujo, decisiones),
`docs/ROADMAP.md` (fases y normas de Riot), `CONTRIBUTING.md`, `README.md` (fórmula y uso).
Las tareas están en las issues de GitHub, por hitos (Fase 1, 2 y 3); el orden, en la issue
fijada #28. Estrategia de datos (Lolalytics ahora, API de Riot después): `docs/DATOS.md`; formato propio:
`docs/FORMATO_DATOS.md`; recolector: `docs/RECOLECTOR.md`.

## Usuario
- Escribe en español: responde en español; la UI y los comentarios del código también.
- Jugador Master en EUW, main jungla; pool actual Taliyah, Zaahen, Naafiri, Qiyana, Graves.
- Quiere los cambios probados en el cliente real y explicados con brevedad.
- Objetivo: hoy uso personal; en el futuro, **versión pública y monetizable**. Diseña todo para
  que valga en público (fuentes y normas de Riot en `docs/DATOS.md` y `docs/ROADMAP.md`).

## Comandos
```
.venv\Scripts\python -m ruff check src tests run.py scripts
.venv\Scripts\python -m ruff format src tests run.py scripts
.venv\Scripts\python -m mypy
.venv\Scripts\python -m pytest
python run.py [--demo] [--observe] [--tray] [--port 8766] [--browser | --no-browser] [--profile]
.venv\Scripts\python scripts/build_exe.py      # dist/nachero.exe (pip install -e ".[build]")
```
Desde Git Bash: `.venv/Scripts/python`. Si `.venv` no existe: `python -m venv .venv` y
`.venv\Scripts\python -m pip install -e ".[dev]"`.

## Flujo de trabajo
- Nunca trabajar en `main`: rama (`feat/`, `fix/`, `chore/`, `docs/`) → PR → CI verde → squash merge.
- Una issue por chat: rama `tipo/<n>-descripcion`, PR con `Closes #n`. Al terminar, marcar la
  casilla en #28 si la PR no la cierra sola. Issues nuevas con hito y etiquetas
  (`datos`, `cliente`, `panel`, `normas-riot`, `infra`, `distribucion`).
- Fusionar solo cuando el usuario lo pida. El repo es privado (NachoGarcia15/nachero); GitHub no
  permite auto-merge en él.
- Cada PR que cambie la app: sube `__version__` en `src/nachero/__init__.py` (semver: `fix` →
  parche, `feat` → menor) y añade su entrada en `CHANGELOG.md`. Eso no publica nada.
- Toda lógica nueva con tests en `tests/` (dobles en `tests/conftest.py`, sin cliente ni red).

## Publicar una versión (solo cuando el usuario lo pida: «publica», «saca el .exe»…)
1. `main` actualizado, CI verde y `__version__` = versión a publicar, con su entrada en el CHANGELOG.
2. `git tag -a vX.Y.Z -m "Nachero X.Y.Z"` y `git push origin vX.Y.Z`.
3. `release.yml` pasa los tests, comprueba que la etiqueta coincide con `__version__`, construye
   `nachero.exe`, lo prueba y lo publica en Releases con las notas del CHANGELOG.
4. Vigilar el run (`gh run watch`) y comprobar la Release (`gh release view vX.Y.Z`).
- Si el run falla, no borrar ni mover etiquetas ya subidas: arreglar en una PR y publicar la
  siguiente versión de parche, o subir a mano con `gh release create` el `.exe` de
  `scripts/build_exe.py` construido desde esa etiqueta.
- La Release es privada (repo privado): solo la descargan los colaboradores invitados.

## Reglas del proyecto
- `domain/` es lógica pura (sin red ni disco). Fuentes externas en `sources/`, cliente en `clients/`.
- Todas las partes de una recomendación se expresan en puntos de winrate y se suman (ver README).
- Los datos del usuario viven en `%APPDATA%\nachero` (`NACHERO_HOME` en tests). Nunca al repo.
- Fuentes de datos: respetar `robots.txt` y condiciones, con caché y ~1,5 s entre peticiones.
  - **Coachless**: prohibido leer sus datos automáticamente (condiciones). Solo se abre su página.
  - **Lolalytics**: sin API pública; se lee el estado `qwik/json` incrustado en sus páginas
    (`parse_build`). No usar sus endpoints ofuscados (`a1.lolalytics.com/mega`, de donde salen
    sus sinergias) ni pedir acceso a ellos. Solo uso personal: en público, datos propios.
  - **gol.gg**: `/champion/` permitido; el filtro de rol va por POST con cookie de sesión. Solo uso
    personal: lo sustituye Leaguepedia (#80).
  - **Leaguepedia** (API Cargo, CC BY-SA con atribución): competitivo válido en público. El lado
    azul sale de `ScoreboardGames`, no del `Team1` de `PicksAndBansS7`.
  - **API de Riot**: solo en el recolector, con la clave en `RIOT_API_KEY`; nunca en la app.
- Draft: varias opciones con sus motivos, nunca una sola respuesta (Riot pide diversidad de
  decisiones). Predicciones del rival solo con lo visible; no detectar dúos.
- Normas de Riot: una decisión de juego automática (auto-ban, auto-marcar, auto-confirmar) solo
  se permite si sigue la lógica de la app, es opcional (desactivada por defecto) y nunca pisa la
  selección del jugador: Nachero marca, el jugador puede cambiarlo, y se confirma lo marcado.
  No identificar jugadores ocultos. Recomendar e importar runas sí.

## Pruebas con el cliente
- El usuario puede tener su Nachero abierto en 8765: probar en otro puerto (`--port 8766`).
  No cerrar procesos suyos.
- Champ select real sin partida larga: lobby de Practice Tool (blind: sin roles ni bans).
  Draft completo solo en Normal Draft/ranked: no esquivar partidas del usuario.
- Si se prueba algo que escribe en el cliente (p. ej. páginas de runas), dejarlo como estaba.
- Con el cliente cerrado la app usa CommunityDragon y los datos guardados (modo sin cliente).

## Trampas conocidas
- `run.py` abre la ventana de la app (pywebview). Para probar el panel con la vista previa del
  navegador: arrancar con `--no-browser` en Bash en segundo plano y abrir
  `http://localhost:<puerto>/?v=<versión>` (la versión evita la caché del panel antiguo).
  Sin consola (Bash en segundo plano), `serve()` abre un cuadro de aviso de Windows en el
  escritorio del usuario y cerrarlo cierra Nachero: lanza `main()` desde un script que ponga
  `desktop.has_console = lambda: True`. Para simular el cliente cerrado sin cerrarlo,
  `worker.client_ready = lambda lcu: False`.
- No abrir ventanas de prueba si el usuario está en partida (`League of Legends.exe`).
- La API local tarda a veces más de 5 s (historial): usa timeouts largos y no bloquees el bucle.
- Tipo de cola (`domain/queues.py`): fuera de la Grieta (ARAM, Arena, URF…) no se recomienda ni
  se toca el cliente, salvo en ARAM las runas de ARAM (`Draft.aram_tick`); a ciegas y Practice
  Tool, rol principal y sin bans.
- Conexión al cliente: línea de comandos de `LeagueClientUx.exe` y, si no se puede leer (cliente
  como administrador), el `lockfile` de la carpeta del juego.
- Crear la sala de Practice Tool por la API falla (`INVALID_LOBBY`): pide al usuario que la abra.
- La consola de Windows congela el proceso si se hace clic en ella (QuickEdit): `main` lo desactiva.
