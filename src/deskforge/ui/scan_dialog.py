"""Discovery dialog: scan Downloads for .AppImage/.jar files and import existing .desktop launchers."""

from __future__ import annotations

from pathlib import Path
import tkinter as tk
from tkinter import filedialog
from typing import Callable

import ttkbootstrap as ttk

from deskforge.application import ServiceContainer
from deskforge.domain.exceptions import DeskForgeError
from deskforge.domain.models import ManagedApp, ScanCandidate
from deskforge.ui.widgets import center_window, run_in_background


class ScanAndImportDialog(ttk.Toplevel):
    """Modal dialog to discover unintegrated files and adopt existing .desktop entries."""

    def __init__(
        self,
        parent: tk.Misc,
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
        self.var_dir = tk.StringVar(value=default_dir)

        self.title("Descubrir e importar aplicaciones")
        self.minsize(720, 480)
        self._build_ui()
        self.bind("<Escape>", lambda _e: self.destroy())
        self.transient(parent)
        center_window(self, 780, 520, parent)
        self.grab_set()

        self._run_scan()
        self._load_externals()

    def _build_ui(self) -> None:
        root = ttk.Frame(self, padding=14)
        root.pack(fill="both", expand=True)

        nb = ttk.Notebook(root)
        nb.pack(fill="both", expand=True)

        tab_scan = ttk.Frame(nb, padding=10)
        tab_import = ttk.Frame(nb, padding=10)
        nb.add(tab_scan, text="  🔎 Escanear carpeta (.AppImage / .jar)  ")
        nb.add(tab_import, text="  📥 Importar .desktop existentes  ")

        # --- Tab 1: Folder Scanner ---
        top = ttk.Frame(tab_scan)
        top.pack(fill="x", pady=(0, 8))
        ttk.Label(top, text="Carpeta:").pack(side="left", padx=(0, 6))
        ttk.Entry(top, textvariable=self.var_dir).pack(side="left", fill="x", expand=True, padx=(0, 6))
        ttk.Button(top, text="Cambiar...", bootstyle="secondary-outline", command=self._choose_dir).pack(
            side="left", padx=(0, 6)
        )
        ttk.Button(top, text="Escanear", bootstyle="info", command=self._run_scan).pack(side="left")

        self._scan_tree = ttk.Treeview(
            tab_scan,
            columns=("type", "name", "size", "path"),
            show="headings",
            height=13,
        )
        self._scan_tree.heading("type", text="Tipo")
        self._scan_tree.heading("name", text="Nombre sugerido")
        self._scan_tree.heading("size", text="Tamaño")
        self._scan_tree.heading("path", text="Ruta")
        self._scan_tree.column("type", width=85)
        self._scan_tree.column("name", width=180)
        self._scan_tree.column("size", width=80)
        self._scan_tree.column("path", width=360)
        self._scan_tree.pack(fill="both", expand=True, pady=(0, 8))
        self._scan_tree.bind("<Double-1>", lambda _e: self._integrate_selected())

        scan_footer = ttk.Frame(tab_scan)
        scan_footer.pack(fill="x")
        self._scan_status = ttk.Label(scan_footer, text="Escaneando...", bootstyle="secondary")
        self._scan_status.pack(side="left")
        ttk.Button(
            scan_footer,
            text="＋ Integrar seleccionado...",
            bootstyle="success",
            command=self._integrate_selected,
        ).pack(side="right")

        # --- Tab 2: Import Existing .desktop ---
        ttk.Label(
            tab_import,
            text="Lanzadores encontrados en ~/.local/share/applications (incluyendo lanzadores viejos de AutoJar):",
            bootstyle="secondary",
        ).pack(anchor="w", pady=(0, 8))

        self._ext_tree = ttk.Treeview(
            tab_import,
            columns=("type", "name", "target"),
            show="headings",
            height=13,
        )
        self._ext_tree.heading("type", text="Tipo")
        self._ext_tree.heading("name", text="Nombre")
        self._ext_tree.heading("target", text="Ejecutable / URL")
        self._ext_tree.column("type", width=85)
        self._ext_tree.column("name", width=210)
        self._ext_tree.column("target", width=410)
        self._ext_tree.pack(fill="both", expand=True, pady=(0, 8))

        ext_footer = ttk.Frame(tab_import)
        ext_footer.pack(fill="x")
        self._ext_status = ttk.Label(ext_footer, text="", bootstyle="secondary")
        self._ext_status.pack(side="left")
        ttk.Button(
            ext_footer,
            text="📥 Importar a DeskForge",
            bootstyle="info",
            command=self._import_selected,
        ).pack(side="right")

    def _choose_dir(self) -> None:
        chosen = filedialog.askdirectory(parent=self, initialdir=self.var_dir.get())
        if chosen:
            self.var_dir.set(chosen)
            self._run_scan()

    def _run_scan(self) -> None:
        directory = Path(self.var_dir.get()).expanduser()
        self._scan_status.configure(text=f"Escaneando {directory}...")

        def _done(result: object) -> None:
            self._candidates = result if isinstance(result, list) else []
            for item in self._scan_tree.get_children():
                self._scan_tree.delete(item)
            for idx, c in enumerate(self._candidates):
                mb = c.size_bytes / (1024 * 1024)
                self._scan_tree.insert("", "end", iid=str(idx), values=(c.app_type.short_badge, c.name_guess, f"{mb:.1f} MB", c.path))
            self._scan_status.configure(text=f"{len(self._candidates)} archivo(s) sin integrar encontrado(s).")

        run_in_background(self, lambda: self._services.app_service.scan_directory(directory), _done)

    def _integrate_selected(self) -> None:
        sel = self._scan_tree.selection()
        if not sel:
            return
        cand = self._candidates[int(sel[0])]
        self.destroy()
        self._on_integrate_target(cand.path)

    def _load_externals(self) -> None:
        self._externals = self._services.app_service.discover_external_launchers()
        for item in self._ext_tree.get_children():
            self._ext_tree.delete(item)
        for idx, app in enumerate(self._externals):
            self._ext_tree.insert("", "end", iid=str(idx), values=(app.app_type.short_badge, app.name, app.exec_target))
        self._ext_status.configure(text=f"{len(self._externals)} lanzador(es) externo(s) detectado(s).")

    def _import_selected(self) -> None:
        sel = self._ext_tree.selection()
        if not sel:
            return
        ext = self._externals[int(sel[0])]
        try:
            imported = self._services.app_service.import_external_launcher(ext)
        except DeskForgeError as exc:
            self._ext_status.configure(text=f"⚠ No se pudo importar '{ext.name}': {exc}", bootstyle="danger")
            return
        except Exception as exc:
            self._ext_status.configure(text=f"⚠ Error inesperado al importar '{ext.name}': {exc}", bootstyle="danger")
            return
        self._ext_status.configure(text=f"✓ '{imported.name}' importada correctamente.", bootstyle="success")
        self._on_imported(imported)
        self._load_externals()
