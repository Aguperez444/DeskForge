"""Settings, System Self-Install, and Doctor Diagnostic QDialog (PySide6)."""

from __future__ import annotations

from typing import Callable

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
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
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from deskforge.application import ServiceContainer
from deskforge.domain.models import IssueSeverity, StorageMode
from deskforge.ui.theme import AVAILABLE_THEMES


class SettingsAndDoctorDialog(QDialog):
    """Modal dialog for DeskForge preferences, self-installation into MIME/menu, and Doctor checks."""

    def __init__(
        self,
        parent: QWidget,
        services: ServiceContainer,
        current_theme: str,
        on_theme_change: Callable[[str], None],
        on_repaired: Callable[[int], None],
        on_toast: Callable[[str, str], None],
        initial_tab: int = 0,
    ) -> None:
        super().__init__(parent)
        self._services = services
        self._current_theme = current_theme
        self._on_theme_change = on_theme_change
        self._on_repaired = on_repaired
        self._on_toast = on_toast

        self.setWindowTitle("Ajustes y Diagnóstico — DeskForge")
        self.resize(760, 560)
        self.setMinimumSize(680, 500)
        self.setModal(True)

        self._build_ui(initial_tab)

    def _build_ui(self, initial_tab: int) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(16, 14, 16, 14)
        root.setSpacing(10)

        tabs = QTabWidget()
        tabs.addTab(self._build_prefs_tab(), "  ⚙ Preferencias e Integración  ")
        tabs.addTab(self._build_doctor_tab(), "  🩺 Diagnóstico (Doctor)  ")
        tabs.setCurrentIndex(initial_tab)
        root.addWidget(tabs, stretch=1)

        footer = QHBoxLayout()
        footer.addStretch(1)
        close_btn = QPushButton("Cerrar")
        close_btn.clicked.connect(self.reject)
        footer.addWidget(close_btn)

        save_btn = QPushButton("💾 Guardar preferencias")
        save_btn.setProperty("variant", "success")
        save_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        save_btn.clicked.connect(self._save_prefs)
        footer.addWidget(save_btn)
        root.addLayout(footer)

    def _build_prefs_tab(self) -> QWidget:
        cfg = self._services.app_service.get_config()
        tab = QWidget()
        v = QVBoxLayout(tab)
        v.setContentsMargins(14, 14, 14, 14)
        v.setSpacing(12)

        form = QFormLayout()
        form.setSpacing(10)

        # Managed apps dir
        m_row = QHBoxLayout()
        self._managed_edit = QLineEdit(cfg.managed_apps_dir or str(self._services.paths.managed_apps_dir))
        m_row.addWidget(self._managed_edit, stretch=1)
        m_btn = QPushButton("Elegir...")
        m_btn.clicked.connect(self._pick_managed_dir)
        m_row.addWidget(m_btn)
        form.addRow("Carpeta de apps gestionadas:", m_row)

        # Scan dir
        s_row = QHBoxLayout()
        self._scan_edit = QLineEdit(cfg.scan_directory or str(self._services.paths.downloads_dir))
        s_row.addWidget(self._scan_edit, stretch=1)
        s_btn = QPushButton("Elegir...")
        s_btn.clicked.connect(self._pick_scan_dir)
        s_row.addWidget(s_btn)
        form.addRow("Carpeta de escaneo:", s_row)

        # Default storage mode
        self._storage_combo = QComboBox()
        for mode in StorageMode:
            self._storage_combo.addItem(mode.label_es, mode.value)
        idx = self._storage_combo.findData(cfg.default_storage_mode)
        if idx >= 0:
            self._storage_combo.setCurrentIndex(idx)
        form.addRow("Almacenamiento por defecto:", self._storage_combo)

        # Theme switcher (live preview)
        self._theme_combo = QComboBox()
        for code, label in AVAILABLE_THEMES:
            self._theme_combo.addItem(label, code)
        t_idx = self._theme_combo.findData(self._current_theme)
        if t_idx >= 0:
            self._theme_combo.setCurrentIndex(t_idx)
        self._theme_combo.currentIndexChanged.connect(self._on_theme_selected)
        form.addRow("Tema visual:", self._theme_combo)

        self._shortcut_check = QCheckBox("Crear acceso directo en el Escritorio por defecto")
        self._shortcut_check.setChecked(cfg.default_desktop_shortcut)
        form.addRow("", self._shortcut_check)

        self._trash_check = QCheckBox("Usar Papelera del sistema (gio trash) al eliminar binarios")
        self._trash_check.setChecked(cfg.move_to_trash_on_delete)
        form.addRow("", self._trash_check)

        v.addLayout(form)

        # System Integration Box (Self-install)
        sys_box = QGroupBox("Integración de DeskForge con el sistema")
        sv = QVBoxLayout(sys_box)
        sv.setSpacing(10)

        desc = QLabel(
            "Instalá el lanzador propio de DeskForge en tu menú de aplicaciones y registrá asociaciones MIME "
            "para integrar archivos .AppImage y .jar en 1 clic desde 'Abrir con DeskForge'."
        )
        desc.setWordWrap(True)
        desc.setProperty("muted", True)
        sv.addWidget(desc)

        action_row = QHBoxLayout()
        self._self_status = QLabel("")
        action_row.addWidget(self._self_status, stretch=1)
        self._self_btn = QPushButton("")
        self._self_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._self_btn.clicked.connect(self._toggle_self_install)
        action_row.addWidget(self._self_btn)
        sv.addLayout(action_row)
        v.addWidget(sys_box)
        v.addStretch(1)

        self._refresh_self_status()
        return tab

    def _build_doctor_tab(self) -> QWidget:
        tab = QWidget()
        v = QVBoxLayout(tab)
        v.setContentsMargins(14, 14, 14, 14)
        v.setSpacing(10)

        tools_box = QGroupBox("Herramientas de Linux detectadas")
        grid = QGridLayout(tools_box)
        grid.setHorizontalSpacing(18)
        grid.setVerticalSpacing(4)
        tools = self._services.doctor_service.get_system_tools()
        for idx, (tool, path) in enumerate(tools.items()):
            mark = "✓" if path else "·"
            lbl = QLabel(f"{mark}  {tool}")
            lbl.setToolTip(path or "No instalada (opcional)")
            if path:
                lbl.setStyleSheet("color: #22c55e; font-weight: 600;")
            else:
                lbl.setProperty("muted", True)
            grid.addWidget(lbl, idx // 3, idx % 3)
        v.addWidget(tools_box)

        hdr = QLabel("Salud de aplicaciones gestionadas:")
        hdr.setStyleSheet("font-weight: 700;")
        v.addWidget(hdr)

        self._issues_table = QTableWidget(0, 4)
        self._issues_table.setHorizontalHeaderLabels(["Nivel", "Aplicación", "Detalle", "Reparable"])
        self._issues_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self._issues_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Interactive)
        self._issues_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        self._issues_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        self._issues_table.setColumnWidth(1, 160)
        self._issues_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._issues_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._issues_table.setAlternatingRowColors(True)
        v.addWidget(self._issues_table, stretch=1)

        btn_row = QHBoxLayout()
        self._doctor_summary = QLabel("")
        btn_row.addWidget(self._doctor_summary, stretch=1)

        recheck_btn = QPushButton("↻ Re-analizar")
        recheck_btn.clicked.connect(self._refresh_doctor)
        btn_row.addWidget(recheck_btn)

        repair_btn = QPushButton("🔧 Reparar automáticamente")
        repair_btn.setProperty("variant", "warning")
        repair_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        repair_btn.clicked.connect(self._run_repair)
        btn_row.addWidget(repair_btn)
        v.addLayout(btn_row)

        self._refresh_doctor()
        return tab

    def _pick_managed_dir(self) -> None:
        d = QFileDialog.getExistingDirectory(self, "Carpeta de apps gestionadas", self._managed_edit.text())
        if d:
            self._managed_edit.setText(d)

    def _pick_scan_dir(self) -> None:
        d = QFileDialog.getExistingDirectory(self, "Carpeta de escaneo", self._scan_edit.text())
        if d:
            self._scan_edit.setText(d)

    def _on_theme_selected(self) -> None:
        code = self._theme_combo.currentData()
        if code:
            self._on_theme_change(str(code))

    def _refresh_self_status(self) -> None:
        installed = self._services.system.is_self_installed()
        if installed:
            self._self_status.setText("✓ Instalado en el menú del sistema y 'Abrir con...'")
            self._self_status.setStyleSheet("color: #22c55e; font-weight: 600;")
            self._self_btn.setText("Desinstalar lanzador")
            self._self_btn.setProperty("variant", "danger")
        else:
            self._self_status.setText("No instalado todavía en el menú del sistema")
            self._self_status.setStyleSheet("")
            self._self_status.setProperty("muted", True)
            self._self_btn.setText("Instalar en menú del sistema")
            self._self_btn.setProperty("variant", "success")
        self._self_btn.style().unpolish(self._self_btn)
        self._self_btn.style().polish(self._self_btn)

    def _toggle_self_install(self) -> None:
        if self._services.system.is_self_installed():
            self._services.system.uninstall_self_desktop_entry()
            self._on_toast("Lanzador de DeskForge eliminado del menú.", "info")
        else:
            self._services.system.install_self_desktop_entry()
            self._on_toast("DeskForge instalado en el menú y en 'Abrir con...'.", "success")
        self._refresh_self_status()

    def _refresh_doctor(self) -> None:
        self._issues_table.setRowCount(0)
        issues = self._services.doctor_service.run_checks()
        for issue in issues:
            row = self._issues_table.rowCount()
            self._issues_table.insertRow(row)
            sev = "ERROR" if issue.severity == IssueSeverity.ERROR else "AVISO"
            self._issues_table.setItem(row, 0, QTableWidgetItem(sev))
            self._issues_table.setItem(row, 1, QTableWidgetItem(issue.app_name or "-"))
            self._issues_table.setItem(row, 2, QTableWidgetItem(issue.message))
            self._issues_table.setItem(row, 3, QTableWidgetItem("Sí" if issue.fixable else "No"))

        if not issues:
            self._doctor_summary.setText("✓ Todas las aplicaciones están saludables.")
            self._doctor_summary.setStyleSheet("color: #22c55e; font-weight: 600;")
        else:
            self._doctor_summary.setText(f"⚠ Se encontraron {len(issues)} incidencia(s).")
            self._doctor_summary.setStyleSheet("color: #f59e0b; font-weight: 600;")

    def _run_repair(self) -> None:
        repaired = self._services.doctor_service.repair_all()
        self._refresh_doctor()
        self._on_repaired(repaired)
        self._on_toast(
            f"Diagnóstico completado: {repaired} problema(s) reparado(s).",
            "success" if repaired else "info",
        )

    def _save_prefs(self) -> None:
        cfg = self._services.app_service.get_config()
        cfg.managed_apps_dir = self._managed_edit.text().strip()
        cfg.scan_directory = self._scan_edit.text().strip()
        cfg.default_storage_mode = str(self._storage_combo.currentData() or StorageMode.MOVE.value)
        cfg.default_desktop_shortcut = self._shortcut_check.isChecked()
        cfg.move_to_trash_on_delete = self._trash_check.isChecked()
        cfg.theme = str(self._theme_combo.currentData() or self._current_theme)
        self._services.app_service.save_config(cfg)
        self._on_toast("Preferencias guardadas.", "success")
        self.accept()
