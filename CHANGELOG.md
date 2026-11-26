# Cambios

Formato basado en [Keep a Changelog](https://keepachangelog.com/es-ES/1.1.0/) y
[versionado semántico](https://semver.org/lang/es/).

## [0.32.0] - 2026-11-27

Marcar y confirmar pick en ranked (lo que no funcionaba en el cliente real), seguridad del panel,
#93 sin destellos de consola, validación de los datos propios (#21) y una revisión de bugs y de la
interfaz. Probado sin el cliente: simulaciones, dobles y la CI de Windows.

### Corregido
- **Confirmar pick no confirmaba**: el reloj de la sesión del cliente es una foto del último
  cambio (`adjustedTimeLeftInPhase` en el instante `internalNowInEpochMs`), no una cuenta atrás.
  Si nadie tocaba nada al final de tu turno, Nachero seguía leyendo los ~30 s del principio y
  nunca llegaba a «a falta de 8 s» (en ranked, sin confirmar se esquiva). Ahora descuenta lo que ha
  pasado desde la foto, como el propio cliente, y el reloj del panel también cuenta de verdad.
- **La marca dejaba de seguir la recomendación**: si el cliente tardaba más de 5 s en responder al
  marcar (en ranked espera al servidor), la vuelta se cortaba con un error aunque el cliente lo
  aplicara, y en la siguiente la marca de Nachero parecía tuya («Has elegido…») y ya no la
  cambiaba. Ahora espera hasta 10 s y, sin respuesta, la marca sigue contando como de Nachero.
  Igual con el ban y al confirmar.
- Un fallo puntual al leer la fase del cliente ya no se toma por «Sin cliente»: al volver a la
  selección se borraba lo que llevaba marcado Nachero y su marca pasaba a parecer tuya.
- **Sin destellos de consola** (#93): para encontrar el cliente, Nachero leía su línea de comandos
  con PowerShell, que abría una consola un instante en cada intento (con el cliente cerrado, cada
  10 s). Ahora la lee con la API de Windows (`clients/winproc.py`), sin abrir nada; PowerShell
  queda de respaldo y sin ventana. Si el cliente va como administrador, sigue el `lockfile`.
- El acceso directo del Menú Inicio (`--install-shortcut`) se crea sin ventanas y funciona con
  carpetas de usuario con apóstrofo (O'Brien).
- **Al acabar una partida, un fallo del cliente reiniciaba toda la sesión**: el historial (hasta
  60 s) y la maestría se leían fuera de la protección del bucle; si el cliente tardaba o fallaba,
  Nachero volvía a cargarlo todo. Ahora se leen en segundo plano y una sola vez a la vez (antes,
  dos: en PreEndOfGame y en EndOfGame, con el bucle parado), y si la maestría no llega se queda la
  que había (antes se perdía).
- Un fallo que se repite en cada vuelta del bucle se apunta una vez (y cuántas veces más se ha
  repetido) en lugar de llenar la Actividad cada segundo; su traza completa va al archivo de
  registro. «Selección lenta», como mucho una vez cada 30 s.
- **Tu pool y la pantalla de espera daban otro WR para el mismo campeón**: Tu pool sumaba solo tu
  parte y la fuerza en el parche; la recomendación cuenta además el riesgo de counter a ciegas,
  tus puntos de «practicando» y tu estilo. Ahora Tu pool usa el mismo cálculo del motor y el mismo
  campeón sale con el mismo número en las dos vistas (y el plan de Tu pool ordena con él).
- **Ajustes rotos**: si `config.json` era JSON válido pero no un objeto, Nachero no arrancaba; si
  estaba corrupto, seguía con los de por defecto sin avisar y el siguiente guardado lo pisaba (se
  perdían tus ajustes). Ahora arranca, guarda una copia en `config.roto.json` y lo dice en la
  Actividad. Un valor con un tipo que no toca (p. ej. `"weights": "x"`, que rompía el motor en cada
  vuelta) no entra: se queda el de por defecto.
- **Barra superior en ventanas medianas** (~800-1000 px): las pestañas se montaban encima del
  estado («Selección de campeón»). Ahora el estado se recorta con «…» y se ve entero al pasar el
  ratón.
- **Actividad: las pistas salían rotas** (todo lo de «Observando · …» y «Te toca elegir…»): su
  tipo iba como clase CSS `hint`, la misma del botón «?» de ayuda, y cada entrada se pintaba
  como un círculo de 17 px con el texto desbordado encima de las demás. Ahora el tipo va en
  `data-kind`.
- Simulador pro sin conexión con gol.gg: el selector de torneo se quedaba en «Cargando…» para
  siempre. Ahora sale «Reintentar gol.gg».
- «En partida»: los porcentajes de la ventaja de draft usaban los colores de daño físico y mágico
  (naranja y morado); ahora, los de la barra y los equipos (azul y rojo).
- Accesibilidad: la pestaña activa se anuncia (`aria-current`) y el modelo de matchups de Ajustes
  dice cuál está elegido (`aria-checked`), como el resto de selectores.
- Ajustes decía que Nachero marca su recomendación «una vez»: desde la 0.31.1 la va cambiando.
- Plan de Tu pool: «Todos tus campeones son de elegir pronto» salía también con campeones
  intermedios; ahora dice cuáles son de elegir pronto y que falta un counter.

### Seguridad
- **El panel solo atiende al propio panel.** Escucha en 127.0.0.1, pero cualquier web abierta en
  el navegador podía mandarle órdenes: activar «Confirmar pick», cambiar la fuente de datos o el
  inicio con Windows, marcar un campeón o pedir un intercambio. Con un nombre que apunte a
  127.0.0.1 (DNS rebinding) podía además leer tu estado. Ahora rechaza (403) las peticiones con
  otro `Host` u otro `Origin` y los POST que no son JSON (desde otra web, eso exige un permiso
  CORS que el panel nunca da). Cuerpos de más de 1 MiB o que no son un objeto JSON, 413 y 400.

### Cambiado
- Si el cliente rechaza confirmar con `PATCH` (`completed`), Nachero confirma lo que ya está
  marcado con el otro camino de la API local (`POST …/actions/{id}/complete`): un rechazo
  puntual ya no acaba en esquivar la partida.
- Fuera de tu turno, lo marcado es tu **intención de pick** (lo que ven tus aliados), aunque la
  acción guarde una marca anterior. Con tu ban en curso no se toca tu pick: se sigue al acabar los
  bans.
- Si el cliente no deja marcar o confirmar, el registro dice por qué (su mensaje de error).

### Añadido
- **Validar los datos propios frente a Lolalytics** (#21): `scripts/validar_datos.py` compara, por
  rol, el WR relativo y el pick rate (correlación, diferencia media, sesgo), los campeones que más
  se desvían (en errores típicos), cuánto de la muestra es ruido y los matchups de la misma liga.
  Usa lo que ya tiene Nachero en tu carpeta de datos, sin descargar nada, y deja un informe en
  Markdown. Detalle en `docs/DATOS.md`.
- **Bans que no te quitan un combo** (#85, primera parte): con datos propios, la sinergia medida
  de lo que han elegido o marcado tus aliados protege a sus parejas de combo (≥ 1,5 pp) de los
  roles aún libres en tu equipo: no banea Ashe si tu support ha marcado Seraphine. Si aun así sale,
  lo dice («pero hace combo con tu …»). Con Lolalytics (sin sinergias) no cambia nada.
  `Engine.pair_synergies` reúne el cálculo de la sinergia que ya usaba el pick (#77).
- **Tu pick depende de su pareja** (#85, segunda parte): con datos propios, si el spread de
  sinergia de tu pick con un rol aún libre en tu equipo es alto (≥ 1,5 pp) y su mejor pareja
  disponible da 1,5 pp o más, el panel lo dice («Taliyah rinde mucho más con Ahri (+2,1 pp):
  propónselo a tu Mid») con «Copiar mensaje» para el chat. Si tu aliado ya la ha marcado, no sale.
  `Engine.synergy_table` y `Engine.combo_advice`.
- **Registro de diagnóstico de cada selección** en `logs/selecciones` de tu carpeta de datos (las
  10 últimas): acciones, intenciones, reloj y lo que marca, confirma y responde el cliente. Sin
  nombres ni ids de cuenta.

## [0.31.1] - 2026-11-24

### Cambiado
- **Marcar pick sigue la recomendación**: si la recomendación cambia durante el draft, Nachero
  cambia la marca en el cliente (antes marcaba una sola vez por turno y se quedaba con la
  primera). Si marcas otro campeón tú (en el cliente o en el panel), deja de cambiarla en ese
  turno. Una marca anterior de Nachero que el cliente devuelva tarde no cuenta como elección tuya.

## [0.31.0] - 2026-11-22

Vista **«En partida»** (#88): al cargar la partida, la ventana de Nachero enseña los drafts, su
puntuación y tu build. Solo lo que ya ves en la pantalla de carga y nunca dentro del juego.

### Añadido
- **Drafts de los dos equipos** con campeón, rol y hechizos. Los roles rivales se estiman por sus
  campeones (no se leen del cliente); ni nombres, ni rangos, ni historiales de otros jugadores.
- **Ventaja de draft** en puntos de WR: cada campeón se puntúa con el motor del draft (fuerza,
  matchups, encaje, sinergias y composición, sin tu parte personal) y la ventaja es
  (media de tu equipo − media del rival) / 2. Matchup de cada línea y notas de composición.
- **Build recomendada** para tu campeón y rol: inicio, núcleo, botas, varias opciones para el 4.º,
  5.º y 6.º objeto con su WR, y prioridad y orden de habilidades. Sale de las páginas de
  Lolalytics que ya se descargan (sin peticiones nuevas) y va detrás de la interfaz de fuentes
  (`StatsProvider.build`), lista para los datos propios. Coachless, solo como enlace.

## [0.30.0] - 2026-11-22

Datos propios con volumen: el recolector lee también Diamante y Esmeralda (#86).

### Añadido
- **Recolector: `--league diamond_plus` y `emerald_plus`** (recolector 0.2.0). Además de los apex,
  lee los jugadores de `league-v4 /entries` por divisiones y páginas, rotando cada división en
  proporción a su tamaño, con el estado de cada liga en `state/collector.json` (el de antes se
  convierte solo). Cada muestra va a su archivo `<parche>/<región>/<liga>.json.gz`.
- `docs/RECOLECTOR.md`: presupuesto de la clave personal y partidas por parche que da cada liga.

### Cambiado
- **La liga de los datos propios es la de los matchups** (`build_tier`, Esmeralda+ por defecto),
  la misma que la de las páginas de build de Lolalytics. `stats_league` ya no se usa. El panel dice
  la liga de los datos (Esmeralda+, Diamante+ o Master+).
- El recolector pide 7 días de ids en Diamante+ y Esmeralda+ (3 en Master+), en orden aleatorio, y
  deja de pedirlos al tener las partidas de la pasada: allí muchos jugadores juegan poco y cada
  petición cuenta. Recuerda los ids contados un día más de los que pide (antes, 30 días).

### Corregido
- **Partidas por rol**: eran 1/10 de la suma de las del rol (un apaño para que el panel sumara las
  cinco líneas), así que con 5 partidas salía 1 por rol. Ahora son las partidas reales con ese rol
  (suma / 2) y el total del panel es el de la línea con más, con datos propios y con Lolalytics.

## [0.29.0] - 2026-11-22

Draft con **blindability**: las ideas de los vídeos de MachineLoLing sobre quién debe elegir
primero, adaptadas a soloq (#68).

### Añadido
- **Seguro a ciegas / Intermedio / Mejor de counter** en cada pick, en las alternativas, en Tu pool
  y en el simulador pro: probabilidad de que tu rival de línea tenga un counter en su pool si
  eliges el primero, con el spread verdadero del campeón (sin el ruido de las pocas partidas) (#69).
- **Riesgo de counter nuevo** (#72): lo esperado de los rivales que eligen después de ti con los
  campeones que siguen disponibles (sin bans ni ya elegidos). Tu rival de línea coge con
  probabilidad η su mejor respuesta de un pool medio; los de otras líneas eligen para la suya.
  «Te pueden counterear» enseña los rivales que más aportan.
- **Bans según tu hueco** (#73): eligiendo el primero protegen tu pick; eligiendo el último, quitan
  fuerza. La cabecera de bans dice cuál toca.
- **Intercambio de orden de pick** (#74): si un aliado que elige después marca un campeón más
  seguro a ciegas que el tuyo, Nachero sugiere el cambio (y aconseja aceptar o rechazar el que te
  piden), con botón en modo Activo y un mensaje para copiar al chat. Nunca lo hace solo.
- **Plan de Tu pool** (#75): tus seguros a ciegas y tus counters por rol, el tamaño de tu pool
  (regla del 80 %) y qué te falta, con candidatos del parche. En la champ select, una línea dice
  qué toca según tu hueco.
- **¿Acierta Nachero?: a ciegas o de counter** (#71): se apunta el orden de picks y, al acabar la
  partida, la posición real de cada rival. Enseña tu WR a ciegas y de counter, si la probabilidad
  de counter acierta, η medido y cuántos roles rivales acertó Nachero.
- **Sinergias medidas** con datos propios (#77): WR de cada dúo con tus aliados menos el esperado.
- Ajustes **A ciegas y counters**: η, pool medio del rival, modelo de matchups y liga de las
  páginas de matchups.

### Cambiado
- **Matchups con encogimiento bayesiano empírico** (#70): cada *delta 2* se encoge con el spread
  medido de su pareja de roles, que sustituye a los pesos por línea a mano (el modelo clásico
  sigue en Ajustes). Intervalo del 95 % y «dentro del ruido» al pasar el ratón por un matchup.
- **Rol de los rivales con probabilidades** (#70): con campeones flex el matchup se reparte entre
  sus roles posibles en vez de apostar por uno.
- **Matchups y runas de Esmeralda+ por defecto**: unas 5 veces más partidas por matchup que
  Master+ de un parche, donde casi todo es ruido. La fuerza en el parche sigue siendo Master+.
- Simulador pro (#76): riesgo de counter con información completa (el rival siempre responde) y
  bans encogidos por muestra.
- Datos propios: el *delta 2* se calcula con el WR esperado por *odds*.

## [0.28.0] - 2026-11-20

### Cambiado
- **Composición de tu equipo con lo marcado**: cuenta tu campeón y los que tus aliados solo han
  marcado, como estimación («estimado con lo marcado»), en vez de quedarse en 0 hasta que
  confirmen. Nueva barra de reparto de daño físico/mágico en los dos equipos.
- **Desglose del WR más legible**: barras más gruesas con el eje en 0 marcado y las partes que
  no suman nada, atenuadas.
- **Runas con el color de su rama** (Precisión, Dominación, Brujería, Valor, Inspiración).
- **Alternativas como las tarjetas**: tier en píldora junto al nombre y debajo tus partidas y la
  confianza con su punto de color.
- Pantalla de espera: el **mejor pick destaca** con borde dorado, lo que evalúas lleva aro blanco
  y al pasar el ratón la tarjeta sube y muestra «Ver análisis →».
- **Tu pool**: tabla en tarjeta con cabecera fija, **buscador de campeón** y barra de experiencia
  relativa a tu campeón con más maestría.
- Barra superior: el trabajo en segundo plano es una píldora corta («Actualizando 2/5») con el
  detalle en el tooltip, y ya no empuja las pestañas.
- Ajustes: velo con desenfoque, el modo actual marcado («Ahora») y las normas del modo Activo en
  tres puntos.
- Cifras tabulares en toda la app, scroll fino y un fundido corto al cambiar de vista.

## [0.27.0] - 2026-11-20

### Cambiado
- **Pantalla de espera en dos columnas**: los picks a ciegas a la izquierda y, al lado, «Evaluar
  cualquier campeón» y una tarjeta de estado (fuente de datos, parche y su antigüedad, tus
  partidas). Por debajo de 1100 px vuelve a una columna.
- **Tarjetas de pick nuevas**: posición y tier (píldora de color: S dorado, A verde, B azul, C y D
  neutros) en las esquinas, WR estimado grande, y debajo tus partidas y la confianza con un punto
  de color. El detalle completo, al pasar el ratón. **Pulsar una tarjeta la evalúa** al lado, con
  el desglose de por qué sale ese WR.
- Cabecera de la espera con un **punto vivo** mientras escucha al cliente, el botón de demo a la
  derecha y los tres pasos de Nachero en una sola línea en vez de tres tarjetas.
- **Menos texto fijo**: las explicaciones (tu rol, base de la recomendación, modo, alternativas,
  evaluar, Tu pool) pasan a un «?» que se abre al pasar el ratón o con el teclado.
- **Capas de superficie** (fondo, paneles y controles con tonos y sombras distintos), rango en
  una insignia, foco visible con teclado y tier en color también en Tu pool. En Tu pool, evaluar
  y «¿Acierta Nachero?» van uno al lado del otro bajo la tabla.

## [0.26.0] - 2026-11-19

### Añadido
- **Datos propios publicados**: `python -m nachero_collector publicar` escribe `index.json` (con
  `sha256`) para subir la carpeta a un sitio estático (GitHub Pages de un repo de datos, R2…).
  La app (`stats_url`) descarga el archivo del parche y el del anterior al arrancar y cada hora,
  con `ETag`/`If-None-Match`, los guarda en `cache/stats/` y comprueba su `sha256`. Sin red, usa
  los guardados.
- **Fuente de estadísticas** en Ajustes → Datos: automática (propios si hay del parche y la liga;
  si no, Lolalytics, y el panel lo dice), propia o Lolalytics. Cambiarla recarga los datos sin
  reiniciar Nachero.

## [0.25.0] - 2026-11-19

### Añadido
- **Recolector de partidas** con la API de Riot (`src/nachero_collector/`, aparte de la app y del
  `.exe`; ver `docs/RECOLECTOR.md`): jugadores de Master+ de EUW, partidas nuevas de soloq y
  conteos del esquema 1 por parche. Respeta los límites de la clave personal y `Retry-After`. Las
  partidas en bruto se descartan al contarse; la clave solo va en `RIOT_API_KEY`.
- **Tu historial completo**: `python -m nachero_collector historial "Nombre#TAG"` descarga tus
  partidas de la temporada que el cliente ya no da, y Nachero las une a tu historial si dejas
  `history_import.json` en la carpeta de tu perfil.

## [0.24.0] - 2026-11-19

### Añadido
- **Formato de datos propio, esquema 1** (`docs/FORMATO_DATOS.md`): un archivo por parche, región
  y liga (`16.22/euw1/master_plus.json.gz`) con conteos agregados (partidas y victorias) por
  campeón y rol, bans, matchups por pareja de líneas, sinergias de dúo y páginas de runas. Sin
  identificadores de jugadores: el lector rechaza el archivo si los lleva.
- Lector con validación (`sources/dataset.py`) que calcula WR, pick y ban rate, reparto por roles,
  tier, «delta 1/2» de los matchups y las runas más jugada y de mayor WR.
- **Principio de parche**: con pocas partidas se mezcla con el parche anterior; el anterior pesa
  k / (n + k), el mismo encogimiento del motor.
- La fuente «Archivo local» (`stats_sources: ["local"]`) lee un archivo del esquema o una carpeta
  con la estructura publicada.

## [0.23.0] - 2026-11-19

### Añadido
- **¿Acierta Nachero?** (en Tu pool): al confirmar un pick en soloq, flex o normal se apunta el
  WR estimado del campeón, sus partes y lo que recomendaba Nachero; al aparecer la partida en tu
  historial, el resultado. El informe compara WR estimado y real **por tramos**, tu WR **siguiendo
  la recomendación o no**, y cuánto separa **cada parte** las victorias de las derrotas, para
  ajustar los pesos con datos. Avisa si aún hay pocas partidas (< 20).
- Se guarda por cuenta (`predictions.json` en el perfil). Los picks sin partida en un día
  (esquivas, remakes) se descartan. La demo y Practice Tool no cuentan.

## [0.22.0] - 2026-11-19

### Añadido
- **Todos los ajustes desde el panel** (Ajustes → Más ajustes): modo al abrir Nachero
  (`start_mode`), hechizos por rol (`spells_by_role`), tu estilo (`style`: carry y utilidad),
  bans prioritarios por rol (`ban_priority`), puntos extra por campeón (`pool_bonus`, de −5 a 5) y
  campeones que no recomendar nunca (`never_pick`). Ya no hace falta tocar el JSON.
- Validación de todos ellos en `config.apply_settings`: dos hechizos distintos y conocidos, pesos
  de 0 a 2, como mucho 10 bans prioritarios por rol, roles válidos.

## [0.21.0] - 2026-11-19

### Añadido
- **Frescura de los datos**: junto a la recomendación, de qué fuente salen las estadísticas, el
  parche y su antigüedad («Datos: Lolalytics Master+ · parche 16.23 · hace 2 h»). Si tienen más de
  24 h o son de otro parche, se marcan como desfasadas. En Ajustes → Datos, también la del último
  torneo de gol.gg.
- **Aviso si una fuente cambia de formato**: si el lector de Lolalytics, gol.gg o el archivo local
  deja de encontrar datos (cambio de HTML), Nachero sigue con la última caché y lo avisa en
  Actividad (una vez) y en un banner del panel. Un fallo de red no cuenta como cambio de formato.

### Arreglado
- Una tier list de Lolalytics que llega sin campeones ya no pisa la buena guardada.
- Si gol.gg falla al actualizar un torneo, el simulador sigue con los datos guardados de ese torneo.

## [0.20.0] - 2026-11-19

### Añadido
- **Fuentes de estadísticas intercambiables**: el motor solo usa la interfaz `StatsProvider`
  (`domain/stats.py`). Lolalytics es una implementación más; otra lee un archivo local
  (`nachero-stats.json`, formato provisional en `docs/DATOS.md`).
- Ajuste `stats_sources` (por defecto `["lolalytics"]`): varias fuentes en orden, la primera manda
  y las demás cubren lo que le falte. `stats_file` para la ruta del archivo local.
- El panel (Ajustes → Datos) y el diagnóstico dicen de qué fuente salen los datos.
- Tests de contrato comunes que toda fuente debe pasar.

## [0.19.0] - 2026-11-19

### Añadido
- **Autofill**: si el cliente te asigna un rol que no es tu principal ni tu secundario y apenas
  lo juegas (menos de 15 partidas o menos del 10 % de tu historial), el panel lo avisa y la
  recomendación cambia: suma lo **fácil de jugar** que es cada campeón (dificultad del cliente),
  pesa más su **fuerza en el parche** y castiga más el **riesgo de counter**. Entran más campeones
  fuertes del parche como candidatos. Sin historial no se considera autofill.
- **Rol secundario** (`secondary_role`, de la configuración guiada): cuenta como rol tuyo, sin
  ajustes de autofill, y el panel lo indica.

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
- **Auto ban: solo marca**. Con «Banear» (desactivado por defecto), en la fase de bans
  (`BAN_PICK`, nunca en la planificación) Nachero marca el ban recomendado sin confirmarlo: lo
  banea el cliente al acabar el tiempo. Comprueba que el cliente lo muestra (si no, reintenta)
  y, si marcas otro (en el cliente o en el panel), no lo vuelve a tocar. La
  recomendación tiene en cuenta el campeón que Nachero te recomienda jugar (o el que tengas
  marcado) y los picks o intenciones de tus aliados: prioriza a quien los countea (matchups en
  caché) junto con la fuerza en el parche, dice por qué («countea a Taliyah (tu pick) y a
  Garen») y no repite lo que ya han marcado o baneado tus aliados.
- **El bucle de la champ select ya no espera a la red**: las fichas de campeón y el catálogo de
  runas se piden en segundo plano al arrancar, y la caché de Lolalytics se escribe sin bloquear
  al motor. Si analizar la selección tarda más de 3 s, el registro lo dice («Selección lenta: …»).
- **Causa de que no saliera (ni se aplicara) el ban en la fase de bans**: ahí el cliente devuelve
  `[-1]` en `bannable-champion-ids` y el filtro dejaba fuera a todos. Ahora solo cuentan ids
  reales; si no hay, vale la lista de la planificación (igual con `pickable`).
- Una personalizada con bans dice en el registro «con bans, recomiendo como en un draft» en
  lugar de «sin bans».
- Mensajes nuevos en el panel y el registro: «Marcado X · se confirmará a falta de N s» y
  «Has elegido X: se confirmará X».

### Añadido
- **Tu turno de ban en primer plano**: en la fase de bans, con tu ban en curso, el panel enseña
  arriba el ban recomendado con su motivo y los botones de ban; tu pick recomendado pasa debajo.
  En la planificación y en tu turno de pick, el pick vuelve al primer plano.
- **Elegir desde el panel**: en tu turno, botones con las 5 mejores opciones de pick o de ban.
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
