"""Importar la pagina de runas recomendada al cliente.

Solo crea, reemplaza o borra paginas cuyo nombre empieza por "Nachero" (o "draftbot", su nombre
antiguo): nunca toca las tuyas.
"""

import threading

from nachero.domain import runes as R


class RuneImporter:
    def __init__(self, catalog_src) -> None:
        """catalog_src: el cliente o CommunityDragon (ambos sirven /lol-game-data/...)."""
        self.src = catalog_src
        self._styles_of: dict[int, int] | None = None
        self.perk_names: dict[int, str] = {}
        self.style_names: dict[int, str] = {}
        self.loading = False  # catálogo pidiéndose en segundo plano (ver preload)

    def preload(self) -> None:
        """Pide el catálogo de runas en segundo plano: describe() no espera mientras llega."""
        self.loading = True

        def load():
            try:
                self.styles_of()
            finally:
                self.loading = False

        threading.Thread(target=load, daemon=True).start()

    def styles_of(self) -> dict[int, int]:
        if self._styles_of is None:
            styles = self.src.get("/lol-game-data/assets/v1/perkstyles.json") or {}
            perks = self.src.get("/lol-game-data/assets/v1/perks.json") or []
            self._styles_of = R.perk_styles(styles) if isinstance(styles, dict) else {}
            self.perk_names = {p["id"]: p["name"] for p in perks if isinstance(p, dict) and "id" in p}
            self.style_names = (
                {s["id"]: s["name"] for s in styles.get("styles", [])} if isinstance(styles, dict) else {}
            )
        return self._styles_of

    def describe(self, rune_set: dict) -> dict | None:
        if self._styles_of is None and self.loading:
            return None  # el catálogo aún no ha llegado: el panel lo describe en el siguiente tick
        return R.describe(rune_set, self.styles_of(), self.perk_names, self.style_names)

    def apply(self, lcu, champion: str, role_short: str, rune_set: dict) -> tuple[bool, str]:
        """Crea la pagina y la deja activa. Devuelve (ok, mensaje para el registro)."""
        page = R.build_page(rune_set, self.styles_of(), R.page_name(champion, role_short))
        if not page:
            return False, f"La recomendación de runas de {champion} no es una página válida: no importo nada"
        pages = lcu.get("/lol-perks/v1/pages") or []
        for p in pages:
            if p.get("isEditable") and R.is_own_page(str(p.get("name", ""))):
                lcu.req("DELETE", f"/lol-perks/v1/pages/{p['id']}")
        inv = lcu.get("/lol-perks/v1/inventory") or {}
        if inv.get("canAddCustomPage") is False:
            return False, "No queda hueco para una página de runas nueva: no toco las tuyas"
        created = lcu.req("POST", "/lol-perks/v1/pages", page)
        if not created:
            return False, f"El cliente rechazó la página de runas de {champion}"
        desc = self.describe(rune_set) or {}
        return (
            True,
            f"Runas importadas: {desc.get('keystone', '')} ({desc.get('primary', '')} + {desc.get('secondary', '')})",
        )
