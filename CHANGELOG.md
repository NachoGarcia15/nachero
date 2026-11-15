# Cambios

Formato basado en [Keep a Changelog](https://keepachangelog.com/es-ES/1.1.0/) y
[versionado semántico](https://semver.org/lang/es/).

## [0.6.1] - 2026-11-15

### Corregido
- Tipo de cola: al entrar en la champ select se lee la cola de la partida.
  - Grieta con draft (solo/dúo, flexible, normal draft, Clash): todo como antes.
  - Grieta a ciegas, personalizadas y herramienta de práctica: recomienda para tu rol principal,
    sin bans y sin riesgo de counter (nadie ve el pick del otro). Una personalizada con bans
    se trata como draft.
  - ARAM, Arena, URF y demás modos: no recomienda ni toca el cliente (antes, en modo Activo,
    podía poner Smite + Flash o marcar un pick). El panel lo indica.
- El panel muestra la cola junto a la fase de la champ select.

## [0.6.0] - 2026-11-14

### Añadido
- `draftbot.exe`: un solo archivo con Python dentro (`scripts/build_exe.py`, PyInstaller). Doble
  clic y listo; si falla al arrancar, la ventana muestra el error en vez de cerrarse.
- Publicación automática en GitHub Releases al subir una etiqueta `vX.Y.Z` (workflow `release.yml`).
- Test de arranque del punto de entrada.

## [0.5.1] - 2026-11-14

### Corregido
- Rol: el historial reconoce mejor el rol de cada partida (antes se perdían partidas de support)
  y cuenta también flex, normal draft y partida rápida, así que el rol principal de quien no es
  jungla ya no sale «Jungla». En la champ select manda siempre el rol asignado por el cliente.
- Conexión: si el cliente está abierto como administrador, se conecta con el `lockfile` de la
  carpeta del juego en vez de quedarse en «cliente cerrado».
- Un fallo puntual al leer la fase del cliente ya no reinicia toda la sesión (antes podía dejar
  la app recargando datos durante la champ select).
- Hacer clic en la ventana de la consola ya no congela draftbot (modo de selección de Windows).

### Añadido
- Selector de rol principal en la pantalla de espera (Auto o un rol fijo).
- La pantalla de espera avisa de que en modo Observar no se acepta la partida.

## [0.5.0] - 2026-11-14

### Añadido
- Importar runas al confirmar campeón: crea la página «draftbot · Campeón Rol» con la página
  más popular (o la de mayor WR) de Lolalytics Master+ y la deja activa. Solo reemplaza páginas
  de draftbot; si no hay hueco, no toca las tuyas. Si no hay datos suficientes no importa nada.
- Vista previa de las runas del pick recomendado en el panel, y ajustes para activarlo y elegir la fuente.

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
