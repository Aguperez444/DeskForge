"""Modern dark & light QSS themes and badge semantics for DeskForge (PySide6 / Qt 6)."""

from __future__ import annotations

from deskforge.domain.models import AppType

THEME_DARK = "dark"
THEME_LIGHT = "light"
AVAILABLE_THEMES: tuple[tuple[str, str], ...] = (
    (THEME_DARK, "Oscuro (DeskForge Dark)"),
    (THEME_LIGHT, "Claro (DeskForge Light)"),
)

_LEGACY_DARK_NAMES = {"dark", "darkly", "superhero", "cyborg", "slate", "solar"}
_LEGACY_LIGHT_NAMES = {"light", "litera", "flatly", "cosmo", "minty", "journal"}


def normalize_theme_name(raw: str, system_is_dark: bool = True) -> str:
    """Normalize persisted theme values (including legacy ttkbootstrap names) to 'dark' or 'light'."""
    cleaned = (raw or "").strip().lower()
    if cleaned in _LEGACY_DARK_NAMES:
        return THEME_DARK
    if cleaned in _LEGACY_LIGHT_NAMES:
        return THEME_LIGHT
    return THEME_DARK if system_is_dark else THEME_LIGHT


def is_dark_theme(theme_name: str) -> bool:
    return normalize_theme_name(theme_name) == THEME_DARK


def toggled_theme(current_theme: str) -> str:
    return THEME_LIGHT if is_dark_theme(current_theme) else THEME_DARK


def badge_colors_for_type(app_type: AppType) -> tuple[str, str]:
    """Return (background_hex, foreground_hex) for an AppType pill badge."""
    mapping = {
        AppType.APPIMAGE: ("#147a72", "#e8fffd"),
        AppType.JAR: ("#b8620b", "#fff7ed"),
        AppType.BINARY: ("#1e5fa8", "#edf6ff"),
        AppType.SCRIPT: ("#1f7a44", "#edfff4"),
        AppType.WEBAPP: ("#6d3ea8", "#f6efff"),
    }
    return mapping.get(app_type, ("#4b5563", "#ffffff"))


def monogram_color_for_type(app_type: AppType) -> tuple[int, int, int]:
    """RGB color for generated rounded monogram fallback icons."""
    mapping = {
        AppType.APPIMAGE: (38, 166, 154),
        AppType.JAR: (230, 126, 34),
        AppType.BINARY: (52, 152, 219),
        AppType.SCRIPT: (46, 204, 113),
        AppType.WEBAPP: (142, 68, 173),
    }
    return mapping.get(app_type, (90, 110, 130))


