# Cambios

Formato basado en [Keep a Changelog](https://keepachangelog.com/es-ES/1.1.0/) y
[versionado semántico](https://semver.org/lang/es/).

## [0.9.0] - 2026-11-17

### Añadido
- Roles de cada campeón: principal, flex, ocasional o fuera de rol según su reparto por línea en
  Master+ (umbrales en `roles` de la config). Cualquier campeón se puede evaluar en cualquier rol.
- Confianza en cada tarjeta (Alta, Media, Baja o Sin datos) según las partidas del campeón en ese
  rol, y su rol si no es el principal («ADC flex»).
- Buscador «Evaluar cualquier campeón» en Draft y Tu pool: campeón y rol, con su estimación y su
  confianza (en la selección de campeón, con el draft actual).
- Simulador pro: clic en la etiqueta de rol de un pick para elegirlo a mano si la asignación
  automática falla.

### Cambiado
- Draft: entran los principales y flex del rol entre los fuertes del parche (Katarina ADC, Jayce
  jungla, Cassiopeia top), lo que has jugado en el rol desde 1 partida y tu maestría si el rol es
  al menos ocasional.
- Fuera de su rol principal, la fuerza del campeón se encoge hacia la de su rol principal con una
  penalización que crece cuanto menos se juega ahí (hasta −4 pp; medida con la caché real). Sustituye
  el −2,5 fijo.
- Sin matchups del campeón en ese rol, se usan los de su rol principal con la mitad de peso,
  marcados como datos de otro rol.
- Tu pool: la maestría cuenta en los roles principal y flex del campeón (no solo en tu rol
  principal); filtro por los cinco roles y columna de confianza.
- Simulador pro: un campeón se sugiere en sus roles flex de Master+ aunque en el torneo solo se haya
  jugado en otro.
- Roles del rival: suelo del 1 % para que un pick fuera de rol no descoloque al resto.

## [0.8.0] - 2026-11-15

### Cambiado
- La app se llama **Nachero**: `nachero.exe`, comando `nachero` y paquete `nachero`.
- Los datos pasan de `%APPDATA%\draftbot` a `%APPDATA%\nachero` en el primer arranque, sin perder
  ajustes, historial ni cachés. Si el draftbot antiguo sigue abierto, se copian y la carpeta antigua
  se queda.
- Las páginas de runas nuevas se llaman «Nachero · Campeón Rol». Las antiguas «draftbot · …» se
  siguen tratando como propias y se reemplazan, así que no se quedan sueltas.
- El panel conserva la pestaña abierta y el simulador pro guardados con el nombre antiguo.

## [0.7.0] - 2026-11-15

### Añadido
- Aviso legal de Riot al pie del panel, con el texto exacto de sus normas.
- El panel explica qué hace cada modo (Pausado, Observar, Activo) y qué toca en el cliente con
  tus ajustes: bajo la barra superior, al pasar por los botones de modo y en Ajustes.

### Cambiado
- Banear, marcar pick y confirmar pick vienen desactivados por defecto (normas de Riot: no
  decidir por el jugador). Aceptar partida, hechizos e importar runas siguen disponibles. Los
  ajustes que ya tengas guardados se respetan.
- En tu turno, el panel dice «draftbot lo confirmará» solo si de verdad tiene activado confirmar
  pick; si no, «hazlo tú».

## [0.6.3] - 2026-11-15

### Corregido
- Fuera de Windows (Linux, WSL o macOS) draftbot avisa en la consola y en el panel de que
  necesita Windows con el cliente abierto y recomienda `draftbot.exe`, en vez de quedarse cargando.
- Sin cliente, el parche actual sale de Data Dragon o CommunityDragon (con caché de 6 h) en vez
  del parche «30», que no existe. Sin internet se usa el último conocido.
- El panel dice qué falta en vez de «Calculando tu pool…» o «Cargando…» para siempre: sin
  cliente, sin partidas, sin datos de campeones, sin parche o sin estadísticas de Lolalytics.

### Añadido
- Botón «Copiar diagnóstico» en Actividad: versión, sistema, conexión, fase, parche y las
  últimas líneas del registro, sin rutas de usuario ni identificadores, para mandar un informe.

## [0.6.2] - 2026-11-15

### Corregido
- Tu pool explica cuántas partidas tiene y desde cuándo. El cliente solo da tus últimas 200
  partidas de cualquier modo, así que el pool podía sumar menos partidas que las victorias y
  derrotas de la cabecera sin decir por qué. Las nuevas se siguen guardando todas.

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
