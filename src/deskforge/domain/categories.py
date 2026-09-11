"""FreeDesktop.org standard main categories with Spanish UI metadata."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class CategoryInfo:
    """Represents a standard FreeDesktop main category."""

    code: str
    label_es: str
    description_es: str


CATEGORIES: tuple[CategoryInfo, ...] = (
    CategoryInfo("Utility", "Utilidad", "Herramientas y utilidades de escritorio"),
    CategoryInfo("Development", "Desarrollo", "IDEs, editores, SDKs y herramientas de programación"),
    CategoryInfo("Game", "Juego", "Juegos, emuladores y lanzadores"),
    CategoryInfo("Network", "Redes", "Navegadores, mensajería, clientes web y red"),
    CategoryInfo("Office", "Oficina", "Productividad, notas, documentos y finanzas"),
    CategoryInfo("Graphics", "Gráficos", "Diseño, dibujo, edición de imágenes y 3D"),
    CategoryInfo("AudioVideo", "Audio y Video", "Multimedia, streaming y producción audiovisual"),
    CategoryInfo("Audio", "Audio", "Reproductores y editores de sonido"),
    CategoryInfo("Video", "Video", "Reproductores y editores de video"),
    CategoryInfo("Education", "Educación", "Aprendizaje, estudio e idiomas"),
    CategoryInfo("Science", "Ciencia", "Matemática, simulación e investigación"),
    CategoryInfo("System", "Sistema", "Monitores, terminales y administración del sistema"),
    CategoryInfo("Settings", "Configuración", "Preferencias y ajustes del entorno"),
)

CATEGORY_BY_CODE: dict[str, CategoryInfo] = {c.code: c for c in CATEGORIES}
CATEGORY_BY_LABEL_ES: dict[str, CategoryInfo] = {c.label_es.lower(): c for c in CATEGORIES}

# Backward-compatible Spanish aliases (including old AutoJar names)
LEGACY_CATEGORY_ALIASES: dict[str, str] = {
    "juego": "Game",
    "audio video": "AudioVideo",
    "audio y video": "AudioVideo",
    "audio": "Audio",
    "video": "Video",
    "educación": "Education",
    "educacion": "Education",
    "desarrollo": "Development",
    "gráficos": "Graphics",
    "graficos": "Graphics",
    "redes": "Network",
    "internet": "Network",
    "oficina": "Office",
    "ciencia": "Science",
    "configuraciones": "Settings",
    "configuración": "Settings",
    "configuracion": "Settings",
    "sistema": "System",
    "utilidad": "Utility",
    "utilidades": "Utility",
}


def get_category_label(code: str) -> str:
    """Return the Spanish display label for a FreeDesktop category code."""
    info = CATEGORY_BY_CODE.get(code)
    return info.label_es if info else code


def resolve_category_code(raw: str) -> str | None:
    """Resolve a Spanish label, legacy alias, or FreeDesktop code into a canonical code."""
    cleaned = raw.strip()
    if not cleaned:
        return None
    if cleaned in CATEGORY_BY_CODE:
        return cleaned
    lower = cleaned.lower()
    if lower in LEGACY_CATEGORY_ALIASES:
        return LEGACY_CATEGORY_ALIASES[lower]
    if lower in CATEGORY_BY_LABEL_ES:
        return CATEGORY_BY_LABEL_ES[lower].code
    # Case-insensitive match against standard codes
    for code in CATEGORY_BY_CODE:
        if code.lower() == lower:
            return code
    return None


def normalize_categories(raw_categories: list[str] | tuple[str, ...]) -> list[str]:
    """Normalize a sequence of categories into unique valid FreeDesktop codes."""
    result: list[str] = []
    seen: set[str] = set()
    for item in raw_categories:
        code = resolve_category_code(item)
        if code and code not in seen:
            seen.add(code)
            result.append(code)
    return result or ["Utility"]
