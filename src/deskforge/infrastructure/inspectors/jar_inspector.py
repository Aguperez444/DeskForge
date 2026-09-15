"""Inspector for Java Archive (.jar) executables: MANIFEST.MF and embedded icon extraction."""

from __future__ import annotations

import hashlib
import io
from pathlib import Path
import zipfile

from PIL import Image

from deskforge.domain.models import AppType, DetectionResult
from deskforge.infrastructure.inspectors.base import BaseInspector, guess_name_and_version


def parse_manifest(raw_text: str) -> dict[str, str]:
    """Parse JAR META-INF/MANIFEST.MF handling RFC-style line continuations."""
    entries: dict[str, str] = {}
    current_key: str | None = None
    for raw_line in raw_text.splitlines():
        if not raw_line.strip():
            current_key = None
            continue
        if raw_line.startswith(" ") and current_key is not None:
            entries[current_key] += raw_line[1:]
        elif ":" in raw_line:
            key, val = raw_line.split(":", 1)
            current_key = key.strip()
            entries[current_key] = val.strip()
    return entries


def _score_icon_entry(name: str, width: int, height: int) -> int:
    """Heuristic score to pick the best embedded application icon inside a JAR."""
    lower = name.lower()
    score = 0

    if any(kw in lower for kw in ("icon", "logo", "appicon", "favicon", "launcher", "tray")):
        score += 50
    if any(bad in lower for bad in ("splash", "banner", "background", "bg_", "texture", "font", "sprite")):
        score -= 45

    # Prefer square icons
    if width > 0 and height > 0:
        ratio = max(width, height) / max(1, min(width, height))
        if ratio <= 1.15:
            score += 35
        elif ratio > 1.6:
            score -= 30

        max_dim = max(width, height)
        if 48 <= max_dim <= 512:
            score += 30 + min(max_dim, 256) // 16
        elif 24 <= max_dim < 48:
            score += 10
        elif max_dim < 16 or max_dim > 1024:
            score -= 25

    # Prefer icons closer to root or resources/icons
    depth = lower.count("/")
    if depth <= 2:
        score += 10
    return score


class JarInspector(BaseInspector):
    """Inspects .jar files without executing them."""

    MAX_CANDIDATES = 6

    def can_handle(self, target: str) -> bool:
        if target.startswith(("http://", "https://")):
            return False
        p = Path(target).expanduser()
        return p.suffix.lower() == ".jar"

    def inspect(self, target: str) -> DetectionResult:
        path = Path(target).expanduser().resolve()
        name_guess, version_guess = guess_name_and_version(path.name)
        warnings: list[str] = []
        metadata: dict[str, str] = {}
        icon_candidates: list[str] = []

        if not path.is_file():
            warnings.append("El archivo .jar no existe en la ruta indicada.")
        elif not zipfile.is_zipfile(path):
            warnings.append("El archivo no parece ser un ZIP/JAR válido.")
        else:
            try:
                with zipfile.ZipFile(path, "r") as zf:
                    if "META-INF/MANIFEST.MF" in zf.namelist():
                        manifest_raw = zf.read("META-INF/MANIFEST.MF").decode("utf-8", errors="replace")
                        manifest = parse_manifest(manifest_raw)
                        metadata.update(
                            {
                                k: v
                                for k, v in manifest.items()
                                if k in ("Main-Class", "Implementation-Title", "Implementation-Version", "Specification-Title")
                            }
                        )
                        if not manifest.get("Main-Class"):
                            warnings.append(
                                "El MANIFEST.MF no declara 'Main-Class'. Es posible que este .jar sea una librería y no un ejecutable."
                            )
                        impl_title = manifest.get("Implementation-Title") or manifest.get("Specification-Title")
                        if impl_title and len(impl_title) <= 60:
                            name_guess = impl_title
                        impl_ver = manifest.get("Implementation-Version")
                        if impl_ver:
                            version_guess = impl_ver
                    else:
                        warnings.append("No se encontró META-INF/MANIFEST.MF dentro del archivo .jar.")

                    icon_candidates = self._extract_icon_candidates(zf, path)
            except (zipfile.BadZipFile, OSError) as exc:
                warnings.append(f"No se pudo inspeccionar el contenido del .jar: {exc}")

        # Always include the classic AutoJar icon as a fallback option
        if self._paths.default_jar_icon.exists():
            icon_candidates.append(str(self._paths.default_jar_icon))

        selected_icon = icon_candidates[0] if icon_candidates else ""

        return DetectionResult(
            target=str(path),
            app_type=AppType.JAR,
            suggested_name=name_guess,
            comment=f"Aplicación Java ({path.name})",
            version=version_guess,
            categories=["Utility"],
            icon_candidates=icon_candidates,
            selected_icon=selected_icon,
            working_dir=str(path.parent),
            warnings=warnings,
            metadata=metadata,
        )

    def _extract_icon_candidates(self, zf: zipfile.ZipFile, jar_path: Path) -> list[str]:
        """Score and extract up to MAX_CANDIDATES embedded PNG/ICO icons into cache."""
        scored: list[tuple[int, str, bytes]] = []
        image_members = [
            info
            for info in zf.infolist()
            if not info.is_dir()
            and info.file_size > 100
            and info.file_size <= 2 * 1024 * 1024
            and info.filename.lower().endswith((".png", ".ico"))
        ]

        # Prioritize likely icon names first to keep scanning fast on huge JARs (e.g. games/IDEs)
        image_members.sort(
            key=lambda i: (
                0 if any(k in i.filename.lower() for k in ("icon", "logo", "app", "favicon")) else 1,
                i.filename.count("/"),
            )
        )

        for info in image_members[:120]:
            try:
                raw = zf.read(info)
                with Image.open(io.BytesIO(raw)) as img:
                    w, h = img.size
                score = _score_icon_entry(info.filename, w, h)
                if score > 0:
                    scored.append((score, info.filename, raw))
            except Exception:
                continue

        scored.sort(key=lambda item: item[0], reverse=True)
        if not scored:
            return []

        key_hash = hashlib.sha1(f"{jar_path}:{jar_path.stat().st_mtime}".encode()).hexdigest()[:12]
        out_dir = self._paths.cache_dir / "extracted" / f"jar_{key_hash}"
        out_dir.mkdir(parents=True, exist_ok=True)

        extracted: list[str] = []
        seen_digests: set[str] = set()
        for idx, (_score, member_name, raw) in enumerate(scored):
            digest = hashlib.sha1(raw).hexdigest()
            if digest in seen_digests:
                continue
            seen_digests.add(digest)

            ext = Path(member_name).suffix.lower() or ".png"
            out_file = out_dir / f"icon_{idx}{ext}"
            try:
                out_file.write_bytes(raw)
                extracted.append(str(out_file))
            except OSError:
                continue
            if len(extracted) >= self.MAX_CANDIDATES:
                break
        return extracted
