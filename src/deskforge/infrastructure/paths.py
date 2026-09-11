"""XDG Base Directory and user directory resolution."""

from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import shutil
import subprocess


def _resolve_xdg_user_dir(kind: str, fallback_names: tuple[str, ...]) -> Path:
    """Resolve Desktop/Downloads directory using xdg-user-dir with safe fallbacks."""
    xdg_bin = shutil.which("xdg-user-dir")
    if xdg_bin:
        try:
            proc = subprocess.run(
                [xdg_bin, kind],
                capture_output=True,
                text=True,
                timeout=3,
                check=False,
            )
            out = proc.stdout.strip()
            if proc.returncode == 0 and out:
                return Path(out)
        except OSError:
            pass

    home = Path.home()
    for name in fallback_names:
        candidate = home / name
        if candidate.exists():
            return candidate
    return home / fallback_names[0]


@dataclass(frozen=True)
class DeskForgePaths:
    """Resolved runtime paths for DeskForge (injectable for isolated testing)."""

    data_dir: Path
    config_dir: Path
    cache_dir: Path
    applications_dir: Path
    icons_dir: Path
    managed_apps_dir: Path
    desktop_dir: Path
    downloads_dir: Path
    assets_dir: Path

    @classmethod
    def default(cls, managed_apps_override: str = "") -> DeskForgePaths:
        home = Path.home()
        xdg_data = Path(os.environ.get("XDG_DATA_HOME") or (home / ".local" / "share"))
        xdg_config = Path(os.environ.get("XDG_CONFIG_HOME") or (home / ".config"))
        xdg_cache = Path(os.environ.get("XDG_CACHE_HOME") or (home / ".cache"))

        data_dir = xdg_data / "deskforge"
        config_dir = xdg_config / "deskforge"
        cache_dir = xdg_cache / "deskforge"
        applications_dir = xdg_data / "applications"
        icons_dir = data_dir / "icons"

        if managed_apps_override.strip():
            managed_apps_dir = Path(managed_apps_override).expanduser()
        else:
            managed_apps_dir = home / "Applications" / "DeskForge"

        desktop_dir = _resolve_xdg_user_dir("DESKTOP", ("Desktop", "Escritorio"))
        downloads_dir = _resolve_xdg_user_dir("DOWNLOAD", ("Downloads", "Descargas"))
        assets_dir = Path(__file__).resolve().parent.parent / "assets"

        return cls(
            data_dir=data_dir,
            config_dir=config_dir,
            cache_dir=cache_dir,
            applications_dir=applications_dir,
            icons_dir=icons_dir,
            managed_apps_dir=managed_apps_dir,
            desktop_dir=desktop_dir,
            downloads_dir=downloads_dir,
            assets_dir=assets_dir,
        )

    @property
    def registry_file(self) -> Path:
        return self.data_dir / "registry.json"

    @property
    def config_file(self) -> Path:
        return self.config_dir / "config.json"

    @property
    def default_app_icon(self) -> Path:
        return self.assets_dir / "deskforge.png"

    @property
    def default_jar_icon(self) -> Path:
        return self.assets_dir / "AutoJar.png"

    def ensure_dirs(self) -> None:
        """Create required application directories if they do not exist."""
        for directory in (
            self.data_dir,
            self.config_dir,
            self.cache_dir,
            self.applications_dir,
            self.icons_dir,
            self.managed_apps_dir,
        ):
            directory.mkdir(parents=True, exist_ok=True)
