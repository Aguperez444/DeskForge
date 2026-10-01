"""Discovery & Import QDialog (PySide6): scan Downloads and safely import existing .desktop launchers."""

from __future__ import annotations

from pathlib import Path
from typing import Callable

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QFileDialog,
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
from deskforge.domain.exceptions import DeskForgeError
from deskforge.domain.models import ManagedApp, ScanCandidate
from deskforge.ui.widgets import run_async


class ScanAndImportDialog(QDialog):
    """Modal dialog to discover unintegrated .AppImage/.jar files and adopt existing .desktop entries."""

    def __init__(
        self,
        parent: QWidget,
        services: ServiceContainer,
        on_integrate_target: Callable[[str], None],
        on_imported: Callable[[ManagedApp], None],
    ) -> None:
        super().__init__(parent)
        self._services = services
        self._on_integrate_target = on_integrate_target
        self._on_imported = on_imported
        self._candidates: list[ScanCandidate] = []
        self._externals: list[ManagedApp] = []

        cfg = services.app_service.get_config()
        default_dir = cfg.scan_directory or str(services.paths.downloads_dir)

        self.setWindowTitle("Descubrir e importar aplicaciones")
        self.resize(800, 540)
        self.setMinimumSize(700, 460)
        self.setModal(True)

        self._build_ui(default_dir)
        self._run_scan()
        self._load_externals()

    def _build_ui(self, default_dir: str) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(16, 14, 16, 14)
        root.setSpacing(10)

        tabs = QTabWidget()
        tabs.addTab(self._build_scan_tab(default_dir), "  🔎 Escanear carpeta (.AppImage / .jar)  ")
        tabs.addTab(self._build_import_tab(), "  📥 Importar .desktop existentes  ")
        root.addWidget(tabs, stretch=1)

        close_row = QHBoxLayout()
        close_row.addStretch(1)
        close_btn = QPushButton("Cerrar")
        close_btn.clicked.connect(self.accept)
        close_row.addWidget(close_btn)
        root.addLayout(close_row)

    def _build_scan_tab(self, default_dir: str) -> QWidget:
        tab = QWidget()
        v = QVBoxLayout(tab)
        v.setContentsMargins(12, 12, 12, 12)
        v.setSpacing(10)

        top = QHBoxLayout()
        top.setSpacing(6)
        top.addWidget(QLabel("Carpeta:"))
        self._dir_edit = QLineEdit(default_dir)
        top.addWidget(self._dir_edit, stretch=1)

        choose_btn = QPushButton("Cambiar...")
        choose_btn.clicked.connect(self._choose_dir)
        top.addWidget(choose_btn)

        scan_btn = QPushButton("Escanear")
        scan_btn.setProperty("variant", "primary")
        scan_btn.clicked.connect(self._run_scan)
        top.addWidget(scan_btn)
        v.addLayout(top)

        self._scan_table = QTableWidget(0, 4)
        self._scan_table.setHorizontalHeaderLabels(["Tipo", "Nombre sugerido", "Tamaño", "Ruta"])
        self._scan_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self._scan_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Interactive)
        self._scan_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        self._scan_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        self._scan_table.setColumnWidth(1, 190)
        self._scan_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._scan_table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self._scan_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._scan_table.setAlternatingRowColors(True)
        self._scan_table.itemDoubleClicked.connect(lambda _item: self._integrate_selected())
        v.addWidget(self._scan_table, stretch=1)

        footer = QHBoxLayout()
        self._scan_status = QLabel("Escaneando...")
        self._scan_status.setProperty("muted", True)
        footer.addWidget(self._scan_status, stretch=1)

        int_btn = QPushButton("＋ Integrar seleccionado...")
        int_btn.setProperty("variant", "success")
        int_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        int_btn.clicked.connect(self._integrate_selected)
        footer.addWidget(int_btn)
        v.addLayout(footer)
        return tab

    def _build_import_tab(self) -> QWidget:
        tab = QWidget()
        v = QVBoxLayout(tab)
        v.setContentsMargins(12, 12, 12, 12)
        v.setSpacing(10)

        hint = QLabel("Lanzadores encontrados en ~/.local/share/applications (incluyendo lanzadores previos de AutoJar):")
        hint.setProperty("muted", True)
        hint.setWordWrap(True)
        v.addWidget(hint)

        self._ext_table = QTableWidget(0, 3)
        self._ext_table.setHorizontalHeaderLabels(["Tipo", "Nombre", "Ejecutable / URL"])
        self._ext_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self._ext_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Interactive)
        self._ext_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        self._ext_table.setColumnWidth(1, 220)
        self._ext_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._ext_table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self._ext_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._ext_table.setAlternatingRowColors(True)
        self._ext_table.itemDoubleClicked.connect(lambda _item: self._import_selected())
        v.addWidget(self._ext_table, stretch=1)

        footer = QHBoxLayout()
        self._ext_status = QLabel("")
        self._ext_status.setProperty("muted", True)
        self._ext_status.setWordWrap(True)
        footer.addWidget(self._ext_status, stretch=1)

        imp_btn = QPushButton("📥 Importar a DeskForge")
        imp_btn.setProperty("variant", "primary")
        imp_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        imp_btn.clicked.connect(self._import_selected)
        footer.addWidget(imp_btn)
        v.addLayout(footer)
        return tab

    def _choose_dir(self) -> None:
        chosen = QFileDialog.getExistingDirectory(self, "Seleccionar carpeta para escanear", self._dir_edit.text())
        if chosen:
            self._dir_edit.setText(chosen)
            self._run_scan()

    def _run_scan(self) -> None:
        directory = Path(self._dir_edit.text()).expanduser()
        self._scan_status.setText(f"Escaneando {directory}...")

        def _done(result: object) -> None:
            self._candidates = result if isinstance(result, list) else []
            self._scan_table.setRowCount(0)
            for c in self._candidates:
                row = self._scan_table.rowCount()
                self._scan_table.insertRow(row)
                mb = c.size_bytes / (1024 * 1024)
                self._scan_table.setItem(row, 0, QTableWidgetItem(c.app_type.short_badge))
                self._scan_table.setItem(row, 1, QTableWidgetItem(c.name_guess))
                self._scan_table.setItem(row, 2, QTableWidgetItem(f"{mb:.1f} MB"))
                self._scan_table.setItem(row, 3, QTableWidgetItem(c.path))
            self._scan_status.setText(f"{len(self._candidates)} archivo(s) sin integrar encontrado(s).")

        run_async(self, lambda: self._services.app_service.scan_directory(directory), _done)

    def _integrate_selected(self) -> None:
        row = self._scan_table.currentRow()
        if row < 0 or row >= len(self._candidates):
            return
        cand = self._candidates[row]
        self.accept()
        self._on_integrate_target(cand.path)

    def _load_externals(self) -> None:
        self._externals = self._services.app_service.discover_external_launchers()
        self._ext_table.setRowCount(0)
        for app in self._externals:
            row = self._ext_table.rowCount()
            self._ext_table.insertRow(row)
            self._ext_table.setItem(row, 0, QTableWidgetItem(app.app_type.short_badge))
            self._ext_table.setItem(row, 1, QTableWidgetItem(app.name))
            self._ext_table.setItem(row, 2, QTableWidgetItem(app.exec_target))
        self._ext_status.setStyleSheet("")
        self._ext_status.setText(f"{len(self._externals)} lanzador(es) externo(s) detectado(s).")

    def _import_selected(self) -> None:
        row = self._ext_table.currentRow()
        if row < 0 or row >= len(self._externals):
            return
        ext = self._externals[row]
        try:
            imported = self._services.app_service.import_external_launcher(ext)
        except DeskForgeError as exc:
            self._ext_status.setStyleSheet("color: #ef4444; font-weight: 600;")
            self._ext_status.setText(f"⚠ No se pudo importar '{ext.name}': {exc}")
            return
        except Exception as exc:
            self._ext_status.setStyleSheet("color: #ef4444; font-weight: 600;")
            self._ext_status.setText(f"⚠ Error inesperado al importar '{ext.name}': {exc}")
            return

        self._on_imported(imported)
        self._load_externals()
        self._ext_status.setStyleSheet("color: #22c55e; font-weight: 600;")
        self._ext_status.setText(f"✓ '{imported.name}' importada correctamente.")
