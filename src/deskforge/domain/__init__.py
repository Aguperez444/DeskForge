"""Pure domain layer: entities, value objects, FreeDesktop taxonomy, and exceptions."""

from deskforge.domain.categories import CATEGORIES, CategoryInfo, get_category_label, normalize_categories
from deskforge.domain.exceptions import (
    AppAlreadyExistsError,
    AppNotFoundError,
    DeskForgeError,
    DesktopEntryError,
    InspectionError,
    SystemIntegrationError,
    ValidationError,
)
from deskforge.domain.models import (
    AppConfig,
    AppType,
    DetectionResult,
    HealthIssue,
    IssueSeverity,
    JavaOptions,
    JavaRuntime,
    ManagedApp,
    ScanCandidate,
    StorageMode,
)

__all__ = [
    "AppAlreadyExistsError",
    "AppConfig",
    "AppNotFoundError",
    "AppType",
    "CATEGORIES",
    "CategoryInfo",
    "DeskForgeError",
    "DesktopEntryError",
    "DetectionResult",
    "HealthIssue",
    "InspectionError",
    "IssueSeverity",
    "JavaOptions",
    "JavaRuntime",
    "ManagedApp",
    "ScanCandidate",
    "StorageMode",
    "SystemIntegrationError",
    "ValidationError",
    "get_category_label",
    "normalize_categories",
]
