"""Reusable PySide6 (Qt 6) UI widgets, native SVG/theme icon cache, and async workers."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable
from urllib.parse import unquote, urlparse

from PySide6.QtCore import QObject, QRunnable, QSize, Qt, QThreadPool, QTimer, QUrl, Signal
from PySide6.QtGui import QColor, QFont, QIcon, QPainter, QPainterPath, QPen, QPixmap
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from deskforge.domain.models import AppType
from deskforge.infrastructure.icon_store import IconStore
from deskforge.ui.theme import monogram_color_for_type


def extract_targets_from_urls(urls: list[QUrl]) -> list[str]:
    """Convert dropped Qt QUrl objects into local filesystem paths or http(s) URLs."""
    targets: list[str] = []
    for url in urls:
        if url.isLocalFile():
            local = url.toLocalFile()
            if local and Path(local).exists():
                targets.append(local)
        else:
            raw = url.toString().strip()
            if raw.startswith(("http://", "https://")):
                targets.append(raw)
    return targets


def extract_target_from_text(raw: str) -> str | None:
    """Parse pasted clipboard text (file:// URI, local path, or https:// URL)."""
    text = (raw or "").strip()
    if not text:
        return None
    first = next((line.strip() for line in text.splitlines() if line.strip()), "")
    if not first:
        return None
    if first.startswith("file://"):
        decoded = unquote(urlparse(first).path)
        return decoded if Path(decoded).exists() else None
    if first.startswith(("http://", "https://")):
        return first
    expanded = Path(first).expanduser()
    if expanded.is_file():
        return str(expanded.resolve())
    return None


class IconProvider:
    """
    Loads and caches crisp QPixmaps for PNG, JPG, ICO, SVG, AND system icon theme names
    (via QIcon.fromTheme), with anti-aliased rounded monogram fallbacks.
    """

    def __init__(self, icon_store: IconStore) -> None:
        self._icon_store = icon_store
        self._cache: dict[tuple[str, int, str, str], QPixmap] = {}

    def invalidate(self) -> None:
        self._cache.clear()

    def get_pixmap(
        self,
        icon_path: str,
        size: int = 48,
        app_name: str = "D",
        app_type: AppType = AppType.BINARY,
    ) -> QPixmap:
        key = (icon_path or "", size, (app_name[:1] or "D").upper(), app_type.value)
        cached = self._cache.get(key)
        if cached is not None:
            return cached

        pm = self._load_pixmap(icon_path, size)
        if pm is None or pm.isNull():
            pm = self._make_monogram_pixmap(app_name, size, app_type)

        self._cache[key] = pm
        return pm

    def get_qicon(
        self,
        icon_path: str,
        size: int = 48,
        app_name: str = "D",
        app_type: AppType = AppType.BINARY,
    ) -> QIcon:
        return QIcon(self.get_pixmap(icon_path, size=size, app_name=app_name, app_type=app_type))

    def _load_pixmap(self, icon_path: str, size: int) -> QPixmap | None:
        raw = (icon_path or "").strip()
        if not raw:
            return None

        # 1. System icon theme name (e.g. "steam", "utilities-terminal", "org.mozilla.firefox")
        if "/" not in raw and "\\" not in raw and not Path(raw).exists():
            theme_icon = QIcon.fromTheme(raw)
            if not theme_icon.isNull():
                pm = theme_icon.pixmap(QSize(size, size))
                if not pm.isNull():
                    return pm
            return None

        path = Path(raw).expanduser()
        if not path.is_file():
            return None

        # 2. Direct Qt load (natively supports PNG, JPG, WEBP, ICO, and SVG with QtSvg)
        icon = QIcon(str(path))
        if not icon.isNull():
            pm = icon.pixmap(QSize(size, size))
            if not pm.isNull():
                return pm

        # 3. Fallback SVG rasterizer via IconStore if QtSvg plugin is absent
        if path.suffix.lower() == ".svg":
            rasterized = self._icon_store.rasterize_svg(path, size=max(size * 2, 64))
            if rasterized and rasterized.is_file():
                pm = QPixmap(str(rasterized))
                if not pm.isNull():
                    return pm.scaled(size, size, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)

        pm = QPixmap(str(path))
        if not pm.isNull():
            return pm.scaled(size, size, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
        return None

    @staticmethod
    def _make_monogram_pixmap(name: str, size: int, app_type: AppType) -> QPixmap:
        pm = QPixmap(size, size)
        pm.fill(Qt.GlobalColor.transparent)

        painter = QPainter(pm)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

        r, g, b = monogram_color_for_type(app_type)
        margin = 2
        radius = size * 0.24
        path = QPainterPath()
        path.addRoundedRect(margin, margin, size - margin * 2, size - margin * 2, radius, radius)
        painter.fillPath(path, QColor(r, g, b))

        pen = QPen(QColor(255, 255, 255, 70))
        pen.setWidthF(1.5)
        painter.setPen(pen)
        painter.drawPath(path)

        letter = (name.strip()[:1] or "D").upper()
        font = QFont("Sans", max(10, int(size * 0.42)), QFont.Weight.Bold)
        painter.setFont(font)
        painter.setPen(QColor(255, 255, 255, 240))
        painter.drawText(pm.rect(), Qt.AlignmentFlag.AlignCenter, letter)
        painter.end()
        return pm


class _WorkerSignals(QObject):
    finished = Signal(object)
    error = Signal(Exception)


class _BackgroundRunnable(QRunnable):
    def __init__(self, fn: Callable[[], Any]) -> None:
        super().__init__()
        self._fn = fn
        self.signals = _WorkerSignals()

    def run(self) -> None:
        try:
            res = self._fn()
        except Exception as exc:
            self.signals.error.emit(exc)
            return
        self.signals.finished.emit(res)


def run_async(
    parent: QObject,
    fn: Callable[[], Any],
    on_done: Callable[[Any], None],
    on_error: Callable[[Exception], None] | None = None,
) -> None:
    """Run blocking IO/inspection on Qt's global thread pool and deliver results safely on the UI thread."""
    runnable = _BackgroundRunnable(fn)
    runnable.signals.finished.connect(on_done)
    if on_error is not None:
        runnable.signals.error.connect(on_error)
    # Attach reference to parent until completion to prevent premature GC of signals
    active_list = getattr(parent, "_active_workers", None)
    if active_list is None:
        active_list = []
        setattr(parent, "_active_workers", active_list)
    active_list.append(runnable)

    def _cleanup(*_args: Any) -> None:
        try:
            active_list.remove(runnable)
        except ValueError:
            pass

    runnable.signals.finished.connect(_cleanup)
    runnable.signals.error.connect(_cleanup)
    QThreadPool.globalInstance().start(runnable)


class ToastBanner(QFrame):
    """Non-blocking floating corner notification banner."""

    _STYLES = {
        "success": ("#168a57", "#ffffff"),
        "info": ("#0d7490", "#ffffff"),
        "warning": ("#b45309", "#ffffff"),
        "danger": ("#c82333", "#ffffff"),
    }

    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent)
        self.setObjectName("ToastBanner")
        self.hide()

        layout = QHBoxLayout(self)
        layout.setContentsMargins(14, 10, 10, 10)
        layout.setSpacing(10)

        self._label = QLabel("")
        self._label.setWordWrap(True)
        self._label.setMaximumWidth(380)
        layout.addWidget(self._label)

        close_btn = QPushButton("✕")
        close_btn.setFixedSize(24, 24)
        close_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        close_btn.setStyleSheet(
            "QPushButton { background: transparent; border: none; color: #ffffff; font-weight: bold; padding: 0; }"
            "QPushButton:hover { background: rgba(255,255,255,0.2); border-radius: 12px; }"
        )
        close_btn.clicked.connect(self.hide)
        layout.addWidget(close_btn)

        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self.hide)

    def show_message(self, message: str, kind: str = "success", duration_ms: int = 3500) -> None:
        bg, fg = self._STYLES.get(kind, self._STYLES["info"])
        self.setStyleSheet(f"QFrame#ToastBanner {{ background-color: {bg}; border-radius: 10px; }}")
        self._label.setStyleSheet(f"color: {fg}; font-weight: 600; background: transparent;")
        self._label.setText(message)
        self.adjustSize()
        self.reposition()
        self.show()
        self.raise_()
        self._timer.start(duration_ms)

    def reposition(self) -> None:
        parent = self.parentWidget()
        if parent is None:
            return
        self.adjustSize()
        margin_x = 18
        margin_y = 44
        x = max(12, parent.width() - self.width() - margin_x)
        y = max(12, parent.height() - self.height() - margin_y)
        self.move(x, y)


