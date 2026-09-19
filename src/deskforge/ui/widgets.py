"""Reusable, Tk 9.0 & Pillow 12 safe UI widgets for DeskForge."""

from __future__ import annotations

from pathlib import Path
import tkinter as tk
from typing import Callable

from PIL import Image, ImageDraw, ImageTk
import ttkbootstrap as ttk

from deskforge.domain.models import AppType
from deskforge.infrastructure.icon_store import IconStore
from deskforge.ui.theme import monogram_color_for_type


def center_window(win: tk.Misc, width: int, height: int, parent: tk.Misc | None = None) -> None:
    """Center a window safely on single or multi-monitor setups without external dependencies."""
    win.update_idletasks()
    if parent is not None:
        try:
            px = parent.winfo_rootx()
            py = parent.winfo_rooty()
            pw = parent.winfo_width()
            ph = parent.winfo_height()
            x = max(0, px + (pw - width) // 2)
            y = max(0, py + (ph - height) // 2)
            win.geometry(f"{width}x{height}+{x}+{y}")
            return
        except tk.TclError:
            pass

    sw = win.winfo_screenwidth()
    sh = win.winfo_screenheight()
    x = max(0, (sw - width) // 2)
    y = max(0, (sh - height) // 2)
    win.geometry(f"{width}x{height}+{x}+{y}")


class IconCache:
    """
    Loads, resizes, and caches PhotoImage instances so Tk's garbage collector
    never drops active widget images. Supports PNG/JPG/ICO/SVG and generates crisp
    rounded monogram fallbacks when an icon cannot be loaded.
    """

    def __init__(self, icon_store: IconStore) -> None:
        self._icon_store = icon_store
        self._cache: dict[tuple[str, int, str, str], ImageTk.PhotoImage] = {}

    def get_icon(
        self,
        icon_path: str,
        size: int = 48,
        app_name: str = "A",
        app_type: AppType = AppType.BINARY,
    ) -> ImageTk.PhotoImage:
        key = (icon_path or "", size, app_name[:1].upper() or "A", app_type.value)
        if key in self._cache:
            return self._cache[key]

        pil_img = self._load_pil_image(icon_path, size)
        if pil_img is None:
            pil_img = self._make_monogram_icon(app_name, size, app_type)

        photo = ImageTk.PhotoImage(pil_img)
        self._cache[key] = photo
        return photo

    def invalidate(self) -> None:
        self._cache.clear()

    def _load_pil_image(self, icon_path: str, size: int) -> Image.Image | None:
        if not icon_path:
            return None
        p = Path(icon_path).expanduser()
        if not p.is_file():
            return None

        target_file: Path | None = p
        if p.suffix.lower() == ".svg":
            target_file = self._icon_store.rasterize_svg(p, size=max(size * 2, 64))
            if target_file is None:
                return None

        try:
            with Image.open(target_file) as img:
                rgba = img.convert("RGBA")
                rgba.thumbnail((size, size), Image.Resampling.LANCZOS)
                canvas = Image.new("RGBA", (size, size), (0, 0, 0, 0))
                offset = ((size - rgba.width) // 2, (size - rgba.height) // 2)
                canvas.paste(rgba, offset, rgba)
                return canvas
        except Exception:
            return None

    @staticmethod
    def _make_monogram_icon(name: str, size: int, app_type: AppType) -> Image.Image:
        s = size * 2
        img = Image.new("RGBA", (s, s), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)
        r, g, b = monogram_color_for_type(app_type)
        draw.rounded_rectangle([4, 4, s - 4, s - 4], radius=s // 4, fill=(r, g, b, 255))
        # Subtle inner ring for polish
        draw.rounded_rectangle([10, 10, s - 10, s - 10], radius=s // 5, outline=(255, 255, 255, 70), width=3)
        letter = (name.strip()[:1] or "D").upper()
        bbox = draw.textbbox((0, 0), letter)
        tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
        draw.text(((s - tw) / 2, (s - th) / 2 - 2), letter, fill=(255, 255, 255, 245))
        return img.resize((size, size), Image.Resampling.LANCZOS)


class ToastManager:
    """Displays clean, non-blocking toast notifications in the bottom-right corner."""

    def __init__(self, root: tk.Misc) -> None:
        self._root = root
        self._active_frame: ttk.Frame | None = None
        self._after_id: str | None = None

    def show(self, message: str, bootstyle: str = "success", duration_ms: int = 3500) -> None:
        self.dismiss()
        frame = ttk.Frame(self._root, bootstyle=bootstyle, padding=(14, 10))
        lbl = ttk.Label(
            frame,
            text=message,
            bootstyle=f"{bootstyle}-inverse",
            font=("Sans", 10, "bold"),
            wraplength=360,
        )
        lbl.pack(side="left")

        close_btn = ttk.Button(
            frame,
            text="✕",
            bootstyle=f"{bootstyle}-link",
            width=2,
            command=self.dismiss,
        )
        close_btn.pack(side="left", padx=(10, 0))

        frame.place(relx=0.98, rely=0.96, anchor="se")
        frame.lift()
        self._active_frame = frame
        self._after_id = self._root.after(duration_ms, self.dismiss)

    def dismiss(self) -> None:
        if self._after_id is not None:
            try:
                self._root.after_cancel(self._after_id)
            except tk.TclError:
                pass
            self._after_id = None
        if self._active_frame is not None:
            try:
                self._active_frame.destroy()
            except tk.TclError:
                pass
            self._active_frame = None


class ScrollableFrame(ttk.Frame):
    """Smooth vertical scrolling container with Linux X11/Wayland wheel support."""

    def __init__(self, master: tk.Misc, **kwargs) -> None:
        super().__init__(master, **kwargs)
        self.canvas = tk.Canvas(self, highlightthickness=0, bd=0)
        self.scrollbar = ttk.Scrollbar(self, orient="vertical", command=self.canvas.yview)
        self.inner = ttk.Frame(self.canvas)

        self._window_id = self.canvas.create_window((0, 0), window=self.inner, anchor="nw")
        self.canvas.configure(yscrollcommand=self.scrollbar.set)

        self.canvas.pack(side="left", fill="both", expand=True)
        self.scrollbar.pack(side="right", fill="y")

        self.inner.bind("<Configure>", self._on_inner_configure)
        self.canvas.bind("<Configure>", self._on_canvas_configure)
        self.bind("<Enter>", self._bind_wheel)
        self.bind("<Leave>", self._unbind_wheel)
        self.sync_canvas_bg()

    def sync_canvas_bg(self) -> None:
        """Keep the underlying tk.Canvas background matched to the current ttkbootstrap theme."""
        try:
            style = ttk.Style()
            bg = style.colors.bg
            self.canvas.configure(bg=bg)
        except Exception:
            pass

    def _on_inner_configure(self, _event=None) -> None:
        self.canvas.configure(scrollregion=self.canvas.bbox("all"))

    def _on_canvas_configure(self, event) -> None:
        self.canvas.itemconfigure(self._window_id, width=event.width)

    def _on_mousewheel(self, event) -> None:
        if getattr(event, "num", None) == 4:
            self.canvas.yview_scroll(-3, "units")
        elif getattr(event, "num", None) == 5:
            self.canvas.yview_scroll(3, "units")
        elif getattr(event, "delta", 0):
            step = -1 if event.delta > 0 else 1
            self.canvas.yview_scroll(step * 3, "units")

    def _bind_wheel(self, _event=None) -> None:
        self.canvas.bind_all("<Button-4>", self._on_mousewheel)
        self.canvas.bind_all("<Button-5>", self._on_mousewheel)
        self.canvas.bind_all("<MouseWheel>", self._on_mousewheel)

    def _unbind_wheel(self, _event=None) -> None:
        self.canvas.unbind_all("<Button-4>")
        self.canvas.unbind_all("<Button-5>")
        self.canvas.unbind_all("<MouseWheel>")


class ConfirmDialog(ttk.Toplevel):
    """Clean modal confirmation dialog with an optional checkbox."""

    def __init__(
        self,
        parent: tk.Misc,
        title: str,
        message: str,
        confirm_text: str = "Confirmar",
        confirm_style: str = "danger",
        checkbox_text: str | None = None,
        checkbox_default: bool = False,
    ) -> None:
        super().__init__(parent)
        self.title(title)
        self.resizable(False, False)
        self.confirmed = False
        self.checkbox_var = tk.BooleanVar(value=checkbox_default)

        container = ttk.Frame(self, padding=20)
        container.pack(fill="both", expand=True)

        ttk.Label(container, text=title, font=("Sans", 13, "bold")).pack(anchor="w")
        ttk.Label(container, text=message, wraplength=420, justify="left").pack(anchor="w", pady=(8, 12))

        if checkbox_text:
            ttk.Checkbutton(
                container,
                text=checkbox_text,
                variable=self.checkbox_var,
                bootstyle="round-toggle",
            ).pack(anchor="w", pady=(0, 14))

        btn_row = ttk.Frame(container)
        btn_row.pack(fill="x", pady=(6, 0))
        ttk.Button(btn_row, text="Cancelar", bootstyle="secondary-outline", command=self._cancel).pack(side="right")
        ttk.Button(btn_row, text=confirm_text, bootstyle=confirm_style, command=self._ok).pack(side="right", padx=(0, 8))

        self.bind("<Escape>", lambda _e: self._cancel())
        self.bind("<Return>", lambda _e: self._ok())

        self.transient(parent)
        self.update_idletasks()
        center_window(self, max(440, self.winfo_reqwidth()), max(175, self.winfo_reqheight()), parent)
        self.grab_set()
        self.wait_window(self)

    def _ok(self) -> None:
        self.confirmed = True
        self.destroy()

    def _cancel(self) -> None:
        self.confirmed = False
        self.destroy()


def run_in_background(
    widget: tk.Misc,
    worker: Callable[[], object],
    on_done: Callable[[object], None],
    on_error: Callable[[Exception], None] | None = None,
) -> None:
    """Execute blocking inspection/IO in a daemon thread and safely marshal results back to Tk."""
    import threading

    def _target() -> None:
        try:
            result = worker()
        except Exception as exc:
            if on_error:
                widget.after(0, lambda e=exc: on_error(e))
            return
        widget.after(0, lambda r=result: on_done(r))

    threading.Thread(target=_target, daemon=True).start()
