"""Linux desktop environment integration (permissions, XDG caches, KDE, trash, launch, self-install)."""

from __future__ import annotations

import os
from pathlib import Path
import shutil
import stat
import subprocess
import sys

from deskforge.domain.exceptions import SystemIntegrationError
from deskforge.domain.models import AppType, ManagedApp
from deskforge.infrastructure.desktop_entry import DesktopEntryEngine, escape_exec_arg
from deskforge.infrastructure.paths import DeskForgePaths


SYSTEM_BINARY_PREFIXES = ("/usr/", "/bin/", "/sbin/", "/lib/", "/lib64/")


def is_system_binary(target: str) -> bool:
    """Return True if target is a PATH command name or lives in a read-only system directory."""
    raw = target.strip()
    if not raw:
        return False
    if "/" not in raw and not raw.startswith("."):
        return True
    try:
        resolved = str(Path(raw).expanduser().resolve())
    except OSError:
        resolved = raw
    return resolved.startswith(SYSTEM_BINARY_PREFIXES)


def resolve_executable_target(target: str) -> tuple[str, Path | None, bool]:
    """
    Resolve an Exec target which may be either a local file path or a bare command in $PATH.
    Returns (normalized_target, resolved_path_or_none, is_system_cmd).
    """
    raw = target.strip()
    if not raw:
        return ("", None, False)
    if "/" not in raw and not raw.startswith("."):
        found = shutil.which(raw)
        return (raw, Path(found) if found else None, True)
    path = Path(raw).expanduser().resolve()
    is_sys = str(path).startswith(SYSTEM_BINARY_PREFIXES)
    return (str(path), path if path.is_file() else None, is_sys)


