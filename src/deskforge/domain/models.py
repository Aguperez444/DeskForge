"""Domain entities and value objects for DeskForge."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any
import uuid


def utc_now_iso() -> str:
    """Return an ISO-8601 UTC timestamp."""
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


class AppType(str, Enum):
    """Supported desktop application types."""

    APPIMAGE = "appimage"
    JAR = "jar"
    BINARY = "binary"
    SCRIPT = "script"
    WEBAPP = "webapp"

    @property
    def label(self) -> str:
        labels = {
            AppType.APPIMAGE: "AppImage",
            AppType.JAR: "JAR (Java)",
            AppType.BINARY: "Binario",
            AppType.SCRIPT: "Script",
            AppType.WEBAPP: "WebApp",
        }
        return labels[self]

    @property
    def short_badge(self) -> str:
        badges = {
            AppType.APPIMAGE: "AppImage",
            AppType.JAR: "JAR",
            AppType.BINARY: "ELF",
            AppType.SCRIPT: "Script",
            AppType.WEBAPP: "WebApp",
        }
        return badges[self]


class StorageMode(str, Enum):
    """How DeskForge stores the target executable file on integration."""

    MOVE = "move"
    COPY = "copy"
    KEEP = "keep"

    @property
    def label_es(self) -> str:
        labels = {
            StorageMode.MOVE: "Mover a carpeta gestionada",
            StorageMode.COPY: "Copiar a carpeta gestionada",
            StorageMode.KEEP: "Mantener en ubicación original",
        }
        return labels[self]


class IssueSeverity(str, Enum):
    """Severity level for diagnostic issues."""

    INFO = "info"
    WARNING = "warning"
    ERROR = "error"


@dataclass
class JavaRuntime:
    """Represents a detected Java runtime installation on the system."""

    path: str
    version: str
    vendor: str = ""
    is_default: bool = False

    @property
    def display_label(self) -> str:
        prefix = "Por defecto — " if self.is_default else ""
        ver = self.version or "Java"
        return f"{prefix}{ver} ({self.path})"


@dataclass
class JavaOptions:
    """JVM launch configuration for JAR applications."""

    java_path: str = "java"
    max_memory: str = ""
    min_memory: str = ""
    jvm_args: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "java_path": self.java_path,
            "max_memory": self.max_memory,
            "min_memory": self.min_memory,
            "jvm_args": list(self.jvm_args),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> JavaOptions:
        if not data:
            return cls()
        return cls(
            java_path=str(data.get("java_path", "java") or "java"),
            max_memory=str(data.get("max_memory", "") or ""),
            min_memory=str(data.get("min_memory", "") or ""),
            jvm_args=[str(a) for a in data.get("jvm_args", []) if str(a).strip()],
        )


@dataclass
class ManagedApp:
    """Core entity representing a desktop-integrated application."""

    name: str
    app_type: AppType
    exec_target: str
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    icon_path: str = ""
    comment: str = ""
    categories: list[str] = field(default_factory=lambda: ["Utility"])
    keywords: list[str] = field(default_factory=list)
    args: list[str] = field(default_factory=list)
    env_vars: dict[str, str] = field(default_factory=dict)
    working_dir: str = ""
    terminal: bool = False
    dedicated_gpu: bool = False
    startup_wm_class: str = ""
    no_display: bool = False
    create_desktop_shortcut: bool = False
    storage_mode: StorageMode = StorageMode.KEEP
    java_options: JavaOptions = field(default_factory=JavaOptions)
    script_interpreter: str = ""
    webapp_browser: str = ""
    version: str = ""
    desktop_file_path: str = ""
    desktop_shortcut_path: str = ""
    sha256: str = ""
    created_at: str = field(default_factory=utc_now_iso)
    updated_at: str = field(default_factory=utc_now_iso)
    managed_by_deskforge: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "app_type": self.app_type.value,
            "exec_target": self.exec_target,
            "icon_path": self.icon_path,
            "comment": self.comment,
            "categories": list(self.categories),
            "keywords": list(self.keywords),
            "args": list(self.args),
            "env_vars": dict(self.env_vars),
            "working_dir": self.working_dir,
            "terminal": self.terminal,
            "dedicated_gpu": self.dedicated_gpu,
            "startup_wm_class": self.startup_wm_class,
            "no_display": self.no_display,
            "create_desktop_shortcut": self.create_desktop_shortcut,
            "storage_mode": self.storage_mode.value,
            "java_options": self.java_options.to_dict(),
            "script_interpreter": self.script_interpreter,
            "webapp_browser": self.webapp_browser,
            "version": self.version,
            "desktop_file_path": self.desktop_file_path,
            "desktop_shortcut_path": self.desktop_shortcut_path,
            "sha256": self.sha256,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "managed_by_deskforge": self.managed_by_deskforge,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ManagedApp:
        raw_type = str(data.get("app_type", AppType.BINARY.value))
        try:
            app_type = AppType(raw_type)
        except ValueError:
            app_type = AppType.BINARY

        raw_storage = str(data.get("storage_mode", StorageMode.KEEP.value))
        try:
            storage_mode = StorageMode(raw_storage)
        except ValueError:
            storage_mode = StorageMode.KEEP

        return cls(
            id=str(data.get("id") or uuid.uuid4().hex[:12]),
            name=str(data.get("name", "")),
            app_type=app_type,
            exec_target=str(data.get("exec_target", "")),
            icon_path=str(data.get("icon_path", "")),
            comment=str(data.get("comment", "")),
            categories=[str(c) for c in data.get("categories", ["Utility"])],
            keywords=[str(k) for k in data.get("keywords", [])],
            args=[str(a) for a in data.get("args", [])],
            env_vars={str(k): str(v) for k, v in (data.get("env_vars") or {}).items()},
            working_dir=str(data.get("working_dir", "")),
            terminal=bool(data.get("terminal", False)),
            dedicated_gpu=bool(data.get("dedicated_gpu", False)),
            startup_wm_class=str(data.get("startup_wm_class", "")),
            no_display=bool(data.get("no_display", False)),
            create_desktop_shortcut=bool(data.get("create_desktop_shortcut", False)),
            storage_mode=storage_mode,
            java_options=JavaOptions.from_dict(data.get("java_options")),
            script_interpreter=str(data.get("script_interpreter", "")),
            webapp_browser=str(data.get("webapp_browser", "")),
            version=str(data.get("version", "")),
            desktop_file_path=str(data.get("desktop_file_path", "")),
            desktop_shortcut_path=str(data.get("desktop_shortcut_path", "")),
            sha256=str(data.get("sha256", "")),
            created_at=str(data.get("created_at") or utc_now_iso()),
            updated_at=str(data.get("updated_at") or utc_now_iso()),
            managed_by_deskforge=bool(data.get("managed_by_deskforge", True)),
        )


@dataclass
class DetectionResult:
    """Output of inspecting a file or URL before integration."""

    target: str
    app_type: AppType
    suggested_name: str
    comment: str = ""
    version: str = ""
    categories: list[str] = field(default_factory=lambda: ["Utility"])
    icon_candidates: list[str] = field(default_factory=list)
    selected_icon: str = ""
    working_dir: str = ""
    terminal: bool = False
    startup_wm_class: str = ""
    script_interpreter: str = ""
    webapp_browser: str = ""
    warnings: list[str] = field(default_factory=list)
    metadata: dict[str, str] = field(default_factory=dict)


@dataclass
class ScanCandidate:
    """An unintegrated application file discovered in a scanned folder."""

    path: str
    app_type: AppType
    name_guess: str
    size_bytes: int
    modified_ts: float


@dataclass
class HealthIssue:
    """A diagnostic finding from DoctorService."""

    code: str
    severity: IssueSeverity
    message: str
    app_id: str | None = None
    app_name: str | None = None
    fixable: bool = False


@dataclass
class AppConfig:
    """User preferences persisted in ~/.config/deskforge/config.json."""

    theme: str = ""  # Empty means auto-detect dark/light on first run
    managed_apps_dir: str = ""  # Empty means ~/Applications/DeskForge
    default_storage_mode: str = StorageMode.MOVE.value
    default_desktop_shortcut: bool = False
    move_to_trash_on_delete: bool = True
    window_geometry: str = "1080x700"
    scan_directory: str = ""  # Empty means XDG Downloads

    def to_dict(self) -> dict[str, Any]:
        return {
            "theme": self.theme,
            "managed_apps_dir": self.managed_apps_dir,
            "default_storage_mode": self.default_storage_mode,
            "default_desktop_shortcut": self.default_desktop_shortcut,
            "move_to_trash_on_delete": self.move_to_trash_on_delete,
            "window_geometry": self.window_geometry,
            "scan_directory": self.scan_directory,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> AppConfig:
        if not data:
            return cls()
        return cls(
            theme=str(data.get("theme", "")),
            managed_apps_dir=str(data.get("managed_apps_dir", "")),
            default_storage_mode=str(data.get("default_storage_mode", StorageMode.MOVE.value)),
            default_desktop_shortcut=bool(data.get("default_desktop_shortcut", False)),
            move_to_trash_on_delete=bool(data.get("move_to_trash_on_delete", True)),
            window_geometry=str(data.get("window_geometry", "1080x700")),
            scan_directory=str(data.get("scan_directory", "")),
        )
