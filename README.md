<h1>
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="assets/logo-dark.svg">
    <img src="assets/logo-light.svg" alt="Nachero" height="48">
  </picture>
</h1>

Asistente de cola y selección de campeón para League of Legends, con panel local.

- Usa la **API local del cliente** (la misma que Blitz o Porofessor). No toca el juego,
  su memoria ni Vanguard, y no lee nombres de jugadores en champ select.
- Estadísticas **Master+ del parche actual** de Lolalytics (cache local, pocas peticiones).
- Estadísticas de **competitivo** de gol.gg para el simulador de drafts pro.
- Tu parte sale de tu **historial** (soloq, flex, normal draft y partida rápida) y tus **puntos de maestría**.

## Requisitos
Windows 10 u 11 con el cliente de LoL abierto. Con el ejecutable no hace falta nada más; desde el
código, Python 3.10 o superior y `pip install -e .` (instala pywebview, para la ventana).

## Ejecutable (lo más fácil para compartir)
Descarga `Nachero.exe` de *Releases* en GitHub (o pídeselo a quien te lo pase), abre el cliente
de LoL y haz doble clic. Nachero se abre en **su propia ventana**, sin consola ni navegador, y
recuerda su tamaño y posición. Cerrar la ventana cierra Nachero. Si ya está abierto, volver a
abrirlo trae su ventana al frente. En la barra de tareas, Menú Inicio y `Alt + Tab` se muestra
como **`Nachero`** con su icono personalizado.

- La ventana usa WebView2, el motor de Edge que ya trae Windows 10 y 11. Si faltara, Nachero lo
  avisa y abre el panel en el navegador; el aviso queda abierto y, al cerrarlo, se cierra Nachero.
- Si algo falla al arrancar, un cuadro de diálogo lo dice con la ruta del registro (`logs`).

- Windows avisa de que es una app desconocida (no está firmada): *Más información → Ejecutar de
  todas formas*. Algún antivirus puede marcarlo por error; es un falso positivo habitual de PyInstaller.
- Tus ajustes y datos van a `%APPDATA%\nachero`, así que puedes sustituir el `.exe` por una
  versión nueva sin perder nada.

Construirlo: `pip install -e ".[build]"` y `python scripts/build_exe.py` → `dist/Nachero.exe`
(`--onedir` hace una carpeta, `dist/Nachero/`, que arranca un segundo antes). Incluye metadatos
de versión de Windows (`version_info.txt`) con `FileDescription = "Nachero"` y el icono multi-resolución.
El icono y el logo salen de `assets/icon.svg` con `python scripts/make_icons.py` (genera el `.ico` con
resoluciones de 16 a 256 px; solo hace falta si cambia el diseño; lo generado ya está en el repositorio).
Publicar una versión: sube la etiqueta (`git tag v0.13.0 && git push origin v0.13.0`) y GitHub
Actions construye el `.exe` y lo publica en *Releases* con las notas del CHANGELOG.

## Uso
Desde esta carpeta:

```
python run.py                     # abre la ventana de Nachero (panel en http://127.0.0.1:8765)
python run.py --browser           # el panel en el navegador, sin ventana (desarrollo)
python run.py --observe           # arranca en modo Observar
python run.py --demo              # draft simulado con tus datos reales
python run.py --no-browser        # ni ventana ni navegador: solo el servidor del panel
python run.py --profile           # tu pool en consola
python run.py --install-shortcut  # crea el acceso directo en el Menú Inicio de Windows
python run.py --port 8766         # otro puerto para el panel
python run.py --version
```

Si lo instalas (`pip install -e .`), el comando es `nachero` con las mismas opciones (instalado bajo
`gui-scripts` para no abrir ventana de consola en Windows).

Para integrar la app con Windows:
```
nachero --install-shortcut
```
Crea `Nachero.lnk` en el Menú Inicio con su icono y `AppUserModelID`, permitiendo anclarlo a la
barra de tareas mostrando `Nachero` y su icono en lugar del ejecutable genérico de Python.

**Bandeja del sistema**: cerrar la ventana deja Nachero en la bandeja (junto al reloj) y sigue
aceptando partidas y leyendo la selección. Clic en su icono para abrirlo; clic derecho para
cambiar de modo o salir. En Ajustes → App: «Cerrar deja Nachero en la bandeja» (desactívalo para
que cerrar salga del todo) y «Abrir al iniciar Windows» (arranca en la bandeja; también `--tray`).

