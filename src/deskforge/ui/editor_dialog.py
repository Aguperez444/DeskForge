"""3-tab Integrate / Edit QDialog (PySide6) with async inspection, JVM/Env controls, and .desktop preview."""

from __future__ import annotations

import shlex
from typing import Callable

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QAbstractItemView,
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QDialog,
    QFileDialog,
    QFormLayout,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QRadioButton,
    QScrollArea,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from deskforge.application import ServiceContainer
from deskforge.domain.categories import CATEGORIES
from deskforge.domain.exceptions import DeskForgeError
from deskforge.domain.models import AppType, DetectionResult, JavaOptions, ManagedApp, StorageMode
from deskforge.infrastructure.inspectors.java_runtime import detect_java_runtimes
from deskforge.infrastructure.inspectors.webapp_inspector import detect_installed_browsers
from deskforge.ui.widgets import IconProvider, run_async


class AppEditorDialog(QDialog):
    """Modal 3-tab dialog for integrating a new application or editing an existing ManagedApp."""

    def __init__(
        self,
        parent: QWidget,
        services: ServiceContainer,
        icon_provider: IconProvider,
        on_saved: Callable[[ManagedApp, bool], None],
        existing_app: ManagedApp | None = None,
        initial_target: str = "",
        initial_mode_webapp: bool = False,
    ) -> None:
        super().__init__(parent)
        self._services = services
        self._icon_provider = icon_provider
        self._on_saved = on_saved
        self._existing = existing_app
        self._is_edit = existing_app is not None
        self._icon_candidates: list[str] = []
        self._env_vars: dict[str, str] = dict(existing_app.env_vars) if existing_app else {}
        self._cat_checks: dict[str, QCheckBox] = {}
        self._type_buttons: dict[AppType, QPushButton] = {}
        self._storage_radios: dict[StorageMode, QRadioButton] = {}
        self._java_runtimes = detect_java_runtimes()
        self._browsers = detect_installed_browsers()
        self._cfg = services.app_service.get_config()

        self._current_type = (
            existing_app.app_type
            if existing_app
            else (AppType.WEBAPP if initial_mode_webapp else AppType.APPIMAGE)
        )

        self.setWindowTitle(f"Editar — {existing_app.name}" if existing_app else "Integrar nueva aplicación")
        self.resize(840, 690)
        self.setMinimumSize(760, 600)
        self.setModal(True)

        self._build_ui(initial_target)
        self._populate_initial_values(initial_target)
        self._sync_conditional_sections()
        self._refresh_icon_preview()

        if initial_target and not existing_app:
            self._run_inspection(initial_target)

    # ----------------------------------------------------------------- UI Build

    def _build_ui(self, initial_target: str) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(16, 14, 16, 14)
        root.setSpacing(10)

        # Header + async progress indicator
        header = QHBoxLayout()
        title_txt = f"Editar aplicación: {self._existing.name}" if self._existing else "Integrar aplicación en tu escritorio"
        title_lbl = QLabel(title_txt)
        title_lbl.setStyleSheet("font-size: 16px; font-weight: 700;")
        header.addWidget(title_lbl)
        header.addStretch(1)

        self._status_lbl = QLabel("")
        self._status_lbl.setStyleSheet("color: #2ec4b6; font-weight: 600;")
        header.addWidget(self._status_lbl)

        self._progress = QProgressBar()
        self._progress.setRange(0, 0)
        self._progress.setFixedWidth(130)
        self._progress.hide()
        header.addWidget(self._progress)
        root.addLayout(header)

        # Warning banner
        self._warning_lbl = QLabel("")
        self._warning_lbl.setWordWrap(True)
        self._warning_lbl.setStyleSheet(
            "background-color: rgba(217, 119, 6, 0.18); border: 1px solid #d97706; "
            "border-radius: 8px; padding: 8px 10px; color: #f59e0b; font-weight: 600;"
        )
        self._warning_lbl.hide()
        root.addWidget(self._warning_lbl)

        # Notebook tabs
        self._tabs = QTabWidget()
        self._tabs.currentChanged.connect(self._on_tab_changed)

        self._tabs.addTab(self._build_general_tab(), "  General  ")
        self._tabs.addTab(self._build_advanced_tab(), "  Avanzado (JVM / Env / GPU)  ")
        self._tabs.addTab(self._build_preview_tab(), "  Vista previa .desktop  ")
        root.addWidget(self._tabs, stretch=1)

        # Footer
        footer = QHBoxLayout()
        self._error_lbl = QLabel("")
        self._error_lbl.setStyleSheet("color: #ef4444; font-weight: 600;")
        self._error_lbl.setWordWrap(True)
        footer.addWidget(self._error_lbl, stretch=1)

        cancel_btn = QPushButton("Cancelar")
        cancel_btn.clicked.connect(self.reject)
        footer.addWidget(cancel_btn)

        save_txt = "💾 Guardar cambios" if self._is_edit else "✓ Integrar aplicación"
        self._save_btn = QPushButton(save_txt)
        self._save_btn.setProperty("variant", "success")
        self._save_btn.setDefault(True)
        self._save_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._save_btn.clicked.connect(self._on_submit)
        footer.addWidget(self._save_btn)
        root.addLayout(footer)

    def _build_general_tab(self) -> QWidget:
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        host = QWidget()
        form = QFormLayout(host)
        form.setContentsMargins(14, 14, 14, 14)
        form.setSpacing(10)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

        # Target row
        target_box = QHBoxLayout()
        target_box.setSpacing(6)
        self._target_edit = QLineEdit()
        self._target_edit.setPlaceholderText("/ruta/al/archivo.AppImage, .jar, binario o https://...")
        target_box.addWidget(self._target_edit, stretch=1)

        browse_btn = QPushButton("Examinar...")
        browse_btn.clicked.connect(self._browse_target)
        target_box.addWidget(browse_btn)

        detect_btn = QPushButton("✨ Detectar")
        detect_btn.setProperty("variant", "primary")
        detect_btn.clicked.connect(self._trigger_inspect)
        target_box.addWidget(detect_btn)
        form.addRow("Archivo o URL:", target_box)

        # AppType selector pills
        type_row = QHBoxLayout()
        type_row.setSpacing(6)
        self._type_group = QButtonGroup(self)
        self._type_group.setExclusive(True)
        for app_type in AppType:
            btn = QPushButton(app_type.label)
            btn.setCheckable(True)
            btn.setProperty("pill", True)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.clicked.connect(lambda _c=False, t=app_type: self._set_app_type(t))
            self._type_group.addButton(btn)
            type_row.addWidget(btn)
            self._type_buttons[app_type] = btn
        type_row.addStretch(1)
        form.addRow("Tipo de app:", type_row)

        # Name + Version
        nv_row = QHBoxLayout()
        nv_row.setSpacing(8)
        self._name_edit = QLineEdit()
        self._name_edit.setPlaceholderText("Nombre visible en el menú de aplicaciones")
        self._name_edit.textChanged.connect(self._refresh_icon_preview)
        nv_row.addWidget(self._name_edit, stretch=3)

        nv_row.addWidget(QLabel("Versión:"))
        self._version_edit = QLineEdit()
        self._version_edit.setPlaceholderText("ej. 1.0.0")
        self._version_edit.setMaximumWidth(130)
        nv_row.addWidget(self._version_edit, stretch=1)
        form.addRow("Nombre:", nv_row)

        # Comment
        self._comment_edit = QLineEdit()
        self._comment_edit.setPlaceholderText("Descripción breve de la aplicación")
        form.addRow("Descripción:", self._comment_edit)

        # Icon preview + path + extracted gallery
        icon_container = QWidget()
        icon_grid = QHBoxLayout(icon_container)
        icon_grid.setContentsMargins(0, 0, 0, 0)
        icon_grid.setSpacing(12)

        self._icon_preview = QLabel()
        self._icon_preview.setFixedSize(64, 64)
        self._icon_preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        icon_grid.addWidget(self._icon_preview, alignment=Qt.AlignmentFlag.AlignTop)

        icon_right = QVBoxLayout()
        icon_right.setSpacing(6)
        icon_input_row = QHBoxLayout()
        icon_input_row.setSpacing(6)
        self._icon_edit = QLineEdit()
        self._icon_edit.setPlaceholderText("Ruta a PNG/SVG/ICO o nombre de ícono del sistema")
        self._icon_edit.textChanged.connect(self._refresh_icon_preview)
        icon_input_row.addWidget(self._icon_edit, stretch=1)

        pick_icon_btn = QPushButton("Elegir...")
        pick_icon_btn.clicked.connect(self._browse_icon)
        icon_input_row.addWidget(pick_icon_btn)

        default_icon_btn = QPushButton("Default")
        default_icon_btn.setProperty("variant", "ghost")
        default_icon_btn.clicked.connect(lambda: self._icon_edit.setText(""))
        icon_input_row.addWidget(default_icon_btn)
        icon_right.addLayout(icon_input_row)

        self._gallery_host = QWidget()
        self._gallery_layout = QHBoxLayout(self._gallery_host)
        self._gallery_layout.setContentsMargins(0, 0, 0, 0)
        self._gallery_layout.setSpacing(6)
        self._gallery_host.hide()
        icon_right.addWidget(self._gallery_host)

        icon_grid.addLayout(icon_right, stretch=1)
        form.addRow("Ícono:", icon_container)

        # Categories multi-select grid
        cat_host = QWidget()
        cat_grid = QGridLayout(cat_host)
        cat_grid.setContentsMargins(0, 2, 0, 2)
        cat_grid.setHorizontalSpacing(14)
        cat_grid.setVerticalSpacing(5)
        for idx, cat in enumerate(CATEGORIES):
            cb = QCheckBox(cat.label_es)
            cb.setToolTip(f"{cat.code}: {cat.description_es}")
            self._cat_checks[cat.code] = cb
            cat_grid.addWidget(cb, idx // 4, idx % 4)
        form.addRow("Categorías:", cat_host)

        # Storage mode (shown only when integrating new non-WebApp)
        self._storage_label = QLabel("Almacenamiento:")
        self._storage_widget = QWidget()
        st_layout = QVBoxLayout(self._storage_widget)
        st_layout.setContentsMargins(0, 0, 0, 0)
        st_layout.setSpacing(4)
        self._storage_group = QButtonGroup(self)
        for mode in StorageMode:
            rb = QRadioButton(mode.label_es)
            self._storage_group.addButton(rb)
            self._storage_radios[mode] = rb
            st_layout.addWidget(rb)
        if not self._is_edit:
            form.addRow(self._storage_label, self._storage_widget)

        # Desktop shortcut toggle
        self._shortcut_check = QCheckBox("Crear también acceso directo en el Escritorio")
        form.addRow("", self._shortcut_check)

        scroll.setWidget(host)
        return scroll

    def _build_advanced_tab(self) -> QWidget:
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        host = QWidget()
        layout = QVBoxLayout(host)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(12)

        # 1. Java / JVM Section
        self._jvm_box = QGroupBox("Configuración Java / JVM (.jar)")
        jvm_form = QFormLayout(self._jvm_box)
        jvm_form.setSpacing(8)

        self._java_combo = QComboBox()
        self._java_combo.setEditable(True)
        self._java_combo.addItem("java")
        for rt in self._java_runtimes:
            self._java_combo.addItem(rt.path)
        jvm_form.addRow("Runtime Java / JDK:", self._java_combo)

        if self._java_runtimes:
            det_lbl = QLabel("Detectados: " + " · ".join(rt.version for rt in self._java_runtimes[:3]))
            det_lbl.setProperty("muted", True)
            det_lbl.setStyleSheet("font-size: 11px;")
            jvm_form.addRow("", det_lbl)

        mem_row = QHBoxLayout()
        mem_row.setSpacing(8)
        self._xmx_combo = QComboBox()
        self._xmx_combo.setEditable(True)
        self._xmx_combo.addItems(["", "512M", "1G", "2G", "4G", "6G", "8G", "16G"])
        self._xmx_combo.setMinimumWidth(100)
        mem_row.addWidget(QLabel("Máx (-Xmx):"))
        mem_row.addWidget(self._xmx_combo)

        self._xms_combo = QComboBox()
        self._xms_combo.setEditable(True)
        self._xms_combo.addItems(["", "256M", "512M", "1G", "2G"])
        self._xms_combo.setMinimumWidth(100)
        mem_row.addSpacing(12)
        mem_row.addWidget(QLabel("Inicial (-Xms):"))
        mem_row.addWidget(self._xms_combo)
        mem_row.addStretch(1)
        jvm_form.addRow("Memoria JVM:", mem_row)

        self._jvm_args_edit = QLineEdit()
        self._jvm_args_edit.setPlaceholderText("ej. -XX:+UseG1GC -Dsun.java2d.opengl=true")
        jvm_form.addRow("Flags JVM extra:", self._jvm_args_edit)
        layout.addWidget(self._jvm_box)

        # 2. WebApp Section
        self._webapp_box = QGroupBox("Configuración WebApp")
        web_form = QFormLayout(self._webapp_box)
        self._browser_combo = QComboBox()
        self._browser_combo.setEditable(True)
        browsers = [b[0] for b in self._browsers] or ["chromium", "google-chrome", "firefox"]
        self._browser_combo.addItems(browsers)
        web_form.addRow("Navegador:", self._browser_combo)
        layout.addWidget(self._webapp_box)

        # 3. Script Section
        self._script_box = QGroupBox("Configuración Script")
        scr_form = QFormLayout(self._script_box)
        self._interp_combo = QComboBox()
        self._interp_combo.setEditable(True)
        self._interp_combo.addItems(["", "bash", "python3", "sh", "node", "ruby"])
        scr_form.addRow("Intérprete (vacío = usar #!):", self._interp_combo)
        layout.addWidget(self._script_box)

        # 4. Execution & Desktop Options
        exec_box = QGroupBox("Ejecución y Escritorio")
        exec_form = QFormLayout(exec_box)
        exec_form.setSpacing(8)

        self._args_edit = QLineEdit()
        self._args_edit.setPlaceholderText("Argumentos CLI adicionales (ej. --fullscreen --profile work)")
        exec_form.addRow("Argumentos CLI:", self._args_edit)

        wd_row = QHBoxLayout()
        wd_row.setSpacing(6)
        self._workdir_edit = QLineEdit()
        self._workdir_edit.setPlaceholderText("Directorio de trabajo (Path=)")
        wd_row.addWidget(self._workdir_edit, stretch=1)
        wd_btn = QPushButton("Carpeta...")
        wd_btn.clicked.connect(self._browse_workdir)
        wd_row.addWidget(wd_btn)
        exec_form.addRow("Directorio trabajo:", wd_row)

        self._wm_class_edit = QLineEdit()
        self._wm_class_edit.setPlaceholderText("Opcional: agrupa ventanas correctamente en la barra de tareas")
        exec_form.addRow("StartupWMClass:", self._wm_class_edit)

        self._keywords_edit = QLineEdit()
        self._keywords_edit.setPlaceholderText("Separadas por ';' (ej. editor;notas;markdown)")
        exec_form.addRow("Palabras clave:", self._keywords_edit)

        self._gpu_check = QCheckBox("Preferir GPU dedicada (PrefersNonDefaultGPU=true + DRI_PRIME=1)")
        self._terminal_check = QCheckBox("Ejecutar en Terminal")
        self._nodisplay_check = QCheckBox("Ocultar del menú de aplicaciones (NoDisplay=true)")
        exec_form.addRow("", self._gpu_check)
        exec_form.addRow("", self._terminal_check)
        exec_form.addRow("", self._nodisplay_check)
        layout.addWidget(exec_box)

        # 5. Environment Variables Editor
        env_box = QGroupBox("Variables de entorno (KEY=VALUE)")
        env_v = QVBoxLayout(env_box)
        env_v.setSpacing(8)

        add_row = QHBoxLayout()
        add_row.setSpacing(6)
        self._env_key_edit = QLineEdit()
        self._env_key_edit.setPlaceholderText("CLAVE (ej. SDL_VIDEODRIVER)")
        add_row.addWidget(self._env_key_edit, stretch=2)
        add_row.addWidget(QLabel("="))
        self._env_val_edit = QLineEdit()
        self._env_val_edit.setPlaceholderText("VALOR (ej. wayland)")
        add_row.addWidget(self._env_val_edit, stretch=3)
        add_env_btn = QPushButton("＋ Agregar")
        add_env_btn.setProperty("variant", "primary")
        add_env_btn.clicked.connect(self._add_env_var)
        add_row.addWidget(add_env_btn)
        env_v.addLayout(add_row)

        self._env_table = QTableWidget(0, 2)
        self._env_table.setHorizontalHeaderLabels(["Variable", "Valor"])
        self._env_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self._env_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self._env_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._env_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._env_table.setMinimumHeight(110)
        self._env_table.setMaximumHeight(160)
        env_v.addWidget(self._env_table)

        rm_env_btn = QPushButton("Eliminar seleccionada")
        rm_env_btn.setProperty("variant", "danger")
        rm_env_btn.clicked.connect(self._remove_selected_env)
        env_v.addWidget(rm_env_btn, alignment=Qt.AlignmentFlag.AlignRight)
        layout.addWidget(env_box)

        layout.addStretch(1)
        scroll.setWidget(host)
        return scroll

    def _build_preview_tab(self) -> QWidget:
        tab = QWidget()
        v = QVBoxLayout(tab)
        v.setContentsMargins(14, 14, 14, 14)
        v.setSpacing(10)

        top = QHBoxLayout()
        lbl = QLabel("Archivo .desktop generado (FreeDesktop Desktop Entry Spec v1.5):")
        lbl.setStyleSheet("font-weight: 700;")
        top.addWidget(lbl)
        top.addStretch(1)
        val_btn = QPushButton("✓ Validar ahora")
        val_btn.setProperty("variant", "primary")
        val_btn.clicked.connect(self._refresh_preview)
        top.addWidget(val_btn)
        v.addLayout(top)

        self._preview_text = QPlainTextEdit()
        self._preview_text.setReadOnly(True)
        mono = QFont("Monospace", 10)
        mono.setStyleHint(QFont.StyleHint.TypeWriter)
        self._preview_text.setFont(mono)
        v.addWidget(self._preview_text, stretch=1)

        self._validation_lbl = QLabel("")
        self._validation_lbl.setWordWrap(True)
        v.addWidget(self._validation_lbl)
        return tab

    # ------------------------------------------------------------ Data Binding

    def _populate_initial_values(self, initial_target: str) -> None:
        ex = self._existing
        self._target_edit.setText(ex.exec_target if ex else initial_target)
        self._name_edit.setText(ex.name if ex else "")
        self._version_edit.setText(ex.version if ex else "")
        self._comment_edit.setText(ex.comment if ex else "")
        self._icon_edit.setText(ex.icon_path if ex else "")
        self._type_buttons[self._current_type].setChecked(True)

        selected_cats = set(ex.categories if ex else ["Utility"])
        for code, cb in self._cat_checks.items():
            cb.setChecked(code in selected_cats)

        default_mode_str = ex.storage_mode.value if ex else self._cfg.default_storage_mode
        try:
            st_mode = StorageMode(default_mode_str)
        except ValueError:
            st_mode = StorageMode.MOVE
        self._storage_radios[st_mode].setChecked(True)

        self._shortcut_check.setChecked(ex.create_desktop_shortcut if ex else self._cfg.default_desktop_shortcut)
        self._java_combo.setCurrentText(ex.java_options.java_path if ex else "java")
        self._xmx_combo.setCurrentText(ex.java_options.max_memory if ex else "")
        self._xms_combo.setCurrentText(ex.java_options.min_memory if ex else "")
        self._jvm_args_edit.setText(" ".join(ex.java_options.jvm_args) if ex else "")

        if ex and ex.webapp_browser:
            self._browser_combo.setCurrentText(ex.webapp_browser)
        self._interp_combo.setCurrentText(ex.script_interpreter if ex else "")
        self._args_edit.setText(" ".join(ex.args) if ex else "")
        self._workdir_edit.setText(ex.working_dir if ex else "")
        self._wm_class_edit.setText(ex.startup_wm_class if ex else "")
        self._keywords_edit.setText("; ".join(ex.keywords) if ex else "")
        self._gpu_check.setChecked(ex.dedicated_gpu if ex else False)
        self._terminal_check.setChecked(ex.terminal if ex else False)
        self._nodisplay_check.setChecked(ex.no_display if ex else False)
        self._refresh_env_table()

    def _set_app_type(self, app_type: AppType) -> None:
        self._current_type = app_type
        self._type_buttons[app_type].setChecked(True)
        self._sync_conditional_sections()
        self._refresh_icon_preview()

    def _sync_conditional_sections(self) -> None:
        self._jvm_box.setVisible(self._current_type == AppType.JAR)
        self._webapp_box.setVisible(self._current_type == AppType.WEBAPP)
        self._script_box.setVisible(self._current_type == AppType.SCRIPT)

        if not self._is_edit:
            show_storage = self._current_type != AppType.WEBAPP
            self._storage_label.setVisible(show_storage)
            self._storage_widget.setVisible(show_storage)

    # ------------------------------------------------------------ Interactions

    def _browse_target(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Seleccionar archivo ejecutable",
            str(self._services.paths.downloads_dir),
            "Aplicaciones (*.AppImage *.appimage *.jar *.sh *.py *.bin *.run);;AppImage (*.AppImage *.appimage);;Java JAR (*.jar);;Todos los archivos (*)",
        )
        if path:
            self._target_edit.setText(path)
            self._run_inspection(path)

    def _browse_icon(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Seleccionar ícono",
            "",
            "Imágenes e íconos (*.png *.svg *.ico *.jpg *.jpeg *.webp);;Todos los archivos (*)",
        )
        if path:
            self._icon_edit.setText(path)

    def _browse_workdir(self) -> None:
        path = QFileDialog.getExistingDirectory(self, "Seleccionar directorio de trabajo", self._workdir_edit.text())
        if path:
            self._workdir_edit.setText(path)

    def _trigger_inspect(self) -> None:
        target = self._target_edit.text().strip()
        if target:
            self._run_inspection(target)

    def _run_inspection(self, target: str) -> None:
        self._status_lbl.setText("Analizando...")
        self._progress.show()
        self._error_lbl.setText("")

        def _done(result: object) -> None:
            self._progress.hide()
            self._status_lbl.setText("✓ Metadatos detectados")
            if isinstance(result, DetectionResult):
                self._apply_detection(result)

        def _err(exc: Exception) -> None:
            self._progress.hide()
            self._status_lbl.setText("")
            self._error_lbl.setText(f"Error al inspeccionar: {exc}")

        run_async(self, lambda: self._services.app_service.inspect_target(target), _done, _err)

    def _apply_detection(self, det: DetectionResult) -> None:
        self._target_edit.setText(det.target)
        self._set_app_type(det.app_type)
        if det.suggested_name:
            self._name_edit.setText(det.suggested_name)
        if det.comment:
            self._comment_edit.setText(det.comment)
        if det.version:
            self._version_edit.setText(det.version)
        if det.working_dir:
            self._workdir_edit.setText(det.working_dir)
        if det.startup_wm_class:
            self._wm_class_edit.setText(det.startup_wm_class)
        if det.script_interpreter:
            self._interp_combo.setCurrentText(det.script_interpreter)
        if det.webapp_browser:
            self._browser_combo.setCurrentText(det.webapp_browser)
        self._terminal_check.setChecked(det.terminal)

        for code, cb in self._cat_checks.items():
            cb.setChecked(code in det.categories)

        self._icon_candidates = list(det.icon_candidates)
        if det.selected_icon:
            self._icon_edit.setText(det.selected_icon)
        self._render_icon_gallery()

        if det.warnings:
            self._warning_lbl.setText("⚠  " + " | ".join(det.warnings))
            self._warning_lbl.show()
        else:
            self._warning_lbl.hide()

    def _refresh_icon_preview(self) -> None:
        icon_path = self._icon_edit.text().strip()
        if not icon_path:
            icon_path = str(self._services.icon_store.default_icon_for(self._current_type))
        pm = self._icon_provider.get_pixmap(
            icon_path,
            size=60,
            app_name=self._name_edit.text() or "D",
            app_type=self._current_type,
        )
        self._icon_preview.setPixmap(pm)

    def _render_icon_gallery(self) -> None:
        while self._gallery_layout.count():
            item = self._gallery_layout.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()

        if not self._icon_candidates:
            self._gallery_host.hide()
            return

        lbl = QLabel("Extraídos:")
        lbl.setProperty("muted", True)
        lbl.setStyleSheet("font-size: 11px;")
        self._gallery_layout.addWidget(lbl)

        for cand in self._icon_candidates[:6]:
            btn = QPushButton()
            btn.setFixedSize(40, 40)
            btn.setIcon(self._icon_provider.get_qicon(cand, size=30, app_name="I", app_type=self._current_type))
            btn.setIconSize(QSize(30, 30))
            btn.setToolTip(cand)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.clicked.connect(lambda _c=False, p=cand: self._icon_edit.setText(p))
            self._gallery_layout.addWidget(btn)

        self._gallery_layout.addStretch(1)
        self._gallery_host.show()

    def _add_env_var(self) -> None:
        key = self._env_key_edit.text().strip()
        val = self._env_val_edit.text().strip()
        if not key:
            return
        self._env_vars[key] = val
        self._env_key_edit.clear()
        self._env_val_edit.clear()
        self._refresh_env_table()

    def _remove_selected_env(self) -> None:
        rows = sorted({idx.row() for idx in self._env_table.selectedIndexes()}, reverse=True)
        for row in rows:
            item = self._env_table.item(row, 0)
            if item is not None:
                self._env_vars.pop(item.text(), None)
        self._refresh_env_table()

    def _refresh_env_table(self) -> None:
        self._env_table.setRowCount(0)
        for key, val in sorted(self._env_vars.items()):
            r = self._env_table.rowCount()
            self._env_table.insertRow(r)
            self._env_table.setItem(r, 0, QTableWidgetItem(key))
            self._env_table.setItem(r, 1, QTableWidgetItem(val))

    def _selected_storage_mode(self) -> StorageMode:
        for mode, rb in self._storage_radios.items():
            if rb.isChecked():
                return mode
        return StorageMode.KEEP

    def _build_managed_app_from_form(self) -> ManagedApp:
        selected_cats = [code for code, cb in self._cat_checks.items() if cb.isChecked()] or ["Utility"]

        raw_args = self._args_edit.text().strip()
        try:
            extra_args = shlex.split(raw_args) if raw_args else []
        except ValueError:
            extra_args = raw_args.split()

        raw_jvm = self._jvm_args_edit.text().strip()
        try:
            jvm_args = shlex.split(raw_jvm) if raw_jvm else []
        except ValueError:
            jvm_args = raw_jvm.split()

        keywords = [k.strip() for k in self._keywords_edit.text().replace(",", ";").split(";") if k.strip()]

        kwargs = dict(
            name=self._name_edit.text().strip(),
            app_type=self._current_type,
            exec_target=self._target_edit.text().strip(),
            icon_path=self._icon_edit.text().strip(),
            comment=self._comment_edit.text().strip(),
            categories=selected_cats,
            keywords=keywords,
            args=extra_args,
            env_vars=dict(self._env_vars),
            working_dir=self._workdir_edit.text().strip(),
            terminal=self._terminal_check.isChecked(),
            dedicated_gpu=self._gpu_check.isChecked(),
            startup_wm_class=self._wm_class_edit.text().strip(),
            no_display=self._nodisplay_check.isChecked(),
            create_desktop_shortcut=self._shortcut_check.isChecked(),
            storage_mode=self._selected_storage_mode(),
            java_options=JavaOptions(
                java_path=self._java_combo.currentText().strip() or "java",
                max_memory=self._xmx_combo.currentText().strip(),
                min_memory=self._xms_combo.currentText().strip(),
                jvm_args=jvm_args,
            ),
            script_interpreter=self._interp_combo.currentText().strip(),
            webapp_browser=self._browser_combo.currentText().strip(),
            version=self._version_edit.text().strip(),
        )
        if self._existing:
            kwargs["id"] = self._existing.id
            kwargs["desktop_file_path"] = self._existing.desktop_file_path
            kwargs["desktop_shortcut_path"] = self._existing.desktop_shortcut_path
            kwargs["created_at"] = self._existing.created_at
            kwargs["sha256"] = self._existing.sha256
        return ManagedApp(**kwargs)

    def _on_tab_changed(self, index: int) -> None:
        if index == 2:
            self._refresh_preview()

    def _refresh_preview(self) -> None:
        try:
            draft = self._build_managed_app_from_form()
            content, report = self._services.app_service.preview_desktop_entry(draft)
            self._preview_text.setPlainText(content)
            if report.valid:
                suffix = " (verificado con desktop-file-validate)" if report.used_external_validator else ""
                warn_txt = f" · Avisos: {'; '.join(report.warnings)}" if report.warnings else ""
                self._validation_lbl.setText(f"✓ Archivo .desktop válido{suffix}{warn_txt}")
                self._validation_lbl.setStyleSheet("color: #22c55e; font-weight: 600;")
            else:
                self._validation_lbl.setText("✕ Errores: " + " | ".join(report.errors))
                self._validation_lbl.setStyleSheet("color: #ef4444; font-weight: 600;")
        except DeskForgeError as exc:
            self._preview_text.setPlainText(
                f"# Completá los campos obligatorios para generar la vista previa.\n# {exc}\n"
            )
            self._validation_lbl.setText(str(exc))
            self._validation_lbl.setStyleSheet("color: #f59e0b; font-weight: 600;")

    def _on_submit(self) -> None:
        self._error_lbl.setText("")
        try:
            app = self._build_managed_app_from_form()
            if self._is_edit:
                saved = self._services.app_service.update_app(app, source_icon=app.icon_path)
            else:
                saved = self._services.app_service.integrate_app(app, source_icon=app.icon_path)
        except DeskForgeError as exc:
            self._error_lbl.setText(str(exc))
            return
        except Exception as exc:
            self._error_lbl.setText(f"Error inesperado: {exc}")
            return

        self.accept()
        self._on_saved(saved, self._is_edit)
