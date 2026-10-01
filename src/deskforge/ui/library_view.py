"""Main library view (PySide6): Gear Lever-style filter pills, rich app cards, context menu, and empty state."""

from __future__ import annotations

from pathlib import Path
from typing import Callable

from PySide6.QtCore import Qt
from PySide6.QtGui import QAction
from PySide6.QtWidgets import (
    QButtonGroup,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMenu,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from deskforge.domain.categories import get_category_label
from deskforge.domain.models import AppType, ManagedApp
from deskforge.infrastructure.system_integration import resolve_executable_target
from deskforge.ui.theme import badge_colors_for_type
from deskforge.ui.widgets import IconProvider


def _make_pill_badge(text: str, bg: str, fg: str = "#ffffff") -> QLabel:
    lbl = QLabel(text)
    lbl.setStyleSheet(
        f"background-color: {bg}; color: {fg}; border-radius: 9px; "
        "padding: 2px 8px; font-size: 11px; font-weight: 700;"
    )
    return lbl


class AppCard(QFrame):
    """Interactive card representing a single managed application."""

    def __init__(
        self,
        app: ManagedApp,
        icon_provider: IconProvider,
        on_launch: Callable[[ManagedApp], None],
        on_edit: Callable[[ManagedApp], None],
        on_upgrade: Callable[[ManagedApp], None],
        on_remove: Callable[[ManagedApp], None],
        on_open_folder: Callable[[ManagedApp], None],
    ) -> None:
        super().__init__()
        self._app = app
        self._on_launch = on_launch
        self._on_edit = on_edit
        self._on_upgrade = on_upgrade
        self._on_remove = on_remove
        self._on_open_folder = on_open_folder

        self.setObjectName("AppCard")
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(self._open_context_menu)

        root = QHBoxLayout(self)
        root.setContentsMargins(14, 12, 14, 12)
        root.setSpacing(14)

        # 48x48 crisp icon
        icon_lbl = QLabel()
        icon_lbl.setFixedSize(48, 48)
        icon_lbl.setPixmap(icon_provider.get_pixmap(app.icon_path, size=48, app_name=app.name, app_type=app.app_type))
        root.addWidget(icon_lbl, alignment=Qt.AlignmentFlag.AlignVCenter)

        # Center metadata column
        info_col = QVBoxLayout()
        info_col.setSpacing(4)

        title_row = QHBoxLayout()
        title_row.setSpacing(7)
        name_lbl = QLabel(app.name)
        name_lbl.setStyleSheet("font-size: 14px; font-weight: 700;")
        title_row.addWidget(name_lbl)

        bg, fg = badge_colors_for_type(app.app_type)
        title_row.addWidget(_make_pill_badge(app.app_type.short_badge, bg, fg))

        if app.version:
            title_row.addWidget(_make_pill_badge(f"v{app.version}", "#3b475a", "#e5ecf6"))

        if app.dedicated_gpu:
            title_row.addWidget(_make_pill_badge("GPU", "#b91c1c", "#ffffff"))

        missing_target = app.app_type != AppType.WEBAPP and resolve_executable_target(app.exec_target)[1] is None
        if missing_target:
            title_row.addWidget(_make_pill_badge("⚠ Archivo faltante", "#c82333", "#ffffff"))

        title_row.addStretch(1)
        info_col.addLayout(title_row)

        details_parts: list[str] = []
        if app.app_type == AppType.JAR:
            if app.java_options.max_memory:
                details_parts.append(f"RAM máx: {app.java_options.max_memory}")
            if app.java_options.java_path and app.java_options.java_path != "java":
                details_parts.append(Path(app.java_options.java_path).parent.parent.name)
        if app.categories:
            details_parts.append(", ".join(get_category_label(c) for c in app.categories[:2]))
        details_parts.append(app.exec_target)

        sub_lbl = QLabel("  ·  ".join(details_parts))
        sub_lbl.setProperty("muted", True)
        sub_lbl.setWordWrap(True)
        sub_lbl.setToolTip(app.exec_target)
        sub_lbl.setStyleSheet("font-size: 11.5px;")
        info_col.addWidget(sub_lbl)

        root.addLayout(info_col, stretch=1)

        # Quick action buttons
        actions = QHBoxLayout()
        actions.setSpacing(6)

        launch_btn = QPushButton("▶ Lanzar")
        launch_btn.setProperty("variant", "success")
        launch_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        launch_btn.clicked.connect(lambda: on_launch(app))
        actions.addWidget(launch_btn)

        edit_btn = QPushButton("✎ Editar")
        edit_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        edit_btn.clicked.connect(lambda: on_edit(app))
        actions.addWidget(edit_btn)

        if app.app_type != AppType.WEBAPP:
            upgrade_btn = QPushButton("↑ Actualizar")
            upgrade_btn.setProperty("variant", "warning")
            upgrade_btn.setCursor(Qt.CursorShape.PointingHandCursor)
            upgrade_btn.setToolTip("Reemplazar archivo binario manteniendo tu configuración")
            upgrade_btn.clicked.connect(lambda: on_upgrade(app))
            actions.addWidget(upgrade_btn)

            folder_btn = QPushButton("📁")
            folder_btn.setFixedWidth(36)
            folder_btn.setCursor(Qt.CursorShape.PointingHandCursor)
            folder_btn.setToolTip("Abrir carpeta contenedora")
            folder_btn.clicked.connect(lambda: on_open_folder(app))
            actions.addWidget(folder_btn)

        del_btn = QPushButton("🗑")
        del_btn.setFixedWidth(36)
        del_btn.setProperty("variant", "danger")
        del_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        del_btn.setToolTip("Eliminar aplicación")
        del_btn.clicked.connect(lambda: on_remove(app))
        actions.addWidget(del_btn)

        root.addLayout(actions)

    def mouseDoubleClickEvent(self, event) -> None:
        self._on_edit(self._app)
        super().mouseDoubleClickEvent(event)

    def _open_context_menu(self, pos) -> None:
        menu = QMenu(self)
        act_launch = QAction("▶ Lanzar aplicación", self)
        act_launch.triggered.connect(lambda: self._on_launch(self._app))
        menu.addAction(act_launch)

        act_edit = QAction("✎ Editar configuración", self)
        act_edit.triggered.connect(lambda: self._on_edit(self._app))
        menu.addAction(act_edit)

        if self._app.app_type != AppType.WEBAPP:
            act_upg = QAction("↑ Actualizar versión (reemplazar archivo)...", self)
            act_upg.triggered.connect(lambda: self._on_upgrade(self._app))
            menu.addAction(act_upg)

            act_dir = QAction("📁 Abrir carpeta contenedora", self)
            act_dir.triggered.connect(lambda: self._on_open_folder(self._app))
            menu.addAction(act_dir)

        menu.addSeparator()
        act_del = QAction("🗑 Eliminar", self)
        act_del.triggered.connect(lambda: self._on_remove(self._app))
        menu.addAction(act_del)

        menu.exec(self.mapToGlobal(pos))


class LibraryView(QWidget):
    """Displays filter pills and a scrollable stack of AppCards."""

    _FILTERS: tuple[tuple[AppType | None, str], ...] = (
        (None, "Todas"),
        (AppType.APPIMAGE, "AppImage"),
        (AppType.JAR, "JAR"),
        (AppType.BINARY, "Binarios"),
        (AppType.SCRIPT, "Scripts"),
        (AppType.WEBAPP, "WebApps"),
    )

    def __init__(
        self,
        icon_provider: IconProvider,
        on_launch: Callable[[ManagedApp], None],
        on_edit: Callable[[ManagedApp], None],
        on_upgrade: Callable[[ManagedApp], None],
        on_remove: Callable[[ManagedApp], None],
        on_open_folder: Callable[[ManagedApp], None],
        on_new_file: Callable[[], None],
        on_new_webapp: Callable[[], None],
        on_scan: Callable[[], None],
    ) -> None:
        super().__init__()
        self._icon_provider = icon_provider
        self._on_launch = on_launch
        self._on_edit = on_edit
        self._on_upgrade = on_upgrade
        self._on_remove = on_remove
        self._on_open_folder = on_open_folder
        self._on_new_file = on_new_file
        self._on_new_webapp = on_new_webapp
        self._on_scan = on_scan

        self._all_apps: list[ManagedApp] = []
        self._active_filter: AppType | None = None
        self._search_text: str = ""
        self._pill_buttons: dict[AppType | None, QPushButton] = {}

        root = QVBoxLayout(self)
        root.setContentsMargins(16, 10, 16, 8)
        root.setSpacing(10)

        # Filter pills row
        pill_row = QHBoxLayout()
        pill_row.setSpacing(7)
        self._pill_group = QButtonGroup(self)
        self._pill_group.setExclusive(True)

        for ftype, label in self._FILTERS:
            btn = QPushButton(label)
            btn.setCheckable(True)
            btn.setProperty("pill", True)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            if ftype is None:
                btn.setChecked(True)
            btn.clicked.connect(lambda _checked=False, t=ftype: self.set_filter(t))
            self._pill_group.addButton(btn)
            pill_row.addWidget(btn)
            self._pill_buttons[ftype] = btn
        pill_row.addStretch(1)
        root.addLayout(pill_row)

        # Scrollable cards container
        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        self._list_host = QWidget()
        self._list_layout = QVBoxLayout(self._list_host)
        self._list_layout.setContentsMargins(0, 2, 4, 12)
        self._list_layout.setSpacing(8)
        self._list_layout.addStretch(1)

        self._scroll.setWidget(self._list_host)
        root.addWidget(self._scroll, stretch=1)

    def set_apps(self, apps: list[ManagedApp]) -> None:
        self._all_apps = list(apps)
        self._render()

    def set_filter(self, app_type: AppType | None) -> None:
        self._active_filter = app_type
        btn = self._pill_buttons.get(app_type)
        if btn is not None:
            btn.setChecked(True)
        self._render()

    def set_search(self, query: str) -> None:
        self._search_text = query.strip().lower()
        self._render()

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

    def _update_pill_counts(self) -> None:
        counts: dict[AppType | None, int] = {None: len(self._all_apps)}
        for t in AppType:
            counts[t] = sum(1 for a in self._all_apps if a.app_type == t)
        for ftype, label in self._FILTERS:
            self._pill_buttons[ftype].setText(f"{label} ({counts[ftype]})")

    def _clear_cards(self) -> None:
        while self._list_layout.count():
            item = self._list_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

    def _render(self) -> None:
        self._update_pill_counts()
        self._clear_cards()

        visible = self._filtered_apps()
        if not visible:
            self._render_empty_state()
            self._list_layout.addStretch(1)
            return

        for app in visible:
            card = AppCard(
                app=app,
                icon_provider=self._icon_provider,
                on_launch=self._on_launch,
                on_edit=self._on_edit,
                on_upgrade=self._on_upgrade,
                on_remove=self._on_remove,
                on_open_folder=self._on_open_folder,
            )
            self._list_layout.addWidget(card)
        self._list_layout.addStretch(1)

    def _render_empty_state(self) -> None:
        if self._all_apps:
            box = QWidget()
            v = QVBoxLayout(box)
            v.setContentsMargins(20, 60, 20, 20)
            v.setAlignment(Qt.AlignmentFlag.AlignCenter)
            lbl = QLabel("No hay aplicaciones que coincidan con tu búsqueda o filtro.")
            lbl.setStyleSheet("font-size: 14px; font-weight: 600;")
            v.addWidget(lbl, alignment=Qt.AlignmentFlag.AlignCenter)

            clear_btn = QPushButton("Limpiar filtros")
            clear_btn.setProperty("variant", "primary")
            clear_btn.clicked.connect(lambda: (self.set_filter(None), self.set_search("")))
            v.addWidget(clear_btn, alignment=Qt.AlignmentFlag.AlignCenter)
            self._list_layout.addWidget(box)
            return

        hero = QFrame()
        hero.setObjectName("HeroCard")
        hv = QVBoxLayout(hero)
        hv.setContentsMargins(32, 34, 32, 34)
        hv.setSpacing(12)

        title = QLabel("Arrastrá cualquier app aquí para integrarla en tu escritorio")
        title.setStyleSheet("font-size: 17px; font-weight: 700;")
        hv.addWidget(title)

        desc = QLabel(
            "DeskForge soporta AppImages, archivos .jar (con selector de JDK y memoria JVM), "
            "binarios portables ELF, scripts y WebApps.\n"
            "Soltá un archivo o URL sobre esta ventana, pegalo con Ctrl+V, o usá 'Abrir con DeskForge' desde Dolphin."
        )
        desc.setWordWrap(True)
        desc.setProperty("muted", True)
        hv.addWidget(desc)

        btn_row = QHBoxLayout()
        btn_row.setSpacing(10)

        btn_file = QPushButton("＋ Integrar archivo (.AppImage, .jar, binario...)")
        btn_file.setProperty("variant", "success")
        btn_file.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_file.clicked.connect(self._on_new_file)
        btn_row.addWidget(btn_file)

        btn_web = QPushButton("🌐 Agregar WebApp")
        btn_web.setProperty("variant", "primary")
        btn_web.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_web.clicked.connect(self._on_new_webapp)
        btn_row.addWidget(btn_web)

        btn_scan = QPushButton("🔎 Escanear Descargas / Importar .desktop")
        btn_scan.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_scan.clicked.connect(self._on_scan)
        btn_row.addWidget(btn_scan)

        btn_row.addStretch(1)
        hv.addSpacing(6)
        hv.addLayout(btn_row)

        wrapper = QWidget()
        wv = QVBoxLayout(wrapper)
        wv.setContentsMargins(24, 36, 24, 24)
        wv.addWidget(hero)
        self._list_layout.addWidget(wrapper)