**Aviso de nueva versión**: si `update_url` (en `config.json`) apunta a un `latest.json` público
con `{"version": "0.17.0", "url": "https://…", "notes": "…"}`, Nachero avisa al arrancar.

Si Nachero ya está abierto en ese puerto, volver a ejecutarlo trae su ventana al frente (o abre
su panel en el navegador si va sin ventana). En otro puerto (`--port`) se abre una copia aparte.
Desde un terminal, la consola muestra la actividad; `Ctrl+C` cierra Nachero.

## Primer arranque
Al abrir Nachero por primera vez sale una **bienvenida** de cuatro pantallas (se puede saltar):
qué hace, cómo decide, qué toca en el cliente y qué más tiene. Se vuelve a ver desde **«?»** en la
barra superior, donde también está la versión y el aviso de Riot.

Después, **Empezar** abre la configuración guiada de tu perfil (también en Ajustes → Tu perfil):
rol principal y secundario, campeones que estás practicando (suman 1,5 puntos de WR y entran como
candidatos aunque aún no los hayas jugado) y campeones que nunca quieres jugar.

Cada cuenta de LoL tiene su perfil: historial, maestría y rango se guardan aparte
(`profiles/<puuid>` en la carpeta de datos). Sin cliente, Nachero usa los de la última cuenta.

**Probar con una partida de demo** (en la pantalla de espera o en «?») abre una selección de
campeón simulada con tus datos reales, sin reiniciar y sin tocar el cliente. Se cierra con
«Salir de la demo» o sola si empieza una partida de verdad. `--demo` hace lo mismo al arrancar.

## ¿Acierta Nachero?
En **Tu pool**, abajo: cada pick que confirmas en soloq, flex o normal queda apuntado con su WR
estimado y, al acabar la partida, con el resultado. El informe enseña el WR real en cada tramo de
WR estimado (si en «52–54 %» ganas el 53 %, está bien calibrado), tu WR siguiendo la
recomendación o no, y qué partes de la fórmula separan de verdad victorias y derrotas.

Desde la 0.29 apunta también el **orden de picks**: qué rivales eligieron después de ti (solo el
campeón) y, al acabar, la posición real de cada uno (del detalle de la partida en el cliente). Con
eso enseña tu WR **a ciegas** (tu rival de línea eligió después) y **de counter**, si la
probabilidad de counter acierta, cuánto counterea de verdad tu rival (**η medido**, con el valor
que sugiere para Ajustes) y cuántos roles rivales acertó Nachero.

## Ajustes
Todo se cambia desde el panel (botón de ajustes, arriba a la derecha): modos y qué toca en el
cliente, pesos de la recomendación, tu perfil y, en **Más ajustes**, el modo al abrir Nachero,
los hechizos de cada rol, tu estilo, los bans prioritarios por rol, los puntos extra por campeón
y los campeones que no quieres que te recomiende nunca. En **A ciegas y counters**: cuánto
counterea el rival (η), su pool medio, el modelo de matchups y la liga de las páginas de
matchups. Se guardan en `config.json` de tu carpeta de datos.

## Modos
- **Pausado**: no analiza ni actúa: ni recomienda ni toca el cliente.
- **Observar** (el modo con el que arranca): recomienda y dice qué haría, sin tocar el cliente
  (solo lee la selección de campeón y tu historial). No acepta la partida: para eso, pasa a **Activo**.
- **Activo**: actúa según los interruptores del panel de ajustes (aceptar partida, hechizos,
  importar runas, abrir Coachless y, si los activas, marcar el ban, marcar pick y confirmar pick).

El panel explica cada modo bajo la barra superior y en Ajustes, con lo que tocará en el cliente
según tus interruptores.

**Banear, marcar pick y confirmar pick vienen desactivados**: las normas de Riot no aceptan apps
que tomen decisiones de juego por el jugador. Si los activas, siguen la recomendación de Nachero,
pero **la última palabra es tuya**:
- **Pick**: Nachero marca su recomendación y **la va cambiando** si la recomendación cambia con
  el draft (o si otro se lleva ese campeón), hasta que marques otro tú. A falta de `lock_when_seconds_left` segundos (8 por defecto) confirma **lo que esté
  marcado**: lo suyo si no has tocado nada, o el campeón que hayas marcado tú.
