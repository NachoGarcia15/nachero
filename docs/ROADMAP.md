# Hoja de ruta

## Normas de Riot que condicionan el producto

- **Registrar el producto** en el Developer Portal, aunque solo use la API local del cliente
  ([políticas](https://developer.riotgames.com/policies/general)). La API local no tiene soporte
  oficial y puede cambiar ([docs](https://developer.riotgames.com/docs/lol)).
- Prohibido: *"Apps that dictate player decisions"*. Los productos *"should not remove game
  decisions, but may highlight decisions that are important and give multiple choices"*.
  → Recomendar sí; **auto-ban, auto-marcar y auto-confirmar no** en versiones compartidas.
  Auto-aceptar: opcional y desactivado por defecto.
- No identificar a jugadores ocultos por el juego (Nachero no lo hace).
- Aviso obligatorio y visible: *"Nachero isn't endorsed by Riot Games and doesn't reflect the
  views or opinions of Riot Games or anyone officially involved in producing or managing Riot
  Games properties…"*.
- Debe existir acceso gratuito.
- Los productos deben obtener los datos de servicios oficiales de Riot: en una versión pública,
  nada de leer Lolalytics ni gol.gg (ver `docs/DATOS.md`).
- Estadísticas agregadas sí; jugadores concretos, MMR o calculadoras de ELO no.
- Desde el 6 de octubre de 2026 Riot bloquea el acceso a la memoria del juego a apps
  desconocidas. Nachero no lee memoria: solo la API local del cliente, que no tiene soporte
  oficial y puede cambiar.
- API keys ([tipos](https://developer.riotgames.com/docs/portal)): *personal* para proyectos
  personales o grupos pequeños; *production* para cualquier uso público. Nunca dentro del ejecutable.

## Fase 0 · Cimientos (hecha)

Repositorio, paquete por capas, datos del usuario fuera del repo, tests, CI, ejecutable de
Windows (0.6.0) y publicación en GitHub Releases.

## Fases siguientes

Seguimiento en la issue fijada **#28** (hoja de ruta) y en los hitos de GitHub. Una issue por
chat, en este orden salvo que el usuario diga otra cosa.

### Fase 1 · Tú y tus amigos
Robustez, ajustes, normas de Riot para uso personal y preparar el cambio de fuente de datos:
#3, #15, #7, #17, #8, #5, #4, #16, #6, #9.

### Fase 2 · Datos propios (clave personal, EUW Master+)
Recolector con la API de Riot, formato propio, publicación, validación y competitivo desde
Leaguepedia: #18, #19, #20, #21, #22. Detalle en `docs/DATOS.md`.

### Fase 3 · Versión pública
Clave de producción y todas las regiones y ligas, cumplimiento de normas, inglés, distribución
pública y privacidad: #23, #24, #25, #26, #27.
