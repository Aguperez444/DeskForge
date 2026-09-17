"""Diagnostic & auto-repair service (DeskForge Doctor)."""

from __future__ import annotations

import os
from pathlib import Path
import shutil

from deskforge.application.app_service import AppService
from deskforge.domain.models import AppType, HealthIssue, IssueSeverity
from deskforge.infrastructure.app_repository import AppRepository
from deskforge.infrastructure.desktop_entry import DesktopEntryEngine
from deskforge.infrastructure.paths import DeskForgePaths
from deskforge.infrastructure.system_integration import SystemIntegration, resolve_executable_target


class DoctorService:
    """Audits managed applications and system environment, repairing fixable issues."""

    def __init__(
        self,
        paths: DeskForgePaths,
        app_repo: AppRepository,
        desktop_engine: DesktopEntryEngine,
        system: SystemIntegration,
        app_service: AppService,
    ) -> None:
        self._paths = paths
        self._app_repo = app_repo
        self._desktop_engine = desktop_engine
        self._system = system
        self._app_service = app_service

    def run_checks(self) -> list[HealthIssue]:
        issues: list[HealthIssue] = []

        for app in self._app_repo.list_all():
            # 1. Target binary or $PATH command exists (non-webapp)
            if app.app_type != AppType.WEBAPP:
                _norm, target, is_sys = resolve_executable_target(app.exec_target)
                if target is None:
                    issues.append(
                        HealthIssue(
                            code="MISSING_TARGET",
                            severity=IssueSeverity.ERROR,
                            message=f"Archivo o comando ejecutable faltante: {app.exec_target}",
                            app_id=app.id,
                            app_name=app.name,
                            fixable=False,
                        )
                    )
                elif (
                    not is_sys
                    and app.app_type in (AppType.APPIMAGE, AppType.BINARY, AppType.SCRIPT)
                    and not os.access(target, os.X_OK)
                ):
                    issues.append(
                        HealthIssue(
                            code="NOT_EXECUTABLE",
                            severity=IssueSeverity.WARNING,
                            message=f"Falta permiso de ejecución (+x) en {target.name}",
                            app_id=app.id,
                            app_name=app.name,
                            fixable=True,
                        )
                    )

            # 2. Java runtime check for JAR apps
            if app.app_type == AppType.JAR:
                java_bin = app.java_options.java_path or "java"
                java_exists = Path(java_bin).is_file() if "/" in java_bin else bool(shutil.which(java_bin))
                if not java_exists:
                    issues.append(
                        HealthIssue(
                            code="MISSING_JAVA",
                            severity=IssueSeverity.ERROR,
                            message=f"Runtime Java no encontrado: {java_bin}",
                            app_id=app.id,
                            app_name=app.name,
                            fixable=False,
                        )
                    )

            # 3. .desktop file presence & validity
            desktop_path = Path(app.desktop_file_path) if app.desktop_file_path else None
            if not desktop_path or not desktop_path.is_file():
                issues.append(
                    HealthIssue(
                        code="MISSING_DESKTOP_FILE",
                        severity=IssueSeverity.ERROR,
                        message="Falta el archivo .desktop en ~/.local/share/applications",
                        app_id=app.id,
                        app_name=app.name,
                        fixable=True,
                    )
                )
            else:
                report = self._desktop_engine.validate_content(desktop_path.read_text(encoding="utf-8", errors="replace"))
                if not report.valid:
                    issues.append(
                        HealthIssue(
                            code="INVALID_DESKTOP_FILE",
                            severity=IssueSeverity.ERROR,
                            message=f".desktop inválido: {'; '.join(report.errors)}",
                            app_id=app.id,
                            app_name=app.name,
                            fixable=True,
                        )
                    )

            # 4. Desktop shortcut consistency
            if app.create_desktop_shortcut:
                sc = Path(app.desktop_shortcut_path) if app.desktop_shortcut_path else None
                if not sc or not sc.is_file():
                    issues.append(
                        HealthIssue(
                            code="MISSING_SHORTCUT",
                            severity=IssueSeverity.WARNING,
                            message="Falta el acceso directo en el Escritorio",
                            app_id=app.id,
                            app_name=app.name,
                            fixable=True,
                        )
                    )

            # 5. Icon check (if path-based)
            if app.icon_path and ("/" in app.icon_path) and not Path(app.icon_path).is_file():
                issues.append(
                    HealthIssue(
                        code="MISSING_ICON",
                        severity=IssueSeverity.WARNING,
                        message=f"Ícono faltante: {app.icon_path}",
                        app_id=app.id,
                        app_name=app.name,
                        fixable=True,
                    )
                )

        return issues

    def repair_all(self) -> int:
        """Automatically repair all fixable issues and return count of repaired items."""
        issues = self.run_checks()
        repaired = 0
        apps_to_rewrite: set[str] = set()

        for issue in issues:
            if not issue.fixable or not issue.app_id:
                continue
            app = self._app_repo.get(issue.app_id)
            if not app:
                continue

            if issue.code == "NOT_EXECUTABLE":
                self._system.make_executable(Path(app.exec_target))
                repaired += 1
            elif issue.code in ("MISSING_DESKTOP_FILE", "INVALID_DESKTOP_FILE", "MISSING_SHORTCUT"):
                apps_to_rewrite.add(app.id)
                repaired += 1
            elif issue.code == "MISSING_ICON":
                app.icon_path = ""
                self._app_service.update_app(app, source_icon="")
                repaired += 1

        for app_id in apps_to_rewrite:
            app = self._app_repo.get(app_id)
            if app:
                self._app_service.rewrite_desktop_entry(app)

        return repaired

    def get_system_tools(self) -> dict[str, str | None]:
        return self._system.get_tool_diagnostics()
