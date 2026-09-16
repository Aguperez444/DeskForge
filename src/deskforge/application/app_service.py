"""Application service orchestrating the full lifecycle of desktop-integrated apps."""

from __future__ import annotations

import hashlib
from pathlib import Path
import shutil

from deskforge.domain.categories import normalize_categories
from deskforge.domain.exceptions import AppNotFoundError, ValidationError
from deskforge.domain.models import (
    AppConfig,
    AppType,
    DetectionResult,
    ManagedApp,
    ScanCandidate,
    StorageMode,
    utc_now_iso,
)
from deskforge.infrastructure.app_repository import AppRepository
from deskforge.infrastructure.config_repository import ConfigRepository
from deskforge.infrastructure.desktop_entry import DesktopEntryEngine, ValidationReport, slugify_desktop_id
from deskforge.infrastructure.icon_store import IconStore
from deskforge.infrastructure.inspectors.registry import InspectorRegistry
from deskforge.infrastructure.paths import DeskForgePaths
from deskforge.infrastructure.system_integration import (
    SystemIntegration,
    is_system_binary,
    resolve_executable_target,
)


def _compute_sha256(path: Path) -> str:
    if not path.is_file():
        return ""
    h = hashlib.sha256()
    try:
        with path.open("rb") as fh:
            for chunk in iter(lambda: fh.read(1024 * 1024), b""):
                h.update(chunk)
        return h.hexdigest()
    except OSError:
        return ""


