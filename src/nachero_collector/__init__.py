"""Recolector de partidas con la API de Riot (fase 2, issue #19).

No es parte de la app ni del .exe: se ejecuta aparte (cada hora, en un PC o VPS) con la clave de la
API en la variable de entorno RIOT_API_KEY, que nunca se guarda en el repositorio ni en la app.
Genera los archivos del esquema 1 (docs/FORMATO_DATOS.md) que lee la app. Ver docs/RECOLECTOR.md.
"""

__version__ = "0.1.0"
