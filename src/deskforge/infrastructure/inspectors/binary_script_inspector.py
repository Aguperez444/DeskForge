"""Inspectors for portable ELF binaries and executable scripts (.sh, .py, etc.)."""

from __future__ import annotations

from pathlib import Path

from deskforge.domain.models import AppType, DetectionResult
from deskforge.infrastructure.inspectors.base import BaseInspector, guess_name_and_version, read_file_header

SCRIPT_INTERPRETERS: dict[str, str] = {
    ".sh": "bash",
    ".bash": "bash",
    ".zsh": "zsh",
    ".py": "python3",
    ".rb": "ruby",
    ".js": "node",
    ".mjs": "node",
    ".pl": "perl",
}


def _find_nearby_icons(folder: Path, app_stem: str) -> list[str]:
    """Look for icon files next to a portable binary/script (e.g., Blender/Godot extracted folders)."""
    search_dirs = [folder, folder / "icons", folder / "share" / "icons", folder / "resources", folder / "assets"]
    found: list[tuple[int, str]] = []
    seen: set[Path] = set()
    stem_lower = app_stem.lower()

    for d in search_dirs:
        if not d.is_dir():
            continue
        try:
            for item in sorted(d.iterdir()):
                if not item.is_file() or item.suffix.lower() not in (".png", ".svg", ".ico"):
                    continue
                resolved = item.resolve()
                if resolved in seen:
                    continue
                seen.add(resolved)
                score = 10
                lower = item.name.lower()
                if stem_lower and stem_lower in lower:
                    score += 35
                if any(k in lower for k in ("icon", "logo", "app")):
                    score += 25
                if item.suffix.lower() == ".png":
                    score += 10
                found.append((score, str(item)))
        except OSError:
            continue

    found.sort(key=lambda x: x[0], reverse=True)
    return [path for _s, path in found[:6]]


class ScriptInspector(BaseInspector):
    """Detects shell/Python/Node/Ruby scripts by extension or #! shebang."""

    def can_handle(self, target: str) -> bool:
        if target.startswith(("http://", "https://")):
            return False
        p = Path(target).expanduser()
        if p.suffix.lower() in SCRIPT_INTERPRETERS:
            return True
        if p.is_file():
            hdr = read_file_header(p, 4)
            return hdr.startswith(b"#!")
        return False

    def inspect(self, target: str) -> DetectionResult:
        path = Path(target).expanduser().resolve()
        name_guess, version_guess = guess_name_and_version(path.name)
        interpreter = SCRIPT_INTERPRETERS.get(path.suffix.lower(), "")
        comment = f"Script ejecutable ({path.name})"
        warnings: list[str] = []
        metadata: dict[str, str] = {}

        if path.is_file():
            try:
                lines = path.read_text(encoding="utf-8", errors="replace").splitlines()[:10]
                if lines and lines[0].startswith("#!"):
                    shebang = lines[0][2:].strip()
                    metadata["shebang"] = shebang
                    # If file has a valid shebang, we can execute it directly once +x is set
                    interpreter = ""
                for line in lines[1:5]:
                    stripped = line.strip()
                    if stripped.startswith("#") and len(stripped) > 4 and not stripped.startswith("#!"):
                        comment = stripped.lstrip("# ").strip()[:100]
                        break
            except OSError as exc:
                warnings.append(f"No se pudo leer el script: {exc}")
        else:
            warnings.append("El archivo script no existe en la ruta indicada.")

        icons = _find_nearby_icons(path.parent, path.stem) if path.parent.is_dir() else []
        if self._paths.default_app_icon.exists():
            icons.append(str(self._paths.default_app_icon))

        return DetectionResult(
            target=str(path),
            app_type=AppType.SCRIPT,
            suggested_name=name_guess,
            comment=comment,
            version=version_guess,
            categories=["Utility", "System"],
            icon_candidates=icons,
            selected_icon=icons[0] if icons else "",
            working_dir=str(path.parent),
            terminal=True,
            script_interpreter=interpreter,
            warnings=warnings,
            metadata=metadata,
        )


class BinaryInspector(BaseInspector):
    """Fallback inspector for native ELF binaries and portable executables."""

    def can_handle(self, target: str) -> bool:
        return not target.startswith(("http://", "https://"))

    def inspect(self, target: str) -> DetectionResult:
        path = Path(target).expanduser().resolve()
        name_guess, version_guess = guess_name_and_version(path.name)
        warnings: list[str] = []
        metadata: dict[str, str] = {}

        if not path.is_file():
            warnings.append("El archivo ejecutable no existe en la ruta indicada.")
        else:
            hdr = read_file_header(path, 8)
            if hdr[:4] == b"\x7fELF":
                metadata["format"] = "ELF"
            else:
                warnings.append("El archivo no tiene cabecera ELF estándar; verificá que sea ejecutable en Linux.")

        icons = _find_nearby_icons(path.parent, path.stem) if path.parent.is_dir() else []
        if self._paths.default_app_icon.exists():
            icons.append(str(self._paths.default_app_icon))

        return DetectionResult(
            target=str(path),
            app_type=AppType.BINARY,
            suggested_name=name_guess,
            comment=f"Aplicación portable ({path.name})",
            version=version_guess,
            categories=["Utility"],
            icon_candidates=icons,
            selected_icon=icons[0] if icons else "",
            working_dir=str(path.parent),
            warnings=warnings,
            metadata=metadata,
        )
