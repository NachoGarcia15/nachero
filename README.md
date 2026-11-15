# Nachero

Asistente de cola y selección de campeón para League of Legends, con panel local.

- Usa la **API local del cliente** (la misma que Blitz o Porofessor). No toca el juego,
  su memoria ni Vanguard, y no lee nombres de jugadores en champ select.
- Estadísticas **Master+ del parche actual** de Lolalytics (cache local, pocas peticiones).
- Estadísticas de **competitivo** de gol.gg para el simulador de drafts pro.
- Tu parte sale de tu **historial** (soloq, flex, normal draft y partida rápida) y tus **puntos de maestría**.

## Requisitos
Windows con el cliente de LoL abierto. Con el ejecutable no hace falta nada más; desde el código,
Python 3.10 o superior (sin librerías extra).

## Ejecutable (lo más fácil para compartir)
Descarga `nachero.exe` de *Releases* en GitHub (o pídeselo a quien te lo pase), abre el cliente
de LoL y haz doble clic. Se abre el panel en el navegador; cerrar la ventana negra cierra Nachero.

- Windows avisa de que es una app desconocida (no está firmada): *Más información → Ejecutar de
  todas formas*. Algún antivirus puede marcarlo por error; es un falso positivo habitual de PyInstaller.
- Tus ajustes y datos van a `%APPDATA%\nachero`, así que puedes sustituir el `.exe` por una
  versión nueva sin perder nada.

Construirlo: `pip install -e ".[build]"` y `python scripts/build_exe.py` → `dist/nachero.exe`.
Publicar una versión: sube la etiqueta (`git tag v0.6.0 && git push origin v0.6.0`) y GitHub
Actions construye el `.exe` y lo publica en *Releases* con las notas del CHANGELOG.

## Uso
Desde esta carpeta:

```
python run.py              # abre el panel en http://127.0.0.1:8765
python run.py --observe    # arranca en modo Observar
python run.py --demo       # draft simulado con tus datos reales
python run.py --no-browser # no abre el navegador
python run.py --profile    # tu pool en consola
python run.py --port 8766  # otro puerto para el panel
python run.py --version
```

Si lo instalas (`pip install -e .`), el comando es `nachero` con las mismas opciones.

Si Nachero ya está abierto, volver a ejecutarlo abre el panel existente.

## Modos
- **Pausado**: no analiza ni actúa: ni recomienda ni toca el cliente.
- **Observar** (el modo con el que arranca): recomienda y dice qué haría, sin tocar el cliente
  (solo lee la selección de campeón y tu historial). No acepta la partida: para eso, pasa a **Activo**.
- **Activo**: actúa según los interruptores del panel de ajustes (aceptar partida, hechizos,
  importar runas, abrir Coachless y, si los activas, banear, marcar pick y confirmar pick).

El panel explica cada modo bajo la barra superior y en Ajustes, con lo que tocará en el cliente
según tus interruptores.

**Banear, marcar pick y confirmar pick vienen desactivados**: deciden por ti, y las normas de Riot
no aceptan apps que tomen decisiones de juego por el jugador. Si ya los tenías activados, Nachero
respeta tus ajustes guardados.

## Roles
En la selección de campeón recomienda para el rol que te asigna el cliente, sea cual sea.
Fuera de ella (y en colas sin roles, como Practice Tool) usa tu rol principal: por defecto el que
más juegas, o el que elijas en la pantalla de espera del panel.

## Cómo recomienda
Hay dos modos (selector en el panel y en ajustes):

- **Con tu pool** (por defecto): tu experiencia y resultados pesan junto a todo lo demás.
- **Solo meta y draft**: ignora tu pool y recomienda entre los ~45 campeones con más fuerza
  en tu rol este parche, por su fuerza y su encaje en el draft.

Cada candidato recibe un **WR estimado = 50 + suma de partes**, todas en puntos de winrate:

| Parte | Qué mide |
|---|---|
| **Tú con él** *(solo con tu pool)* | Experiencia (partidas + maestría/700): unas −6 pp la primera vez, sube hasta ~100-150 partidas. Tu WR y rendimiento (oro, daño, CS frente a tu media del rol), muy encogidos. **Forma**: partidas en los últimos 30 días. |
| **Fuerza en el parche** | WR del campeón en tu rol en Master+ menos la media, encogido por número de partidas. Penaliza campeones fuera de rol. |
| **Rival de línea** | *Delta 2* de Lolalytics contra el enemigo que juega tu línea. |
| **Resto del rival** | *Delta 2* contra los otros enemigos, ponderado por cuánto interactúa tu rol con su línea (p. ej. jungla: mid 0,5, support 0,4, top/ADC 0,35). |
| **Encaje con tu equipo** | Lo que le falta a tu equipo: daño mágico o físico (ponderado por cuánto daño hace cada uno), frontline, control, daño. Y lo que sobra (demasiados carries, más de lo mismo). Los aliados que solo marcan cuentan a la mitad. |
| **Contra su composición** | Ajustes pequeños: poco móvil contra mucho control, frágil contra mucha amenaza de entrada, asesino contra un equipo sin frontline… |
| **Riesgo de counter** | Si tu rival de línea aún no ha elegido y le quedan picks después de ti: castiga campeones con malos matchups frecuentes. |

*Delta 2* = WR real del enfrentamiento − WR esperado por la fuerza de ambos campeones. Mide solo la
interacción, por eso se suma a la fuerza del parche sin contarla dos veces.

El **rol de cada enemigo** se estima con la asignación más probable según el % de partidas que cada
campeón juega en cada línea en Master+.

**Sinergias entre aliados**: Lolalytics solo las sirve a través de su API interna ofuscada, y Nachero
no la usa. El encaje con tu equipo sale de lo que aporta cada campeón, no de estadísticas de parejas.

**Bans**: valor = presencia del campeón en tu rol × (0,4 × fuerza en el meta + cuánto counterea
a tus 3 mejores picks). Lo que de verdad importa es lo que counterea *tu* pool.

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
| **Riesgo de counter** | Si el rival aún puede elegir en tu línea después de ti. |
| **Denegar** | Quitarle al rival un campeón prioritario que encaja en sus roles libres. |

Bans: en la primera ronda pesa la prioridad y **no se banea lo que vas a coger tú** antes que el
rival. En la segunda ronda se apunta a los **roles que le faltan al rival** y a los campeones que
**counterean tus picks**.

Los roles de cada equipo se deducen del reparto por rol de cada campeón en el torneo. Al terminar
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
- `ban_priority`: bans que quieres priorizar por rol (el resto se calcula).
- `spells_by_role`, `style`, `start_mode`, `lock_when_seconds_left`.

## Proyecto
- `src/nachero/`: el paquete, por capas (`clients`, `sources`, `domain`, `app`, `ui`).
  Detalles en [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).
- `tests/`: pruebas (sin cliente ni internet).
- [docs/ROADMAP.md](docs/ROADMAP.md): hoja de ruta y normas de Riot que la condicionan.
- [CONTRIBUTING.md](CONTRIBUTING.md): entorno de desarrollo, comprobaciones y flujo de trabajo.
- [CHANGELOG.md](CHANGELOG.md): cambios por versión.

## Runas
Al confirmar campeón (modo Activo), Nachero crea la página **«Nachero · Campeón Rol»** con las
runas de Lolalytics Master+ del parche actual y la deja activa:

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
