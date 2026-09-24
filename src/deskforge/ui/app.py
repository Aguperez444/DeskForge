"""Main DeskForge ttkbootstrap GUI application window."""

from __future__ import annotations

from pathlib import Path
import tkinter as tk
from tkinter import filedialog
from urllib.parse import unquote, urlparse

import ttkbootstrap as ttk

from deskforge import __app_name__, __version__
from deskforge.application import ServiceContainer, build_services
from deskforge.domain.exceptions import DeskForgeError
from deskforge.domain.models import AppType, ManagedApp
from deskforge.infrastructure.system_integration import is_system_binary, resolve_executable_target
from deskforge.ui.editor_dialog import AppEditorDialog
from deskforge.ui.library_view import LibraryView
from deskforge.ui.scan_dialog import ScanAndImportDialog
from deskforge.ui.settings_dialog import SettingsAndDoctorDialog
from deskforge.ui.theme import DEFAULT_DARK_THEME, DEFAULT_LIGHT_THEME, is_dark_theme, toggled_theme
from deskforge.ui.widgets import ConfirmDialog, IconCache, ToastManager, center_window
from deskforge.ui.xdnd import XdndDropTarget


def _extract_target_from_text(raw: str) -> str | None:
    """Parse a pasted clipboard or DnD string (file:// URI, local path, or https:// URL)."""
    text = raw.strip()
    if not text:
        return None
    # Take first non-empty line (handles multi-line file:// URI drops)
    first = next((line.strip() for line in text.splitlines() if line.strip()), "")
    if not first:
        return None
    # Strip TkDnD braces {path with spaces}
    if first.startswith("{") and first.endswith("}"):
        first = first[1:-1]
    if first.startswith("file://"):
        path = unquote(urlparse(first).path)
        return path if Path(path).exists() else None
    if first.startswith(("http://", "https://")):
        return first
    expanded = Path(first).expanduser()
    if expanded.is_file():
        return str(expanded.resolve())
    return None