class DropOverlay(QFrame):
    """Visual overlay shown when dragging files or URLs over the DeskForge window."""

    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent)
        self.setObjectName("DropOverlay")
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.hide()

        layout = QVBoxLayout(self)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.setSpacing(8)

        title = QLabel("⬇  Soltá el archivo o URL aquí")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title.setStyleSheet("color: #ffffff; font-size: 20px; font-weight: 700; background: transparent;")
        subtitle = QLabel("AppImage · .jar (Java) · Binario ELF · Script · URL de WebApp")
        subtitle.setAlignment(Qt.AlignmentFlag.AlignCenter)
        subtitle.setStyleSheet("color: #9cebe3; font-size: 13px; background: transparent;")
        layout.addWidget(title)
        layout.addWidget(subtitle)

    def sync_geometry(self) -> None:
        parent = self.parentWidget()
        if parent is None:
            return
        margin = 18
        self.setGeometry(margin, margin, max(100, parent.width() - margin * 2), max(100, parent.height() - margin * 2))


class ConfirmActionDialog(QDialog):
    """Clean modal confirmation dialog with an optional checkbox."""

    def __init__(
        self,
        parent: QWidget,
        title: str,
        message: str,
        confirm_text: str = "Confirmar",
        confirm_variant: str = "danger-solid",
        checkbox_text: str | None = None,
        checkbox_default: bool = False,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setMinimumWidth(440)
        self.setModal(True)
        self._checkbox: QCheckBox | None = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 18, 20, 18)
        layout.setSpacing(12)

        hdr = QLabel(title)
        hdr.setStyleSheet("font-size: 15px; font-weight: 700;")
        layout.addWidget(hdr)

        body = QLabel(message)
        body.setWordWrap(True)
        body.setProperty("muted", True)
        layout.addWidget(body)

        if checkbox_text:
            self._checkbox = QCheckBox(checkbox_text)
            self._checkbox.setChecked(checkbox_default)
            layout.addWidget(self._checkbox)

        btn_row = QHBoxLayout()
        btn_row.addStretch(1)
        cancel_btn = QPushButton("Cancelar")
        cancel_btn.clicked.connect(self.reject)
        btn_row.addWidget(cancel_btn)

        confirm_btn = QPushButton(confirm_text)
        confirm_btn.setProperty("variant", confirm_variant)
        confirm_btn.setDefault(True)
        confirm_btn.clicked.connect(self.accept)
        btn_row.addWidget(confirm_btn)
        layout.addLayout(btn_row)

    @property
    def checkbox_checked(self) -> bool:
        return self._checkbox.isChecked() if self._checkbox is not None else False
