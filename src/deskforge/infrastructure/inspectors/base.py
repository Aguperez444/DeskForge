"""Base inspector abstraction and shared naming/heuristic helpers."""

from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path
import re

from deskforge.domain.models import DetectionResult
from deskforge.infrastructure.paths import DeskForgePaths

_ARCH_SUFFIX_RE = re.compile(
    r"[-_.]?(x86_64|amd64|aarch64|arm64|i386|i686|linux|gnu|universal|all|shaded|fat|standalone)$",
    re.IGNORECASE,
)
_VERSION_RE = re.compile(r"[-_.]v?(\d+(?:\.\d+){1,3}(?:[-+._][A-Za-z0-9]+)?)$")


def guess_name_and_version(filename: str) -> tuple[str, str]:
    """Turn filenames like 'Obsidian-1.7.4-x86_64.AppImage' into ('Obsidian', '1.7.4')."""
    stem = Path(filename).name
    # Strip known multi-part or single extensions
    for ext in (".appimage", ".jar", ".sh", ".bash", ".py", ".rb", ".js", ".bin", ".run"):
        if stem.lower().endswith(ext):
            stem = stem[: -len(ext)]
            break

    # Repeatedly peel trailing arch tags and version tokens
    version = ""
    for _ in range(3):
        m_arch = _ARCH_SUFFIX_RE.search(stem)
        if m_arch:
            stem = stem[: m_arch.start()]
            continue
        if not version:
            m_ver = _VERSION_RE.search(stem)
            if m_ver:
                version = m_ver.group(1)
                stem = stem[: m_ver.start()]
                continue
        break

    cleaned = re.sub(r"[-_]+", " ", stem).strip()
    if not cleaned:
        cleaned = Path(filename).stem
    # Title-case only if fully lowercase/uppercase so camelCase like "AutoJar" is preserved
    if cleaned.islower() or cleaned.isupper():
        cleaned = cleaned.title()
    return cleaned, version


def read_file_header(path: Path, size: int = 32) -> bytes:
    """Safely read up to `size` leading bytes from a file."""
    try:
        with path.open("rb") as fh:
            return fh.read(size)
    except OSError:
        return b""


class BaseInspector(ABC):
    """Strategy interface for inspecting a candidate application target."""

    def __init__(self, paths: DeskForgePaths) -> None:
        self._paths = paths

    @abstractmethod
    def can_handle(self, target: str) -> bool:
        """Return True if this inspector should handle the given file path or URL."""

    @abstractmethod
    def inspect(self, target: str) -> DetectionResult:
        """Extract metadata, icon candidates, and defaults for the target."""