class DeskForgeApp(ttk.Window):
    """Root application window for DeskForge."""

    def __init__(
        self,
        services: ServiceContainer | None = None,
        initial_target: str | None = None,
    ) -> None:
        self._services = services or build_services()
        self._config = self._services.app_service.get_config()

        initial_theme = self._config.theme or (
            DEFAULT_DARK_THEME if self._services.system.detect_system_dark_mode() else DEFAULT_LIGHT_THEME
        )
        super().__init__(themename=initial_theme, title=f"{__app_name__} v{__version__}")

        self._current_theme = initial_theme
        self._icon_cache = IconCache(self._services.icon_store)
        self._toast = ToastManager(self)
        self._dnd_enabled = False
        self._xdnd: XdndDropTarget | None = None
        self._drop_overlay: ttk.Frame | None = None
        self._search_var = tk.StringVar()

        self.minsize(920, 580)
        self._apply_window_icon()
        self._restore_geometry()
        self._build_layout()
        self._bind_shortcuts()
        self.after(200, self._enable_drag_and_drop)
        self._refresh_library()

        self.protocol("WM_DELETE_WINDOW", self._on_close)

        if initial_target:
            cleaned = _extract_target_from_text(initial_target) or initial_target
            self.after(150, lambda: self.open_integrate_dialog(initial_target=cleaned))

    # --------------------------------------------------------------- Setup UI

    def _apply_window_icon(self) -> None:
        icon_path = self._services.paths.default_app_icon
        if icon_path.exists():
            photo = self._icon_cache.get_icon(str(icon_path), size=64, app_name="D")
            self._window_icon_ref = photo
            try:
                self.wm_iconphoto(True, photo)
            except tk.TclError:
                pass

    def _restore_geometry(self) -> None:
        w, h = 1080, 700
        geom = self._config.window_geometry
        if "x" in geom:
            try:
                parts = geom.split("+")[0].split("x")
                w = max(920, min(1920, int(parts[0])))
                h = max(580, min(1200, int(parts[1])))
            except ValueError:
                pass
        center_window(self, w, h)

    def _build_layout(self) -> None:
        # Top Navigation / Toolbar
        topbar = ttk.Frame(self, padding=(14, 12, 14, 8))
        topbar.pack(fill="x")

        brand_icon = self._icon_cache.get_icon(str(self._services.paths.default_app_icon), size=32, app_name="D")
        brand_lbl = ttk.Label(topbar, image=brand_icon)
        brand_lbl.image = brand_icon
        brand_lbl.pack(side="left", padx=(0, 8))

        title_col = ttk.Frame(topbar)
        title_col.pack(side="left", padx=(0, 16))
        ttk.Label(title_col, text="DeskForge", font=("Sans", 14, "bold")).pack(anchor="w")
        ttk.Label(title_col, text="Gestor universal de apps Linux", bootstyle="secondary", font=("Sans", 8)).pack(
            anchor="w"
        )

        # Search input
        search_box = ttk.Frame(topbar)
        search_box.pack(side="left", fill="x", expand=True, padx=(0, 12))
        self._search_entry = ttk.Entry(search_box, textvariable=self._search_var, width=28)
        self._search_entry.pack(side="left", fill="x", expand=True)
        self._search_var.trace_add("write", lambda *_: self._library.set_search(self._search_var.get()))

        # Primary Actions
        ttk.Button(
            topbar,
            text="＋ Integrar",
            bootstyle="success",
            command=self.open_file_and_integrate,
        ).pack(side="left", padx=(0, 6))

        ttk.Button(
            topbar,
            text="🌐 WebApp",
            bootstyle="info-outline",
            command=lambda: self.open_integrate_dialog(webapp_mode=True),
        ).pack(side="left", padx=(0, 6))

        ttk.Button(
            topbar,
            text="🔎 Escanear",
            bootstyle="secondary-outline",
            command=self.open_scan_dialog,
        ).pack(side="left", padx=(0, 6))

        self._theme_btn = ttk.Button(
            topbar,
            text="☀" if is_dark_theme(self._current_theme) else "🌙",
            bootstyle="secondary-outline",
            width=3,
            command=self._toggle_theme,
        )
        self._theme_btn.pack(side="left", padx=(0, 6))

        ttk.Button(
            topbar,
            text="⚙",
            bootstyle="secondary-outline",
            width=3,
            command=lambda: self.open_settings_dialog(initial_tab=0),
        ).pack(side="left")

        ttk.Separator(self, orient="horizontal").pack(fill="x")

        # Main Library View
        self._library = LibraryView(
            self,
            icon_cache=self._icon_cache,
            on_launch=self._handle_launch,
            on_edit=self._handle_edit,
            on_upgrade=self._handle_upgrade,
            on_remove=self._handle_remove,
            on_open_folder=self._handle_open_folder,
            on_new_file=self.open_file_and_integrate,
            on_new_webapp=lambda: self.open_integrate_dialog(webapp_mode=True),
            on_scan=self.open_scan_dialog,
        )
        self._library.pack(fill="both", expand=True)

        # Bottom Status Bar
        ttk.Separator(self, orient="horizontal").pack(fill="x")
        statusbar = ttk.Frame(self, padding=(14, 6))
        statusbar.pack(fill="x")
        self._status_count = ttk.Label(statusbar, text="", bootstyle="secondary", font=("Sans", 9))
        self._status_count.pack(side="left")

        self._doctor_badge = ttk.Button(
            statusbar,
            text="",
            bootstyle="secondary-link",
            command=lambda: self.open_settings_dialog(initial_tab=1),
        )
        self._doctor_badge.pack(side="left", padx=(12, 0))

        self._status_tip = ttk.Label(
            statusbar,
            text="Tip: Pegá un archivo o URL con Ctrl+V · Ctrl+N integrar · Ctrl+F buscar",
            bootstyle="secondary",
            font=("Sans", 9),
        )
        self._status_tip.pack(side="right")

    def _bind_shortcuts(self) -> None:
        self.bind_all("<Control-n>", lambda _e: self.open_file_and_integrate())
        self.bind_all("<Control-f>", lambda _e: self._search_entry.focus_set())
        self.bind_all("<F5>", lambda _e: self._refresh_library(show_toast=True))
        self.bind_all("<Control-comma>", lambda _e: self.open_settings_dialog(0))
        self.bind("<Control-v>", self._handle_paste_shortcut)

    def _enable_drag_and_drop(self) -> None:
        """Enable native Drag & Drop via tkdnd (if installed) or pure-Python X11/XWayland XDND v5."""
        # 1. Try tkdnd if present
        try:
            self.tk.call("package", "require", "tkdnd")
            self.tk.call("tkdnd::drop_target", "register", self._w, "DND_Files")
            self.bind("<<Drop>>", self._handle_tkdnd_drop)
            self._dnd_enabled = True
            self._status_tip.configure(text="Tip: Arrastrá un archivo/URL aquí o pegalo con Ctrl+V · Ctrl+N integrar")
            return
        except tk.TclError:
            pass

        # 2. Pure-Python X11/XWayland XDND v5 proxy (works on Tcl/Tk 9.0 + KDE/GNOME!)
        xdnd = XdndDropTarget(
            self,
            on_drop=self._handle_xdnd_drop,
            on_drag_enter=self._show_drop_overlay,
            on_drag_leave=self._hide_drop_overlay,
        )
        if xdnd.start():
            self._xdnd = xdnd
            self._dnd_enabled = True
            self._status_tip.configure(text="Tip: Arrastrá un archivo/URL aquí o pegalo con Ctrl+V · Ctrl+N integrar")
        else:
            self._dnd_enabled = False

    def _show_drop_overlay(self) -> None:
        if self._drop_overlay is not None:
            return
        overlay = ttk.Frame(self, bootstyle="info", padding=24)
        ttk.Label(
            overlay,
            text="⬇  Soltá el archivo o URL aquí para integrarlo en DeskForge",
            bootstyle="info-inverse",
            font=("Sans", 14, "bold"),
        ).pack(expand=True)
        overlay.place(relx=0.5, rely=0.5, anchor="center", relwidth=0.72, height=110)
        overlay.lift()
        self._drop_overlay = overlay

    def _hide_drop_overlay(self) -> None:
        if self._drop_overlay is not None:
            try:
                self._drop_overlay.destroy()
            except tk.TclError:
                pass
            self._drop_overlay = None

    def _handle_xdnd_drop(self, targets: list[str]) -> None:
        self._hide_drop_overlay()
        if not targets:
            return
        self.open_integrate_dialog(initial_target=targets[0])

    def _handle_tkdnd_drop(self, event) -> None:
        data = getattr(event, "data", "")
        target = _extract_target_from_text(str(data))
        if target:
            self.open_integrate_dialog(initial_target=target)

    def _handle_paste_shortcut(self, _event=None) -> None:
        # Don't intercept normal typing paste inside text/entry widgets
        focused = self.focus_get()
        if isinstance(focused, (tk.Entry, ttk.Entry, tk.Text)):
            return
        try:
            clip = self.clipboard_get()
        except tk.TclError:
            return
        target = _extract_target_from_text(clip)
        if target:
            self.open_integrate_dialog(initial_target=target)
        else:
            self._toast.show("El portapapeles no contiene una ruta de archivo válida ni una URL http(s).", "warning")

    # ---------------------------------------------------------------- Actions

    def _refresh_library(self, show_toast: bool = False) -> None:
        apps = self._services.app_service.list_apps()
        self._library.set_apps(apps)
        self._status_count.configure(text=f"{len(apps)} aplicación(es) gestionada(s)")

        issues = self._services.doctor_service.run_checks()
        if issues:
            self._doctor_badge.configure(text=f"⚠ {len(issues)} incidencia(s) — Ver Doctor", bootstyle="warning-link")
        else:
            self._doctor_badge.configure(text="✓ Todo saludable", bootstyle="success-link")

        if show_toast:
            self._toast.show("Biblioteca actualizada.", "info", duration_ms=1800)

    def open_file_and_integrate(self) -> None:
        path = filedialog.askopenfilename(
            parent=self,
            title="Seleccionar archivo para integrar en DeskForge",
            filetypes=[
                ("Aplicaciones soportadas", "*.AppImage *.appimage *.jar *.sh *.py *.bin *.run"),
                ("AppImage", "*.AppImage *.appimage"),
                ("Java JAR", "*.jar"),
                ("Scripts", "*.sh *.bash *.py *.rb *.js"),
                ("Todos los archivos", "*"),
            ],
        )
        if path:
            self.open_integrate_dialog(initial_target=path)

    def open_integrate_dialog(self, initial_target: str = "", webapp_mode: bool = False) -> None:
        AppEditorDialog(
            parent=self,
            services=self._services,
            icon_cache=self._icon_cache,
            on_saved=self._on_app_saved,
            existing_app=None,
            initial_target=initial_target,
            initial_mode_webapp=webapp_mode,
        )

    def open_scan_dialog(self) -> None:
        ScanAndImportDialog(
            parent=self,
            services=self._services,
            on_integrate_target=lambda target: self.open_integrate_dialog(initial_target=target),
            on_imported=self._on_external_imported,
        )

    def open_settings_dialog(self, initial_tab: int = 0) -> None:
        SettingsAndDoctorDialog(
            parent=self,
            services=self._services,
            current_theme=self._current_theme,
            on_theme_change=self._apply_theme,
            on_repaired=lambda _count: self._refresh_library(),
            on_toast=lambda msg, style: self._toast.show(msg, style),
            initial_tab=initial_tab,
        )

    def _on_app_saved(self, app: ManagedApp, is_edit: bool) -> None:
        self._icon_cache.invalidate()
        self._refresh_library()
        verb = "actualizada" if is_edit else "integrada"
        self._toast.show(f"✓ '{app.name}' {verb} correctamente en tu escritorio.", "success")

    def _on_external_imported(self, app: ManagedApp) -> None:
        self._refresh_library()
        self._toast.show(f"📥 '{app.name}' importada a DeskForge.", "info")

    def _handle_launch(self, app: ManagedApp) -> None:
        try:
            self._services.app_service.launch_app(app.id)
            self._toast.show(f"▶ Lanzando {app.name}...", "info", duration_ms=2200)
        except DeskForgeError as exc:
            self._toast.show(str(exc), "danger", duration_ms=5000)

    def _handle_edit(self, app: ManagedApp) -> None:
        AppEditorDialog(
            parent=self,
            services=self._services,
            icon_cache=self._icon_cache,
            on_saved=self._on_app_saved,
            existing_app=app,
        )

    def _handle_upgrade(self, app: ManagedApp) -> None:
        new_file = filedialog.askopenfilename(
            parent=self,
            title=f"Seleccionar nueva versión para {app.name}",
            filetypes=[
                ("AppImage / JAR / Ejecutables", "*.AppImage *.appimage *.jar *.sh *.py *.bin *.run"),
                ("Todos los archivos", "*"),
            ],
        )
        if not new_file:
            return
        dlg = ConfirmDialog(
            parent=self,
            title=f"Actualizar {app.name}",
            message=(
                f"Se reemplazará el ejecutable de '{app.name}' por:\n{new_file}\n\n"
                "Se mantendrán intactos tus argumentos, variables de entorno, configuración JVM y categorías."
            ),
            confirm_text="↑ Actualizar versión",
            confirm_style="warning",
            checkbox_text="Actualizar también el ícono desde el nuevo archivo",
            checkbox_default=False,
        )
        if not dlg.confirmed:
            return
        try:
            updated = self._services.app_service.replace_binary(
                app.id,
                new_file,
                refresh_icon=dlg.checkbox_var.get(),
            )
            self._icon_cache.invalidate()
            self._refresh_library()
            ver = f" (v{updated.version})" if updated.version else ""
            self._toast.show(f"✓ '{updated.name}' actualizada{ver}.", "success")
        except DeskForgeError as exc:
            self._toast.show(str(exc), "danger", duration_ms=5000)

    def _handle_remove(self, app: ManagedApp) -> None:
        checkbox_text = None
        if app.app_type != AppType.WEBAPP and not is_system_binary(app.exec_target):
            action = "mover a la Papelera" if self._config.move_to_trash_on_delete else "eliminar del disco"
            checkbox_text = f"También {action} el archivo ejecutable ({Path(app.exec_target).name})"

        dlg = ConfirmDialog(
            parent=self,
            title=f"Eliminar {app.name}",
            message=f"Se eliminará el lanzador de '{app.name}' del menú de aplicaciones y del Escritorio.",
            confirm_text="🗑 Eliminar",
            confirm_style="danger",
            checkbox_text=checkbox_text,
            checkbox_default=False,
        )
        if not dlg.confirmed:
            return
        try:
            self._services.app_service.remove_app(
                app.id,
                delete_target_file=dlg.checkbox_var.get(),
                use_trash=self._config.move_to_trash_on_delete,
            )
            self._refresh_library()
            self._toast.show(f"✓ '{app.name}' eliminada.", "info")
        except DeskForgeError as exc:
            self._toast.show(str(exc), "danger", duration_ms=5000)

    def _handle_open_folder(self, app: ManagedApp) -> None:
        try:
            _norm, resolved, _is_sys = resolve_executable_target(app.exec_target)
            target = resolved or Path(app.exec_target)
            self._services.system.open_in_file_manager(target)
        except DeskForgeError as exc:
            self._toast.show(str(exc), "danger", duration_ms=4000)

    def _toggle_theme(self) -> None:
        self._apply_theme(toggled_theme(self._current_theme))

    def _apply_theme(self, theme_name: str) -> None:
        try:
            self.style.theme_use(theme_name)
        except tk.TclError:
            return
        self._current_theme = theme_name
        self._theme_btn.configure(text="☀" if is_dark_theme(theme_name) else "🌙")
        self._library.sync_theme()
        cfg = self._services.app_service.get_config()
        cfg.theme = theme_name
        self._services.app_service.save_config(cfg)

    def _on_close(self) -> None:
        if self._xdnd is not None:
            self._xdnd.stop()
        try:
            cfg = self._services.app_service.get_config()
            cfg.window_geometry = f"{self.winfo_width()}x{self.winfo_height()}"
            self._services.app_service.save_config(cfg)
        except Exception:
            pass
        self.destroy()


def launch_gui(initial_target: str | None = None, services: ServiceContainer | None = None) -> None:
    """Instantiate and run the DeskForge graphical interface."""
    app = DeskForgeApp(services=services, initial_target=initial_target)
    app.mainloop()
