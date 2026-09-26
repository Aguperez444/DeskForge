"""Unit tests for smart target inspectors (JAR, Script, ELF, WebApp, Folder Scanner, JDKs)."""

from __future__ import annotations

import io
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import zipfile

from PIL import Image

from deskforge.domain.models import AppType
from deskforge.infrastructure.inspectors.base import guess_name_and_version
from deskforge.infrastructure.inspectors.java_runtime import detect_java_runtimes
from deskforge.infrastructure.inspectors.registry import InspectorRegistry
from deskforge.infrastructure.inspectors.webapp_inspector import WebAppInspector
from deskforge.infrastructure.paths import DeskForgePaths


def _make_sandbox_paths(tmp: Path) -> DeskForgePaths:
    assets_dir = Path(__file__).resolve().parents[1] / "src" / "deskforge" / "assets"
    paths = DeskForgePaths(
        data_dir=tmp / "data",
        config_dir=tmp / "config",
        cache_dir=tmp / "cache",
        applications_dir=tmp / "applications",
        icons_dir=tmp / "data" / "icons",
        managed_apps_dir=tmp / "Applications",
        desktop_dir=tmp / "Desktop",
        downloads_dir=tmp / "Downloads",
        assets_dir=assets_dir,
    )
    paths.ensure_dirs()
    paths.downloads_dir.mkdir(parents=True, exist_ok=True)
    return paths


def _png_bytes(size: int = 128) -> bytes:
    buf = io.BytesIO()
    img = Image.new("RGBA", (size, size), (40, 160, 180, 255))
    img.save(buf, format="PNG")
    return buf.getvalue()


class TestInspectors(unittest.TestCase):
    def test_guess_name_and_version_cleans_filenames(self) -> None:
        self.assertEqual(guess_name_and_version("Obsidian-1.7.4-x86_64.AppImage"), ("Obsidian", "1.7.4"))
        self.assertEqual(guess_name_and_version("cool_tool-2.0.1-linux-amd64.jar"), ("Cool Tool", "2.0.1"))
        self.assertEqual(guess_name_and_version("AutoJar.jar"), ("AutoJar", ""))

    def test_jar_inspector_extracts_manifest_and_embedded_icon(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_str:
            tmp = Path(tmp_str)
            paths = _make_sandbox_paths(tmp)
            jar_path = tmp / "sample-app-1.2.3.jar"
            with zipfile.ZipFile(jar_path, "w") as zf:
                zf.writestr(
                    "META-INF/MANIFEST.MF",
                    "Manifest-Version: 1.0\n"
                    "Implementation-Title: PixelForge Studio\n"
                    "Implementation-Version: 3.4.0\n"
                    "Main-Class: com.example.Main\n",
                )
                zf.writestr("resources/icons/app_icon.png", _png_bytes(128))

            registry = InspectorRegistry(paths)
            result = registry.inspect(str(jar_path))
            self.assertEqual(result.app_type, AppType.JAR)
            self.assertEqual(result.suggested_name, "PixelForge Studio")
            self.assertEqual(result.version, "3.4.0")
            self.assertEqual(result.warnings, [])
            self.assertTrue(len(result.icon_candidates) >= 2)  # extracted icon + AutoJar default
            self.assertTrue(Path(result.selected_icon).is_file())
            self.assertIn("jar_", result.selected_icon)

    def test_jar_inspector_warns_when_missing_main_class(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_str:
            tmp = Path(tmp_str)
            paths = _make_sandbox_paths(tmp)
            jar_path = tmp / "library-only.jar"
            with zipfile.ZipFile(jar_path, "w") as zf:
                zf.writestr("META-INF/MANIFEST.MF", "Manifest-Version: 1.0\n")

            result = InspectorRegistry(paths).inspect(str(jar_path))
            self.assertEqual(result.app_type, AppType.JAR)
            self.assertTrue(any("Main-Class" in w for w in result.warnings))

    def test_script_and_elf_binary_detection(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_str:
            tmp = Path(tmp_str)
            paths = _make_sandbox_paths(tmp)

            script = tmp / "deploy_helper.sh"
            script.write_text("#!/usr/bin/env bash\n# Herramienta de despliegue rápido\necho ok\n", encoding="utf-8")

            elf_bin = tmp / "my_portable_app"
            elf_bin.write_bytes(b"\x7fELF" + b"\x00" * 60)

            registry = InspectorRegistry(paths)
            s_res = registry.inspect(str(script))
            self.assertEqual(s_res.app_type, AppType.SCRIPT)
            self.assertTrue(s_res.terminal)
            self.assertIn("despliegue", s_res.comment.lower())

            b_res = registry.inspect(str(elf_bin))
            self.assertEqual(b_res.app_type, AppType.BINARY)
            self.assertEqual(b_res.metadata.get("format"), "ELF")
            self.assertEqual(b_res.warnings, [])

    def test_webapp_inspector_offline_and_metadata_parsing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_str:
            paths = _make_sandbox_paths(Path(tmp_str))
            inspector = WebAppInspector(paths)
            self.assertTrue(inspector.can_handle("https://excalidraw.com"))
            with patch.object(
                inspector,
                "_fetch_page_metadata",
                return_value=("Excalidraw — Hand-drawn diagrams", "Virtual whiteboard", []),
            ), patch.object(inspector, "_download_icons", return_value=[]):
                res = inspector.inspect("https://excalidraw.com", fetch_remote=True)
            self.assertEqual(res.app_type, AppType.WEBAPP)
            self.assertEqual(res.suggested_name, "Excalidraw")
            self.assertEqual(res.comment, "Virtual whiteboard")
            self.assertIn("Network", res.categories)

    def test_folder_scanner_finds_unintegrated_appimage_and_jar(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_str:
            tmp = Path(tmp_str)
            paths = _make_sandbox_paths(tmp)
            dl = paths.downloads_dir
            f1 = dl / "ToolA-1.0.AppImage"
            f2 = dl / "ToolB-2.0.jar"
            f3 = dl / "notes.txt"
            f1.write_bytes(b"\x7fELF\x02\x01\x01\x00AI\x02\x00" + b"\x00" * 32)
            f2.write_bytes(b"PK\x03\x04")
            f3.write_text("ignore me", encoding="utf-8")

            registry = InspectorRegistry(paths)
            found = registry.scan_directory(dl, already_managed_targets={str(f2.resolve())})
            self.assertEqual(len(found), 1)
            self.assertEqual(found[0].app_type, AppType.APPIMAGE)
            self.assertEqual(found[0].name_guess, "ToolA")

    def test_java_runtime_discovery_runs_cleanly(self) -> None:
        runtimes = detect_java_runtimes()
        self.assertIsInstance(runtimes, tuple)


if __name__ == "__main__":
    unittest.main()
