"""Native X11 / XWayland XDND v5 Drop Target for Tkinter (compatible with Tcl/Tk 9.0!).

Uses the standard XDND v5 `XdndProxy` mechanism via `python-xlib`:
1. Creates a dedicated lightweight InputOnly proxy window owned by a background X11 Display.
2. Advertises `XdndAware=5` and `XdndProxy=<proxy_id>` on both the Tk top-level X11 window
   and the proxy window itself.
3. Receives `XdndEnter`, `XdndPosition`, `XdndLeave`, `XdndDrop`, and `SelectionNotify`
   directly on the proxy window without requiring a compiled `tkdnd` C extension!
4. Works natively on X11 and on Wayland desktops (KDE Plasma KWin, GNOME Mutter) via XWayland.
"""

from __future__ import annotations

from pathlib import Path
import queue
import select
import threading
import tkinter as tk
from typing import Any, Callable
from urllib.parse import unquote, urlparse


def parse_uri_list(payload: str) -> list[str]:
    """Parse a text/uri-list or plain text payload into local paths and http(s) URLs."""
    results: list[str] = []
    for raw_line in payload.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("file://"):
            parsed = urlparse(line)
            decoded = unquote(parsed.path)
            if decoded:
                results.append(decoded)
        elif line.startswith(("http://", "https://")):
            results.append(line)
        else:
            p = Path(line).expanduser()
            if p.exists():
                results.append(str(p.resolve()))
    return results


