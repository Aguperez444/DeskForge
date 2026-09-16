"""Safe AppImage inspector: extracts .desktop metadata and icons without executing the binary."""

from __future__ import annotations

import hashlib
from pathlib import Path
import shutil
import struct
import subprocess

from deskforge.domain.categories import normalize_categories
from deskforge.domain.models import AppType, DetectionResult
from deskforge.infrastructure.desktop_entry import DesktopEntryEngine
from deskforge.infrastructure.inspectors.base import BaseInspector, guess_name_and_version, read_file_header


def find_appimage_squashfs_offset(path: Path) -> int | None:
    """
    Calculate the SquashFS payload offset for a Type 2 AppImage by reading its ELF64/ELF32 header
    and verifying the 'hsqs' SquashFS magic signature.
    """
    try:
        with path.open("rb") as fh:
            header = fh.read(64)
            if len(header) < 64 or header[:4] != b"\x7fELF":
                return None

            elf_class = header[4]
            if elf_class == 2:  # 64-bit ELF
                e_shoff = struct.unpack_from("<Q", header, 40)[0]
                e_shentsize = struct.unpack_from("<H", header, 58)[0]
                e_shnum = struct.unpack_from("<H", header, 60)[0]
                offset = e_shoff + (e_shentsize * e_shnum)
            elif elf_class == 1:  # 32-bit ELF
                e_shoff = struct.unpack_from("<I", header, 32)[0]
                e_shentsize = struct.unpack_from("<H", header, 46)[0]
                e_shnum = struct.unpack_from("<H", header, 48)[0]
                offset = e_shoff + (e_shentsize * e_shnum)
            else:
                return None

            fh.seek(offset)
            magic = fh.read(4)
            if magic == b"hsqs":
                return offset

            # Fallback scan within first 2 MiB for SquashFS magic
            fh.seek(0)
            chunk = fh.read(2 * 1024 * 1024)
            pos = chunk.find(b"hsqs")
            return pos if pos != -1 else None
    except OSError:
        return None