- **Ban**: la recomendación tiene en cuenta tu pick recomendado y los de tus aliados: prioriza a
  quien los countea y a los fuertes del parche, y no repite lo que ya han marcado o baneado tus
  aliados. Con «Banear», en la fase de bans (no en la planificación) Nachero **marca** el primero
  y **no lo confirma**: lo banea el cliente al acabar el tiempo. Si marcas otro, se banea el tuyo.
- **Si marcas otro campeón** (en el cliente o en el panel), Nachero no lo vuelve a cambiar en ese
  turno, aunque el cliente tarde en reflejar tu cambio.
- **Desde el panel**: en tu turno salen las 5 mejores opciones de pick o de ban; un clic la marca
  en el cliente y cuenta como elección tuya. Solo en modo Activo.
- El pick se confirma unos segundos antes del final, no a cero: si no da tiempo, en ranked se
  esquiva.

Si ya los tenías activados, Nachero respeta tus ajustes guardados.

## Otros modos
Fuera de la Grieta (Arena, URF y demás) Nachero no recomienda ni toca el cliente: sus datos son
de soloq Master+. **En ARAM** solo hace una cosa, con «Importar runas» activado y en modo Activo:
crea la página «Nachero · Campeón ARAM» con las runas de ARAM de Lolalytics del campeón que te
toque, y la cambia si cambias de campeón (reroll o banquillo), sin dejar páginas sueltas. Ni
picks, ni bans, ni hechizos. Coachless no se abre en ARAM: no se puede saber si tiene página de
ARAM sin leer su web, y sus condiciones no lo permiten.

## Roles
En la selección de campeón recomienda para el rol que te asigna el cliente, sea cual sea.
Fuera de ella (y en colas sin roles, como Practice Tool) usa tu rol principal: por defecto el que
más juegas, o el que elijas en la pantalla de espera del panel.

### Autofill y rol secundario
Si el cliente te da un rol que no es tu principal ni tu secundario (configuración guiada) y casi
no lo juegas (menos de 15 partidas o menos del 10 % de tu historial), es **autofill**: el panel
lo avisa y la recomendación suma una parte más, **Fácil de jugar** (+0,8 los campeones fáciles,
−1 los difíciles, según el cliente), pesa la fuerza en el parche ×1,25 y el riesgo de counter
×1,6. Un rol que juegas a menudo, aunque no sea el principal, no cuenta como autofill.

### Roles de cada campeón
Cualquier campeón se puede evaluar en cualquier rol. Con el reparto por línea de Master+
(partidas y % de las partidas del campeón en cada línea), cada pareja campeón-rol tiene una categoría:

| Categoría | Criterio (ajustable en `roles` de la config) | Ejemplo |
|---|---|---|
| **Principal** | su rol con más partidas | Katarina mid |
| **Flex** | ≥ 10 % de sus partidas o ≥ 3.000 partidas | Katarina ADC, Jayce jungla, Cassiopeia top |
| **Ocasional** | ≥ 2 % o ≥ 300 partidas | Teemo jungla, Taliyah ADC |
| **Fuera de rol** | el resto | Katarina jungla |

- **Draft**: candidatos = principal y flex del rol entre los fuertes del parche, lo que has jugado
  en el rol (desde 1 partida) y tus campeones con maestría si el rol es al menos ocasional.
- **Tu pool**: con maestría alta, el campeón sale en sus roles principal y flex; cada fila dice sus
  roles («Mid · ADC flex») y se filtra por rol.
- **Confianza** en cada tarjeta, según las partidas en ese rol en Master+: Alta (≥ 5.000),
  Media (≥ 1.000), Baja (≥ 50) o Sin datos.
- **Evaluar cualquier campeón** (Draft y Tu pool): eliges campeón y rol y sale su estimación con su
  confianza, aunque sea Teemo jungla. En la selección de campeón usa el draft actual.
- Si no hay matchups del campeón en ese rol, se usan los de su rol principal con la mitad de peso,
  marcados con «*» como datos de otro rol.

## Cómo recomienda
Hay dos modos (selector en el panel y en ajustes):

- **Con tu pool** (por defecto): tu experiencia y resultados pesan junto a todo lo demás.
- **Solo meta y draft**: ignora tu pool y recomienda entre los ~45 campeones con más fuerza
  en tu rol este parche, por su fuerza y su encaje en el draft.

Cada candidato recibe un **WR estimado = 50 + suma de partes**, todas en puntos de winrate:

