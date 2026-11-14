# Cómo trabajar en draftbot

## Entorno

```
python -m venv .venv
.venv\Scripts\python -m pip install -e ".[dev]"
.venv\Scripts\python -m pip install pre-commit
.venv\Scripts\pre-commit install
```

## Antes de subir cambios

```
.venv\Scripts\python -m ruff check src tests run.py
.venv\Scripts\python -m ruff format src tests run.py
.venv\Scripts\python -m mypy
.venv\Scripts\python -m pytest
```

La integración continua ejecuta lo mismo en cada push y pull request.

## Flujo

- `main` siempre funciona. Cada cambio va en su rama (`feat/…`, `fix/…`, `chore/…`, `docs/…`)
  y entra por pull request con la CI en verde.
- Mensajes de commit en imperativo y con prefijo:
  `feat: modo solo meta`, `fix: rol del enemigo flex`, `chore: actualizar ruff`.
- Cada versión: subir `__version__` en `src/draftbot/__init__.py`, anotar en `CHANGELOG.md`
  y etiquetar (`git tag v0.5.0`).

## Reglas del proyecto

- La lógica de recomendación va en `domain/` y no toca red ni disco: así se puede probar.
- Toda fuente de datos nueva va en `sources/`, con caché y respetando su `robots.txt` y sus condiciones.
- Nada de datos personales en el repositorio: viven en `%APPDATA%\draftbot`.
- No automatizar decisiones de juego en versiones compartidas (ver `docs/ROADMAP.md`).
