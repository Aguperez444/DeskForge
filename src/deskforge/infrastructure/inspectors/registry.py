"""Unified InspectorRegistry facade and directory scanner for unintegrated apps."""

from __future__ import annotations

from pathlib import Path

from deskforge.domain.models import AppType, DetectionResult, ScanCandidate
from deskforge.infrastructure.inspectors.appimage_inspector import AppImageInspector
from deskforge.infrastructure.inspectors.base import BaseInspector, guess_name_and_version, read_file_header
from deskforge.infrastructure.inspectors.binary_script_inspector import BinaryInspector, ScriptInspector
from deskforge.infrastructure.inspectors.jar_inspector import JarInspector
from deskforge.infrastructure.inspectors.webapp_inspector import WebAppInspector
from deskforge.infrastructure.paths import DeskForgePaths


class InspectorRegistry:
    """Dispatches inspection requests to the best matching Strategy inspector."""

    def __init__(self, paths: DeskForgePaths) -> None:
        self._paths = paths
        self._inspectors: list[BaseInspector] = [
            WebAppInspector(paths),
            AppImageInspector(paths),
            JarInspector(paths),
            ScriptInspector(paths),
            BinaryInspector(paths),  # Fallback catch-all for local files
        ]

    def inspect(self, target: str) -> DetectionResult:
        cleaned = target.strip()
        if cleaned.startswith("file://"):
            from urllib.parse import unquote, urlparse

            cleaned = unquote(urlparse(cleaned).path)

        for inspector in self._inspectors:
            if inspector.can_handle(cleaned):
                return inspector.inspect(cleaned)
        return self._inspectors[-1].inspect(cleaned)

    def scan_directory(
        self,
        directory: Path,
        already_managed_targets: set[str] | None = None,
        max_depth: int = 2,
    ) -> list[ScanCandidate]:
        """Scan a folder (e.g., ~/Downloads) for unintegrated .AppImage and .jar files."""
        if not directory.is_dir():
            return []

        managed = {str(Path(p).expanduser().resolve()) for p in (already_managed_targets or set()) if not p.startswith(("http://", "https://"))}
        candidates: list[ScanCandidate] = []
        base_depth = len(directory.resolve().parts)

        for item in directory.rglob("*"):
            try:
                if not item.is_file():
                    continue
                if len(item.resolve().parts) - base_depth > max_depth:
                    continue
                resolved_str = str(item.resolve())
                if resolved_str in managed:
                    continue

                suffix = item.suffix.lower()
                app_type: AppType | None = None
                if suffix == ".appimage":
                    app_type = AppType.APPIMAGE
                elif suffix == ".jar":
                    app_type = AppType.JAR
                elif suffix == "":
                    hdr = read_file_header(item, 12)
                    if hdr[:4] == b"\x7fELF" and hdr[8:11] in (b"AI\x02", b"AI\x01"):
                        app_type = AppType.APPIMAGE

                if app_type is None:
                    continue

                stat = item.stat()
                name_guess, _ver = guess_name_and_version(item.name)
                candidates.append(
                    ScanCandidate(
                        path=resolved_str,
                        app_type=app_type,
                        name_guess=name_guess,
                        size_bytes=stat.st_size,
                        modified_ts=stat.st_mtime,
                    )
                )
            except OSError:
                continue

        candidates.sort(key=lambda c: c.modified_ts, reverse=True)
        return candidates
