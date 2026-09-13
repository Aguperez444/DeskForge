"""FreeDesktop Desktop Entry Specification v1.5 engine: build, parse, and validate."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import tempfile

from deskforge.domain.categories import normalize_categories
from deskforge.domain.exceptions import DesktopEntryError
from deskforge.domain.models import AppType, JavaOptions, ManagedApp

# Characters that require double-quoting inside a FreeDesktop Exec argument
_EXEC_RESERVED_CHARS = set(' \t\n"\'\\><~|&;$*?()#`')
_ENV_KEY_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_MEM_RE = re.compile(r"^\d+[kKmMgG]?$")


@dataclass
class ValidationReport:
    """Result of validating a generated .desktop entry."""

    valid: bool
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    used_external_validator: bool = False


def slugify_desktop_id(name: str, app_id: str) -> str:
    """Create a clean, safe, unique .desktop filename stem (e.g. deskforge-obsidian-a1b2c3)."""
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", name.lower()).strip("-")
    slug = slug[:40] or "app"
    return f"deskforge-{slug}-{app_id[:8]}"


def escape_exec_arg(arg: str) -> str:
    """
    Escape a single command argument according to FreeDesktop Desktop Entry Spec v1.5.
    Also escapes literal '%' to '%%' so desktop launchers don't treat it as a field code.
    """
    escaped = arg.replace("%", "%%")
    needs_quotes = not escaped or any(ch in _EXEC_RESERVED_CHARS for ch in escaped)
    if not needs_quotes:
        return escaped
    # Inside double quotes, escape backslash, double-quote, backtick, and dollar sign
    inner = (
        escaped.replace("\\", "\\\\")
        .replace('"', '\\"')
        .replace("`", "\\`")
        .replace("$", "\\$")
    )
    return f'"{inner}"'


def sanitize_entry_value(value: str) -> str:
    """Remove newlines and leading/trailing whitespace from single-line desktop entry values."""
    return " ".join(value.replace("\r", " ").replace("\n", " ").split())


def format_list_value(values: list[str]) -> str:
    """Format a FreeDesktop string list (semicolon-separated and terminated)."""
    cleaned = [sanitize_entry_value(v).replace(";", "") for v in values if v.strip()]
    if not cleaned:
        return ""
    return ";".join(cleaned) + ";"


def _gpu_env_vars() -> dict[str, str]:
    """Return environment hints for discrete GPU offloading when requested."""
    return {"DRI_PRIME": "1"}


class DesktopEntryEngine:
    """Builds, parses, and validates FreeDesktop .desktop files."""

    def build_exec_tokens(self, app: ManagedApp) -> list[str]:
        """Build the exact argv token list for an application."""
        tokens: list[str] = []

        merged_env: dict[str, str] = {}
        if app.dedicated_gpu:
            merged_env.update(_gpu_env_vars())
        for key, val in app.env_vars.items():
            k = key.strip()
            if k and _ENV_KEY_RE.match(k):
                merged_env[k] = val

        if merged_env:
            tokens.append("env")
            for k, v in merged_env.items():
                tokens.append(f"{k}={v}")

        if app.app_type == AppType.JAR:
            java_bin = (app.java_options.java_path or "java").strip()
            tokens.append(java_bin)
            if app.java_options.min_memory and _MEM_RE.match(app.java_options.min_memory.strip()):
                tokens.append(f"-Xms{app.java_options.min_memory.strip()}")
            if app.java_options.max_memory and _MEM_RE.match(app.java_options.max_memory.strip()):
                tokens.append(f"-Xmx{app.java_options.max_memory.strip()}")
            for flag in app.java_options.jvm_args:
                if flag.strip():
                    tokens.append(flag.strip())
            tokens.extend(["-jar", app.exec_target])
        elif app.app_type == AppType.WEBAPP:
            browser = (app.webapp_browser or "chromium").strip()
            browser_name = Path(browser).name.lower()
            if "firefox" in browser_name:
                tokens.extend([browser, "--new-window", app.exec_target])
            else:
                tokens.append(browser)
                tokens.append(f"--app={app.exec_target}")
                if app.startup_wm_class.strip():
                    tokens.append(f"--class={app.startup_wm_class.strip()}")
        elif app.app_type == AppType.SCRIPT and app.script_interpreter.strip():
            tokens.extend([app.script_interpreter.strip(), app.exec_target])
        else:
            tokens.append(app.exec_target)

        for arg in app.args:
            if arg.strip():
                tokens.append(arg)

        return tokens

    def build_exec_line(self, app: ManagedApp) -> str:
        """Render the FreeDesktop Exec= string."""
        tokens = self.build_exec_tokens(app)
        return " ".join(escape_exec_arg(tok) for tok in tokens)

    def render(self, app: ManagedApp) -> str:
        """Render complete .desktop file contents for a ManagedApp."""
        if not app.name.strip():
            raise DesktopEntryError("El nombre de la aplicación no puede estar vacío.")
        if not app.exec_target.strip():
            raise DesktopEntryError("El destino ejecutable o URL no puede estar vacío.")

        categories = normalize_categories(app.categories)
        lines: list[str] = [
            "[Desktop Entry]",
            "Version=1.5",
            "Type=Application",
            f"Name={sanitize_entry_value(app.name)}",
        ]

        comment = sanitize_entry_value(app.comment) or self._default_comment(app)
        lines.append(f"Comment={comment}")
        lines.append(f"Exec={self.build_exec_line(app)}")

        if app.icon_path.strip():
            lines.append(f"Icon={sanitize_entry_value(app.icon_path)}")

        if app.working_dir.strip():
            lines.append(f"Path={sanitize_entry_value(app.working_dir)}")

        lines.append(f"Terminal={'true' if app.terminal else 'false'}")
        lines.append("StartupNotify=true")
        lines.append(f"Categories={format_list_value(categories)}")

        if app.keywords:
            kw_line = format_list_value(app.keywords)
            if kw_line:
                lines.append(f"Keywords={kw_line}")

        if app.startup_wm_class.strip():
            lines.append(f"StartupWMClass={sanitize_entry_value(app.startup_wm_class)}")

        if app.dedicated_gpu:
            lines.append("PrefersNonDefaultGPU=true")

        if app.no_display:
            lines.append("NoDisplay=true")

        # Non-intrusive DeskForge tracking keys (valid per X- vendor extension spec)
        lines.append("X-DeskForge-Managed=true")
        lines.append(f"X-DeskForge-Id={app.id}")
        lines.append(f"X-DeskForge-Type={app.app_type.value}")
        if app.version.strip():
            lines.append(f"X-DeskForge-Version={sanitize_entry_value(app.version)}")

        return "\n".join(lines) + "\n"

    def validate_content(self, content: str) -> ValidationReport:
        """Validate .desktop content with built-in rules plus desktop-file-validate if installed."""
        errors: list[str] = []
        warnings: list[str] = []

        if "[Desktop Entry]" not in content:
            errors.append("Falta la cabecera obligatoria [Desktop Entry].")

        parsed = self.parse_text(content)
        if not parsed.get("Name"):
            errors.append("Falta la clave obligatoria Name=.")
        if not parsed.get("Exec"):
            errors.append("Falta la clave obligatoria Exec=.")
        if parsed.get("Type") != "Application":
            errors.append("Type= debe ser 'Application'.")
        cats = parsed.get("Categories", "")
        if cats and not cats.endswith(";"):
            errors.append("Categories= debe terminar con ';'.")

        validator_bin = shutil.which("desktop-file-validate")
        used_ext = False
        if validator_bin and not errors:
            used_ext = True
            with tempfile.NamedTemporaryFile("w", suffix=".desktop", encoding="utf-8", delete=True) as tmp:
                tmp.write(content)
                tmp.flush()
                try:
                    proc = subprocess.run(
                        [validator_bin, tmp.name],
                        capture_output=True,
                        text=True,
                        timeout=5,
                        check=False,
                    )
                    output = (proc.stdout + "\n" + proc.stderr).strip()
                    for raw_line in output.splitlines():
                        line = raw_line.strip()
                        if not line:
                            continue
                        cleaned = line.replace(f"{tmp.name}: ", "")
                        if "error:" in cleaned.lower():
                            errors.append(cleaned)
                        elif "warning:" in cleaned.lower():
                            warnings.append(cleaned)
                        elif proc.returncode != 0:
                            errors.append(cleaned)
                except (OSError, subprocess.SubprocessError) as exc:
                    warnings.append(f"No se pudo ejecutar desktop-file-validate: {exc}")

        return ValidationReport(
            valid=len(errors) == 0,
            errors=errors,
            warnings=warnings,
            used_external_validator=used_ext,
        )

    def parse_text(self, text: str) -> dict[str, str]:
        """Parse the [Desktop Entry] section without configparser interpolation bugs."""
        result: dict[str, str] = {}
        in_main_section = False
        for raw_line in text.splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue
            if line.startswith("[") and line.endswith("]"):
                in_main_section = line == "[Desktop Entry]"
                continue
            if not in_main_section or "=" not in line:
                continue
            key, val = line.split("=", 1)
            result[key.strip()] = val.strip()
        return result

    def parse_file(self, path: Path) -> dict[str, str]:
        """Parse an existing .desktop file from disk."""
        return self.parse_text(path.read_text(encoding="utf-8", errors="replace"))

    def import_from_desktop_file(self, path: Path) -> ManagedApp | None:
        """Convert an existing external .desktop file into a ManagedApp model."""
        data = self.parse_file(path)
        if data.get("Type") != "Application":
            return None
        name = data.get("Name", "").strip()
        exec_line = data.get("Exec", "").strip()
        if not name or not exec_line:
            return None

        try:
            tokens = shlex.split(exec_line)
        except ValueError:
            tokens = exec_line.split()

        # Strip FreeDesktop field codes like %U, %F, %f, %u
        tokens = [t for t in tokens if not re.fullmatch(r"%[fFuUdDnNickvm]", t)]
        if not tokens:
            return None

        env_vars: dict[str, str] = {}
        idx = 0
        if tokens[0] == "env":
            idx = 1
            while idx < len(tokens) and "=" in tokens[idx]:
                k, v = tokens[idx].split("=", 1)
                env_vars[k] = v
                idx += 1
        cmd_tokens = tokens[idx:]
        if not cmd_tokens:
            return None

        app_type = AppType.BINARY
        exec_target = cmd_tokens[0]
        extra_args = cmd_tokens[1:]
        java_opts = JavaOptions()
        webapp_browser = ""

        # Detect JAR command pattern: java [flags...] -jar <path> [args...]
        if "-jar" in cmd_tokens:
            jar_idx = cmd_tokens.index("-jar")
            if jar_idx + 1 < len(cmd_tokens):
                app_type = AppType.JAR
                java_opts.java_path = cmd_tokens[0]
                for flag in cmd_tokens[1:jar_idx]:
                    if flag.startswith("-Xmx"):
                        java_opts.max_memory = flag[4:]
                    elif flag.startswith("-Xms"):
                        java_opts.min_memory = flag[4:]
                    else:
                        java_opts.jvm_args.append(flag)
                exec_target = cmd_tokens[jar_idx + 1]
                extra_args = cmd_tokens[jar_idx + 2 :]
        elif any(tok.startswith("--app=http") for tok in cmd_tokens):
            app_type = AppType.WEBAPP
            webapp_browser = cmd_tokens[0]
            for tok in cmd_tokens[1:]:
                if tok.startswith("--app="):
                    exec_target = tok[6:]
                    break
            extra_args = []
        elif exec_target.lower().endswith(".appimage"):
            app_type = AppType.APPIMAGE
        elif Path(exec_target).suffix.lower() in {".sh", ".bash", ".py", ".rb", ".js"}:
            app_type = AppType.SCRIPT

        raw_cats = [c for c in data.get("Categories", "").split(";") if c.strip()]
        raw_kw = [k for k in data.get("Keywords", "").split(";") if k.strip()]

        return ManagedApp(
            name=name,
            app_type=app_type,
            exec_target=exec_target,
            icon_path=data.get("Icon", ""),
            comment=data.get("Comment", ""),
            categories=normalize_categories(raw_cats),
            keywords=raw_kw,
            args=extra_args,
            env_vars=env_vars,
            working_dir=data.get("Path", ""),
            terminal=data.get("Terminal", "false").lower() == "true",
            dedicated_gpu=data.get("PrefersNonDefaultGPU", "false").lower() == "true" or env_vars.get("DRI_PRIME") == "1",
            startup_wm_class=data.get("StartupWMClass", ""),
            no_display=data.get("NoDisplay", "false").lower() == "true",
            java_options=java_opts,
            webapp_browser=webapp_browser,
            desktop_file_path=str(path),
            managed_by_deskforge=data.get("X-DeskForge-Managed", "").lower() == "true",
        )

    @staticmethod
    def _default_comment(app: ManagedApp) -> str:
        defaults = {
            AppType.APPIMAGE: "Aplicación AppImage integrada con DeskForge",
            AppType.JAR: "Aplicación Java (.jar) integrada con DeskForge",
            AppType.BINARY: "Aplicación portable integrada con DeskForge",
            AppType.SCRIPT: "Script ejecutable integrado con DeskForge",
            AppType.WEBAPP: f"Aplicación web ({app.exec_target})",
        }
        return defaults.get(app.app_type, "Aplicación integrada con DeskForge")
