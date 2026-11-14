# Hoja de ruta

## Normas de Riot que condicionan el producto

- **Registrar el producto** en el Developer Portal, aunque solo use la API local del cliente
  ([políticas](https://developer.riotgames.com/policies/general)). La API local no tiene soporte
  oficial y puede cambiar ([docs](https://developer.riotgames.com/docs/lol)).
- Prohibido: *"Apps that dictate player decisions"*. Los productos *"should not remove game
  decisions, but may highlight decisions that are important and give multiple choices"*.
  → Recomendar sí; **auto-ban, auto-marcar y auto-confirmar no** en versiones compartidas.
  Auto-aceptar: opcional y desactivado por defecto.
- No identificar a jugadores ocultos por el juego (draftbot no lo hace).
- Aviso obligatorio y visible: *"draftbot isn't endorsed by Riot Games and doesn't reflect the
  views or opinions of Riot Games or anyone officially involved in producing or managing Riot
  Games properties…"*.
- Debe existir acceso gratuito.
- API keys ([tipos](https://developer.riotgames.com/docs/portal)): *personal* para proyectos
  personales o grupos pequeños; *production* para cualquier uso público. Nunca dentro del ejecutable.

## Fase 0 · Cimientos (hecha)

- [x] Repositorio privado, `.gitignore` sin datos personales, `.gitattributes`
- [x] Paquete por capas (`clients`, `sources`, `domain`, `app`, `ui`)
- [x] Datos del usuario en `%APPDATA%\draftbot`, con migración automática
- [x] `pyproject.toml`, ruff, mypy, pytest, pre-commit
- [x] Tests del motor, del simulador, de los lectores y de la configuración
- [x] CI en GitHub Actions (Windows, Python 3.10 y 3.13)

## Fase 1 · Para ti y tus amigos

- [ ] Perfil por cuenta (puuid): historial y maestría separados si se usan varias cuentas
- [ ] Primer arranque guiado: rol principal/secundario, campeones a practicar, nunca elegir
- [ ] Todos los ajustes editables desde el panel (también bans prioritarios y bonus de pool)
- [ ] Ejecutable de Windows (PyInstaller) sin consola, con icono en la bandeja
- [ ] Publicar versiones en GitHub Releases y aviso de actualización al arrancar
- [ ] Automatizaciones que deciden por el jugador desactivadas por defecto y marcadas como experimentales
- [ ] Aviso legal de Riot visible en el panel
- [ ] Registrar el producto en el Developer Portal (clave personal)
- [ ] Indicador de frescura de datos y aviso si una fuente cambia de formato
- [ ] Medir la calidad: WR estimado frente a resultado real de tus partidas (calibración)

## Fase 2 · Más gente

- [ ] Datos propios: proceso programado con la API de Riot (clave production) que recoge partidas
      Master+, calcula WR por rol y matchups, y publica un archivo por parche
- [ ] Datos de competitivo desde Leaguepedia (licencia CC BY-SA) en lugar de gol.gg
- [ ] Interfaz en español e inglés
- [ ] Firma del ejecutable, página pública, licencia
- [ ] Telemetría solo con consentimiento y anónima
