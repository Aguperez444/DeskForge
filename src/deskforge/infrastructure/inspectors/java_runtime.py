"""Discover installed JDK / JRE runtimes on Linux."""

from __future__ import annotations

from functools import lru_cache
import os
from pathlib import Path
import re
import shutil
import subprocess

from deskforge.domain.models import JavaRuntime

_VERSION_LINE_RE = re.compile(r'version "([^"]+)"')


def _probe_java_binary(java_bin: Path) -> tuple[str, str]:
    """Run `java -version` to obtain version string and vendor description."""
    try:
        proc = subprocess.run(
            [str(java_bin), "-version"],
            capture_output=True,
            text=True,
            timeout=3,
            check=False,
        )
        output = (proc.stderr or proc.stdout).strip()
        lines = [line.strip() for line in output.splitlines() if line.strip()]
        if not lines:
            return ("Java", "")
        first = lines[0]
        match = _VERSION_LINE_RE.search(first)
        ver = match.group(1) if match else first
        vendor = first.split(" version")[0].strip().capitalize() if "version" in first.lower() else "Java"
        return (f"{vendor} {ver}".strip(), vendor)
    except (OSError, subprocess.SubprocessError):
        return ("Java", "")


@lru_cache(maxsize=1)
def detect_java_runtimes() -> tuple[JavaRuntime, ...]:
    """Scan standard Linux JVM directories and PATH for available Java executables."""
    candidates: list[Path] = []
    default_java = shutil.which("java")
    default_resolved = Path(default_java).resolve() if default_java else None
    if default_java:
        candidates.append(Path(default_java))

    if java_home := os.environ.get("JAVA_HOME"):
        candidates.append(Path(java_home) / "bin" / "java")

    search_roots = (
        Path("/usr/lib/jvm"),
        Path("/usr/lib64/jvm"),
        Path.home() / ".sdkman" / "candidates" / "java",
        Path.home() / ".jdks",
        Path.home() / ".asdf" / "installs" / "java",
    )
    for root in search_roots:
        if not root.is_dir():
            continue
        try:
            for entry in sorted(root.iterdir()):
                java_bin = entry / "bin" / "java"
                if java_bin.is_file() and os.access(java_bin, os.X_OK):
                    candidates.append(java_bin)
        except OSError:
            continue

    runtimes: list[JavaRuntime] = []
    seen_realpaths: set[Path] = set()

    for cand in candidates:
        if not cand.is_file() or not os.access(cand, os.X_OK):
            continue
        try:
            resolved = cand.resolve()
        except OSError:
            continue
        if resolved in seen_realpaths:
            continue
        seen_realpaths.add(resolved)

        version_label, vendor = _probe_java_binary(cand)
        is_default = default_resolved is not None and resolved == default_resolved
        runtimes.append(
            JavaRuntime(
                path=str(cand),
                version=version_label,
                vendor=vendor,
                is_default=is_default,
            )
        )

    # Sort with default runtime first, then descending version/path
    runtimes.sort(key=lambda r: (not r.is_default, r.path))
    return tuple(runtimes)


def clear_java_runtime_cache() -> None:
    """Clear cached JDK discovery results (useful after installing a new JDK)."""
    detect_java_runtimes.cache_clear()
