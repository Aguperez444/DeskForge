"""Unit tests for FreeDesktop Desktop Entry Spec v1.5 generation, escaping, parsing, and validation."""

from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from deskforge.domain.models import AppType, JavaOptions, ManagedApp
from deskforge.infrastructure.desktop_entry import DesktopEntryEngine, escape_exec_arg


class TestDesktopEntryEngine(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = DesktopEntryEngine()

    def test_escape_exec_arg_handles_spaces_quotes_percent_and_dollar(self) -> None:
        self.assertEqual(escape_exec_arg("/usr/bin/java"), "/usr/bin/java")
        self.assertEqual(
            escape_exec_arg("/home/user/My Apps/Game 100%.jar"),
            '"/home/user/My Apps/Game 100%%.jar"',
        )
        self.assertEqual(escape_exec_arg('arg$with"quote'), '"arg\\$with\\"quote"')

    def test_render_and_validate_jar_app_with_jvm_env_and_gpu(self) -> None:
        app = ManagedApp(
            id="jar123456789",
            name="Minecraft Launcher",
            app_type=AppType.JAR,
            exec_target="/home/user/My Games/mc launcher.jar",
            icon_path="/home/user/.local/share/deskforge/icons/jar123456789.png",
            comment="Custom Java game launcher",
            categories=["Juego", "Utilidad"],
            env_vars={"SDL_VIDEODRIVER": "wayland"},
            dedicated_gpu=True,
            java_options=JavaOptions(
                java_path="/usr/lib/jvm/java-21-openjdk/bin/java",
                max_memory="4G",
                min_memory="512M",
                jvm_args=["-XX:+UseG1GC"],
            ),
            args=["--fullscreen"],
        )
        content = self.engine.render(app)
        self.assertIn("Version=1.5", content)
        self.assertIn("Name=Minecraft Launcher", content)
        self.assertIn("Categories=Game;Utility;", content)
        self.assertIn("PrefersNonDefaultGPU=true", content)
        self.assertIn("env DRI_PRIME=1 SDL_VIDEODRIVER=wayland", content)
        self.assertIn("-Xms512M -Xmx4G -XX:+UseG1GC -jar \"/home/user/My Games/mc launcher.jar\" --fullscreen", content)
        self.assertIn("X-DeskForge-Managed=true", content)

        report = self.engine.validate_content(content)
        self.assertTrue(report.valid, msg=f"Errors: {report.errors}")

    def test_render_and_validate_all_five_app_types(self) -> None:
        cases = [
            ManagedApp(
                name="Obsidian",
                app_type=AppType.APPIMAGE,
                exec_target="/home/user/Applications/Obsidian 1.7.AppImage",
                categories=["Office"],
            ),
            ManagedApp(
                name="Backup Tool",
                app_type=AppType.SCRIPT,
                exec_target="/home/user/scripts/backup.sh",
                script_interpreter="bash",
                terminal=True,
                categories=["System"],
            ),
            ManagedApp(
                name="Godot Engine",
                app_type=AppType.BINARY,
                exec_target="/home/user/Tools/Godot/godot.linuxbsd",
                working_dir="/home/user/Tools/Godot",
                categories=["Development"],
            ),
            ManagedApp(
                name="Excalidraw",
                app_type=AppType.WEBAPP,
                exec_target="https://excalidraw.com",
                webapp_browser="chromium",
                startup_wm_class="deskforge-excalidraw",
                categories=["Network", "Graphics"],
            ),
        ]
        for app in cases:
            with self.subTest(app_type=app.app_type.value):
                content = self.engine.render(app)
                report = self.engine.validate_content(content)
                self.assertTrue(report.valid, msg=f"{app.name} failed validation: {report.errors}")

    def test_import_legacy_autojar_desktop_file(self) -> None:
        legacy_desktop = (
            "[Desktop Entry]\n"
            "Name=Mi Viejo Jar\n"
            "Comment=Executable jar file\n"
            "Exec=java -Xmx2G -jar /opt/apps/demo.jar --nogui\n"
            "Icon=/opt/apps/AutoJar.png\n"
            "Terminal=false\n"
            "Type=Application\n"
            "Categories=Game;\n"
        )
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "Mi Viejo Jar.desktop"
            p.write_text(legacy_desktop, encoding="utf-8")
            imported = self.engine.import_from_desktop_file(p)
            self.assertIsNotNone(imported)
            assert imported is not None
            self.assertEqual(imported.app_type, AppType.JAR)
            self.assertEqual(imported.name, "Mi Viejo Jar")
            self.assertEqual(imported.exec_target, "/opt/apps/demo.jar")
            self.assertEqual(imported.java_options.max_memory, "2G")
            self.assertEqual(imported.args, ["--nogui"])
            self.assertFalse(imported.managed_by_deskforge)


if __name__ == "__main__":
    unittest.main()