| Parte | Qué mide |
|---|---|
| **Tú con él** *(solo con tu pool)* | Experiencia (partidas + maestría/700): unas −6 pp la primera vez, sube hasta ~100-150 partidas. Tu WR y rendimiento (oro, daño, CS frente a tu media del rol), muy encogidos. **Forma**: partidas en los últimos 30 días. |
| **Fuerza en el parche** | WR del campeón en tu rol en Master+ menos la media, encogido por número de partidas. Fuera de su rol principal, se encoge hacia su fuerza allí menos una penalización que crece cuanto menos se juega en tu rol (hasta −4 con el 0 % de sus partidas, nada desde el 10 %). |
| **Rival de línea** | *Delta 2* contra el enemigo que juega tu línea, **encogido por muestra** (bayesiano empírico, ver «Blindability») y ponderado por la probabilidad de que juegue tu línea. |
| **Resto del rival** | Lo mismo contra los otros enemigos. Cuánto importa cada línea lo dice el spread medido de cada pareja de roles (el jungla reparte; el top casi solo mira al top). |
| **Encaje con tu equipo** | Lo que le falta a tu equipo: daño mágico o físico (ponderado por cuánto daño hace cada uno), frontline, control, daño. Y lo que sobra (demasiados carries, más de lo mismo). Los aliados que solo marcan cuentan a la mitad. |
| **Sinergias medidas** *(solo con datos propios)* | WR de cada dúo con tus aliados (por su rol del cliente) menos el esperado por la fuerza de los dos, encogido igual. |
| **Contra su composición** | Ajustes pequeños: poco móvil contra mucho control, frágil contra mucha amenaza de entrada, asesino contra un equipo sin frontline… |
| **Riesgo de counter** | Lo esperado de los rivales que eligen después de ti, con los campeones que siguen disponibles: tu rival de línea, con probabilidad η, coge su mejor respuesta de un pool medio; los de otras líneas eligen para la suya (cuentan poco). Ver «Blindability». |

*Delta 2* = WR real del enfrentamiento − WR esperado por la fuerza de ambos campeones. Mide solo la
interacción, por eso se suma a la fuerza del parche sin contarla dos veces.

El **rol de cada enemigo** está oculto en ranked: se estima con **probabilidades** a partir del % de
partidas que cada campeón juega en cada línea en Master+ (todas las asignaciones posibles), con un
suelo del 1 % para que un pick fuera de rol (un Teemo jungla) no descoloque al resto. Un Sylas
elegido con el mid rival ya claro va casi seguro a top; solo, se reparte entre top y mid.

**Sinergias entre aliados**: Lolalytics solo las sirve a través de su API interna ofuscada, y Nachero
no la usa. Con datos propios (esquema 1) sí se miden; sin ellos, el encaje sale de lo que aporta
cada campeón.

**Bans**: valor = presencia del campeón × (0,4 × fuerza en el meta + 2 × η × P(tu rival de línea
elige después) × cuánto counterea a tus picks). Si eliges el primero (B1/R1), casi todo es proteger
tu pick; si eliges el último, casi todo es quitar fuerza. En ranked los bans son simultáneos y
ocultos: no se intenta adivinar los del rival.