class SystemIntegration:
    """Handles OS-level desktop integration actions safely and portably."""

    SELF_DESKTOP_FILENAME = "deskforge.desktop"
    MIME_TYPES = (
        "application/x-java-archive",
        "application/vnd.appimage",
        "application/x-iso9660-appimage",
        "application/x-shellscript",
    )

    def __init__(self, paths: DeskForgePaths, entry_engine: DesktopEntryEngine | None = None) -> None:
        self._paths = paths
        self._entry_engine = entry_engine or DesktopEntryEngine()

    def make_executable(self, file_path: Path) -> None:
        """Add executable bits (+x) to a file unless it is already executable."""
        if not file_path.exists():
            return
        if os.access(file_path, os.X_OK):
            return
        try:
            current_mode = file_path.stat().st_mode
            file_path.chmod(current_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
        except OSError as exc:
            raise SystemIntegrationError(f"No se pudo asignar permiso de ejecución a {file_path}: {exc}") from exc

    def trust_desktop_file(self, desktop_file: Path) -> None:
        """Mark a .desktop file executable and trusted for GNOME/KDE desktop shortcuts."""
        self.make_executable(desktop_file)
        gio = shutil.which("gio")
        if gio:
            try:
                subprocess.run(
                    [gio, "set", str(desktop_file), "metadata::trusted", "true"],
                    capture_output=True,
                    timeout=3,
                    check=False,
                )
            except (OSError, subprocess.SubprocessError):
                pass

    def refresh_desktop_caches(self) -> list[str]:
        """Refresh XDG, KDE Plasma, and GTK icon caches so new launchers appear immediately."""
        ran: list[str] = []
        commands: list[tuple[str, list[str]]] = []

        if upd := shutil.which("update-desktop-database"):
            commands.append(("update-desktop-database", [upd, str(self._paths.applications_dir)]))
        if kbuild := (shutil.which("kbuildsycoca6") or shutil.which("kbuildsycoca5")):
            commands.append((Path(kbuild).name, [kbuild]))

        for name, cmd in commands:
            try:
                subprocess.run(cmd, capture_output=True, timeout=8, check=False)
                ran.append(name)
            except (OSError, subprocess.SubprocessError):
                continue
        return ran

    def move_to_trash(self, file_path: Path) -> bool:
        """Move a file to desktop trash via gio trash; return True if trashed."""
        if not file_path.exists():
            return True
        gio = shutil.which("gio")
        if gio:
            try:
                proc = subprocess.run(
                    [gio, "trash", str(file_path)],
                    capture_output=True,
                    timeout=5,
                    check=False,
                )
                if proc.returncode == 0:
                    return True
            except (OSError, subprocess.SubprocessError):
                pass
        return False

    def open_in_file_manager(self, path: Path) -> None:
        """Open a folder (or parent folder of a file) in the system file manager."""
        target = path if path.is_dir() else path.parent
        opener = shutil.which("xdg-open")
        if not opener:
            raise SystemIntegrationError("No se encontró 'xdg-open' en el sistema.")
        subprocess.Popen([opener, str(target)], start_new_session=True)

    def launch_app(self, app: ManagedApp) -> None:
        """Launch a managed application detached from DeskForge."""
        # Prefer gtk-launch/kioclient/gio launch when a valid .desktop exists and terminal=True
        if app.terminal and app.desktop_file_path and Path(app.desktop_file_path).exists():
            if gio := shutil.which("gio"):
                try:
                    subprocess.Popen([gio, "launch", app.desktop_file_path], start_new_session=True)
                    return
                except OSError:
                    pass

        resolved_target: Path | None = None
        is_sys_cmd = False
        if app.app_type != AppType.WEBAPP:
            _norm, resolved_target, is_sys_cmd = resolve_executable_target(app.exec_target)
            if resolved_target is None:
                raise SystemIntegrationError(f"El archivo o comando ejecutable no existe: {app.exec_target}")

        tokens = self._entry_engine.build_exec_tokens(app)
        env = os.environ.copy()
        # Extract leading `env K=V` tokens directly into subprocess env for cleaner spawning
        if tokens and tokens[0] == "env":
            idx = 1
            while idx < len(tokens) and "=" in tokens[idx]:
                k, v = tokens[idx].split("=", 1)
                env[k] = v
                idx += 1
            tokens = tokens[idx:]

        if not tokens:
            raise SystemIntegrationError("El comando de ejecución está vacío.")

        cwd: str | None = None
        if app.working_dir and Path(app.working_dir).is_dir():
            cwd = app.working_dir
        elif app.app_type != AppType.WEBAPP and not is_sys_cmd and resolved_target and resolved_target.parent.is_dir():
            cwd = str(resolved_target.parent)

        try:
            subprocess.Popen(
                tokens,
                cwd=cwd,
                env=env,
                start_new_session=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except OSError as exc:
            raise SystemIntegrationError(f"No se pudo lanzar '{app.name}': {exc}") from exc

    def detect_system_dark_mode(self) -> bool:
        """Detect whether KDE Plasma or GNOME is currently using a dark theme."""
        # 1. KDE Plasma (~/.config/kdeglobals)
        kdeglobals = Path.home() / ".config" / "kdeglobals"
        if kdeglobals.exists():
            try:
                content = kdeglobals.read_text(encoding="utf-8", errors="ignore")
                for line in content.splitlines():
                    stripped = line.strip()
                    if stripped.startswith("ColorScheme=") and "dark" in stripped.lower():
                        return True
                    if stripped.startswith("BackgroundNormal="):
                        rgb = [int(x) for x in stripped.split("=", 1)[1].split(",")[:3]]
                        if len(rgb) == 3 and (0.299 * rgb[0] + 0.587 * rgb[1] + 0.114 * rgb[2]) < 128:
                            return True
            except (OSError, ValueError):
                pass

        # 2. GNOME / GTK via gsettings
        if gsettings := shutil.which("gsettings"):
            try:
                proc = subprocess.run(
                    [gsettings, "get", "org.gnome.desktop.interface", "color-scheme"],
                    capture_output=True,
                    text=True,
                    timeout=2,
                    check=False,
                )
                if "dark" in proc.stdout.lower():
                    return True
            except (OSError, subprocess.SubprocessError):
                pass

        return True  # Modern dark default

    def get_tool_diagnostics(self) -> dict[str, str | None]:
        """Return availability map of external Linux desktop tools."""
        tools = (
            "java",
            "unsquashfs",
            "7z",
            "xdg-user-dir",
            "gio",
            "desktop-file-validate",
            "update-desktop-database",
            "kbuildsycoca6",
            "rsvg-convert",
        )
        return {tool: shutil.which(tool) for tool in tools}

    def install_self_desktop_entry(self) -> Path:
        """Install DeskForge into ~/.local/share/applications with Open With MIME associations."""
        self._paths.ensure_dirs()
        desktop_path = self._paths.applications_dir / self.SELF_DESKTOP_FILENAME

        # Copy official icon into managed icons directory for stability
        icon_dest = self._paths.icons_dir / "deskforge-app.png"
        if self._paths.default_app_icon.exists():
            shutil.copy2(self._paths.default_app_icon, icon_dest)
            icon_value = str(icon_dest)
        else:
            icon_value = "application-x-executable"

        # Prefer installed `deskforge` binary if on PATH, otherwise python3 + main.py / module
        deskforge_bin = shutil.which("deskforge")
        if deskforge_bin:
            exec_cmd = f"{escape_exec_arg(deskforge_bin)} %f"
        else:
            project_root = Path(__file__).resolve().parents[3]
            main_py = project_root / "main.py"
            if main_py.exists():
                exec_cmd = f"{escape_exec_arg(sys.executable)} {escape_exec_arg(str(main_py))} %f"
            else:
                exec_cmd = f"{escape_exec_arg(sys.executable)} -m deskforge.cli.main %f"

        mime_line = ";".join(self.MIME_TYPES) + ";"
        content = "\n".join(
            [
                "[Desktop Entry]",
                "Version=1.5",
                "Type=Application",
                "Name=DeskForge",
                "GenericName=Integrador de Aplicaciones",
                "Comment=Integra y gestiona AppImages, JARs, binarios portables, scripts y WebApps en tu escritorio",
                f"Exec={exec_cmd}",
                f"Icon={icon_value}",
                "Terminal=false",
                "StartupNotify=true",
                "StartupWMClass=DeskForge",
                "Categories=System;Utility;",
                "Keywords=appimage;jar;launcher;desktop;shortcut;gear lever;autojar;",
                f"MimeType={mime_line}",
                "",
            ]
        )
        desktop_path.write_text(content, encoding="utf-8")
        self.trust_desktop_file(desktop_path)
        self.refresh_desktop_caches()
        return desktop_path

    def uninstall_self_desktop_entry(self) -> bool:
        """Remove DeskForge's own .desktop launcher."""
        desktop_path = self._paths.applications_dir / self.SELF_DESKTOP_FILENAME
        removed = False
        if desktop_path.exists():
            desktop_path.unlink()
            removed = True
        self.refresh_desktop_caches()
        return removed

    def is_self_installed(self) -> bool:
        return (self._paths.applications_dir / self.SELF_DESKTOP_FILENAME).exists()
