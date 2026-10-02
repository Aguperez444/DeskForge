"""Main DeskForge PySide6 (Qt 6) window with native Wayland/X11 Drag & Drop."""

from __future__ import annotations

from pathlib import Path
import sys

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QDragEnterEvent, QDragLeaveEvent, QDropEvent, QIcon, QKeySequence, QResizeEvent, QShortcut
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from deskforge import __app_name__, __version__
from deskforge.application import ServiceContainer, build_services
from deskforge.domain.exceptions import DeskForgeError
from deskforge.domain.models import AppType, ManagedApp
from deskforge.infrastructure.system_integration import is_system_binary, resolve_executable_target
from deskforge.ui.editor_dialog import AppEditorDialog
from deskforge.ui.library_view import LibraryView
from deskforge.ui.scan_dialog import ScanAndImportDialog
from deskforge.ui.settings_dialog import SettingsAndDoctorDialog
from deskforge.ui.theme import build_stylesheet, is_dark_theme, normalize_theme_name, toggled_theme
from deskforge.ui.widgets import (
    ConfirmActionDialog,
    DropOverlay,
    IconProvider,
    ToastBanner,
    extract_target_from_text,
    extract_targets_from_urls,
)


class DeskForgeMainWindow(QMainWindow):
    """Root Qt 6 window for DeskForge with native Drag & Drop, dark/light themes, and shortcuts."""

    def __init__(
        self,
        services: ServiceContainer | None = None,
        initial_target: str | None = None,
    ) -> None:
        super().__init__()
        self._services = services or build_services()
        self._config = self._services.app_service.get_config()
        self._current_theme = normalize_theme_name(
            self._config.theme,
            system_is_dark=self._services.system.detect_system_dark_mode(),
        )
        self._icon_provider = IconProvider(self._services.icon_store)

        self.setWindowTitle(f"{__app_name__} v{__version__}")
        self.setMinimumSize(940, 600)
        self.setAcceptDrops(True)

        self._apply_window_icon()
        self._restore_geometry()
        self._build_layout()
        self._bind_shortcuts()

        # Floating overlays
        self._toast = ToastBanner(self)
        self._drop_overlay = DropOverlay(self)

        self._apply_theme(self._current_theme, persist=False)
        self._refresh_library()

        if initial_target:
            cleaned = extract_target_from_text(initial_target) or initial_target
            QTimer.singleShot(150, lambda: self.open_integrate_dialog(initial_target=cleaned))

    # --------------------------------------------------------------- Setup UI

    def _apply_window_icon(self) -> None:
        icon_path = self._services.paths.default_app_icon
        if icon_path.exists():
            self.setWindowIcon(QIcon(str(icon_path)))

    def _restore_geometry(self) -> None:
        w, h = 1100, 720
        geom = self._config.window_geometry
        if "x" in geom:
            try:
                parts = geom.split("+")[0].split("x")
                w = max(940, min(1920, int(parts[0])))
                h = max(600, min(1200, int(parts[1])))
            except ValueError:
                pass
        self.resize(w, h)

    def _build_layout(self) -> None:
        central = QWidget()
        self.setCentralWidget(central)
        main_v = QVBoxLayout(central)
        main_v.setContentsMargins(0, 0, 0, 0)
        main_v.setSpacing(0)

        # Top Bar
        topbar = QFrame()
        topbar.setObjectName("TopBar")
        tb = QHBoxLayout(topbar)
        tb.setContentsMargins(16, 12, 16, 12)
        tb.setSpacing(10)

        brand_icon = QLabel()
        brand_icon.setFixedSize(36, 36)
        brand_icon.setPixmap(
            self._icon_provider.get_pixmap(str(self._services.paths.default_app_icon), size=36, app_name="D")
        )
        tb.addWidget(brand_icon)

        brand_col = QVBoxLayout()
        brand_col.setSpacing(0)
        b_title = QLabel("DeskForge")
        b_title.setObjectName("BrandTitle")
        b_sub = QLabel("Gestor universal de apps Linux")
        b_sub.setObjectName("BrandSubtitle")
        brand_col.addWidget(b_title)
        brand_col.addWidget(b_sub)
        tb.addLayout(brand_col)
        tb.addSpacing(8)

        self._search_edit = QLineEdit()
        self._search_edit.setPlaceholderText("🔍  Buscar aplicaciones por nombre, categoría o ruta... (Ctrl+F)")
        self._search_edit.setClearButtonEnabled(True)
        self._search_edit.textChanged.connect(lambda txt: self._library.set_search(txt))
        tb.addWidget(self._search_edit, stretch=1)

        btn_integrate = QPushButton("＋ Integrar")
        btn_integrate.setProperty("variant", "success")
        btn_integrate.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_integrate.clicked.connect(self.open_file_and_integrate)
        tb.addWidget(btn_integrate)

        btn_webapp = QPushButton("🌐 WebApp")
        btn_webapp.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_webapp.clicked.connect(lambda: self.open_integrate_dialog(webapp_mode=True))
        tb.addWidget(btn_webapp)

        btn_scan = QPushButton("🔎 Escanear")
        btn_scan.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_scan.clicked.connect(self.open_scan_dialog)
        tb.addWidget(btn_scan)

        self._theme_btn = QPushButton("☀" if is_dark_theme(self._current_theme) else "🌙")
        self._theme_btn.setFixedWidth(38)
        self._theme_btn.setToolTip("Alternar tema claro / oscuro")
        self._theme_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._theme_btn.clicked.connect(self._toggle_theme)
        tb.addWidget(self._theme_btn)

        btn_settings = QPushButton("⚙")
        btn_settings.setFixedWidth(38)
        btn_settings.setToolTip("Ajustes y Diagnóstico (Ctrl+,)")
        btn_settings.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_settings.clicked.connect(lambda: self.open_settings_dialog(initial_tab=0))
        tb.addWidget(btn_settings)

        main_v.addWidget(topbar)

        # Main Library View
        self._library = LibraryView(
            icon_provider=self._icon_provider,
            on_launch=self._handle_launch,
            on_edit=self._handle_edit,
            on_upgrade=self._handle_upgrade,
            on_remove=self._handle_remove,
            on_open_folder=self._handle_open_folder,
            on_new_file=self.open_file_and_integrate,
            on_new_webapp=lambda: self.open_integrate_dialog(webapp_mode=True),
            on_scan=self.open_scan_dialog,
        )
        main_v.addWidget(self._library, stretch=1)

        # Bottom Status Bar
        statusbar = QFrame()
        statusbar.setObjectName("StatusBar")
        sb = QHBoxLayout(statusbar)
        sb.setContentsMargins(16, 7, 16, 7)
        sb.setSpacing(12)

        self._status_count = QLabel("")
        self._status_count.setProperty("muted", True)
        self._status_count.setStyleSheet("font-size: 12px;")
        sb.addWidget(self._status_count)

        self._doctor_btn = QPushButton("")
        self._doctor_btn.setProperty("variant", "ghost")
        self._doctor_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._doctor_btn.clicked.connect(lambda: self.open_settings_dialog(initial_tab=1))
        sb.addWidget(self._doctor_btn)

        sb.addStretch(1)

        tip = QLabel("Tip: Arrastrá un archivo/URL aquí o pegalo con Ctrl+V · Ctrl+N integrar · F5 refrescar")
        tip.setProperty("muted", True)
        tip.setStyleSheet("font-size: 11.5px;")
        sb.addWidget(tip)

        main_v.addWidget(statusbar)

    def _bind_shortcuts(self) -> None:
        QShortcut(QKeySequence("Ctrl+N"), self).activated.connect(self.open_file_and_integrate)
        QShortcut(QKeySequence("Ctrl+F"), self).activated.connect(self._focus_search)
        QShortcut(QKeySequence("F5"), self).activated.connect(lambda: self._refresh_library(show_toast=True))
        QShortcut(QKeySequence("Ctrl+,"), self).activated.connect(lambda: self.open_settings_dialog(0))
        QShortcut(QKeySequence("Ctrl+V"), self).activated.connect(self._handle_paste_shortcut)

    def _focus_search(self) -> None:
        self._search_edit.setFocus()
        self._search_edit.selectAll()

    # ------------------------------------------------- Native Qt Drag & Drop

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        mime = event.mimeData()
        if mime.hasUrls() or mime.hasText():
            event.acceptProposedAction()
            self._drop_overlay.sync_geometry()
            self._drop_overlay.show()
            self._drop_overlay.raise_()
        else:
            event.ignore()

    def dragLeaveEvent(self, event: QDragLeaveEvent) -> None:
        self._drop_overlay.hide()
        super().dragLeaveEvent(event)

    def dropEvent(self, event: QDropEvent) -> None:
        self._drop_overlay.hide()
        mime = event.mimeData()
        targets: list[str] = []
        if mime.hasUrls():
            targets = extract_targets_from_urls(mime.urls())
        if not targets and mime.hasText():
            parsed = extract_target_from_text(mime.text())
            if parsed:
                targets = [parsed]

        if targets:
            event.acceptProposedAction()
            self.open_integrate_dialog(initial_target=targets[0])
        else:
            event.ignore()
            self._toast.show_message("No se reconoció un archivo o URL válida en el elemento soltado.", "warning")

    def resizeEvent(self, event: QResizeEvent) -> None:
        super().resizeEvent(event)
        if hasattr(self, "_toast") and self._toast.isVisible():
            self._toast.reposition()
        if hasattr(self, "_drop_overlay") and self._drop_overlay.isVisible():
            self._drop_overlay.sync_geometry()

    def _handle_paste_shortcut(self) -> None:
        focused = QApplication.focusWidget()
        if isinstance(focused, (QLineEdit, QPlainTextEdit)):
            focused.paste()
            return
        clip = QApplication.clipboard()
        if clip is None:
            return
        mime = clip.mimeData()
        targets: list[str] = []
        if mime and mime.hasUrls():
            targets = extract_targets_from_urls(mime.urls())
        if not targets:
            parsed = extract_target_from_text(clip.text())
            if parsed:
                targets = [parsed]

        if targets:
            self.open_integrate_dialog(initial_target=targets[0])
        else:
            self._toast.show_message(
                "El portapapeles no contiene una ruta de archivo válida ni una URL http(s).",
                "warning",
            )

    # ---------------------------------------------------------------- Actions

    def _refresh_library(self, show_toast: bool = False) -> None:
        apps = self._services.app_service.list_apps()
        self._library.set_apps(apps)
        self._status_count.setText(f"{len(apps)} aplicación(es) gestionada(s)")

        issues = self._services.doctor_service.run_checks()
        if issues:
            self._doctor_btn.setText(f"⚠ {len(issues)} incidencia(s) — Ver Doctor")
            self._doctor_btn.setStyleSheet("color: #f59e0b; font-weight: 600;")
        else:
            self._doctor_btn.setText("✓ Todo saludable")
            self._doctor_btn.setStyleSheet("color: #22c55e; font-weight: 600;")

        if show_toast:
            self._toast.show_message("Biblioteca actualizada.", "info", duration_ms=1800)

    def open_file_and_integrate(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Seleccionar archivo para integrar en DeskForge",
            str(self._services.paths.downloads_dir),
            "Aplicaciones soportadas (*.AppImage *.appimage *.jar *.sh *.py *.bin *.run);;AppImage (*.AppImage *.appimage);;Java JAR (*.jar);;Scripts (*.sh *.bash *.py *.rb *.js);;Todos los archivos (*)",
        )
        if path:
            self.open_integrate_dialog(initial_target=path)

    def open_integrate_dialog(self, initial_target: str = "", webapp_mode: bool = False) -> None:
        dlg = AppEditorDialog(
            parent=self,
            services=self._services,
            icon_provider=self._icon_provider,
            on_saved=self._on_app_saved,
            existing_app=None,
            initial_target=initial_target,
            initial_mode_webapp=webapp_mode,
        )
        dlg.exec()

    def open_scan_dialog(self) -> None:
        dlg = ScanAndImportDialog(
            parent=self,
            services=self._services,
            on_integrate_target=lambda target: self.open_integrate_dialog(initial_target=target),
            on_imported=self._on_external_imported,
        )
        dlg.exec()

    def open_settings_dialog(self, initial_tab: int = 0) -> None:
        dlg = SettingsAndDoctorDialog(
            parent=self,
            services=self._services,
            current_theme=self._current_theme,
            on_theme_change=lambda t: self._apply_theme(t, persist=True),
            on_repaired=lambda _count: self._refresh_library(),
            on_toast=lambda msg, kind: self._toast.show_message(msg, kind),
            initial_tab=initial_tab,
        )
        dlg.exec()

    def _on_app_saved(self, app: ManagedApp, is_edit: bool) -> None:
        self._icon_provider.invalidate()
        self._refresh_library()
        verb = "actualizada" if is_edit else "integrada"
        self._toast.show_message(f"✓ '{app.name}' {verb} correctamente en tu escritorio.", "success")

    def _on_external_imported(self, app: ManagedApp) -> None:
        self._refresh_library()
        self._toast.show_message(f"📥 '{app.name}' importada a DeskForge.", "info")

    def _handle_launch(self, app: ManagedApp) -> None:
        try:
            self._services.app_service.launch_app(app.id)
            self._toast.show_message(f"▶ Lanzando {app.name}...", "info", duration_ms=2200)
        except DeskForgeError as exc:
            self._toast.show_message(str(exc), "danger", duration_ms=5000)

    def _handle_edit(self, app: ManagedApp) -> None:
        dlg = AppEditorDialog(
            parent=self,
            services=self._services,
            icon_provider=self._icon_provider,
            on_saved=self._on_app_saved,
            existing_app=app,
        )
        dlg.exec()

    def _handle_upgrade(self, app: ManagedApp) -> None:
        new_file, _ = QFileDialog.getOpenFileName(
            self,
            f"Seleccionar nueva versión para {app.name}",
            str(self._services.paths.downloads_dir),
            "AppImage / JAR / Ejecutables (*.AppImage *.appimage *.jar *.sh *.py *.bin *.run);;Todos los archivos (*)",
        )
        if not new_file:
            return

        dlg = ConfirmActionDialog(
            parent=self,
            title=f"Actualizar {app.name}",
            message=(
                f"Se reemplazará el ejecutable de '{app.name}' por:\n{new_file}\n\n"
                "Se mantendrán intactos tus argumentos, variables de entorno, configuración JVM y categorías."
            ),
            confirm_text="↑ Actualizar versión",
            confirm_variant="primary",
            checkbox_text="Actualizar también el ícono desde el nuevo archivo",
            checkbox_default=False,
        )
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return

        try:
            updated = self._services.app_service.replace_binary(
                app.id,
                new_file,
                refresh_icon=dlg.checkbox_checked,
            )
            self._icon_provider.invalidate()
            self._refresh_library()
            ver = f" (v{updated.version})" if updated.version else ""
            self._toast.show_message(f"✓ '{updated.name}' actualizada{ver}.", "success")
        except DeskForgeError as exc:
            self._toast.show_message(str(exc), "danger", duration_ms=5000)

    def _handle_remove(self, app: ManagedApp) -> None:
        checkbox_text = None
        if app.app_type != AppType.WEBAPP and not is_system_binary(app.exec_target):
            action = "mover a la Papelera" if self._config.move_to_trash_on_delete else "eliminar del disco"
            checkbox_text = f"También {action} el archivo ejecutable ({Path(app.exec_target).name})"

        dlg = ConfirmActionDialog(
            parent=self,
            title=f"Eliminar {app.name}",
            message=f"Se eliminará el lanzador de '{app.name}' del menú de aplicaciones y del Escritorio.",
            confirm_text="🗑 Eliminar",
            confirm_variant="danger-solid",
            checkbox_text=checkbox_text,
            checkbox_default=False,
        )
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return

        try:
            self._services.app_service.remove_app(
                app.id,
                delete_target_file=dlg.checkbox_checked,
                use_trash=self._config.move_to_trash_on_delete,
            )
            self._refresh_library()
            self._toast.show_message(f"✓ '{app.name}' eliminada.", "info")
        except DeskForgeError as exc:
            self._toast.show_message(str(exc), "danger", duration_ms=5000)

    def _handle_open_folder(self, app: ManagedApp) -> None:
        try:
            _norm, resolved, _is_sys = resolve_executable_target(app.exec_target)
            target = resolved or Path(app.exec_target)
            self._services.system.open_in_file_manager(target)
        except DeskForgeError as exc:
            self._toast.show_message(str(exc), "danger", duration_ms=4000)

    def _toggle_theme(self) -> None:
        self._apply_theme(toggled_theme(self._current_theme), persist=True)

    def _apply_theme(self, theme_name: str, persist: bool = True) -> None:
        normalized = normalize_theme_name(theme_name)
        self._current_theme = normalized
        qapp = QApplication.instance()
        if qapp is not None:
            qapp.setStyleSheet(build_stylesheet(normalized))
        self._theme_btn.setText("☀" if is_dark_theme(normalized) else "🌙")
        if persist:
            cfg = self._services.app_service.get_config()
            cfg.theme = normalized
            self._services.app_service.save_config(cfg)

    def closeEvent(self, event) -> None:
        try:
            cfg = self._services.app_service.get_config()
            cfg.window_geometry = f"{self.width()}x{self.height()}"
            self._services.app_service.save_config(cfg)
        except Exception:
            pass
        super().closeEvent(event)


def launch_gui(initial_target: str | None = None, services: ServiceContainer | None = None) -> None:
    """Create the Qt 6 QApplication and run the DeskForge graphical interface."""
    qapp = QApplication.instance()
    owns_app = qapp is None
    if qapp is None:
        qapp = QApplication(sys.argv)
        qapp.setApplicationName(__app_name__)
        qapp.setApplicationVersion(__version__)
        qapp.setDesktopFileName("deskforge")

    window = DeskForgeMainWindow(services=services, initial_target=initial_target)
    window.show()
    if owns_app:
        qapp.exec()
