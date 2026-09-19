"""Theme catalog, color semantics, and dark/light helpers for DeskForge UI."""

from __future__ import annotations

from deskforge.domain.models import AppType

DARK_THEMES: tuple[str, ...] = ("darkly", "superhero", "cyborg", "slate", "solar")
LIGHT_THEMES: tuple[str, ...] = ("litera", "flatly", "cosmo", "minty", "journal")
ALL_THEMES: tuple[str, ...] = DARK_THEMES + LIGHT_THEMES

DEFAULT_DARK_THEME = "darkly"
DEFAULT_LIGHT_THEME = "litera"


def is_dark_theme(theme_name: str) -> bool:
    return theme_name in DARK_THEMES


def toggled_theme(current_theme: str) -> str:
    return DEFAULT_LIGHT_THEME if is_dark_theme(current_theme) else DEFAULT_DARK_THEME


def badge_bootstyle_for_type(app_type: AppType) -> str:
    """Return ttkbootstrap inverse badge bootstyle per application type."""
    mapping = {
        AppType.APPIMAGE: "info-inverse",
        AppType.JAR: "warning-inverse",
        AppType.BINARY: "primary-inverse",
        AppType.SCRIPT: "success-inverse",
        AppType.WEBAPP: "secondary-inverse",
    }
    return mapping.get(app_type, "secondary-inverse")


def monogram_color_for_type(app_type: AppType) -> tuple[int, int, int]:
    """RGB color for generated fallback icon badges."""
    mapping = {
        AppType.APPIMAGE: (38, 166, 154),
        AppType.JAR: (230, 126, 34),
        AppType.BINARY: (52, 152, 219),
        AppType.SCRIPT: (46, 204, 113),
        AppType.WEBAPP: (142, 68, 173),
    }
    return mapping.get(app_type, (90, 110, 130))
