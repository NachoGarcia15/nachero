# Cambios

Formato basado en [Keep a Changelog](https://keepachangelog.com/es-ES/1.1.0/) y
[versionado semántico](https://semver.org/lang/es/).

## [0.4.0] - 2026-11-14

### Cambiado
- Código reorganizado en el paquete `draftbot` por capas (`clients`, `sources`, `domain`, `app`, `ui`).
- Los datos del usuario (ajustes, historial, maestría, cachés) se guardan en `%APPDATA%\draftbot`
  y se migran solos desde la carpeta del proyecto.
- Ajustes: valores por defecto en el paquete + los tuyos en tu carpeta de datos.
- Se arranca con `python run.py` (o `draftbot` si se instala).

### Añadido
- Registro en `%APPDATA%\draftbot\logs\draftbot.log`.
- Tests (36), ruff, mypy, pre-commit e integración continua en GitHub Actions.
- Documentación de arquitectura y hoja de ruta.

### Corregido
- Archivos JSON que se abrían sin cerrar; escritura atómica de cachés.
- El servidor del panel solo sirve archivos de la carpeta `ui/`.

## [0.3.0] - 2026-11-14

### Añadido
- Simulador de draft pro con datos de gol.gg (orden de torneo, fearless, valoración final).
- Etiquetas de papel en la composición e identidad de equipo; condición de victoria y respuesta a la comp rival en soloq.
- Modo "Solo meta y draft"; matchups contra los 5 rivales; modo sin cliente con CommunityDragon.

## [0.2.0] - 2026-11-14

### Añadido
- Estadísticas Master+ de Lolalytics, modelo personal del jugador y panel rediseñado.

## [0.1.0] - 2026-11-14

### Añadido
- Primera versión: aceptar cola, bans y picks automáticos, panel con modos.