def build_stylesheet(theme_name: str) -> str:
    """Generate a cohesive, HiDPI-friendly Qt stylesheet for DeskForge."""
    dark = is_dark_theme(theme_name)
    if dark:
        p = {
            "bg": "#11161f",
            "surface": "#18202c",
            "surface_alt": "#1f2938",
            "card": "#1a2332",
            "card_hover": "#212d40",
            "border": "#2a374b",
            "border_focus": "#2ec4b6",
            "text": "#eef3f9",
            "text_muted": "#96a6bc",
            "accent": "#2ec4b6",
            "accent_hover": "#3ad7c8",
            "accent_text": "#071a19",
            "success": "#22a06b",
            "success_hover": "#2ab87c",
            "warning": "#d97706",
            "warning_hover": "#f59e0b",
            "danger": "#dc3545",
            "danger_hover": "#ef4444",
            "input_bg": "#131a24",
            "pill_bg": "#1a2332",
            "pill_hover": "#243247",
            "selection": "#1c4b59",
        }
    else:
        p = {
            "bg": "#f3f6fa",
            "surface": "#ffffff",
            "surface_alt": "#e9eef5",
            "card": "#ffffff",
            "card_hover": "#f8fbff",
            "border": "#d5deea",
            "border_focus": "#0d9488",
            "text": "#172030",
            "text_muted": "#5c6c82",
            "accent": "#0d9488",
            "accent_hover": "#0f766e",
            "accent_text": "#ffffff",
            "success": "#168a57",
            "success_hover": "#1ea368",
            "warning": "#c76a08",
            "warning_hover": "#e07b10",
            "danger": "#c82333",
            "danger_hover": "#e03142",
            "input_bg": "#ffffff",
            "pill_bg": "#e7edf5",
            "pill_hover": "#dae3f0",
            "selection": "#ccece8",
        }

    return f"""
    QMainWindow, QDialog {{
        background-color: {p['bg']};
        color: {p['text']};
        font-size: 13px;
    }}
    QWidget {{
        color: {p['text']};
    }}
    QLabel[muted="true"] {{
        color: {p['text_muted']};
    }}
    QLabel#BrandTitle {{
        font-size: 18px;
        font-weight: 700;
        color: {p['text']};
    }}
    QLabel#BrandSubtitle {{
        font-size: 11px;
        color: {p['text_muted']};
    }}
    QFrame#TopBar {{
        background-color: {p['surface']};
        border-bottom: 1px solid {p['border']};
    }}
    QFrame#StatusBar {{
        background-color: {p['surface']};
        border-top: 1px solid {p['border']};
    }}
    QFrame#AppCard {{
        background-color: {p['card']};
        border: 1px solid {p['border']};
        border-radius: 12px;
    }}
    QFrame#AppCard:hover {{
        background-color: {p['card_hover']};
        border: 1px solid {p['border_focus']};
    }}
    QFrame#HeroCard {{
        background-color: {p['card']};
        border: 2px dashed {p['border']};
        border-radius: 16px;
    }}
    QFrame#ToastBanner {{
        border-radius: 10px;
        border: 1px solid rgba(255, 255, 255, 0.14);
    }}
    QFrame#DropOverlay {{
        background-color: rgba(14, 34, 48, 0.90);
        border: 3px dashed {p['accent']};
        border-radius: 18px;
    }}
    QLineEdit, QComboBox, QPlainTextEdit {{
        background-color: {p['input_bg']};
        color: {p['text']};
        border: 1px solid {p['border']};
        border-radius: 8px;
        padding: 6px 10px;
        selection-background-color: {p['selection']};
    }}
    QLineEdit:focus, QComboBox:focus, QPlainTextEdit:focus {{
        border: 1px solid {p['border_focus']};
    }}
    QComboBox::drop-down {{
        border: none;
        width: 24px;
    }}
    QComboBox QAbstractItemView {{
        background-color: {p['surface']};
        color: {p['text']};
        border: 1px solid {p['border']};
        selection-background-color: {p['selection']};
    }}
    QPushButton {{
        background-color: {p['surface_alt']};
        color: {p['text']};
        border: 1px solid {p['border']};
        border-radius: 8px;
        padding: 6px 13px;
        font-weight: 600;
    }}
    QPushButton:hover {{
        background-color: {p['pill_hover']};
        border-color: {p['border_focus']};
    }}
    QPushButton:pressed {{
        background-color: {p['selection']};
    }}
    QPushButton:disabled {{
        color: {p['text_muted']};
    }}
    QPushButton[variant="primary"] {{
        background-color: {p['accent']};
        color: {p['accent_text']};
        border: none;
    }}
    QPushButton[variant="primary"]:hover {{
        background-color: {p['accent_hover']};
    }}
    QPushButton[variant="success"] {{
        background-color: {p['success']};
        color: #ffffff;
        border: none;
    }}
    QPushButton[variant="success"]:hover {{
        background-color: {p['success_hover']};
    }}
    QPushButton[variant="warning"] {{
        background-color: transparent;
        color: {p['warning_hover']};
        border: 1px solid {p['warning']};
    }}
    QPushButton[variant="warning"]:hover {{
        background-color: {p['warning']};
        color: #ffffff;
    }}
    QPushButton[variant="danger"] {{
        background-color: transparent;
        color: {p['danger_hover']};
        border: 1px solid {p['danger']};
    }}
    QPushButton[variant="danger"]:hover {{
        background-color: {p['danger']};
        color: #ffffff;
    }}
    QPushButton[variant="danger-solid"] {{
        background-color: {p['danger']};
        color: #ffffff;
        border: none;
    }}
    QPushButton[variant="danger-solid"]:hover {{
        background-color: {p['danger_hover']};
    }}
    QPushButton[variant="ghost"] {{
        background-color: transparent;
        border: none;
        color: {p['accent']};
        padding: 4px 8px;
    }}
    QPushButton[variant="ghost"]:hover {{
        text-decoration: underline;
    }}
    QPushButton[pill="true"] {{
        background-color: {p['pill_bg']};
        color: {p['text_muted']};
        border: 1px solid {p['border']};
        border-radius: 15px;
        padding: 5px 13px;
        font-size: 12px;
        font-weight: 600;
    }}
    QPushButton[pill="true"]:hover {{
        background-color: {p['pill_hover']};
        color: {p['text']};
    }}
    QPushButton[pill="true"]:checked {{
        background-color: {p['accent']};
        color: {p['accent_text']};
        border-color: {p['accent']};
    }}
    QGroupBox {{
        border: 1px solid {p['border']};
        border-radius: 10px;
        margin-top: 12px;
        padding: 12px 10px 10px 10px;
        font-weight: 700;
    }}
    QGroupBox::title {{
        subcontrol-origin: margin;
        left: 12px;
        padding: 0 6px;
        color: {p['accent']};
    }}
    QTabWidget::pane {{
        border: 1px solid {p['border']};
        border-radius: 10px;
        background-color: {p['surface']};
        top: -1px;
    }}
    QTabBar::tab {{
        background-color: {p['surface_alt']};
        color: {p['text_muted']};
        border: 1px solid {p['border']};
        border-bottom: none;
        border-top-left-radius: 8px;
        border-top-right-radius: 8px;
        padding: 8px 16px;
        margin-right: 4px;
        font-weight: 600;
    }}
    QTabBar::tab:selected {{
        background-color: {p['surface']};
        color: {p['text']};
        border-bottom: 2px solid {p['accent']};
    }}
    QTableWidget, QTreeWidget {{
        background-color: {p['input_bg']};
        alternate-background-color: {p['surface_alt']};
        border: 1px solid {p['border']};
        border-radius: 8px;
        gridline-color: {p['border']};
        selection-background-color: {p['selection']};
        selection-color: {p['text']};
    }}
    QHeaderView::section {{
        background-color: {p['surface_alt']};
        color: {p['text_muted']};
        border: none;
        border-bottom: 1px solid {p['border']};
        padding: 6px 8px;
        font-weight: 600;
    }}
    QScrollArea {{
        border: none;
        background-color: transparent;
    }}
    QScrollBar:vertical {{
        background: transparent;
        width: 10px;
        margin: 2px;
    }}
    QScrollBar::handle:vertical {{
        background: {p['border']};
        border-radius: 5px;
        min-height: 30px;
    }}
    QScrollBar::handle:vertical:hover {{
        background: {p['accent']};
    }}
    QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
        height: 0px;
    }}
    QCheckBox, QRadioButton {{
        spacing: 7px;
    }}
    QProgressBar {{
        border: 1px solid {p['border']};
        border-radius: 5px;
        background-color: {p['input_bg']};
        text-align: center;
        max-height: 10px;
    }}
    QProgressBar::chunk {{
        background-color: {p['accent']};
        border-radius: 4px;
    }}
    """
