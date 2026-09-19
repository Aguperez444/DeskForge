"""Main library view: Gear Lever-style filter pills, rich app cards, and empty-state hero."""

from __future__ import annotations

from pathlib import Path
from typing import Callable

import ttkbootstrap as ttk

from deskforge.domain.categories import get_category_label
from deskforge.domain.models import AppType, ManagedApp
from deskforge.infrastructure.system_integration import resolve_executable_target
from deskforge.ui.theme import badge_bootstyle_for_type
from deskforge.ui.widgets import IconCache, ScrollableFrame


class LibraryView(ttk.Frame):
    """Displays managed applications as interactive cards with type filters and quick actions."""

    def __init__(
        self,
        master,
        icon_cache: IconCache,
        on_launch: Callable[[ManagedApp], None],
        on_edit: Callable[[ManagedApp], None],
        on_upgrade: Callable[[ManagedApp], None],
        on_remove: Callable[[ManagedApp], None],
        on_open_folder: Callable[[ManagedApp], None],
        on_new_file: Callable[[], None],
        on_new_webapp: Callable[[], None],
        on_scan: Callable[[], None],
    ) -> None:
        super().__init__(master)
        self._icon_cache = icon_cache
        self._on_launch = on_launch
        self._on_edit = on_edit
        self._on_upgrade = on_upgrade
        self._on_remove = on_remove
        self._on_open_folder = on_open_folder
        self._on_new_file = on_new_file
        self._on_new_webapp = on_new_webapp
        self._on_scan = on_scan

        self._active_filter: AppType | None = None
        self._all_apps: list[ManagedApp] = []
        self._search_text: str = ""
        self._filter_buttons: dict[AppType | None, ttk.Button] = {}

        # Filter pills bar
        self._filter_bar = ttk.Frame(self, padding=(14, 6, 14, 6))
        self._filter_bar.pack(fill="x")

        filter_items: list[tuple[AppType | None, str]] = [
            (None, "Todas"),
            (AppType.APPIMAGE, "AppImage"),
            (AppType.JAR, "JAR"),
            (AppType.BINARY, "Binarios"),
            (AppType.SCRIPT, "Scripts"),
            (AppType.WEBAPP, "WebApps"),
        ]
        for ftype, label in filter_items:
            btn = ttk.Button(
                self._filter_bar,
                text=label,
                bootstyle="secondary-outline",
                command=lambda t=ftype: self.set_filter(t),
            )
            btn.pack(side="left", padx=(0, 6))
            self._filter_buttons[ftype] = btn

        # Scrollable cards area
        self.scroll = ScrollableFrame(self)
        self.scroll.pack(fill="both", expand=True, padx=14, pady=(4, 8))

    def set_filter(self, app_type: AppType | None) -> None:
        self._active_filter = app_type
        self._render()

    def set_search(self, query: str) -> None:
        self._search_text = query.strip().lower()
        self._render()

    def set_apps(self, apps: list[ManagedApp]) -> None:
        self._all_apps = list(apps)
        self._render()

    def sync_theme(self) -> None:
        self.scroll.sync_canvas_bg()

    def _filtered_apps(self) -> list[ManagedApp]:
        items = self._all_apps
        if self._active_filter is not None:
            items = [a for a in items if a.app_type == self._active_filter]
        if self._search_text:
            q = self._search_text
            items = [
                a
                for a in items
                if q in a.name.lower()
                or q in a.comment.lower()
                or q in a.exec_target.lower()
                or any(q in c.lower() for c in a.categories)
            ]
        return items

    def _update_filter_pills(self) -> None:
        counts: dict[AppType | None, int] = {None: len(self._all_apps)}
        for t in AppType:
            counts[t] = sum(1 for a in self._all_apps if a.app_type == t)

        labels = {
            None: "Todas",
            AppType.APPIMAGE: "AppImage",
            AppType.JAR: "JAR",
            AppType.BINARY: "Binarios",
            AppType.SCRIPT: "Scripts",
            AppType.WEBAPP: "WebApps",
        }
        for ftype, btn in self._filter_buttons.items():
            count = counts[ftype]
            btn.configure(
                text=f"{labels[ftype]} ({count})",
                bootstyle="primary" if self._active_filter == ftype else "secondary-outline",
            )

    def _render(self) -> None:
        self._update_filter_pills()
        for child in self.scroll.inner.winfo_children():
            child.destroy()

        visible = self._filtered_apps()
        if not visible:
            self._render_empty_state()
            return

        for app in visible:
            self._render_card(app)

    def _render_empty_state(self) -> None:
        wrapper = ttk.Frame(self.scroll.inner, padding=(24, 48))
        wrapper.pack(fill="both", expand=True)

        if self._all_apps:
            ttk.Label(
                wrapper,
                text="No hay aplicaciones que coincidan con tu búsqueda o filtro.",
                font=("Sans", 13, "bold"),
            ).pack(pady=(0, 8))
            ttk.Button(
                wrapper,
                text="Limpiar filtros",
                bootstyle="primary-outline",
                command=lambda: (self.set_filter(None), self.set_search("")),
            ).pack()
            return

        hero = ttk.Labelframe(wrapper, text=" Bienvenido a DeskForge ", padding=28)
        hero.pack(fill="x", padx=40)

        ttk.Label(
            hero,
            text="Integrá cualquier app en tu escritorio Linux en segundos",
            font=("Sans", 15, "bold"),
        ).pack(anchor="w")
        ttk.Label(
            hero,
            text=(
                "Soporta AppImages, archivos .jar (con selector de JDK y RAM JVM), binarios portables, "
                "scripts y WebApps.\nTambién podés pegar un archivo o URL directamente con Ctrl+V, o usar "
                "'Abrir con DeskForge' desde Dolphin."
            ),
            justify="left",
            wraplength=680,
            bootstyle="secondary",
        ).pack(anchor="w", pady=(8, 18))

        btn_row = ttk.Frame(hero)
        btn_row.pack(anchor="w")
        ttk.Button(
            btn_row,
            text="＋ Integrar archivo (.AppImage, .jar, binario...)",
            bootstyle="success",
            command=self._on_new_file,
        ).pack(side="left", padx=(0, 10))
        ttk.Button(
            btn_row,
            text="🌐 Agregar WebApp",
            bootstyle="info-outline",
            command=self._on_new_webapp,
        ).pack(side="left", padx=(0, 10))
        ttk.Button(
            btn_row,
            text="🔎 Escanear Descargas / Importar .desktop",
            bootstyle="secondary-outline",
            command=self._on_scan,
        ).pack(side="left")

    def _render_card(self, app: ManagedApp) -> None:
        card = ttk.Frame(self.scroll.inner, padding=12, bootstyle="secondary")
        card.pack(fill="x", pady=(0, 8))

        inner = ttk.Frame(card, padding=10)
        inner.pack(fill="both", expand=True)
        inner.columnconfigure(1, weight=1)

        # Icon (48x48)
        icon_img = self._icon_cache.get_icon(app.icon_path, size=48, app_name=app.name, app_type=app.app_type)
        icon_lbl = ttk.Label(inner, image=icon_img)
        icon_lbl.image = icon_img  # Extra safety reference
        icon_lbl.grid(row=0, column=0, rowspan=2, padx=(0, 14), sticky="n")

        # Title + Badges row
        title_row = ttk.Frame(inner)
        title_row.grid(row=0, column=1, sticky="ew")

        ttk.Label(title_row, text=app.name, font=("Sans", 12, "bold")).pack(side="left", padx=(0, 8))
        ttk.Label(
            title_row,
            text=f" {app.app_type.short_badge} ",
            bootstyle=badge_bootstyle_for_type(app.app_type),
            font=("Sans", 8, "bold"),
        ).pack(side="left", padx=(0, 6))

        if app.version:
            ttk.Label(
                title_row,
                text=f" v{app.version} ",
                bootstyle="secondary-inverse",
                font=("Sans", 8),
            ).pack(side="left", padx=(0, 6))

        if app.dedicated_gpu:
            ttk.Label(
                title_row,
                text=" GPU ",
                bootstyle="danger-inverse",
                font=("Sans", 8, "bold"),
            ).pack(side="left", padx=(0, 6))

        missing_target = (
            app.app_type != AppType.WEBAPP and resolve_executable_target(app.exec_target)[1] is None
        )
        if missing_target:
            ttk.Label(
                title_row,
                text=" ⚠ Archivo faltante ",
                bootstyle="danger-inverse",
                font=("Sans", 8, "bold"),
            ).pack(side="left", padx=(0, 6))

        # Subtitle details
        details_parts: list[str] = []
        if app.app_type == AppType.JAR:
            if app.java_options.max_memory:
                details_parts.append(f"RAM máx: {app.java_options.max_memory}")
            if app.java_options.java_path and app.java_options.java_path != "java":
                details_parts.append(Path(app.java_options.java_path).parent.parent.name)
        if app.categories:
            cat_labels = ", ".join(get_category_label(c) for c in app.categories[:2])
            details_parts.append(cat_labels)
        details_parts.append(app.exec_target)
        subtitle = "  ·  ".join(details_parts)

        ttk.Label(
            inner,
            text=subtitle,
            bootstyle="secondary",
            font=("Sans", 9),
            wraplength=560,
            justify="left",
        ).grid(row=1, column=1, sticky="w", pady=(3, 0))

        # Action buttons
        actions = ttk.Frame(inner)
        actions.grid(row=0, column=2, rowspan=2, padx=(12, 0), sticky="e")

        ttk.Button(
            actions,
            text="▶ Lanzar",
            bootstyle="success",
            command=lambda a=app: self._on_launch(a),
        ).pack(side="left", padx=(0, 5))

        ttk.Button(
            actions,
            text="✎ Editar",
            bootstyle="info-outline",
            command=lambda a=app: self._on_edit(a),
        ).pack(side="left", padx=(0, 5))

        if app.app_type != AppType.WEBAPP:
            ttk.Button(
                actions,
                text="↑ Actualizar",
                bootstyle="warning-outline",
                command=lambda a=app: self._on_upgrade(a),
            ).pack(side="left", padx=(0, 5))

            ttk.Button(
                actions,
                text="📁",
                bootstyle="secondary-outline",
                width=3,
                command=lambda a=app: self._on_open_folder(a),
            ).pack(side="left", padx=(0, 5))

        ttk.Button(
            actions,
            text="🗑",
            bootstyle="danger-outline",
            width=3,
            command=lambda a=app: self._on_remove(a),
        ).pack(side="left")
