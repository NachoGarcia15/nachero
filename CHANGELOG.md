# Cambios

Formato basado en [Keep a Changelog](https://keepachangelog.com/es-ES/1.1.0/) y
[versionado semántico](https://semver.org/lang/es/).

## [0.18.0] - 2026-11-19

### Añadido
- **Runas de ARAM** (ARAM por cola, Clash de ARAM y personalizadas de ARAM): con «Importar runas»
  y en modo Activo, Nachero crea «Nachero · Campeón ARAM» con las runas de la build de ARAM de
  Lolalytics del campeón que te toque. Si cambias de campeón (reroll o banquillo) reemplaza la
  página, sin dejar páginas sueltas; espera 1,5 s a que dejes de cambiar. En Observar dice qué
  importaría. Nada más en ARAM: ni picks, ni bans, ni hechizos. Arena, URF y los demás modos
  siguen sin tocar nada.
- En el panel, la champ select de ARAM dice tu campeón y qué runas ha importado.

### Arreglado
- La confirmación de pick y ban ya no falla si falta `lock_when_seconds_left` en los ajustes.

## [0.17.0] - 2026-11-19

### Añadido
- **Bandeja del sistema** (Windows): icono de Nachero con menú (Abrir, Activo, Observar, Pausado y
  Salir). Cerrar la ventana la deja en la bandeja y Nachero sigue aceptando partidas y leyendo la
  selección; la primera vez lo avisa con un bocadillo. Ajuste «Cerrar deja Nachero en la bandeja»
  para que cerrar salga del todo. Sin dependencias nuevas (Win32 con ctypes).
- **Abrir al iniciar Windows** (desactivado por defecto): arranca en la bandeja, sin ventana.
  Opción `--tray` para lo mismo a mano.
- Abrir Nachero otra vez con la ventana en la bandeja la vuelve a mostrar.
- **Aviso de nueva versión** si el ajuste `update_url` apunta a un `latest.json` público
  (`{"version", "url", "notes"}`): banner con «Descargar». Vacío por defecto, porque con el
  repositorio privado no hay un canal público todavía (#26).

## [0.16.0] - 2026-11-19

### Añadido
- **Perfil por cuenta**: el historial, la maestría y el rango de cada cuenta se guardan en
  `profiles/<puuid>` dentro de la carpeta de datos. Sin cliente se usan los de la última cuenta.
  La primera cuenta que se conecta se queda con los datos guardados por versiones anteriores.
- **Configuración guiada** tras «Empezar» en la bienvenida (y desde Ajustes → Tu perfil): rol
  principal y **secundario**, campeones que **practicas** (+1,5 puntos de WR y entran como
  candidatos aunque aún no los hayas jugado) y los que **nunca** quieres jugar. Sugiere los
  campeones de tu historial.
- Ajustes nuevos: `secondary_role` (lo usará la detección de autofill, #16) y `setup_done`.
  `pool_bonus` y `never_pick` se pueden cambiar desde el panel.

## [0.15.0] - 2026-11-19

### Añadido
- **Bienvenida** en el primer arranque: cuatro pantallas cortas que se pueden saltar («Qué hace»,
  «Cómo decide», «Qué toca y qué no» y «Y además»), cada una con su animación. Teclado (← → Esc),
  indicador de pasos y sin animaciones con «reducir movimiento». Se recuerda con `welcome_seen`.
- Botón **«?»** en la barra: panel *Acerca de Nachero* con la misma explicación, la versión, el
  aviso de Riot, «Probar con una partida de demo» y «Ver la bienvenida otra vez».
- **Demo desde el panel**, sin reiniciar y sin tocar el cliente: una champ select simulada que se
  cierra con «Salir de la demo» o sola al empezar una partida de verdad.
- La pantalla de espera es una portada: qué hace Nachero en tres ideas y el botón de la demo.

## [0.14.0] - 2026-11-19

### Cambiado
- **Auto pick que respeta tu elección** (normas de Riot): Nachero marca su recomendación una
  sola vez por turno y, a falta de `lock_when_seconds_left` s, confirma **lo que esté marcado**:
  lo suyo si no has tocado nada o el campeón que hayas marcado tú. Si marcas otro (en el cliente
  o en el panel), no lo vuelve a cambiar en ese turno, aunque el cliente tarde en reflejarlo.
  Antes de marcar o confirmar relee la acción en el cliente. Si el campeón marcado se lo lleva
  otro, vuelve a marcar la recomendación.
- **Los bans solo se recomiendan**: se quita el ajuste «Banear» (`auto_ban`; si lo tenías
  guardado, se ignora). Nachero nunca marca ni confirma un ban, ni desde el panel. La
  recomendación tiene en cuenta el campeón que Nachero te recomienda jugar (o el que tengas
  marcado) y los picks o intenciones de tus aliados: prioriza a quien los countea (matchups en
  caché) junto con la fuerza en el parche, dice por qué («countea a Taliyah (tu pick) y a
  Garen») y no repite lo que ya han marcado o baneado tus aliados.
- **El bucle de la champ select ya no espera a la red**: las fichas de campeón y el catálogo de
  runas se piden en segundo plano al arrancar, y la caché de Lolalytics se escribe sin bloquear
  al motor. Si analizar la selección tarda más de 3 s, el registro lo dice («Selección lenta: …»).
- Una personalizada con bans dice en el registro «con bans, recomiendo como en un draft» en
  lugar de «sin bans».
- Mensajes nuevos en el panel y el registro: «Marcado X · se confirmará a falta de N s» y
  «Has elegido X: se confirmará X».

### Añadido
- **Elegir desde el panel**: en tu turno de pick, botones con las 5 mejores opciones.
  Un clic lo marca en el cliente (`POST /api/draft/choose`) y cuenta como elección tuya.
  Solo en modo Activo y con la acción pendiente.

## [0.13.0] - 2026-11-17

### Añadido
- **Identidad e icono en Windows**: registro de `AppUserModelID` (`Nachero.Desktop.App`) antes
  de crear la ventana y asignación de icono vía `WM_SETICON` (`LoadImageW`) sobre el `HWND` nativo.
  La ventana, la barra de tareas, el Menú Inicio y `Alt + Tab` muestran el icono personalizado y se
  agrupan como **`Nachero`** en lugar del ejecutable genérico de Python.
- Subcomando `--install-shortcut` para crear el acceso directo `Nachero.lnk` en el Menú Inicio de
  Windows con su icono, descripción y `AppUserModelID` asignado vía `IPropertyStore`.
- Entrypoint configurado en `[project.gui-scripts]` para arrancar como aplicación gráfica nativa sin
  abrir ventana de consola negra.
- Metadatos de versión de Windows en `scripts/build_exe.py` con `FileDescription = "Nachero"`,
  `ProductName = "Nachero"`, `InternalName = "Nachero"` y ejecutable nombrado `Nachero.exe`.

## [0.12.0] - 2026-11-17

### Añadido
- **Pantalla de arranque**: mientras Nachero carga se ve qué está haciendo, paso a paso y con
  datos reales: cliente de LoL, tu historial, maestría y rango, campeones y parche, estadísticas
  Master+ (n/5 roles) y tus recomendaciones. Con barra cuando se sabe cuánto falta y animación
  cuando no, y consejos de draft que van cambiando.
- En la barra superior, el trabajo en segundo plano («Actualizando · Matchups y runas 12/40»),
  con el detalle de cada tarea al pasar el ratón.
- Siluetas (skeletons) de Tu pool y del simulador pro mientras llegan los datos. En la champ
  select, «Calculando matchups (n/m)».
- Si un paso falla, se dice cuál y cuándo se reintenta. Las estadísticas Master+ que fallan se
  vuelven a pedir solas cada 2 minutos.
- Si el cliente está cerrado, Draft dice que lo abras y si se usan tus partidas guardadas.

### Cambiado
- La explicación del modo (Pausado, Observar, Activo) pasa al pasar el ratón por el selector, en
  vez de una línea fija debajo de la barra.
- El aviso legal de Riot sigue entero, pero más pequeño y abajo del todo de la ventana.
- Respeta «reducir movimiento» del sistema (`prefers-reduced-motion`).

### Corregido
- Mientras conectaba o cargaba, Draft decía «Abre el cliente de League of Legends» aunque el
  cliente estuviera abierto. Ahora distingue buscando el cliente, cargando, cliente cerrado y
  listo.

## [0.11.0] - 2026-11-17

### Añadido
- **Nachero es una app de escritorio**: `nachero.exe` abre su propia ventana con el panel, sin
  consola ni navegador. Cerrar la ventana cierra Nachero. Usa WebView2, el motor de Edge que ya
  trae Windows 10 y 11. La ventana y la barra de tareas llevan el icono de Nachero.
- La ventana recuerda su tamaño, su posición y si estaba maximizada.
- Una sola instancia: abrir Nachero otra vez trae al frente la ventana que ya está abierta.
- Si algo falla al arrancar, un cuadro de diálogo lo dice con la ruta del registro (antes salía
  en la consola).
- Sin WebView2, Nachero lo avisa y abre el panel en el navegador; cerrar el aviso lo cierra.
- `--browser` abre el panel en el navegador, como antes (para desarrollo).

### Cambiado
- `--no-browser` ya no abre ni ventana ni navegador: solo el servidor del panel.
- Si el puerto del panel lo usa otro programa, Nachero lo dice en vez de abrir ese puerto en el
  navegador.
- La ventana guarda su propia pestaña y simulador pro: la primera vez sale la pestaña por
  defecto, aunque en el navegador tuvieras otra.

## [0.10.0] - 2026-11-17

### Añadido
- Icono propio de Nachero: una «N» con las dos columnas del draft (azul y rojo) cuya pata derecha
  acaba en flecha. Lo llevan `nachero.exe` (en el Explorador y los accesos directos), la cabecera
  del panel y la pestaña del navegador (favicon). La ventana propia y la barra de tareas lo usan
  con la app de escritorio (#44).
- Logo horizontal (icono + «Nachero») en el README, con versión para tema claro y oscuro.
- `scripts/make_icons.py` genera el `.ico` (16 a 256 px), el PNG de la bandeja y los logos a
  partir del original `assets/icon.svg`.

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