class AppImageInspector(BaseInspector):
    """Inspects Type 1 and Type 2 AppImages safely using unsquashfs/7z."""

    def __init__(self, paths) -> None:
        super().__init__(paths)
        self._desktop_engine = DesktopEntryEngine()

    def can_handle(self, target: str) -> bool:
        if target.startswith(("http://", "https://")):
            return False
        p = Path(target).expanduser()
        if p.suffix.lower() == ".appimage":
            return True
        if p.is_file():
            hdr = read_file_header(p, 16)
            # Type 2 AppImage magic: ELF + 'AI\x02' at bytes 8..11
            if hdr[:4] == b"\x7fELF" and hdr[8:11] in (b"AI\x02", b"AI\x01"):
                return True
        return False

    def inspect(self, target: str) -> DetectionResult:
        path = Path(target).expanduser().resolve()
        name_guess, version_guess = guess_name_and_version(path.name)
        comment = f"Aplicación AppImage ({path.name})"
        categories = ["Utility"]
        startup_wm_class = ""
        warnings: list[str] = []
        icon_candidates: list[str] = []
        metadata: dict[str, str] = {}

        if not path.is_file():
            warnings.append("El archivo AppImage no existe en la ruta indicada.")
        else:
            extracted_dir = self._extract_metadata_files(path)
            if extracted_dir:
                desktop_files = sorted(extracted_dir.glob("*.desktop"))
                desktop_icon_name = ""
                if desktop_files:
                    parsed = self._desktop_engine.parse_file(desktop_files[0])
                    if parsed.get("Name"):
                        name_guess = parsed["Name"]
                    if parsed.get("Comment"):
                        comment = parsed["Comment"]
                    if parsed.get("Categories"):
                        raw_cats = [c for c in parsed["Categories"].split(";") if c.strip()]
                        categories = normalize_categories(raw_cats)
                    if parsed.get("StartupWMClass"):
                        startup_wm_class = parsed["StartupWMClass"]
                    if parsed.get("X-AppImage-Version"):
                        version_guess = parsed["X-AppImage-Version"]
                    desktop_icon_name = parsed.get("Icon", "")
                    metadata.update({k: v for k, v in parsed.items() if k in ("Name", "Exec", "Icon", "X-AppImage-Version")})

                icon_candidates = self._collect_extracted_icons(extracted_dir, desktop_icon_name)
            else:
                warnings.append(
                    "No se pudieron extraer metadatos internos del AppImage (verificá que 'unsquashfs' o '7z' estén disponibles)."
                )

        if not icon_candidates and self._paths.default_app_icon.exists():
            icon_candidates.append(str(self._paths.default_app_icon))

        return DetectionResult(
            target=str(path),
            app_type=AppType.APPIMAGE,
            suggested_name=name_guess,
            comment=comment,
            version=version_guess,
            categories=categories,
            icon_candidates=icon_candidates,
            selected_icon=icon_candidates[0] if icon_candidates else "",
            startup_wm_class=startup_wm_class,
            warnings=warnings,
            metadata=metadata,
        )

    def _extract_metadata_files(self, path: Path) -> Path | None:
        key_hash = hashlib.sha1(f"{path}:{path.stat().st_mtime}".encode()).hexdigest()[:12]
        out_dir = self._paths.cache_dir / "extracted" / f"appimage_{key_hash}"
        if out_dir.exists() and any(out_dir.iterdir()):
            return out_dir
        out_dir.mkdir(parents=True, exist_ok=True)

        offset = find_appimage_squashfs_offset(path)
        unsquashfs = shutil.which("unsquashfs")
        if offset is not None and unsquashfs:
            # Extract only root .desktop, .DirIcon, root icons, and usr/share/icons
            cmd = [
                unsquashfs,
                "-f",
                "-n",
                "-o",
                str(offset),
                "-d",
                str(out_dir),
                str(path),
                "*.desktop",
                ".DirIcon",
                "*.png",
                "*.svg",
                "usr/share/icons",
                "usr/share/pixmaps",
            ]
            try:
                subprocess.run(cmd, capture_output=True, timeout=15, check=False)
                if any(out_dir.iterdir()):
                    return out_dir
            except (OSError, subprocess.SubprocessError):
                pass

        # Fallback: 7z extraction of root desktop & icons (also works for Type 1 ISO AppImages)
        sevenz = shutil.which("7z")
        if sevenz:
            try:
                subprocess.run(
                    [sevenz, "x", "-y", f"-o{out_dir}", str(path), "*.desktop", ".DirIcon", "*.png", "*.svg"],
                    capture_output=True,
                    timeout=15,
                    check=False,
                )
                if any(out_dir.iterdir()):
                    return out_dir
            except (OSError, subprocess.SubprocessError):
                pass

        return None

    def _collect_extracted_icons(self, out_dir: Path, desktop_icon_name: str) -> list[str]:
        candidates: list[tuple[int, Path]] = []

        # Resolve .DirIcon symlink/file first
        dir_icon = out_dir / ".DirIcon"
        if dir_icon.exists():
            resolved = dir_icon.resolve() if dir_icon.is_symlink() else dir_icon
            if resolved.is_file() and str(resolved).startswith(str(out_dir.resolve())):
                candidates.append((100, resolved))
            elif dir_icon.is_file():
                candidates.append((100, dir_icon))

        for file_path in out_dir.rglob("*"):
            if not file_path.is_file():
                continue
            ext = file_path.suffix.lower()
            if ext not in (".png", ".svg", ".ico"):
                continue
            score = 20
            if desktop_icon_name and file_path.stem == desktop_icon_name:
                score += 40
            if ext == ".png":
                score += 15
                if "256x256" in str(file_path) or "512x512" in str(file_path):
                    score += 20
                elif "128x128" in str(file_path):
                    score += 15
            elif ext == ".svg":
                score += 10
            candidates.append((score, file_path))

        candidates.sort(key=lambda item: item[0], reverse=True)
        seen: set[Path] = set()
        ordered: list[str] = []
        for _score, p in candidates:
            rp = p.resolve()
            if rp not in seen:
                seen.add(rp)
                ordered.append(str(p))
            if len(ordered) >= 6:
                break
        return ordered
