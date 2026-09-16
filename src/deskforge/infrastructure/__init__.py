"""Infrastructure layer: filesystem, XDG, OS integration, persistence, and inspectors."""

from deskforge.infrastructure.app_repository import AppRepository
from deskforge.infrastructure.config_repository import ConfigRepository
from deskforge.infrastructure.desktop_entry import DesktopEntryEngine, ValidationReport
from deskforge.infrastructure.icon_store import IconStore
from deskforge.infrastructure.paths import DeskForgePaths
from deskforge.infrastructure.system_integration import SystemIntegration

__all__ = [
    "AppRepository",
    "ConfigRepository",
    "DeskForgePaths",
    "DesktopEntryEngine",
    "IconStore",
    "SystemIntegration",
    "ValidationReport",
]