### Blindability: ¿se puede elegir a ciegas?
Ideas de los vídeos de MachineLoLing ([1](https://www.youtube.com/watch?v=3t5dEYyLua0),
[2](https://youtu.be/j7tOMY-HAsk)), adaptadas a soloq (issue #68):

- **Spread**: la desviación típica de los *delta 2* de un campeón contra un rol, sin el ruido de
  las pocas partidas (`spread² = observado² − ruido²`, ruido ≈ 2500/n pp²). Spread bajo = le da
  igual con quién se cruce (Ahri ~1,1 pp); alto = tiene counters y es buen counter (Yasuo ~2,2).
- **Encogimiento bayesiano**: cada matchup se encoge hacia 0 con `k = 2500/spread²` partidas. Con
  1.000 partidas un matchup aún varía ±3,1 pp: contar counters a pelo es casi todo ruido. Con
  poca muestra manda el spread típico de su pareja de roles.
- **Probabilidad de counter**: que tu rival de línea tenga un counter (≥ 2 pp por debajo de lo
  esperado) entre los campeones **disponibles** (sin bans ni ya elegidos) de un pool medio
  (7 campeones, ajustable; nunca se mira quién es). Da la etiqueta **Seguro a ciegas** (≤ 35 %),
  **Intermedio** o **Mejor de counter** (≥ 65 %). Que además lo elija: × η (0,5 por defecto; lo
  mide «¿Acierta Nachero?»).
- **Quién elige primero depende del campeón, no del rol**: si un aliado que elige después marca
  un campeón más ciego que el tuyo, Nachero sugiere el **intercambio de orden** (o aconseja aceptar
  o rechazar el que te piden). Solo aconseja: pedir, aceptar o rechazar es un clic tuyo.
- **Tu pool** dice qué campeones son seguros a ciegas y cuáles de counter, el tamaño de tu pool
  (los que suman el 80 % de tu maestría o de tus partidas en el rol) y qué te falta. En la champ
  select, una línea dice qué toca según tu hueco («Eliges 2.º: tu rival de línea elige después
  con un 60 %…»).
- **Más muestra**: por defecto, las páginas de matchups (y runas) se leen de **Esmeralda+**, unas 5
  veces más partidas por matchup que Master+ de un parche. La fuerza en el parche sigue siendo
  Master+.

Los pesos de **Tu pool**, **Fuerza en el parche**, **Matchups** y **Composición** se ajustan en vivo.

### Condición de victoria (ideas del draft profesional)
Cada campeón tiene etiquetas de su papel en una composición (`tags.py`): engage, dive, followup,
poke, peel, zona, pick, split, scaling y frontline. Con ellas:

- Se detecta la **identidad** de cada equipo: *engage/dive*, *outrange/poke* o *proteger al carry*.
- **Encaje con tu equipo** suma si aportas el engage que falta ("siempre hay que tener alguna
  forma de engage"), si encajas con la identidad del equipo o si rematas su engage, y resta si
  rompes la identidad (poke en una comp de dive).
- **Contra su composición** premia responder a la comp rival (anti-dive contra dive, engage
  contra poke…), con tope de ±1,2 para que nunca compense perder la línea.

## Simulador de draft pro
Pestaña **Simulador pro**: draft de torneo completo (6 bans, 6 picks, 4 bans, 4 picks) con datos
de **gol.gg** del torneo que elijas (por defecto el último gran torneo, p. ej. Worlds 2026).

Para cada paso sugiere picks o bans con sus motivos:

| Parte | Qué mide |
|---|---|
| **Prioridad** | PrioScore de gol.gg (lo fuerte y seguro a ciegas) más el WR pro, encogido. |
| **Flex** | Primera rotación: un campeón que va a varios roles esconde información. |
| **Cohesión** | Lo mismo que el encaje de soloq: identidad, engage, daño, frontline. |
| **Contra su comp** | Respuesta a la composición rival. |
| **Matchup** | Contra el rival de línea y el resto (Master+ de Lolalytics como aproximación). |
| **Riesgo de counter** | Blindability con información completa: el rival siempre busca su mejor respuesta (η = 1) entre lo viable y los roles se conocen. Pronto, campeones seguros a ciegas; al final, los de counter. |
| **Denegar** | Quitarle al rival un campeón prioritario que encaja en sus roles libres. |

Bans: en la primera ronda pesa la prioridad y **no se banea lo que vas a coger tú** antes que el
rival. En la segunda ronda se apunta a los **roles que le faltan al rival** y a los campeones que
**counterean tus picks**.

Los roles de cada equipo se deducen del reparto por rol de cada campeón en el torneo y en Master+.
Un campeón se sugiere en cualquier rol libre que juegue en el torneo (≥ 12 % de sus partidas) o que
sea su rol principal o flex en Master+ (Katarina ADC, Jayce jungla). Si la asignación falla, haz clic
en la etiqueta de rol de un pick para elegirlo a mano («Automático» lo devuelve). Al terminar
el draft da una valoración de ambas composiciones. **Siguiente partida (fearless)** bloquea los
campeones elegidos para la siguiente partida de la serie, y también puedes marcar bloqueos a mano.

Datos: gol.gg permite `/champion/` en su `robots.txt`. Nachero pide 6 páginas por torneo, con
cache de 12 h y 1,5 s entre peticiones.

## Sin cliente abierto
Si el cliente de LoL está cerrado, Nachero usa tu historial y maestría guardados y los datos de
campeones de CommunityDragon (el mismo contenido que el cliente). Al abrir el cliente se conecta solo.

## Tus datos
Ajustes, historial, maestría, cachés y logs se guardan en **`%APPDATA%\nachero`**, no en esta
carpeta. Si vienes de una versión anterior, se mueven solos la primera vez que arrancas.

## Configuración
Los valores por defecto están en `src/nachero/defaults/config.json`; los tuyos, en
`%APPDATA%\nachero\config.json` (solo lo que cambias desde el panel o a mano).
- `pick_mode`: `pool` (por defecto) o `meta` (ignora tu pool).
- `weights`: multiplicadores de cada parte (también desde el panel).
- `pool_bonus`: puntos extra para campeones concretos, p. ej. `{"Zaahen": 1.0}`.
- `never_pick`: campeones que nunca debe recomendar.
- `roles`: umbrales de principal/flex/ocasional, penalización fuera de rol y confianza.
- `ban_priority`: bans que quieres priorizar por rol (el resto se calcula).
- `spells_by_role`, `style`, `start_mode`, `lock_when_seconds_left`.

## Proyecto
- `src/nachero/`: el paquete, por capas (`clients`, `sources`, `domain`, `app`, `ui`).
  Detalles en [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).
- `tests/`: pruebas (sin cliente ni internet).
- [docs/ROADMAP.md](docs/ROADMAP.md): hoja de ruta y normas de Riot que la condicionan.
- [CONTRIBUTING.md](CONTRIBUTING.md): entorno de desarrollo, comprobaciones y flujo de trabajo.
- [CHANGELOG.md](CHANGELOG.md): cambios por versión.

## En partida
Al cargar la partida, la ventana de Nachero cambia a la vista **«En partida»** (nunca dentro del
juego):

- **Los dos drafts**: campeón, rol y hechizos, lo mismo que ves en la pantalla de carga. El rol de
  los rivales es una **estimación** por sus campeones, como en la champ select; no se lee del
  cliente. Ni nombres, ni rangos, ni historiales de otros jugadores.
- **Puntuación de cada campeón** con el motor del draft (fuerza en el parche, matchups, encaje,
  sinergias y composición), sin tu parte personal ni el riesgo de counter, para medir igual a los
  diez. **Ventaja de draft** = (media de tu equipo − media del rival) / 2, en puntos de WR: el WR
  estimado de tu equipo es 50 + ventaja. Matchup de cada línea y notas de composición.
- **Tu build**: objetos iniciales, núcleo, botas, varias opciones para el 4.º, 5.º y 6.º objeto con
  su WR, prioridad y orden de habilidades. Sale de la misma página de Lolalytics que los matchups
  (sin peticiones de más; solo uso personal) y de la fuente que elijas para las runas (más jugada o
  más ganadora). Va detrás de la interfaz de fuentes: los datos propios la podrán dar igual. El
  botón de Coachless solo abre su página.

## Runas
Al confirmar campeón (modo Activo), Nachero crea la página **«Nachero · Campeón Rol»** con las
runas de Lolalytics del parche actual (de la liga de las páginas de matchups: Esmeralda+ por
defecto, se cambia en Ajustes) y la deja activa:

- Fuente: la página **más popular** (por defecto) o la de **mayor WR**, desde el panel de ajustes.
- Solo crea o reemplaza páginas que empiezan por «Nachero»: **nunca toca las tuyas**. Si no queda
  hueco para una página nueva, avisa y no hace nada.
- Si el campeón no tiene datos suficientes en ese rol (p. ej. Zeri jungla), no importa nada; la
  página de Coachless se abre igualmente.
- En modo Observar solo dice qué importaría. El panel muestra las runas del pick recomendado.

Las runas no salen de Coachless: no tiene exportación de runas y sus condiciones no permiten leer
sus datos automáticamente.

## Coachless
No tiene API pública y sus condiciones no permiten leer sus datos automáticamente, así que
Nachero solo abre su página del campeón y rol en tu navegador al confirmar.

## Recomendación
Deja **Confirmar pick** desactivado en ranked: un fallo puede costarte un dodge o un pick
que no querías, y es la parte más dudosa de las normas de Riot.

## Aviso legal
Nachero isn't endorsed by Riot Games and doesn't reflect the views or opinions of Riot Games or
anyone officially involved in producing or managing Riot Games properties. Riot Games, and all
associated properties are trademarks or registered trademarks of Riot Games, Inc.
