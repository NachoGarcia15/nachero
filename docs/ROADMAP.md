# Hoja de ruta

**Objetivo**: hoy, uso personal y con amigos; en el futuro, una **versión pública y
monetizable**. Todo lo nuevo se diseña para que valga también en público: fuentes válidas
(`docs/DATOS.md`), normas de Riot (abajo) y opciones que se puedan quitar o cambiar en la
versión pública.

## Normas de Riot que condicionan el producto

- **Registrar el producto** en el Developer Portal, aunque solo use la API local del cliente
  ([políticas](https://developer.riotgames.com/policies/general)). La API local no tiene soporte
  oficial y puede cambiar ([docs](https://developer.riotgames.com/docs/lol)).
- Prohibido: *"Apps that dictate player decisions"*. Riot también pide que los productos
  *aumenten la diversidad* de decisiones (picks, composiciones): cada recomendación muestra
  **varias opciones con sus motivos**, nunca una sola respuesta. Los productos *"should not remove game
  decisions, but may highlight decisions that are important and give multiple choices"*.
  → Recomendar sí. **Auto-ban (solo marcar: lo confirma el cliente), auto-marcar y
  auto-confirmar el pick solo si** siguen la lógica de la app, son opcionales (desactivados por
  defecto) y **nunca pisan la selección del jugador**: Nachero marca su recomendación, el jugador
  la puede cambiar en el cliente o en el panel, y al final del turno se confirma lo marcado. Al registrar la app (#24) se describe así
  y se pregunta a Riot; si dicen que no, se quitan esos ajustes. Auto-aceptar: opcional.
- No identificar a jugadores ocultos por el juego (Nachero no lo hace) ni detectar dúos premade.
- No dar información de la partida que el jugador no conocía: las predicciones del rival salen
  solo de lo visible en el draft.
- Aviso obligatorio y visible: *"Nachero isn't endorsed by Riot Games and doesn't reflect the
  views or opinions of Riot Games or anyone officially involved in producing or managing Riot
  Games properties…"*.
- **Monetización** (revisado el 22-nov-2026):
  - el producto debe estar registrado con estado *Approved* o *Acknowledged*;
  - **nivel gratuito** obligatorio, que puede llevar publicidad, pero nunca dentro del cliente
    de Riot (ni en la partida ni en la pantalla de carga);
  - si se cobra, el contenido debe ser **transformativo** (información o análisis nuevos):
    blindability, combos, plan de pool, calibración y simulador pro;
  - formas permitidas: suscripción, donaciones o crowdfunding; nada de apuestas ni precios
    abusivos. Detalle en #24.
- Los productos deben obtener los datos de servicios oficiales de Riot: en una versión pública,
  nada de leer Lolalytics ni gol.gg. Soloq con datos propios de la API de Riot y competitivo con
  Leaguepedia (ver `docs/DATOS.md`).
- Estadísticas agregadas sí; jugadores concretos, MMR o calculadoras de ELO no.
- Desde el 6 de octubre de 2026 Riot bloquea el acceso a la memoria del juego a apps
  desconocidas. Nachero no lee memoria: solo la API local del cliente, que no tiene soporte
  oficial y puede cambiar.
- API keys ([tipos](https://developer.riotgames.com/docs/portal)), gratuitas: *development*
  (caduca cada 24 h), *personal* para proyectos personales o grupos pequeños (#7) y *production*
  para cualquier uso público (#23). Nunca dentro del ejecutable. Pasos en `docs/DATOS.md`.

## Fase 0 · Cimientos (hecha)

Repositorio, paquete por capas, datos del usuario fuera del repo, tests, CI, ejecutable de
Windows (0.6.0) y publicación en GitHub Releases.

## Fases siguientes

Seguimiento en la issue fijada **#28** (hoja de ruta) y en los hitos de GitHub. Una issue por
chat, en este orden salvo que el usuario diga otra cosa.

### Fase 1 · Tú y tus amigos
Robustez, ajustes, normas de Riot para uso personal y preparar el cambio de fuente de datos:
#3, #15, #7, #17, #8, #5, #4, #16, #6, #9.
- Draft con blindability (#68, hecho en 0.29.0).
- Draft con combos (#79): competitivo desde Leaguepedia (#80, hace #22), evaluación con drafts
  reales (#81), combos pro (#82–#84) y sinergias de soloq con datos propios (#85).

### Fase 2 · Datos propios (clave personal, EUW)
Recolector con la API de Riot, formato propio, publicación y validación: #18, #19, #20, #21.
Volumen en Esmeralda+ y Diamante+ para matchups y sinergias: #86. Competitivo desde Leaguepedia
pasa a Fase 1 (#80). Detalle en `docs/DATOS.md`.

### Fase 3 · Versión pública
Clave de producción y todas las regiones y ligas, cumplimiento de normas, inglés, distribución
pública y privacidad: #23, #24, #25, #26, #27.