class AppService:
    """Use-case facade for integrating, editing, upgrading, launching, and removing apps."""

    def __init__(
        self,
        paths: DeskForgePaths,
        config_repo: ConfigRepository,
        app_repo: AppRepository,
        desktop_engine: DesktopEntryEngine,
        icon_store: IconStore,
        system: SystemIntegration,
        inspectors: InspectorRegistry,
    ) -> None:
        self._paths = paths
        self._config_repo = config_repo
        self._app_repo = app_repo
        self._desktop_engine = desktop_engine
        self._icon_store = icon_store
        self._system = system
        self._inspectors = inspectors

    # ------------------------------------------------------------------ Queries

    def get_config(self) -> AppConfig:
        return self._config_repo.load()

    def save_config(self, config: AppConfig) -> None:
        self._config_repo.save(config)

    def inspect_target(self, target: str) -> DetectionResult:
        return self._inspectors.inspect(target)

    def list_apps(self, app_type: AppType | None = None, search: str = "") -> list[ManagedApp]:
        apps = self._app_repo.list_all()
        if app_type is not None:
            apps = [a for a in apps if a.app_type == app_type]
        if search.strip():
            q = search.strip().lower()
            apps = [
                a
                for a in apps
                if q in a.name.lower()
                or q in a.comment.lower()
                or q in a.exec_target.lower()
                or any(q in c.lower() for c in a.categories)
                or any(q in k.lower() for k in a.keywords)
            ]
        return apps

    def get_app(self, app_id: str) -> ManagedApp:
        app = self._app_repo.get(app_id)
        if not app:
            raise AppNotFoundError(f"Aplicación '{app_id}' no encontrada.")
        return app

    def find_app(self, query: str) -> ManagedApp:
        return self._app_repo.find_by_id_or_name(query)

    def preview_desktop_entry(self, app: ManagedApp) -> tuple[str, ValidationReport]:
        content = self._desktop_engine.render(app)
        report = self._desktop_engine.validate_content(content)
        return content, report

    def scan_directory(self, directory: Path | None = None) -> list[ScanCandidate]:
        target_dir = directory or self._resolve_scan_dir()
        managed_targets = {a.exec_target for a in self._app_repo.list_all()}
        return self._inspectors.scan_directory(target_dir, already_managed_targets=managed_targets)

    def discover_external_launchers(self) -> list[ManagedApp]:
        """List existing user .desktop applications in ~/.local/share/applications not yet managed by DeskForge."""
        if not self._paths.applications_dir.is_dir():
            return []
        known_desktops = {str(Path(a.desktop_file_path).resolve()) for a in self._app_repo.list_all() if a.desktop_file_path}
        discovered: list[ManagedApp] = []
        for desktop_file in sorted(self._paths.applications_dir.glob("*.desktop")):
            if desktop_file.name == self._system.SELF_DESKTOP_FILENAME:
                continue
            try:
                if str(desktop_file.resolve()) in known_desktops:
                    continue
                parsed = self._desktop_engine.import_from_desktop_file(desktop_file)
                if parsed and not parsed.managed_by_deskforge:
                    discovered.append(parsed)
            except OSError:
                continue
        return discovered

    # ----------------------------------------------------------------- Commands

    def integrate_app(self, app: ManagedApp, source_icon: str | None = None) -> ManagedApp:
        """Integrate a new application into the Linux desktop environment."""
        self._validate_app(app)
        self._paths.ensure_dirs()

        app.categories = normalize_categories(app.categories)
        app.name = app.name.strip()

        # 1. Store/relocate target file according to storage_mode (skipped for WebApps & system/PATH commands)
        if app.app_type != AppType.WEBAPP:
            norm_target, resolved_path, is_sys = resolve_executable_target(app.exec_target)
            if resolved_path is None:
                raise ValidationError(f"El archivo o comando seleccionado no existe: {app.exec_target}")
            if is_sys:
                app.exec_target = norm_target
                app.storage_mode = StorageMode.KEEP
            else:
                final_target = self._place_target_file(resolved_path, app.storage_mode)
                app.exec_target = str(final_target)
                if app.app_type in (AppType.APPIMAGE, AppType.BINARY, AppType.SCRIPT):
                    self._system.make_executable(final_target)
                if not app.working_dir and app.app_type in (AppType.JAR, AppType.BINARY, AppType.SCRIPT):
                    app.working_dir = str(final_target.parent)
                app.sha256 = _compute_sha256(final_target)
        else:
            app.storage_mode = StorageMode.KEEP

        # 2. Persist icon safely inside DeskForge managed icons dir
        chosen_icon = source_icon if source_icon is not None else app.icon_path
        app.icon_path = self._icon_store.store_icon(app.id, chosen_icon, app.app_type)

        # 3. Generate and write .desktop file + optional Desktop shortcut
        app.created_at = app.created_at or utc_now_iso()
        app.updated_at = utc_now_iso()
        app.managed_by_deskforge = True
        self._write_desktop_entries(app)

        # 4. Persist to registry & refresh desktop caches
        self._app_repo.upsert(app)
        self._system.refresh_desktop_caches()
        return app

    def update_app(self, app: ManagedApp, source_icon: str | None = None) -> ManagedApp:
        """Update metadata/settings of an existing managed application and rewrite its .desktop file."""
        existing = self.get_app(app.id)
        self._validate_app(app)
        self._paths.ensure_dirs()

        app.categories = normalize_categories(app.categories)
        app.name = app.name.strip()
        app.created_at = existing.created_at
        app.updated_at = utc_now_iso()

        if app.app_type != AppType.WEBAPP:
            norm_target, resolved_path, is_sys = resolve_executable_target(app.exec_target)
            if resolved_path is not None:
                app.exec_target = norm_target
                if not is_sys:
                    if app.app_type in (AppType.APPIMAGE, AppType.BINARY, AppType.SCRIPT):
                        self._system.make_executable(resolved_path)
                    app.sha256 = _compute_sha256(resolved_path)

        chosen_icon = source_icon if source_icon is not None else app.icon_path
        if chosen_icon != existing.icon_path or not app.icon_path:
            app.icon_path = self._icon_store.store_icon(app.id, chosen_icon, app.app_type)

        # Preserve desktop file path unless missing
        app.desktop_file_path = existing.desktop_file_path
        old_shortcut = existing.desktop_shortcut_path
        if not app.create_desktop_shortcut and old_shortcut:
            self._unlink_if_exists(Path(old_shortcut))
            app.desktop_shortcut_path = ""
        else:
            app.desktop_shortcut_path = old_shortcut

        self._write_desktop_entries(app)
        self._app_repo.upsert(app)
        self._system.refresh_desktop_caches()
        return app

    def replace_binary(self, app_id: str, new_file_path: str | Path, refresh_icon: bool = False) -> ManagedApp:
        """
        Gear Lever-style in-place app upgrade:
        Replaces the underlying binary/AppImage/JAR while preserving all custom settings
        (env vars, JVM memory/JDK, categories, GPU toggle, desktop shortcut).
        """
        app = self.get_app(app_id)
        if app.app_type == AppType.WEBAPP:
            raise ValidationError("Las WebApps no tienen un archivo binario que reemplazar.")

        new_src = Path(new_file_path).expanduser().resolve()
        if not new_src.is_file():
            raise ValidationError(f"El nuevo archivo no existe: {new_src}")

        detection = self._inspectors.inspect(str(new_src))
        old_target = Path(app.exec_target)

        # If target is stored inside DeskForge's managed folder, replace cleanly in-place
        is_in_managed = False
        try:
            is_in_managed = old_target.parent.resolve() == self._managed_apps_dir().resolve()
        except OSError:
            pass

        if is_in_managed:
            dest_path = old_target.parent / new_src.name
            backup_path = old_target.with_suffix(old_target.suffix + ".bak")
            try:
                if old_target.exists():
                    shutil.move(str(old_target), str(backup_path))
                if app.storage_mode == StorageMode.MOVE:
                    shutil.move(str(new_src), str(dest_path))
                else:
                    shutil.copy2(str(new_src), str(dest_path))
                if backup_path.exists():
                    backup_path.unlink()
            except OSError as exc:
                # Rollback backup on failure
                if backup_path.exists() and not old_target.exists():
                    shutil.move(str(backup_path), str(old_target))
                raise ValidationError(f"Error al reemplazar el archivo: {exc}") from exc
            app.exec_target = str(dest_path.resolve())
        else:
            # External KEEP file: point to the new file directly
            app.exec_target = str(new_src)

        if app.app_type in (AppType.APPIMAGE, AppType.BINARY, AppType.SCRIPT):
            self._system.make_executable(Path(app.exec_target))

        app.sha256 = _compute_sha256(Path(app.exec_target))
        if detection.version:
            app.version = detection.version
        if refresh_icon and detection.selected_icon:
            app.icon_path = self._icon_store.store_icon(app.id, detection.selected_icon, app.app_type)

        app.updated_at = utc_now_iso()
        self._write_desktop_entries(app)
        self._app_repo.upsert(app)
        self._system.refresh_desktop_caches()
        return app

    def import_external_launcher(self, external_app: ManagedApp) -> ManagedApp:
        """Adopt an existing external .desktop entry into DeskForge management."""
        old_desktop = Path(external_app.desktop_file_path) if external_app.desktop_file_path else None
        external_app.storage_mode = StorageMode.KEEP
        external_app.managed_by_deskforge = True
        integrated = self.integrate_app(external_app, source_icon=external_app.icon_path)
        # Remove original duplicate .desktop if it had a different filename inside user applications dir
        if (
            old_desktop
            and old_desktop.exists()
            and old_desktop.parent.resolve() == self._paths.applications_dir.resolve()
            and old_desktop.resolve() != Path(integrated.desktop_file_path).resolve()
        ):
            self._unlink_if_exists(old_desktop)
            self._system.refresh_desktop_caches()
        return integrated

    def remove_app(
        self,
        app_id: str,
        delete_target_file: bool = False,
        use_trash: bool = True,
    ) -> ManagedApp:
        """Completely uninstall a managed app launcher and optionally remove its binary."""
        app = self._app_repo.delete(app_id)

        if app.desktop_file_path:
            self._unlink_if_exists(Path(app.desktop_file_path))
        if app.desktop_shortcut_path:
            self._unlink_if_exists(Path(app.desktop_shortcut_path))

        self._icon_store.remove_icon(app.id, app.icon_path)

        if delete_target_file and app.app_type != AppType.WEBAPP and not is_system_binary(app.exec_target):
            target = Path(app.exec_target)
            if target.is_file():
                trashed = self._system.move_to_trash(target) if use_trash else False
                if not trashed:
                    self._unlink_if_exists(target)

        self._system.refresh_desktop_caches()
        return app

    def launch_app(self, app_id: str) -> None:
        app = self.get_app(app_id)
        self._system.launch_app(app)

    def rewrite_desktop_entry(self, app: ManagedApp) -> None:
        """Rewrite .desktop and desktop shortcut for an existing managed app (used by Doctor)."""
        self._write_desktop_entries(app)
        self._app_repo.upsert(app)
        self._system.refresh_desktop_caches()

    # ------------------------------------------------------------------ Helpers

    def _validate_app(self, app: ManagedApp) -> None:
        if not app.name or not app.name.strip():
            raise ValidationError("Debe ingresar un nombre para la aplicación.")
        if not app.exec_target or not app.exec_target.strip():
            raise ValidationError("Debe seleccionar un archivo ejecutable o ingresar una URL.")
        if app.app_type == AppType.WEBAPP:
            if not app.exec_target.strip().startswith(("http://", "https://")):
                raise ValidationError("La URL de una WebApp debe comenzar con http:// o https://.")

    def _managed_apps_dir(self) -> Path:
        cfg = self._config_repo.load()
        if cfg.managed_apps_dir.strip():
            d = Path(cfg.managed_apps_dir).expanduser()
            d.mkdir(parents=True, exist_ok=True)
            return d
        self._paths.managed_apps_dir.mkdir(parents=True, exist_ok=True)
        return self._paths.managed_apps_dir

    def _resolve_scan_dir(self) -> Path:
        cfg = self._config_repo.load()
        if cfg.scan_directory.strip():
            return Path(cfg.scan_directory).expanduser()
        return self._paths.downloads_dir

    def _place_target_file(self, src: Path, mode: StorageMode) -> Path:
        if mode == StorageMode.KEEP:
            return src
        dest_dir = self._managed_apps_dir()
        if src.parent.resolve() == dest_dir.resolve():
            return src

        dest = dest_dir / src.name
        counter = 1
        while dest.exists():
            dest = dest_dir / f"{src.stem}-{counter}{src.suffix}"
            counter += 1

        if mode == StorageMode.MOVE:
            shutil.move(str(src), str(dest))
        else:
            shutil.copy2(str(src), str(dest))
        return dest.resolve()

    def _write_desktop_entries(self, app: ManagedApp) -> None:
        self._paths.applications_dir.mkdir(parents=True, exist_ok=True)
        if app.desktop_file_path:
            desktop_path = Path(app.desktop_file_path)
        else:
            filename = f"{slugify_desktop_id(app.name, app.id)}.desktop"
            desktop_path = self._paths.applications_dir / filename
            app.desktop_file_path = str(desktop_path)

        content = self._desktop_engine.render(app)
        desktop_path.write_text(content, encoding="utf-8")
        self._system.trust_desktop_file(desktop_path)

        if app.create_desktop_shortcut:
            self._paths.desktop_dir.mkdir(parents=True, exist_ok=True)
            safe_shortcut_name = f"{slugify_desktop_id(app.name, app.id)}.desktop"
            shortcut_path = self._paths.desktop_dir / safe_shortcut_name
            shortcut_path.write_text(content, encoding="utf-8")
            self._system.trust_desktop_file(shortcut_path)
            app.desktop_shortcut_path = str(shortcut_path)
        elif app.desktop_shortcut_path:
            self._unlink_if_exists(Path(app.desktop_shortcut_path))
            app.desktop_shortcut_path = ""

    @staticmethod
    def _unlink_if_exists(path: Path) -> None:
        try:
            if path.exists() or path.is_symlink():
                path.unlink()
        except OSError:
            pass
