"""3-tab Integrate / Edit modal dialog with async metadata extraction, JVM/Env controls, and .desktop preview."""

from __future__ import annotations

import shlex
import tkinter as tk
from tkinter import filedialog
from typing import Callable

import ttkbootstrap as ttk

from deskforge.application import ServiceContainer
from deskforge.domain.categories import CATEGORIES
from deskforge.domain.exceptions import DeskForgeError
from deskforge.domain.models import AppType, DetectionResult, JavaOptions, ManagedApp, StorageMode
from deskforge.infrastructure.inspectors.java_runtime import detect_java_runtimes
from deskforge.infrastructure.inspectors.webapp_inspector import detect_installed_browsers
from deskforge.ui.widgets import IconCache, ScrollableFrame, center_window, run_in_background


class AppEditorDialog(ttk.Toplevel):
    """Modal dialog for integrating a new app or editing an existing ManagedApp."""

    def __init__(
        self,
        parent: tk.Misc,
        services: ServiceContainer,
        icon_cache: IconCache,
        on_saved: Callable[[ManagedApp, bool], None],
        existing_app: ManagedApp | None = None,
        initial_target: str = "",
        initial_mode_webapp: bool = False,
    ) -> None:
        super().__init__(parent)
        self._services = services
        self._icon_cache = icon_cache
        self._on_saved = on_saved
        self._existing = existing_app
        self._is_edit = existing_app is not None
        self._icon_candidates: list[str] = []
        self._env_vars: dict[str, str] = dict(existing_app.env_vars) if existing_app else {}
        self._cat_vars: dict[str, tk.BooleanVar] = {}
        self._java_runtimes = detect_java_runtimes()
        self._browsers = detect_installed_browsers()

        cfg = services.app_service.get_config()

        # Tk Variables
        self.var_target = tk.StringVar(value=existing_app.exec_target if existing_app else initial_target)
        self.var_name = tk.StringVar(value=existing_app.name if existing_app else "")
        self.var_comment = tk.StringVar(value=existing_app.comment if existing_app else "")
        self.var_version = tk.StringVar(value=existing_app.version if existing_app else "")
        default_type = (
            existing_app.app_type.value
            if existing_app
            else (AppType.WEBAPP.value if initial_mode_webapp else AppType.APPIMAGE.value)
        )
        self.var_type = tk.StringVar(value=default_type)
        self.var_icon = tk.StringVar(value=existing_app.icon_path if existing_app else "")
        self.var_storage = tk.StringVar(
            value=existing_app.storage_mode.value if existing_app else cfg.default_storage_mode
        )
        self.var_desktop_shortcut = tk.BooleanVar(
            value=existing_app.create_desktop_shortcut if existing_app else cfg.default_desktop_shortcut
        )

        # Advanced vars
        self.var_java_path = tk.StringVar(value=existing_app.java_options.java_path if existing_app else "java")
        self.var_xmx = tk.StringVar(value=existing_app.java_options.max_memory if existing_app else "")
        self.var_xms = tk.StringVar(value=existing_app.java_options.min_memory if existing_app else "")
        self.var_jvm_args = tk.StringVar(
            value=" ".join(existing_app.java_options.jvm_args) if existing_app else ""
        )
        self.var_browser = tk.StringVar(
            value=(
                existing_app.webapp_browser
                if existing_app and existing_app.webapp_browser
                else (self._browsers[0][0] if self._browsers else "chromium")
            )
        )
        self.var_interpreter = tk.StringVar(value=existing_app.script_interpreter if existing_app else "")
        self.var_args = tk.StringVar(value=" ".join(existing_app.args) if existing_app else "")
        self.var_workdir = tk.StringVar(value=existing_app.working_dir if existing_app else "")
        self.var_wm_class = tk.StringVar(value=existing_app.startup_wm_class if existing_app else "")
        self.var_keywords = tk.StringVar(value="; ".join(existing_app.keywords) if existing_app else "")
        self.var_terminal = tk.BooleanVar(value=existing_app.terminal if existing_app else False)
        self.var_gpu = tk.BooleanVar(value=existing_app.dedicated_gpu if existing_app else False)
        self.var_nodisplay = tk.BooleanVar(value=existing_app.no_display if existing_app else False)

        self.title(f"Editar — {existing_app.name}" if existing_app else "Integrar nueva aplicación")
        self.minsize(760, 620)
        self._build_ui()
        self._sync_conditional_sections()

        self.var_type.trace_add("write", lambda *_: self._sync_conditional_sections())
        self.var_icon.trace_add("write", lambda *_: self._refresh_icon_preview())
        self.var_name.trace_add("write", lambda *_: self._refresh_icon_preview())

        self.bind("<Escape>", lambda _e: self.destroy())
        self.transient(parent)
        center_window(self, 820, 680, parent)
        self.grab_set()

        if initial_target and not existing_app:
            self._run_inspection(initial_target)

    # ----------------------------------------------------------------- UI Build

    def _build_ui(self) -> None:
        root_frame = ttk.Frame(self, padding=14)
        root_frame.pack(fill="both", expand=True)

        # Header + progress bar for async inspection
        header = ttk.Frame(root_frame)
        header.pack(fill="x", pady=(0, 8))
        title_text = f"Editar aplicación: {self._existing.name}" if self._existing else "Integrar aplicación en tu escritorio"
        ttk.Label(header, text=title_text, font=("Sans", 13, "bold")).pack(side="left")

        self._status_lbl = ttk.Label(header, text="", bootstyle="info")
        self._status_lbl.pack(side="right", padx=(8, 0))
        self._progress = ttk.Progressbar(header, mode="indeterminate", length=120, bootstyle="info-striped")

        # Warning banner (hidden unless inspector reports warnings)
        self._warning_lbl = ttk.Label(root_frame, text="", bootstyle="warning", wraplength=760, justify="left")

        # Tabs
        self._notebook = ttk.Notebook(root_frame)
        self._notebook.pack(fill="both", expand=True, pady=(4, 10))
        self._notebook.bind("<<NotebookTabChanged>>", self._on_tab_changed)

        tab_general = ttk.Frame(self._notebook, padding=12)
        tab_advanced = ttk.Frame(self._notebook, padding=12)
        tab_preview = ttk.Frame(self._notebook, padding=12)

        self._notebook.add(tab_general, text="  General  ")
        self._notebook.add(tab_advanced, text="  Avanzado (JVM / Env / GPU)  ")
        self._notebook.add(tab_preview, text="  Vista previa .desktop  ")

        self._build_general_tab(tab_general)
        self._build_advanced_tab(tab_advanced)
        self._build_preview_tab(tab_preview)

        # Footer action bar
        footer = ttk.Frame(root_frame)
        footer.pack(fill="x")
        self._error_lbl = ttk.Label(footer, text="", bootstyle="danger")
        self._error_lbl.pack(side="left", fill="x", expand=True)

        ttk.Button(footer, text="Cancelar", bootstyle="secondary-outline", command=self.destroy).pack(side="right")
        save_label = "💾 Guardar cambios" if self._is_edit else "✓ Integrar aplicación"
        self._save_btn = ttk.Button(footer, text=save_label, bootstyle="success", command=self._on_submit)
        self._save_btn.pack(side="right", padx=(0, 8))

    def _build_general_tab(self, parent: ttk.Frame) -> None:
        scroll = ScrollableFrame(parent)
        scroll.pack(fill="both", expand=True)
        body = scroll.inner
        body.columnconfigure(1, weight=1)

        # Row 0: Target file / URL
        ttk.Label(body, text="Archivo o URL:", font=("Sans", 10, "bold")).grid(row=0, column=0, sticky="w", pady=5)
        target_row = ttk.Frame(body)
        target_row.grid(row=0, column=1, sticky="ew", pady=5)
        target_row.columnconfigure(0, weight=1)
        ttk.Entry(target_row, textvariable=self.var_target).grid(row=0, column=0, sticky="ew", padx=(0, 6))
        ttk.Button(target_row, text="Examinar...", bootstyle="secondary-outline", command=self._browse_target).grid(
            row=0, column=1, padx=(0, 6)
        )
        ttk.Button(target_row, text="✨ Detectar", bootstyle="info-outline", command=self._trigger_inspect).grid(
            row=0, column=2
        )

        # Row 1: App Type + Version
        ttk.Label(body, text="Tipo de app:", font=("Sans", 10, "bold")).grid(row=1, column=0, sticky="w", pady=5)
        type_row = ttk.Frame(body)
        type_row.grid(row=1, column=1, sticky="ew", pady=5)
        for app_type in AppType:
            ttk.Radiobutton(
                type_row,
                text=app_type.label,
                variable=self.var_type,
                value=app_type.value,
                bootstyle="info-toolbutton",
            ).pack(side="left", padx=(0, 5))

        # Row 2: Name + Version
        ttk.Label(body, text="Nombre:", font=("Sans", 10, "bold")).grid(row=2, column=0, sticky="w", pady=5)
        name_row = ttk.Frame(body)
        name_row.grid(row=2, column=1, sticky="ew", pady=5)
        name_row.columnconfigure(0, weight=3)
        name_row.columnconfigure(2, weight=1)
        ttk.Entry(name_row, textvariable=self.var_name).grid(row=0, column=0, sticky="ew")
        ttk.Label(name_row, text="Versión:").grid(row=0, column=1, padx=(12, 6))
        ttk.Entry(name_row, textvariable=self.var_version, width=14).grid(row=0, column=2, sticky="ew")

        # Row 3: Comment
        ttk.Label(body, text="Descripción:", font=("Sans", 10, "bold")).grid(row=3, column=0, sticky="w", pady=5)
        ttk.Entry(body, textvariable=self.var_comment).grid(row=3, column=1, sticky="ew", pady=5)

        # Row 4: Icon section with live preview + candidate gallery
        ttk.Label(body, text="Ícono:", font=("Sans", 10, "bold")).grid(row=4, column=0, sticky="nw", pady=8)
        icon_box = ttk.Frame(body)
        icon_box.grid(row=4, column=1, sticky="ew", pady=5)
        icon_box.columnconfigure(1, weight=1)

        self._icon_preview_lbl = ttk.Label(icon_box)
        self._icon_preview_lbl.grid(row=0, column=0, rowspan=2, padx=(0, 12), sticky="n")

        icon_input_row = ttk.Frame(icon_box)
        icon_input_row.grid(row=0, column=1, sticky="ew")
        icon_input_row.columnconfigure(0, weight=1)
        ttk.Entry(icon_input_row, textvariable=self.var_icon).grid(row=0, column=0, sticky="ew", padx=(0, 6))
        ttk.Button(icon_input_row, text="Elegir...", bootstyle="secondary-outline", command=self._browse_icon).grid(
            row=0, column=1, padx=(0, 4)
        )
        ttk.Button(
            icon_input_row,
            text="Default",
            bootstyle="secondary-link",
            command=lambda: self.var_icon.set(""),
        ).grid(row=0, column=2)

        self._icon_gallery = ttk.Frame(icon_box)
        self._icon_gallery.grid(row=1, column=1, sticky="w", pady=(6, 0))
        self._refresh_icon_preview()

        # Row 5: Categories grid (multi-select)
        ttk.Label(body, text="Categorías:", font=("Sans", 10, "bold")).grid(row=5, column=0, sticky="nw", pady=8)
        cat_frame = ttk.Frame(body)
        cat_frame.grid(row=5, column=1, sticky="ew", pady=5)
        selected_cats = set(self._existing.categories if self._existing else ["Utility"])
        for idx, cat in enumerate(CATEGORIES):
            var = tk.BooleanVar(value=cat.code in selected_cats)
            self._cat_vars[cat.code] = var
            cb = ttk.Checkbutton(cat_frame, text=cat.label_es, variable=var, bootstyle="round-toggle")
            cb.grid(row=idx // 4, column=idx % 4, sticky="w", padx=(0, 12), pady=2)

        # Row 6: Storage mode (only when integrating new local file)
        self._storage_label = ttk.Label(body, text="Almacenamiento:", font=("Sans", 10, "bold"))
        self._storage_frame = ttk.Frame(body)
        for mode in StorageMode:
            ttk.Radiobutton(
                self._storage_frame,
                text=mode.label_es,
                variable=self.var_storage,
                value=mode.value,
            ).pack(anchor="w", pady=1)

        if not self._is_edit:
            self._storage_label.grid(row=6, column=0, sticky="nw", pady=8)
            self._storage_frame.grid(row=6, column=1, sticky="w", pady=5)

        # Row 7: Desktop shortcut toggle
        ttk.Checkbutton(
            body,
            text="Crear también acceso directo en el Escritorio",
            variable=self.var_desktop_shortcut,
            bootstyle="success-round-toggle",
        ).grid(row=7, column=1, sticky="w", pady=(10, 4))

    def _build_advanced_tab(self, parent: ttk.Frame) -> None:
        scroll = ScrollableFrame(parent)
        scroll.pack(fill="both", expand=True)
        body = scroll.inner
        body.columnconfigure(0, weight=1)

        # 1. Java / JVM Section (shown only for JAR)
        self._jvm_section = ttk.Labelframe(body, text=" Configuración Java / JVM (.jar) ", padding=10)
        self._jvm_section.columnconfigure(1, weight=1)

        ttk.Label(self._jvm_section, text="Runtime Java / JDK:").grid(row=0, column=0, sticky="w", pady=4)
        java_values = ["java"] + [rt.path for rt in self._java_runtimes]
        java_combo = ttk.Combobox(self._jvm_section, textvariable=self.var_java_path, values=java_values)
        java_combo.grid(row=0, column=1, sticky="ew", padx=(8, 0), pady=4)

        if self._java_runtimes:
            summary = "Detectados: " + " · ".join(rt.version for rt in self._java_runtimes[:3])
            ttk.Label(self._jvm_section, text=summary, bootstyle="secondary", font=("Sans", 8)).grid(
                row=1, column=1, sticky="w", padx=(8, 0)
            )

        mem_row = ttk.Frame(self._jvm_section)
        mem_row.grid(row=2, column=0, columnspan=2, sticky="ew", pady=6)
        ttk.Label(mem_row, text="Memoria Máx (-Xmx):").pack(side="left")
        ttk.Combobox(
            mem_row,
            textvariable=self.var_xmx,
            values=["", "512M", "1G", "2G", "4G", "6G", "8G", "16G"],
            width=10,
        ).pack(side="left", padx=(6, 16))
        ttk.Label(mem_row, text="Memoria Inicial (-Xms):").pack(side="left")
        ttk.Combobox(
            mem_row,
            textvariable=self.var_xms,
            values=["", "256M", "512M", "1G", "2G"],
            width=10,
        ).pack(side="left", padx=(6, 0))

        ttk.Label(self._jvm_section, text="Flags JVM extra:").grid(row=3, column=0, sticky="w", pady=4)
        ttk.Entry(self._jvm_section, textvariable=self.var_jvm_args).grid(row=3, column=1, sticky="ew", padx=(8, 0), pady=4)

        # 2. WebApp Browser Section (shown only for WEBAPP)
        self._webapp_section = ttk.Labelframe(body, text=" Configuración WebApp ", padding=10)
        self._webapp_section.columnconfigure(1, weight=1)
        ttk.Label(self._webapp_section, text="Navegador:").grid(row=0, column=0, sticky="w", pady=4)
        browser_vals = [b[0] for b in self._browsers] or ["chromium", "google-chrome", "firefox"]
        ttk.Combobox(self._webapp_section, textvariable=self.var_browser, values=browser_vals).grid(
            row=0, column=1, sticky="ew", padx=(8, 0), pady=4
        )

        # 3. Script Interpreter Section (shown only for SCRIPT)
        self._script_section = ttk.Labelframe(body, text=" Configuración Script ", padding=10)
        self._script_section.columnconfigure(1, weight=1)
        ttk.Label(self._script_section, text="Intérprete (vacío = usar #!):").grid(row=0, column=0, sticky="w", pady=4)
        ttk.Combobox(
            self._script_section,
            textvariable=self.var_interpreter,
            values=["", "bash", "python3", "sh", "node", "ruby"],
        ).grid(row=0, column=1, sticky="ew", padx=(8, 0), pady=4)

        # 4. Execution & Desktop Options
        self._exec_section = ttk.Labelframe(body, text=" Ejecución y Escritorio ", padding=10)
        exec_section = self._exec_section
        exec_section.pack(fill="x", pady=(0, 10))
        exec_section.columnconfigure(1, weight=1)

        ttk.Label(exec_section, text="Argumentos CLI:").grid(row=0, column=0, sticky="w", pady=4)
        ttk.Entry(exec_section, textvariable=self.var_args).grid(row=0, column=1, sticky="ew", padx=(8, 0), pady=4)

        ttk.Label(exec_section, text="Directorio de trabajo:").grid(row=1, column=0, sticky="w", pady=4)
        wd_row = ttk.Frame(exec_section)
        wd_row.grid(row=1, column=1, sticky="ew", padx=(8, 0), pady=4)
        wd_row.columnconfigure(0, weight=1)
        ttk.Entry(wd_row, textvariable=self.var_workdir).grid(row=0, column=0, sticky="ew", padx=(0, 6))
        ttk.Button(wd_row, text="Carpeta...", bootstyle="secondary-outline", command=self._browse_workdir).grid(
            row=0, column=1
        )

        ttk.Label(exec_section, text="StartupWMClass:").grid(row=2, column=0, sticky="w", pady=4)
        ttk.Entry(exec_section, textvariable=self.var_wm_class).grid(row=2, column=1, sticky="ew", padx=(8, 0), pady=4)

        ttk.Label(exec_section, text="Palabras clave (;):").grid(row=3, column=0, sticky="w", pady=4)
        ttk.Entry(exec_section, textvariable=self.var_keywords).grid(row=3, column=1, sticky="ew", padx=(8, 0), pady=4)

        toggles = ttk.Frame(exec_section)
        toggles.grid(row=4, column=0, columnspan=2, sticky="w", pady=(8, 2))
        ttk.Checkbutton(
            toggles,
            text="Preferir GPU dedicada (DRI_PRIME / PrefersNonDefaultGPU)",
            variable=self.var_gpu,
            bootstyle="warning-round-toggle",
        ).pack(anchor="w", pady=2)
        ttk.Checkbutton(
            toggles,
            text="Ejecutar en Terminal",
            variable=self.var_terminal,
            bootstyle="info-round-toggle",
        ).pack(anchor="w", pady=2)
        ttk.Checkbutton(
            toggles,
            text="Ocultar del menú (NoDisplay=true)",
            variable=self.var_nodisplay,
            bootstyle="secondary-round-toggle",
        ).pack(anchor="w", pady=2)

        # 5. Environment Variables Editor
        env_section = ttk.Labelframe(body, text=" Variables de entorno (KEY=VALUE) ", padding=10)
        env_section.pack(fill="x", pady=(0, 8))

        add_row = ttk.Frame(env_section)
        add_row.pack(fill="x", pady=(0, 6))
        self._env_key_entry = ttk.Entry(add_row, width=22)
        self._env_key_entry.pack(side="left", padx=(0, 6))
        self._env_key_entry.insert(0, "CLAVE")
        ttk.Label(add_row, text="=").pack(side="left", padx=(0, 6))
        self._env_val_entry = ttk.Entry(add_row)
        self._env_val_entry.pack(side="left", fill="x", expand=True, padx=(0, 6))
        ttk.Button(add_row, text="＋ Agregar", bootstyle="info-outline", command=self._add_env_var).pack(side="left")

        self._env_tree = ttk.Treeview(env_section, columns=("key", "val"), show="headings", height=4)
        self._env_tree.heading("key", text="Variable")
        self._env_tree.heading("val", text="Valor")
        self._env_tree.column("key", width=200)
        self._env_tree.column("val", width=420)
        self._env_tree.pack(fill="x", pady=(0, 6))

        ttk.Button(
            env_section,
            text="Eliminar seleccionada",
            bootstyle="danger-outline",
            command=self._remove_selected_env,
        ).pack(anchor="e")
        self._refresh_env_tree()

    def _build_preview_tab(self, parent: ttk.Frame) -> None:
        top = ttk.Frame(parent)
        top.pack(fill="x", pady=(0, 8))
        ttk.Label(top, text="Archivo .desktop generado (FreeDesktop Spec v1.5):", font=("Sans", 10, "bold")).pack(
            side="left"
        )
        ttk.Button(top, text="✓ Validar ahora", bootstyle="info-outline", command=self._refresh_preview).pack(side="right")

        self._preview_text = tk.Text(parent, height=18, font=("Monospace", 10), wrap="none")
        self._preview_text.pack(fill="both", expand=True)

        self._validation_lbl = ttk.Label(parent, text="", font=("Sans", 9, "bold"), wraplength=740, justify="left")
        self._validation_lbl.pack(anchor="w", pady=(8, 0))

    # ------------------------------------------------------------ Interactions

    def _sync_conditional_sections(self) -> None:
        try:
            current_type = AppType(self.var_type.get())
        except ValueError:
            current_type = AppType.BINARY

        for section in (self._jvm_section, self._webapp_section, self._script_section):
            section.pack_forget()

        if current_type == AppType.JAR:
            self._jvm_section.pack(fill="x", pady=(0, 10), before=self._exec_section)
        elif current_type == AppType.WEBAPP:
            self._webapp_section.pack(fill="x", pady=(0, 10), before=self._exec_section)
        elif current_type == AppType.SCRIPT:
            self._script_section.pack(fill="x", pady=(0, 10), before=self._exec_section)

        if not self._is_edit:
            if current_type == AppType.WEBAPP:
                self._storage_label.grid_remove()
                self._storage_frame.grid_remove()
            else:
                self._storage_label.grid()
                self._storage_frame.grid()

    def _browse_target(self) -> None:
        path = filedialog.askopenfilename(
            parent=self,
            title="Seleccionar archivo ejecutable",
            filetypes=[
                ("Aplicaciones soportadas", "*.AppImage *.appimage *.jar *.sh *.py *.bin *.run"),
                ("AppImage", "*.AppImage *.appimage"),
                ("Java JAR", "*.jar"),
                ("Scripts", "*.sh *.bash *.py *.rb *.js"),
                ("Todos los archivos", "*"),
            ],
        )
        if path:
            self.var_target.set(path)
            self._run_inspection(path)

    def _browse_icon(self) -> None:
        path = filedialog.askopenfilename(
            parent=self,
            title="Seleccionar ícono",
            filetypes=[("Imágenes e íconos", "*.png *.svg *.ico *.jpg *.jpeg *.webp"), ("Todos", "*")],
        )
        if path:
            self.var_icon.set(path)

    def _browse_workdir(self) -> None:
        path = filedialog.askdirectory(parent=self, title="Seleccionar directorio de trabajo")
        if path:
            self.var_workdir.set(path)

    def _trigger_inspect(self) -> None:
        target = self.var_target.get().strip()
        if target:
            self._run_inspection(target)

    def _run_inspection(self, target: str) -> None:
        self._status_lbl.configure(text="Analizando...")
        self._progress.pack(side="right")
        self._progress.start(12)

        def _done(result: object) -> None:
            self._progress.stop()
            self._progress.pack_forget()
            self._status_lbl.configure(text="✓ Metadatos detectados")
            if isinstance(result, DetectionResult):
                self._apply_detection(result)

        def _err(exc: Exception) -> None:
            self._progress.stop()
            self._progress.pack_forget()
            self._status_lbl.configure(text="")
            self._error_lbl.configure(text=f"Error al inspeccionar: {exc}")

        run_in_background(self, lambda: self._services.app_service.inspect_target(target), _done, _err)

    def _apply_detection(self, det: DetectionResult) -> None:
        self.var_target.set(det.target)
        self.var_type.set(det.app_type.value)
        if det.suggested_name:
            self.var_name.set(det.suggested_name)
        if det.comment:
            self.var_comment.set(det.comment)
        if det.version:
            self.var_version.set(det.version)
        if det.working_dir:
            self.var_workdir.set(det.working_dir)
        if det.startup_wm_class:
            self.var_wm_class.set(det.startup_wm_class)
        if det.script_interpreter:
            self.var_interpreter.set(det.script_interpreter)
        if det.webapp_browser:
            self.var_browser.set(det.webapp_browser)
        self.var_terminal.set(det.terminal)

        # Update categories checkboxes
        for code, var in self._cat_vars.items():
            var.set(code in det.categories)

        # Update icon candidates & gallery
        self._icon_candidates = list(det.icon_candidates)
        if det.selected_icon:
            self.var_icon.set(det.selected_icon)
        self._render_icon_gallery()

        if det.warnings:
            self._warning_lbl.configure(text="⚠ " + " | ".join(det.warnings))
            self._warning_lbl.pack(fill="x", pady=(0, 6), before=self._notebook)
        else:
            self._warning_lbl.pack_forget()

    def _refresh_icon_preview(self) -> None:
        try:
            app_type = AppType(self.var_type.get())
        except ValueError:
            app_type = AppType.BINARY
        icon_path = self.var_icon.get().strip()
        if not icon_path:
            icon_path = str(self._services.icon_store.default_icon_for(app_type))
        photo = self._icon_cache.get_icon(icon_path, size=64, app_name=self.var_name.get() or "D", app_type=app_type)
        self._icon_preview_lbl.configure(image=photo)
        self._icon_preview_lbl.image = photo

    def _render_icon_gallery(self) -> None:
        for child in self._icon_gallery.winfo_children():
            child.destroy()
        if not self._icon_candidates:
            return
        ttk.Label(self._icon_gallery, text="Extraídos:", bootstyle="secondary", font=("Sans", 8)).pack(
            side="left", padx=(0, 6)
        )
        try:
            app_type = AppType(self.var_type.get())
        except ValueError:
            app_type = AppType.BINARY
        for cand in self._icon_candidates[:6]:
            thumb = self._icon_cache.get_icon(cand, size=32, app_name="I", app_type=app_type)
            btn = ttk.Button(
                self._icon_gallery,
                image=thumb,
                bootstyle="secondary-outline",
                command=lambda p=cand: self.var_icon.set(p),
            )
            btn.image = thumb
            btn.pack(side="left", padx=(0, 4))

    def _add_env_var(self) -> None:
        k = self._env_key_entry.get().strip()
        v = self._env_val_entry.get().strip()
        if not k or k == "CLAVE":
            return
        self._env_vars[k] = v
        self._env_key_entry.delete(0, "end")
        self._env_val_entry.delete(0, "end")
        self._refresh_env_tree()

    def _remove_selected_env(self) -> None:
        for item in self._env_tree.selection():
            vals = self._env_tree.item(item, "values")
            if vals:
                self._env_vars.pop(str(vals[0]), None)
        self._refresh_env_tree()

    def _refresh_env_tree(self) -> None:
        for item in self._env_tree.get_children():
            self._env_tree.delete(item)
        for k, v in sorted(self._env_vars.items()):
            self._env_tree.insert("", "end", values=(k, v))

    def _build_managed_app_from_form(self) -> ManagedApp:
        selected_cats = [code for code, var in self._cat_vars.items() if var.get()]
        if not selected_cats:
            selected_cats = ["Utility"]

        try:
            extra_args = shlex.split(self.var_args.get().strip()) if self.var_args.get().strip() else []
        except ValueError:
            extra_args = self.var_args.get().split()

        try:
            jvm_args = shlex.split(self.var_jvm_args.get().strip()) if self.var_jvm_args.get().strip() else []
        except ValueError:
            jvm_args = self.var_jvm_args.get().split()

        keywords = [k.strip() for k in self.var_keywords.get().replace(",", ";").split(";") if k.strip()]

        app_kwargs = dict(
            name=self.var_name.get().strip(),
            app_type=AppType(self.var_type.get()),
            exec_target=self.var_target.get().strip(),
            icon_path=self.var_icon.get().strip(),
            comment=self.var_comment.get().strip(),
            categories=selected_cats,
            keywords=keywords,
            args=extra_args,
            env_vars=dict(self._env_vars),
            working_dir=self.var_workdir.get().strip(),
            terminal=self.var_terminal.get(),
            dedicated_gpu=self.var_gpu.get(),
            startup_wm_class=self.var_wm_class.get().strip(),
            no_display=self.var_nodisplay.get(),
            create_desktop_shortcut=self.var_desktop_shortcut.get(),
            storage_mode=StorageMode(self.var_storage.get()),
            java_options=JavaOptions(
                java_path=self.var_java_path.get().strip() or "java",
                max_memory=self.var_xmx.get().strip(),
                min_memory=self.var_xms.get().strip(),
                jvm_args=jvm_args,
            ),
            script_interpreter=self.var_interpreter.get().strip(),
            webapp_browser=self.var_browser.get().strip(),
            version=self.var_version.get().strip(),
        )
        if self._existing:
            app_kwargs["id"] = self._existing.id
            app_kwargs["desktop_file_path"] = self._existing.desktop_file_path
            app_kwargs["desktop_shortcut_path"] = self._existing.desktop_shortcut_path
            app_kwargs["created_at"] = self._existing.created_at
            app_kwargs["sha256"] = self._existing.sha256
        return ManagedApp(**app_kwargs)

    def _on_tab_changed(self, _event=None) -> None:
        if self._notebook.index("current") == 2:
            self._refresh_preview()

    def _refresh_preview(self) -> None:
        self._preview_text.configure(state="normal")
        self._preview_text.delete("1.0", "end")
        try:
            draft = self._build_managed_app_from_form()
            content, report = self._services.app_service.preview_desktop_entry(draft)
            self._preview_text.insert("1.0", content)
            if report.valid:
                suffix = " (verificado con desktop-file-validate)" if report.used_external_validator else ""
                warn_txt = f" · Avisos: {'; '.join(report.warnings)}" if report.warnings else ""
                self._validation_lbl.configure(text=f"✓ Archivo .desktop válido{suffix}{warn_txt}", bootstyle="success")
            else:
                self._validation_lbl.configure(text="✕ Errores: " + " | ".join(report.errors), bootstyle="danger")
        except DeskForgeError as exc:
            self._preview_text.insert("1.0", f"# Completá los campos obligatorios para generar la vista previa.\n# {exc}\n")
            self._validation_lbl.configure(text=str(exc), bootstyle="warning")
        self._preview_text.configure(state="disabled")

    def _on_submit(self) -> None:
        self._error_lbl.configure(text="")
        try:
            app = self._build_managed_app_from_form()
            if self._is_edit:
                saved = self._services.app_service.update_app(app, source_icon=app.icon_path)
            else:
                saved = self._services.app_service.integrate_app(app, source_icon=app.icon_path)
        except DeskForgeError as exc:
            self._error_lbl.configure(text=str(exc))
            return
        except Exception as exc:
            self._error_lbl.configure(text=f"Error inesperado: {exc}")
            return

        self.destroy()
        self._on_saved(saved, self._is_edit)
