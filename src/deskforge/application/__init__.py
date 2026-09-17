"""Application services layer (Use Cases) and dependency composition helper."""

from __future__ import annotations

from dataclasses import dataclass

from deskforge.application.app_service import AppService
from deskforge.application.doctor_service import DoctorService
from deskforge.infrastructure.app_repository import AppRepository
from deskforge.infrastructure.config_repository import ConfigRepository
from deskforge.infrastructure.desktop_entry import DesktopEntryEngine
from deskforge.infrastructure.icon_store import IconStore
from deskforge.infrastructure.inspectors.registry import InspectorRegistry
from deskforge.infrastructure.paths import DeskForgePaths
from deskforge.infrastructure.system_integration import SystemIntegration


@dataclass
class ServiceContainer:
    """Wires infrastructure adapters into application services cleanly."""

    paths: DeskForgePaths
    config_repo: ConfigRepository
    app_repo: AppRepository
    desktop_engine: DesktopEntryEngine
    icon_store: IconStore
    system: SystemIntegration
    inspectors: InspectorRegistry
    app_service: AppService
    doctor_service: DoctorService


def build_services(paths: DeskForgePaths | None = None) -> ServiceContainer:
    """Create a fully wired ServiceContainer (accepts custom paths for tests)."""
    base_paths = paths or DeskForgePaths.default()
    config_repo = ConfigRepository(base_paths.config_file)
    config = config_repo.load()

    if paths is None and config.managed_apps_dir.strip():
        base_paths = DeskForgePaths.default(managed_apps_override=config.managed_apps_dir)

    app_repo = AppRepository(base_paths.registry_file)
    desktop_engine = DesktopEntryEngine()
    icon_store = IconStore(base_paths)
    system = SystemIntegration(base_paths, desktop_engine)
    inspectors = InspectorRegistry(base_paths)
    app_service = AppService(
        paths=base_paths,
        config_repo=config_repo,
        app_repo=app_repo,
        desktop_engine=desktop_engine,
        icon_store=icon_store,
        system=system,
        inspectors=inspectors,
    )
    doctor_service = DoctorService(
        paths=base_paths,
        app_repo=app_repo,
        desktop_engine=desktop_engine,
        system=system,
        app_service=app_service,
    )
    return ServiceContainer(
        paths=base_paths,
        config_repo=config_repo,
        app_repo=app_repo,
        desktop_engine=desktop_engine,
        icon_store=icon_store,
        system=system,
        inspectors=inspectors,
        app_service=app_service,
        doctor_service=doctor_service,
    )


__all__ = [
    "AppService",
    "DoctorService",
    "ServiceContainer",
    "build_services",
]
