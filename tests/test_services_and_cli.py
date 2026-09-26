"""Integration tests for AppService, DoctorService, and CLI in an isolated XDG sandbox."""

from __future__ import annotations

import contextlib
import io
import json
from pathlib import Path
import tempfile
import unittest
import zipfile

from deskforge.application import build_services
from deskforge.cli.main import main as cli_main
from deskforge.domain.models import AppType, JavaOptions, ManagedApp, StorageMode
from deskforge.infrastructure.paths import DeskForgePaths


def _create_sandbox_services(tmp: Path):
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
    paths.desktop_dir.mkdir(parents=True, exist_ok=True)
    paths.downloads_dir.mkdir(parents=True, exist_ok=True)
    return build_services(paths=paths)


def _write_dummy_jar(path: Path, title: str, version: str) -> None:
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr(
            "META-INF/MANIFEST.MF",
            f"Manifest-Version: 1.0\nImplementation-Title: {title}\nImplementation-Version: {version}\nMain-Class: app.Main\n",
        )


class TestServicesAndCLI(unittest.TestCase):
    def test_full_app_lifecycle_move_upgrade_doctor_remove(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_str:
            tmp = Path(tmp_str)
            services = _create_sandbox_services(tmp)

            # 1. Create a v1 JAR in Downloads and integrate with MOVE + desktop shortcut
            jar_v1 = services.paths.downloads_dir / "ForgeDemo-1.0.jar"
            _write_dummy_jar(jar_v1, "ForgeDemo", "1.0.0")

            draft = ManagedApp(
                name="ForgeDemo",
                app_type=AppType.JAR,
                exec_target=str(jar_v1),
                categories=["Development"],
                storage_mode=StorageMode.MOVE,
                create_desktop_shortcut=True,
                env_vars={"APP_ENV": "prod"},
                java_options=JavaOptions(max_memory="2G"),
                version="1.0.0",
            )
            integrated = services.app_service.integrate_app(draft)

            # Original file moved to managed folder
            self.assertFalse(jar_v1.exists())
            self.assertTrue(Path(integrated.exec_target).is_file())
            self.assertEqual(Path(integrated.exec_target).parent, services.paths.managed_apps_dir)
            self.assertTrue(Path(integrated.desktop_file_path).is_file())
            self.assertTrue(Path(integrated.desktop_shortcut_path).is_file())
            self.assertTrue(Path(integrated.icon_path).is_file())
            v1_hash = integrated.sha256

            # 2. In-place upgrade to v2 (preserves env_vars, JVM max_memory, shortcut)
            jar_v2 = services.paths.downloads_dir / "ForgeDemo-2.0.jar"
            _write_dummy_jar(jar_v2, "ForgeDemo", "2.0.0")
            upgraded = services.app_service.replace_binary(integrated.id, jar_v2)
            self.assertEqual(upgraded.version, "2.0.0")
            self.assertNotEqual(upgraded.sha256, v1_hash)
            self.assertEqual(upgraded.env_vars, {"APP_ENV": "prod"})
            self.assertEqual(upgraded.java_options.max_memory, "2G")
            self.assertTrue(Path(upgraded.exec_target).is_file())

            # 3. Doctor detects deleted .desktop and repairs automatically
            Path(upgraded.desktop_file_path).unlink()
            issues = services.doctor_service.run_checks()
            self.assertTrue(any(i.code == "MISSING_DESKTOP_FILE" and i.fixable for i in issues))
            repaired_count = services.doctor_service.repair_all()
            self.assertGreaterEqual(repaired_count, 1)
            self.assertTrue(Path(upgraded.desktop_file_path).is_file())
            self.assertEqual(services.doctor_service.run_checks(), [])

            # 4. Clean removal (including managed binary without trash in sandbox)
            target_to_check = Path(upgraded.exec_target)
            services.app_service.remove_app(upgraded.id, delete_target_file=True, use_trash=False)
            self.assertFalse(Path(upgraded.desktop_file_path).exists())
            self.assertFalse(Path(upgraded.desktop_shortcut_path).exists())
            self.assertFalse(target_to_check.exists())
            self.assertEqual(services.app_service.list_apps(), [])

    def test_cli_integrate_list_doctor_install_self_and_remove(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_str:
            tmp = Path(tmp_str)
            services = _create_sandbox_services(tmp)

            script = tmp / "hello_cli.sh"
            script.write_text("#!/bin/bash\necho hi\n", encoding="utf-8")

            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                rc = cli_main(
                    [
                        "integrate",
                        str(script),
                        "--name",
                        "HelloCLI",
                        "--copy",
                        "--env",
                        "FOO=bar",
                        "--json",
                    ],
                    services=services,
                )
            self.assertEqual(rc, 0)
            payload = json.loads(buf.getvalue())
            self.assertEqual(payload["name"], "HelloCLI")
            self.assertEqual(payload["env_vars"], {"FOO": "bar"})
            self.assertEqual(payload["app_type"], "script")

            # list --json
            buf_list = io.StringIO()
            with contextlib.redirect_stdout(buf_list):
                rc_list = cli_main(["list", "--json"], services=services)
            self.assertEqual(rc_list, 0)
            listed = json.loads(buf_list.getvalue())
            self.assertEqual(len(listed), 1)
            self.assertEqual(listed[0]["name"], "HelloCLI")

            # doctor --json
            buf_doc = io.StringIO()
            with contextlib.redirect_stdout(buf_doc):
                rc_doc = cli_main(["doctor", "--json"], services=services)
            self.assertEqual(rc_doc, 0)
            doc_data = json.loads(buf_doc.getvalue())
            self.assertEqual(doc_data["issues"], [])

            # install-self & uninstall-self
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(cli_main(["install-self"], services=services), 0)
            self.assertTrue(services.system.is_self_installed())
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(cli_main(["uninstall-self"], services=services), 0)
            self.assertFalse(services.system.is_self_installed())

            # remove
            with contextlib.redirect_stdout(io.StringIO()):
                rc_rem = cli_main(["remove", "HelloCLI", "--delete-file", "--no-trash"], services=services)
            self.assertEqual(rc_rem, 0)
            self.assertEqual(services.app_service.list_apps(), [])

    def test_import_external_desktop_with_system_binary_and_path_commands(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_str:
            tmp = Path(tmp_str)
            services = _create_sandbox_services(tmp)

            # Case 1: Root-owned system binary (/usr/bin/env) like Flatpak launchers
            sys_desktop = services.paths.applications_dir / "org.example.FlatpakApp.desktop"
            sys_desktop.write_text(
                "[Desktop Entry]\n"
                "Type=Application\n"
                "Name=Flatpak Demo\n"
                "Exec=/usr/bin/env FOO=1 true\n"
                "Icon=application-x-executable\n"
                "Categories=Utility;\n",
                encoding="utf-8",
            )

            # Case 2: Bare command resolved via $PATH (like steam, waydroid, sh)
            path_desktop = services.paths.applications_dir / "sh-demo.desktop"
            path_desktop.write_text(
                "[Desktop Entry]\n"
                "Type=Application\n"
                "Name=Shell Demo\n"
                "Exec=sh -c \"echo hello\"\n"
                "Icon=utilities-terminal\n"
                "Categories=System;\n",
                encoding="utf-8",
            )

            externals = services.app_service.discover_external_launchers()
            self.assertEqual(len(externals), 2)

            imported_apps = [services.app_service.import_external_launcher(ext) for ext in externals]
            self.assertEqual(len(imported_apps), 2)

            # Doctor must report 0 issues for both system-binary and $PATH-command apps
            self.assertEqual(services.doctor_service.run_checks(), [])

            # Removing with delete_target_file=True must NEVER fail or touch system binaries
            for app in imported_apps:
                services.app_service.remove_app(app.id, delete_target_file=True, use_trash=False)
            self.assertTrue(Path("/usr/bin/env").exists())
            self.assertEqual(services.app_service.list_apps(), [])


if __name__ == "__main__":
    unittest.main()