class XdndDropTarget:
    """Attaches a pure-Python XDND v5 drop target to any Tkinter top-level window on Linux/X11/XWayland."""

    PREFERRED_MIMES: tuple[str, ...] = (
        "text/uri-list",
        "text/plain;charset=utf-8",
        "UTF8_STRING",
        "text/plain",
        "STRING",
    )

    def __init__(
        self,
        tk_window: tk.Misc,
        on_drop: Callable[[list[str]], None],
        on_drag_enter: Callable[[], None] | None = None,
        on_drag_leave: Callable[[], None] | None = None,
    ) -> None:
        self._tk_window = tk_window
        self._on_drop = on_drop
        self._on_drag_enter = on_drag_enter
        self._on_drag_leave = on_drag_leave

        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._queue: queue.Queue[tuple[str, Any]] = queue.Queue()
        self._poll_after_id: str | None = None
        self._active = False
        self._target_window_id: int = 0
        self._proxy_window_id: int = 0

    @property
    def is_active(self) -> bool:
        return self._active

    @property
    def proxy_window_id(self) -> int:
        return self._proxy_window_id

    @property
    def target_window_id(self) -> int:
        return self._target_window_id

    def start(self) -> bool:
        """Start the XDND v5 listener thread. Returns True if enabled cleanly."""
        try:
            if self._tk_window.tk.call("tk", "windowingsystem") != "x11":
                return False
        except tk.TclError:
            return False

        try:
            from Xlib import X, Xatom, display  # noqa: F401
        except Exception:
            return False

        self._tk_window.update_idletasks()
        wid = self._tk_window.winfo_id()
        try:
            frame_id = int(self._tk_window.wm_frame(), 16)
        except Exception:
            frame_id = wid

        ready = threading.Event()
        started_ok = [False]

        def _runner() -> None:
            self._event_loop(wid, frame_id, ready, started_ok)

        self._thread = threading.Thread(target=_runner, name="deskforge-xdnd", daemon=True)
        self._thread.start()
        ready.wait(timeout=2.0)
        self._active = started_ok[0]
        if self._active:
            self._schedule_poll()
        return self._active

    def stop(self) -> None:
        """Stop the background X11 event loop and UI queue poller cleanly."""
        self._stop_event.set()
        self._active = False
        if self._poll_after_id is not None:
            try:
                self._tk_window.after_cancel(self._poll_after_id)
            except tk.TclError:
                pass
            self._poll_after_id = None
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=0.6)

    def _schedule_poll(self) -> None:
        if self._stop_event.is_set():
            return
        try:
            self._poll_after_id = self._tk_window.after(50, self._poll_queue)
        except tk.TclError:
            self._poll_after_id = None

    def _poll_queue(self) -> None:
        self._poll_after_id = None
        if self._stop_event.is_set():
            return
        try:
            while True:
                kind, payload = self._queue.get_nowait()
                if kind == "enter" and self._on_drag_enter:
                    self._on_drag_enter()
                elif kind == "leave" and self._on_drag_leave:
                    self._on_drag_leave()
                elif kind == "drop" and payload:
                    self._on_drop(payload)
        except queue.Empty:
            pass
        self._schedule_poll()

    def _event_loop(
        self,
        wid: int,
        frame_id: int,
        ready: threading.Event,
        started_ok: list[bool],
    ) -> None:
        from Xlib import X, Xatom, display, protocol

        disp = None
        proxy = None
        try:
            disp = display.Display()
            root = disp.screen().root

            # Intern XDND & MIME atoms
            xa_aware = disp.intern_atom("XdndAware")
            xa_proxy = disp.intern_atom("XdndProxy")
            xa_enter = disp.intern_atom("XdndEnter")
            xa_position = disp.intern_atom("XdndPosition")
            xa_status = disp.intern_atom("XdndStatus")
            xa_leave = disp.intern_atom("XdndLeave")
            xa_drop = disp.intern_atom("XdndDrop")
            xa_finished = disp.intern_atom("XdndFinished")
            xa_selection = disp.intern_atom("XdndSelection")
            xa_action_copy = disp.intern_atom("XdndActionCopy")
            xa_type_list = disp.intern_atom("XdndTypeList")
            xa_transfer = disp.intern_atom("DESKFORGE_XDND_DATA")
            preferred_atoms = [disp.intern_atom(m) for m in self.PREFERRED_MIMES]

            # Create invisible InputOnly proxy window owned by THIS X11 connection
            proxy = root.create_window(0, 0, 1, 1, 0, X.CopyFromParent, X.InputOnly)
            proxy.change_property(xa_aware, Xatom.ATOM, 32, [5])
            proxy.change_property(xa_proxy, Xatom.WINDOW, 32, [proxy.id])

            # Discover Tk's top-level X11 client window(s) (winfo_id, wm_frame, and Tk wrapper if present)
            attach_ids: list[int] = [wid]
            if frame_id and frame_id not in attach_ids:
                attach_ids.append(frame_id)

            client_base = wid & ~0x1FFFFF
            try:
                tk_win = disp.create_resource_object("window", wid)
                parent = tk_win.query_tree().parent
                if parent and parent.id != root.id and (parent.id & ~0x1FFFFF) == client_base:
                    if parent.id not in attach_ids:
                        attach_ids.append(parent.id)
            except Exception:
                pass

            # The outermost client window is what WM / XWayland sees as the drop target
            target_id = attach_ids[-1]
            self._target_window_id = target_id
            self._proxy_window_id = proxy.id

            for target_wid in attach_ids:
                try:
                    w = disp.create_resource_object("window", target_wid)
                    w.change_property(xa_aware, Xatom.ATOM, 32, [5])
                    w.change_property(xa_proxy, Xatom.WINDOW, 32, [proxy.id])
                except Exception:
                    continue

            disp.flush()
            started_ok[0] = True
            ready.set()

            current_source: int = 0
            chosen_type: int = preferred_atoms[0]
            drag_active = False

            def _send_client_message(dest_win_id: int, msg_type: int, data_longs: list[int]) -> None:
                padded = (data_longs + [0, 0, 0, 0, 0])[:5]
                dest = disp.create_resource_object("window", dest_win_id)
                ev = protocol.event.ClientMessage(
                    window=dest,
                    client_type=msg_type,
                    data=(32, padded),
                )
                dest.send_event(ev, event_mask=X.NoEventMask)
                disp.flush()

            def _pick_mime(offered: list[int]) -> int:
                for pref in preferred_atoms:
                    if pref in offered:
                        return pref
                return preferred_atoms[0]

            fd = disp.fileno()
            while not self._stop_event.is_set():
                if disp.pending_events() == 0:
                    rlist, _, _ = select.select([fd], [], [], 0.25)
                    if not rlist:
                        continue

                while disp.pending_events() > 0:
                    event = disp.next_event()

                    if event.type == X.ClientMessage:
                        ctype = event.client_type
                        vals = list(event.data[1])

                        if ctype == xa_enter:
                            current_source = vals[0]
                            more_than_3 = bool(vals[1] & 1)
                            offered = [a for a in vals[2:5] if a != 0]
                            if more_than_3 and current_source:
                                try:
                                    src_obj = disp.create_resource_object("window", current_source)
                                    prop = src_obj.get_full_property(xa_type_list, Xatom.ATOM)
                                    if prop and prop.value:
                                        offered = list(prop.value)
                                except Exception:
                                    pass
                            chosen_type = _pick_mime(offered)
                            if not drag_active:
                                drag_active = True
                                self._queue.put(("enter", None))

                        elif ctype == xa_position:
                            src_win = vals[0] or current_source
                            if not drag_active:
                                drag_active = True
                                self._queue.put(("enter", None))
                            if src_win:
                                _send_client_message(
                                    src_win,
                                    xa_status,
                                    [target_id, 1, 0, 0, xa_action_copy],
                                )

                        elif ctype == xa_leave:
                            current_source = 0
                            if drag_active:
                                drag_active = False
                                self._queue.put(("leave", None))

                        elif ctype == xa_drop:
                            src_win = vals[0] or current_source
                            timestamp = vals[2] or X.CurrentTime
                            current_source = src_win
                            if drag_active:
                                drag_active = False
                                self._queue.put(("leave", None))
                            proxy.convert_selection(xa_selection, chosen_type, xa_transfer, timestamp)
                            disp.flush()

                    elif event.type == X.SelectionNotify:
                        payload_text = ""
                        if event.property != X.NONE:
                            try:
                                prop = proxy.get_full_property(xa_transfer, X.AnyPropertyType, sizehint=65536)
                                if prop and prop.value is not None:
                                    raw_val = prop.value
                                    if isinstance(raw_val, bytes):
                                        payload_text = raw_val.decode("utf-8", errors="replace")
                                    elif isinstance(raw_val, str):
                                        payload_text = raw_val
                                    else:
                                        payload_text = bytes(raw_val).decode("utf-8", errors="replace")
                                proxy.delete_property(xa_transfer)
                            except Exception:
                                pass

                        if current_source:
                            try:
                                _send_client_message(
                                    current_source,
                                    xa_finished,
                                    [target_id, 1 if payload_text else 0, xa_action_copy, 0, 0],
                                )
                            except Exception:
                                pass
                            current_source = 0

                        targets = parse_uri_list(payload_text)
                        if targets:
                            self._queue.put(("drop", targets))
        except Exception:
            if not ready.is_set():
                ready.set()
        finally:
            if proxy is not None:
                try:
                    proxy.destroy()
                except Exception:
                    pass
            if disp is not None:
                try:
                    disp.close()
                except Exception:
                    pass
