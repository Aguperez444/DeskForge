"""Settings, System Self-Installation, and Doctor Diagnostic dialog."""

from __future__ import annotations

import tkinter as tk
from tkinter import filedialog
from typing import Callable

import ttkbootstrap as ttk

from deskforge.application import ServiceContainer
from deskforge.domain.models import IssueSeverity, StorageMode
from deskforge.ui.theme import ALL_THEMES
from deskforge.ui.widgets import center_window


class SettingsAndDoctorDialog(ttk.Toplevel):
    """Modal dialog for configuring DeskForge, self-installing MIME handlers, and running Doctor."""

    def __init__(
        self,
        parent: tk.Misc,
        services: ServiceContainer,
        current_theme: str,
        on_theme_change: Callable[[str], None],
        on_repaired: Callable[[int], None],
        on_toast: Callable[[str, str], None],
        initial_tab: int = 0,
    ) -> None:
        super().__init__(parent)
        self._services = services
        self._on_theme_change = on_theme_change
        self._on_repaired = on_repaired
        self._on_toast = on_toast

        cfg = services.app_service.get_config()
        self.var_managed_dir = tk.StringVar(value=cfg.managed_apps_dir or str(services.paths.managed_apps_dir))
        self.var_scan_dir = tk.StringVar(value=cfg.scan_directory or str(services.paths.downloads_dir))
        self.var_storage_mode = tk.StringVar(value=cfg.default_storage_mode)
        self.var_shortcut = tk.BooleanVar(value=cfg.default_desktop_shortcut)
        self.var_trash = tk.BooleanVar(value=cfg.move_to_trash_on_delete)
        self.var_theme = tk.StringVar(value=current_theme)

        self.title("Ajustes y Diagnóstico — DeskForge")
        self.minsize(680, 500)
        self._build_ui(initial_tab)
        self.bind("<Escape>", lambda _e: self.destroy())
        self.transient(parent)
        center_window(self, 740, 540, parent)
        self.grab_set()

    def _build_ui(self, initial_tab: int) -> None:
        root = ttk.Frame(self, padding=14)
        root.pack(fill="both", expand=True)

        nb = ttk.Notebook(root)
        nb.pack(fill="both", expand=True, pady=(0, 10))

        tab_prefs = ttk.Frame(nb, padding=12)
        tab_doctor = ttk.Frame(nb, padding=12)
        nb.add(tab_prefs, text="  ⚙ Preferencias e Integración  ")
        nb.add(tab_doctor, text="  🩺 Diagnóstico (Doctor)  ")

        self._build_prefs_tab(tab_prefs)
        self._build_doctor_tab(tab_doctor)
        nb.select(initial_tab)

        footer = ttk.Frame(root)
        footer.pack(fill="x")
        ttk.Button(footer, text="Cerrar", bootstyle="secondary-outline", command=self.destroy).pack(side="right")
        ttk.Button(footer, text="💾 Guardar preferencias", bootstyle="success", command=self._save_prefs).pack(
            side="right", padx=(0, 8)
        )

    def _build_prefs_tab(self, parent: ttk.Frame) -> None:
        parent.columnconfigure(1, weight=1)

        ttk.Label(parent, text="Carpeta de apps gestionadas:", font=("Sans", 10, "bold")).grid(
            row=0, column=0, sticky="w", pady=6
        )
        dir_row = ttk.Frame(parent)
        dir_row.grid(row=0, column=1, sticky="ew", padx=(8, 0), pady=6)
        dir_row.columnconfigure(0, weight=1)
        ttk.Entry(dir_row, textvariable=self.var_managed_dir).grid(row=0, column=0, sticky="ew", padx=(0, 6))
        ttk.Button(dir_row, text="Elegir...", bootstyle="secondary-outline", command=self._pick_managed_dir).grid(
            row=0, column=1
        )

        ttk.Label(parent, text="Carpeta de escaneo:", font=("Sans", 10, "bold")).grid(
            row=1, column=0, sticky="w", pady=6
        )
        scan_row = ttk.Frame(parent)
        scan_row.grid(row=1, column=1, sticky="ew", padx=(8, 0), pady=6)
        scan_row.columnconfigure(0, weight=1)
        ttk.Entry(scan_row, textvariable=self.var_scan_dir).grid(row=0, column=0, sticky="ew", padx=(0, 6))
        ttk.Button(scan_row, text="Elegir...", bootstyle="secondary-outline", command=self._pick_scan_dir).grid(
            row=0, column=1
        )

        ttk.Label(parent, text="Almacenamiento por defecto:", font=("Sans", 10, "bold")).grid(
            row=2, column=0, sticky="w", pady=6
        )
        mode_combo = ttk.Combobox(
            parent,
            textvariable=self.var_storage_mode,
            values=[m.value for m in StorageMode],
            state="readonly",
            width=18,
        )
        mode_combo.grid(row=2, column=1, sticky="w", padx=(8, 0), pady=6)

        ttk.Label(parent, text="Tema visual:", font=("Sans", 10, "bold")).grid(row=3, column=0, sticky="w", pady=6)
        theme_combo = ttk.Combobox(parent, textvariable=self.var_theme, values=list(ALL_THEMES), state="readonly", width=18)
        theme_combo.grid(row=3, column=1, sticky="w", padx=(8, 0), pady=6)
        theme_combo.bind("<<ComboboxSelected>>", lambda _e: self._on_theme_change(self.var_theme.get()))

        ttk.Checkbutton(
            parent,
            text="Crear acceso directo en el Escritorio por defecto",
            variable=self.var_shortcut,
            bootstyle="round-toggle",
        ).grid(row=4, column=0, columnspan=2, sticky="w", pady=(8, 3))

        ttk.Checkbutton(
            parent,
            text="Usar Papelera del sistema (gio trash) al eliminar binarios",
            variable=self.var_trash,
            bootstyle="round-toggle",
        ).grid(row=5, column=0, columnspan=2, sticky="w", pady=3)

        # System Integration Box (Self-install)
        sys_box = ttk.Labelframe(parent, text=" Integración de DeskForge con el sistema ", padding=12)
        sys_box.grid(row=6, column=0, columnspan=2, sticky="ew", pady=(16, 4))

        ttk.Label(
            sys_box,
            text=(
                "Instalá el lanzador propio de DeskForge en tu menú de aplicaciones y registrá asociaciones MIME "
                "para integrar archivos .AppImage y .jar en 1 clic desde 'Abrir con DeskForge'."
            ),
            wraplength=640,
            justify="left",
            bootstyle="secondary",
        ).pack(anchor="w", pady=(0, 10))

        row = ttk.Frame(sys_box)
        row.pack(fill="x")
        self._self_status = ttk.Label(row, text="", font=("Sans", 9, "bold"))
        self._self_status.pack(side="left")
        self._self_btn = ttk.Button(row, text="", command=self._toggle_self_install)
        self._self_btn.pack(side="right")
        self._refresh_self_status()

    def _build_doctor_tab(self, parent: ttk.Frame) -> None:
        tools_box = ttk.Labelframe(parent, text=" Herramientas de Linux detectadas ", padding=8)
        tools_box.pack(fill="x", pady=(0, 10))

        tools = self._services.doctor_service.get_system_tools()
        for idx, (tool, path) in enumerate(tools.items()):
            mark = "✓" if path else "·"
            style = "success" if path else "secondary"
            ttk.Label(tools_box, text=f"{mark} {tool}", bootstyle=style, font=("Sans", 9)).grid(
                row=idx // 3, column=idx % 3, sticky="w", padx=10, pady=2
            )

        ttk.Label(parent, text="Salud de aplicaciones gestionadas:", font=("Sans", 10, "bold")).pack(anchor="w")
        self._issues_tree = ttk.Treeview(
            parent,
            columns=("severity", "app", "msg", "fix"),
            show="headings",
            height=9,
        )
        self._issues_tree.heading("severity", text="Nivel")
        self._issues_tree.heading("app", text="Aplicación")
        self._issues_tree.heading("msg", text="Detalle")
        self._issues_tree.heading("fix", text="Reparable")
        self._issues_tree.column("severity", width=75)
        self._issues_tree.column("app", width=150)
        self._issues_tree.column("msg", width=360)
        self._issues_tree.column("fix", width=80)
        self._issues_tree.pack(fill="both", expand=True, pady=(6, 8))

        btn_row = ttk.Frame(parent)
        btn_row.pack(fill="x")
        self._doctor_summary = ttk.Label(btn_row, text="", bootstyle="secondary")
        self._doctor_summary.pack(side="left")
        ttk.Button(btn_row, text="🔧 Reparar automáticamente", bootstyle="warning", command=self._run_repair).pack(
            side="right", padx=(6, 0)
        )
        ttk.Button(btn_row, text="↻ Re-analizar", bootstyle="info-outline", command=self._refresh_doctor).pack(
            side="right"
        )
        self._refresh_doctor()

    def _pick_managed_dir(self) -> None:
        d = filedialog.askdirectory(parent=self, initialdir=self.var_managed_dir.get())
        if d:
            self.var_managed_dir.set(d)

    def _pick_scan_dir(self) -> None:
        d = filedialog.askdirectory(parent=self, initialdir=self.var_scan_dir.get())
        if d:
            self.var_scan_dir.set(d)

    def _refresh_self_status(self) -> None:
        installed = self._services.system.is_self_installed()
        if installed:
            self._self_status.configure(text="✓ Instalado en el menú del sistema y 'Abrir con...'", bootstyle="success")
            self._self_btn.configure(text="Desinstalar lanzador", bootstyle="danger-outline")
        else:
            self._self_status.configure(text="No instalado todavía en el menú del sistema", bootstyle="secondary")
            self._self_btn.configure(text="Instalar en menú del sistema", bootstyle="success")

    def _toggle_self_install(self) -> None:
        if self._services.system.is_self_installed():
            self._services.system.uninstall_self_desktop_entry()
            self._on_toast("Lanzador de DeskForge eliminado del menú.", "info")
        else:
            self._services.system.install_self_desktop_entry()
            self._on_toast("DeskForge instalado en el menú y en 'Abrir con...'.", "success")
        self._refresh_self_status()

    def _refresh_doctor(self) -> None:
        for item in self._issues_tree.get_children():
            self._issues_tree.delete(item)
        issues = self._services.doctor_service.run_checks()
        for issue in issues:
            sev = "ERROR" if issue.severity == IssueSeverity.ERROR else "AVISO"
            self._issues_tree.insert(
                "",
                "end",
                values=(sev, issue.app_name or "-", issue.message, "Sí" if issue.fixable else "No"),
            )
        if not issues:
            self._doctor_summary.configure(text="✓ Todas las aplicaciones están saludables.", bootstyle="success")
        else:
            self._doctor_summary.configure(text=f"Se encontraron {len(issues)} incidencia(s).", bootstyle="warning")

    def _run_repair(self) -> None:
        repaired = self._services.doctor_service.repair_all()
        self._refresh_doctor()
        self._on_repaired(repaired)
        self._on_toast(f"Diagnóstico completado: {repaired} problema(s) reparado(s).", "success" if repaired else "info")

    def _save_prefs(self) -> None:
        cfg = self._services.app_service.get_config()
        cfg.managed_apps_dir = self.var_managed_dir.get().strip()
        cfg.scan_directory = self.var_scan_dir.get().strip()
        cfg.default_storage_mode = self.var_storage_mode.get()
        cfg.default_desktop_shortcut = self.var_shortcut.get()
        cfg.move_to_trash_on_delete = self.var_trash.get()
        cfg.theme = self.var_theme.get()
        self._services.app_service.save_config(cfg)
        self._on_toast("Preferencias guardadas.", "success")
        self.destroy()
