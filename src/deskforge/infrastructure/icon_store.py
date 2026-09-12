"""Managed icon normalization, SVG conversion fallback, and persistent storage."""

from __future__ import annotations

from pathlib import Path
import shutil
import subprocess

from PIL import Image

from deskforge.domain.models import AppType
from deskforge.infrastructure.paths import DeskForgePaths


class IconStore:
    """Stores normalized copies of app icons inside DeskForge's managed icons folder."""

    MAX_ICON_SIZE = 256

    def __init__(self, paths: DeskForgePaths) -> None:
        self._paths = paths

    def default_icon_for(self, app_type: AppType) -> Path:
        if app_type == AppType.JAR and self._paths.default_jar_icon.exists():
            return self._paths.default_jar_icon
        return self._paths.default_app_icon

    def store_icon(self, app_id: str, source_icon: str | Path | None, app_type: AppType) -> str:
        """
        Persist an icon into DeskForge's managed icons directory.
        - If source_icon is a freedesktop icon theme name (not a path), return it as-is.
        - If source_icon is a valid SVG file, copy as <app_id>.svg and also attempt PNG preview.
        - If source_icon is a raster/ICO image, normalize to PNG <= 256x256.
        - Otherwise fall back to the bundled default icon copied for stability.
        """
        self._paths.icons_dir.mkdir(parents=True, exist_ok=True)

        if source_icon:
            raw = str(source_icon).strip()
            src_path = Path(raw).expanduser()
            # If user supplied a system icon theme name like "utilities-terminal"
            if "/" not in raw and "\\" not in raw and not src_path.exists():
                return raw

            if src_path.is_file():
                # Avoid rewriting onto itself if already stored for this app
                if src_path.parent.resolve() == self._paths.icons_dir.resolve() and src_path.stem == app_id:
                    return str(src_path)

                suffix = src_path.suffix.lower()
                if suffix == ".svg":
                    dest_svg = self._paths.icons_dir / f"{app_id}.svg"
                    shutil.copy2(src_path, dest_svg)
                    return str(dest_svg)

                dest_png = self._paths.icons_dir / f"{app_id}.png"
                if self._convert_to_png(src_path, dest_png):
                    return str(dest_png)

        # Fallback to bundled default icon
        fallback_src = self.default_icon_for(app_type)
        dest_fallback = self._paths.icons_dir / f"{app_id}.png"
        if fallback_src.exists():
            shutil.copy2(fallback_src, dest_fallback)
            return str(dest_fallback)
        return "application-x-executable"

    def remove_icon(self, app_id: str, icon_path: str) -> None:
        """Delete managed icons belonging to app_id (never touches external user files)."""
        if not icon_path:
            return
        try:
            p = Path(icon_path).resolve()
            if p.parent == self._paths.icons_dir.resolve() and p.stem == app_id and p.exists():
                p.unlink()
        except OSError:
            pass
        for ext in (".png", ".svg"):
            candidate = self._paths.icons_dir / f"{app_id}{ext}"
            if candidate.exists():
                try:
                    candidate.unlink()
                except OSError:
                    pass

    def rasterize_svg(self, svg_path: Path, size: int = 64) -> Path | None:
        """Attempt to rasterize an SVG to a cached PNG using available Linux CLI tools."""
        cache_dir = self._paths.cache_dir / "svg_raster"
        cache_dir.mkdir(parents=True, exist_ok=True)
        stat = svg_path.stat()
        out_png = cache_dir / f"{svg_path.stem}_{size}_{int(stat.st_mtime)}.png"
        if out_png.exists():
            return out_png

        converters: list[list[str]] = []
        if rsvg := shutil.which("rsvg-convert"):
            converters.append([rsvg, "-w", str(size), "-h", str(size), str(svg_path), "-o", str(out_png)])
        if ksvg := (shutil.which("ksvgtopng5") or shutil.which("ksvgtopng")):
            converters.append([ksvg, str(size), str(size), str(svg_path), str(out_png)])
        if magick := (shutil.which("magick") or shutil.which("convert")):
            converters.append([magick, "-background", "none", "-resize", f"{size}x{size}", str(svg_path), str(out_png)])

        for cmd in converters:
            try:
                proc = subprocess.run(cmd, capture_output=True, timeout=5, check=False)
                if proc.returncode == 0 and out_png.exists() and out_png.stat().st_size > 0:
                    return out_png
            except (OSError, subprocess.SubprocessError):
                continue
        return None

    def _convert_to_png(self, src: Path, dest: Path) -> bool:
        try:
            with Image.open(src) as img:
                rgba = img.convert("RGBA")
                if max(rgba.size) > self.MAX_ICON_SIZE:
                    rgba.thumbnail((self.MAX_ICON_SIZE, self.MAX_ICON_SIZE), Image.Resampling.LANCZOS)
                rgba.save(dest, format="PNG")
            return True
        except Exception:
            return False
