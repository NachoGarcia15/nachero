# draftbot · guía para Claude

Asistente de draft para League of Legends (Windows): lee la champ select del cliente por su API
local (LCU), recomienda picks/bans con datos Master+ y sirve un panel en `http://127.0.0.1:8765`.
Incluye un simulador de draft pro (datos de gol.gg) e importación de runas (Lolalytics).

Lee primero lo que necesites de: `docs/ARCHITECTURE.md` (capas, flujo, decisiones),
`docs/ROADMAP.md` (fases y normas de Riot), `CONTRIBUTING.md`, `README.md` (fórmula y uso).
Las tareas pendientes están en las issues de GitHub (`gh issue list`).

## Usuario
- Escribe en español: responde en español; la UI y los comentarios del código también.
- Jugador Master en EUW, main jungla; pool actual Taliyah, Zaahen, Naafiri, Qiyana, Graves.
- Quiere los cambios probados en el cliente real y explicados con brevedad.

## Comandos
```
.venv\Scripts\python -m ruff check src tests run.py scripts
.venv\Scripts\python -m ruff format src tests run.py scripts
.venv\Scripts\python -m mypy
.venv\Scripts\python -m pytest
python run.py [--demo] [--observe] [--port 8766] [--no-browser] [--profile]
.venv\Scripts\python scripts/build_exe.py      # dist/draftbot.exe (pip install -e ".[build]")
```
Desde Git Bash: `.venv/Scripts/python`. Si `.venv` no existe: `python -m venv .venv` y
`.venv\Scripts\python -m pip install -e ".[dev]"`.

## Flujo de trabajo
- Nunca trabajar en `main`: rama (`feat/`, `fix/`, `chore/`, `docs/`) → PR → CI verde → squash merge.
- Fusionar solo cuando el usuario lo pida. El repo es privado (NachoGarcia15/draftbot); GitHub no
  permite auto-merge en él.
- Cada versión: `__version__` en `src/draftbot/__init__.py` + entrada en `CHANGELOG.md`.
  Publicar el `.exe`: etiqueta `vX.Y.Z` igual a `__version__` (workflow `release.yml`), solo si el usuario lo pide.
- Toda lógica nueva con tests en `tests/` (dobles en `tests/conftest.py`, sin cliente ni red).

## Reglas del proyecto
- `domain/` es lógica pura (sin red ni disco). Fuentes externas en `sources/`, cliente en `clients/`.
- Todas las partes de una recomendación se expresan en puntos de winrate y se suman (ver README).
- Los datos del usuario viven en `%APPDATA%\draftbot` (`DRAFTBOT_HOME` en tests). Nunca al repo.
- Fuentes de datos: respetar `robots.txt` y condiciones, con caché y ~1,5 s entre peticiones.
  - **Coachless**: prohibido leer sus datos automáticamente (condiciones). Solo se abre su página.
  - **Lolalytics**: sin API pública; se lee el estado `qwik/json` incrustado en sus páginas
    (`parse_build`). No usar sus endpoints ofuscados.
  - **gol.gg**: `/champion/` permitido; el filtro de rol va por POST con cookie de sesión.
- Normas de Riot: no automatizar decisiones de juego en versiones compartidas (auto-ban,
  auto-marcar, auto-confirmar); no identificar jugadores ocultos. Recomendar e importar runas sí.

## Pruebas con el cliente
- El usuario puede tener su draftbot abierto en 8765: probar en otro puerto (`--port 8766`).
  No cerrar procesos suyos.
- Champ select real sin partida larga: lobby de Practice Tool (blind: sin roles ni bans).
  Draft completo solo en Normal Draft/ranked: no esquivar partidas del usuario.
- Si se prueba algo que escribe en el cliente (p. ej. páginas de runas), dejarlo como estaba.
- Con el cliente cerrado la app usa CommunityDragon y los datos guardados (modo sin cliente).

## Trampas conocidas
- La herramienta de vista previa del navegador lanzaba una copia antigua: arrancar el servidor
  con Bash en segundo plano y abrir `http://localhost:<puerto>/?v=<versión>` (la versión evita
  la caché del panel antiguo).
- La API local tarda a veces más de 5 s (historial): usa timeouts largos y no bloquees el bucle.
- La app aún no detecta el tipo de cola: en ARAM/Arena recomienda como si fuera la Grieta (issue #3).
- Conexión al cliente: línea de comandos de `LeagueClientUx.exe` y, si no se puede leer (cliente
  como administrador), el `lockfile` de la carpeta del juego.
- Crear la sala de Practice Tool por la API falla (`INVALID_LOBBY`): pide al usuario que la abra.
- La consola de Windows congela el proceso si se hace clic en ella (QuickEdit): `main` lo desactiva.
