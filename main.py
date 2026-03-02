"""System-tray app that displays GitHub Copilot premium-request quota.

The tray icon colour changes continuously from green (plenty left) to
red (almost exhausted).  Hovering over the icon shows "used / total".

A small desktop-embedded overlay also appears on the wallpaper layer
(behind desktop icons) showing the quota at a glance.

Right-click the tray icon to log in, refresh, or quit.
"""

import logging
import os
import sys
import threading
import tkinter as tk
import webbrowser
from typing import Optional, Tuple

import ctypes
import ctypes.wintypes

import pystray
from PIL import Image, ImageDraw

import api
import config as cfg_module

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
APP_NAME = cfg_module.APP_NAME
UPDATE_INTERVAL = 300  # seconds between automatic refreshes
ICON_SIZE = (64, 64)
_DIALOG_FOCUS_DELAY_MS = 150

# Desktop overlay dimensions
OVERLAY_WIDTH = 170
OVERLAY_HEIGHT = 52
OVERLAY_MARGIN = 24          # px from screen edge
OVERLAY_TASKBAR_GAP = 56     # px above bottom (taskbar ~48 px on Win 11)
_TRANSPARENT_KEY = "#010101" # colour used for click-through transparency

# Windows registry key for startup programs
_STARTUP_KEY = r"SOFTWARE\Microsoft\Windows\CurrentVersion\Run"


# ---------------------------------------------------------------------------
# Icon helpers
# ---------------------------------------------------------------------------

def _lerp_colour(pct: float) -> Tuple[int, int, int]:
    """Return an (R, G, B) colour for a 0-100 *percent remaining* value.

    100 % → green  (56, 193, 114)
     50 % → yellow (234, 179,  8)
      0 % → red    (239,  68,  68)
    """
    pct = max(0.0, min(100.0, pct))
    if pct >= 50:
        t = (pct - 50) / 50          # 1 at 100 %, 0 at 50 %
        r = int(234 + (56 - 234) * t)
        g = int(179 + (193 - 179) * t)
        b = int(8 + (114 - 8) * t)
    else:
        t = pct / 50                  # 1 at 50 %, 0 at 0 %
        r = int(239 + (234 - 239) * t)
        g = int(68 + (179 - 68) * t)
        b = int(68 + (8 - 68) * t)
    return (r, g, b)


def _make_icon(pct_remaining: float) -> Image.Image:
    """Draw a filled circle whose colour reflects *pct_remaining*."""
    colour = _lerp_colour(pct_remaining)
    img = Image.new("RGBA", ICON_SIZE, (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    margin = 4
    draw.ellipse(
        [margin, margin, ICON_SIZE[0] - margin, ICON_SIZE[1] - margin],
        fill=(*colour, 255),
    )
    return img


def _make_placeholder_icon() -> Image.Image:
    """Grey circle shown before the first quota fetch."""
    img = Image.new("RGBA", ICON_SIZE, (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    margin = 4
    draw.ellipse(
        [margin, margin, ICON_SIZE[0] - margin, ICON_SIZE[1] - margin],
        fill=(128, 128, 128, 255),
    )
    return img


# ---------------------------------------------------------------------------
# Desktop overlay (embedded in the wallpaper layer)
# ---------------------------------------------------------------------------

class DesktopOverlay:
    """A small widget embedded in the Windows desktop wallpaper layer.

    It sits *behind* desktop icons, so it never intercepts clicks.
    The WorkerW reparenting trick is the same approach that Rainmeter uses.
    """

    def __init__(self) -> None:
        self._thread: Optional[threading.Thread] = None
        self._root: Optional[tk.Tk] = None
        self._canvas: Optional[tk.Canvas] = None
        self._ready = threading.Event()
        # Shared state -------------------------------------------------------
        self._lock = threading.Lock()
        self._used: Optional[float] = None
        self._total: Optional[int] = None
        self._pct: float = 100.0
        self._dirty = True  # draw at least once

    # ------------------------------------------------------------------
    # Public API (called from any thread)
    # ------------------------------------------------------------------

    def start(self) -> None:
        self._thread = threading.Thread(
            target=self._run, daemon=True, name="desktop-overlay"
        )
        self._thread.start()
        self._ready.wait(timeout=5)

    def update_data(
        self,
        used: Optional[float],
        total: Optional[int],
        pct_remaining: float,
    ) -> None:
        with self._lock:
            self._used = used
            self._total = total
            self._pct = pct_remaining
            self._dirty = True

    # ------------------------------------------------------------------
    # Tk thread
    # ------------------------------------------------------------------

    def _run(self) -> None:
        root = tk.Tk()
        root.overrideredirect(True)
        root.attributes("-topmost", False)

        w, h = OVERLAY_WIDTH, OVERLAY_HEIGHT
        screen_w = root.winfo_screenwidth()
        screen_h = root.winfo_screenheight()
        x = screen_w - w - OVERLAY_MARGIN
        y = screen_h - h - OVERLAY_TASKBAR_GAP
        root.geometry(f"{w}x{h}+{x}+{y}")

        # The "transparent" colour becomes fully see-through + click-through.
        root.attributes("-transparentcolor", _TRANSPARENT_KEY)
        root.config(bg=_TRANSPARENT_KEY)

        canvas = tk.Canvas(
            root, width=w, height=h,
            highlightthickness=0, bg=_TRANSPARENT_KEY,
        )
        canvas.pack(fill=tk.BOTH, expand=True)

        self._root = root
        self._canvas = canvas

        self._redraw()

        root.update()
        self._embed_in_desktop()

        self._ready.set()
        self._poll()
        root.mainloop()

    def _poll(self) -> None:
        """Periodically check whether new data has arrived."""
        with self._lock:
            dirty = self._dirty
            self._dirty = False
        if dirty:
            self._redraw()
        if self._root:
            self._root.after(1000, self._poll)

    # ------------------------------------------------------------------
    # Drawing
    # ------------------------------------------------------------------

    def _redraw(self) -> None:
        if not self._canvas:
            return
        canvas = self._canvas
        canvas.delete("all")

        with self._lock:
            used, total, pct = self._used, self._total, self._pct

        w, h = OVERLAY_WIDTH, OVERLAY_HEIGHT
        r = 12  # corner radius

        colour = _lerp_colour(pct)
        bg = f"#{colour[0]:02x}{colour[1]:02x}{colour[2]:02x}"

        # Rounded rectangle
        self._round_rect(canvas, 0, 0, w, h, r, fill=bg, outline="")

        # Text
        if used is not None and total is not None:
            text = f"{int(used)} / {total}"
        else:
            text = "\u2014"  # em-dash

        canvas.create_text(
            w // 2, h // 2 - 9,
            text="\u26A1 Copilot",
            fill="white", font=("Segoe UI", 9, "bold"),
        )
        canvas.create_text(
            w // 2, h // 2 + 10,
            text=text,
            fill="white", font=("Segoe UI", 12, "bold"),
        )

    @staticmethod
    def _round_rect(
        canvas: tk.Canvas,
        x1: int, y1: int, x2: int, y2: int,
        r: int, **kwargs,
    ) -> None:
        """Draw a rounded rectangle on *canvas*."""
        points = [
            x1 + r, y1,  x2 - r, y1,
            x2, y1,  x2, y1 + r,
            x2, y2 - r,  x2, y2,
            x2 - r, y2,  x1 + r, y2,
            x1, y2,  x1, y2 - r,
            x1, y1 + r,  x1, y1,
        ]
        canvas.create_polygon(points, smooth=True, **kwargs)

    # ------------------------------------------------------------------
    # Desktop embedding (Windows-specific)
    # ------------------------------------------------------------------

    def _embed_in_desktop(self) -> None:
        """Reparent the overlay into the desktop wallpaper layer."""
        if sys.platform != "win32":
            return
        try:
            user32 = ctypes.windll.user32

            hwnd = self._get_hwnd()
            if not hwnd:
                logger.warning("Could not obtain overlay HWND.")
                return

            # Ask Explorer to create the WorkerW behind the icon list
            progman = user32.FindWindowW("Progman", None)
            if not progman:
                logger.warning("Progman window not found.")
                return

            result = ctypes.c_ulong()
            user32.SendMessageTimeoutW(
                progman, 0x052C, 0xD, 0x1,
                0x0, 1000, ctypes.byref(result),
            )

            worker_w = self._find_worker_w()
            if not worker_w:
                logger.info("WorkerW not found; using click-through fallback.")
                self._make_click_through(hwnd)
                return

            user32.SetParent(hwnd, worker_w)

            # Reposition inside the new parent
            w, h = OVERLAY_WIDTH, OVERLAY_HEIGHT
            screen_w = user32.GetSystemMetrics(0)  # SM_CXSCREEN
            screen_h = user32.GetSystemMetrics(1)  # SM_CYSCREEN
            x = screen_w - w - OVERLAY_MARGIN
            y = screen_h - h - OVERLAY_TASKBAR_GAP
            user32.MoveWindow(hwnd, x, y, w, h, True)

            logger.info("Overlay embedded in desktop (WorkerW).")

        except Exception as exc:
            logger.warning("Failed to embed overlay: %s", exc)

    def _get_hwnd(self) -> int:
        """Return the Win32 window handle for the tkinter root."""
        if not self._root:
            return 0
        inner = self._root.winfo_id()
        return ctypes.windll.user32.GetAncestor(inner, 2)  # GA_ROOT

    @staticmethod
    def _find_worker_w() -> int:
        """Find the WorkerW window that sits behind desktop icons."""
        user32 = ctypes.windll.user32
        found = [0]

        @ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.wintypes.HWND, ctypes.wintypes.LPARAM)
        def _cb(hwnd, _lparam):
            if user32.FindWindowExW(hwnd, 0, "SHELLDLL_DefView", None):
                found[0] = user32.FindWindowExW(0, hwnd, "WorkerW", None)
            return True

        user32.EnumWindows(_cb, 0)
        return found[0]

    @staticmethod
    def _make_click_through(hwnd: int) -> None:
        """Fallback: transparent + click-through + bottom z-order."""
        user32 = ctypes.windll.user32
        GWL_EXSTYLE = -20
        WS_EX_LAYERED = 0x00080000
        WS_EX_TRANSPARENT = 0x00000020
        WS_EX_TOOLWINDOW = 0x00000080

        style = user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
        style |= WS_EX_LAYERED | WS_EX_TRANSPARENT | WS_EX_TOOLWINDOW
        user32.SetWindowLongW(hwnd, GWL_EXSTYLE, style)

        HWND_BOTTOM = 1
        SWP_NOMOVE = 0x0002
        SWP_NOSIZE = 0x0001
        SWP_NOACTIVATE = 0x0010
        user32.SetWindowPos(
            hwnd, HWND_BOTTOM, 0, 0, 0, 0,
            SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE,
        )


# ---------------------------------------------------------------------------
# Auto-start (Windows registry)
# ---------------------------------------------------------------------------

def _set_autostart(enabled: bool) -> None:
    """Enable or disable launching this app on Windows login."""
    # Only attempt on Windows
    if sys.platform != "win32":
        logger.info("Auto-start is only supported on Windows.")
        return
    try:
        import winreg  # pylint: disable=import-outside-toplevel

        key = winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            _STARTUP_KEY,
            0,
            winreg.KEY_SET_VALUE,
        )
        if enabled:
            exe = sys.executable
            script = os.path.abspath(__file__)
            winreg.SetValueEx(
                key, APP_NAME, 0, winreg.REG_SZ, f'"{exe}" "{script}"'
            )
            logger.info("Auto-start enabled.")
        else:
            try:
                winreg.DeleteValue(key, APP_NAME)
                logger.info("Auto-start disabled.")
            except FileNotFoundError:
                pass
        winreg.CloseKey(key)
    except Exception as exc:  # pylint: disable=broad-except
        logger.warning("Failed to update registry for auto-start: %s", exc)


# ---------------------------------------------------------------------------
# Custom dialog (supports Ctrl+C / Ctrl+V in pystray callbacks)
# ---------------------------------------------------------------------------

def _ask_string(title: str, prompt: str) -> Optional[str]:
    """Show a simple input dialog in a **separate process**.

    Tk windows created from a pystray background thread on Windows cannot
    receive keyboard input (the cursor blinks but key-presses are lost).
    Spawning a dedicated Python process ensures Tk runs on that process's
    main thread, so typing and clipboard shortcuts work normally.
    """
    import json
    import subprocess

    script = (
        "import tkinter as tk, json, sys\n"
        f"title = {json.dumps(title)}\n"
        f"prompt = {json.dumps(prompt)}\n"
        "result = None\n"
        "root = tk.Tk()\n"
        "root.title(title)\n"
        "root.attributes('-topmost', True)\n"
        "root.resizable(False, False)\n"
        "tk.Label(root, text=prompt).pack(padx=20, pady=(20, 5))\n"
        "entry = tk.Entry(root, width=50)\n"
        "entry.pack(padx=20, pady=5)\n"
        "def on_ok(e=None):\n"
        "    global result; result = entry.get(); root.destroy()\n"
        "def on_cancel(e=None):\n"
        "    root.destroy()\n"
        "f = tk.Frame(root); f.pack(pady=(5, 20))\n"
        "tk.Button(f, text='OK', command=on_ok, width=10).pack(side=tk.LEFT, padx=5)\n"
        "tk.Button(f, text='Cancel', command=on_cancel, width=10).pack(side=tk.LEFT, padx=5)\n"
        "entry.bind('<Return>', on_ok)\n"
        "root.bind('<Escape>', on_cancel)\n"
        "root.protocol('WM_DELETE_WINDOW', on_cancel)\n"
        "root.after(150, lambda: (root.lift(), root.focus_force(), entry.focus_set()))\n"
        "root.mainloop()\n"
        "print(json.dumps(result))\n"
    )

    try:
        proc = subprocess.run(
            [sys.executable, "-c", script],
            capture_output=True,
            text=True,
            timeout=300,
        )
        import json as _json
        value = _json.loads(proc.stdout.strip())
        return value  # str or None
    except Exception as exc:
        logger.warning("Input dialog subprocess failed: %s", exc)
        return None


def _show_error(title: str, message: str) -> None:
    """Show a modal error dialog that is guaranteed to be closable.

    ``messagebox.showerror`` can hang when invoked from a *pystray*
    callback thread on Windows because the underlying Tk instance
    has no running event loop.  This helper creates a self-contained
    Tk window with its own ``mainloop`` so it always responds to
    keyboard and mouse events.
    """
    logger.debug("[_show_error] Creating error dialog (title=%r)", title)
    root = tk.Tk()
    root.title(title)
    root.attributes("-topmost", True)
    root.resizable(False, False)

    tk.Label(root, text=message, justify=tk.LEFT).pack(padx=20, pady=(20, 10))

    def _on_ok(_event: object = None) -> None:
        logger.debug("[_show_error] OK / close pressed")
        root.destroy()

    tk.Button(root, text="OK", command=_on_ok, width=10).pack(pady=(5, 20))
    root.bind("<Return>", _on_ok)
    root.bind("<Escape>", _on_ok)
    root.protocol("WM_DELETE_WINDOW", _on_ok)

    def _delayed_focus() -> None:
        logger.debug("[_show_error] Running delayed focus / grab_set")
        try:
            root.lift()
            root.focus_force()
            root.grab_set()
            logger.debug("[_show_error] grab_set succeeded")
        except tk.TclError as exc:
            logger.warning("[_show_error] grab_set failed: %s", exc)

    root.after(_DIALOG_FOCUS_DELAY_MS, _delayed_focus)

    logger.debug("[_show_error] Entering mainloop")
    root.mainloop()
    logger.debug("[_show_error] mainloop exited")


# ---------------------------------------------------------------------------
# Main application class
# ---------------------------------------------------------------------------

class CopilotTrayApp:
    """System-tray application that periodically shows Copilot quota."""

    def __init__(self) -> None:
        self._config = cfg_module.load()
        self._used: Optional[float] = None
        self._total: Optional[int] = None
        self._pct_remaining: float = 100.0
        self._icon: Optional[pystray.Icon] = None
        self._overlay = DesktopOverlay()
        self._running = False
        self._stop_event = threading.Event()

    # ------------------------------------------------------------------
    # Quota helpers
    # ------------------------------------------------------------------

    def _tooltip(self) -> str:
        if self._used is None or self._total is None:
            return APP_NAME
        used_int = int(self._used)
        return f"{used_int}/{self._total}"

    def _refresh_icon(self) -> None:
        if self._icon is not None:
            self._icon.icon = _make_icon(self._pct_remaining)
            self._icon.title = self._tooltip()

    def _do_update(self) -> None:
        """Fetch quota and update the tray icon."""
        key = self._config.get("api_key", "")
        if not key:
            self._used = None
            self._total = None
            self._pct_remaining = 100.0
        else:
            used, total = api.fetch_quota(key)
            if used is not None and total is not None:
                self._used = used
                self._total = total
                self._pct_remaining = (
                    (total - used) / total * 100 if total else 0
                )
            else:
                self._used = None
                self._total = None
        self._refresh_icon()
        self._overlay.update_data(self._used, self._total, self._pct_remaining)

    def _update_loop(self) -> None:
        """Background thread: fetch quota, then wait UPDATE_INTERVAL seconds."""
        while not self._stop_event.is_set():
            try:
                self._do_update()
            except Exception as exc:  # pylint: disable=broad-except
                logger.exception("Unexpected error in update loop: %s", exc)
            # Block until the interval elapses or the stop event is signalled
            self._stop_event.wait(timeout=UPDATE_INTERVAL)

    # ------------------------------------------------------------------
    # Menu callbacks
    # ------------------------------------------------------------------

    def _on_refresh(self, _icon: pystray.Icon, _item: pystray.MenuItem) -> None:
        threading.Thread(target=self._do_update, daemon=True).start()

    def _on_set_api_key(
        self, _icon: pystray.Icon, _item: pystray.MenuItem
    ) -> None:
        """Authenticate via GitHub Device Flow or manual token entry."""
        logger.debug("[_on_set_api_key] Starting Device Flow login")

        try:
            device_data = api.request_device_code()
        except Exception as exc:
            logger.warning("Device code request failed: %s", exc)
            # Fallback: ask for manual token
            self._manual_token_entry()
            return

        user_code = device_data.get("user_code", "")
        verification_uri = device_data.get("verification_uri", "https://github.com/login/device")
        device_code = device_data.get("device_code", "")
        poll_interval = device_data.get("interval", 5)

        # Copy user code to clipboard and open browser
        try:
            import subprocess as _sp
            _sp.Popen(["clip"], stdin=_sp.PIPE, shell=True).communicate(user_code.encode())
        except Exception:
            pass

        # Show instructions to user
        _show_error(
            "GitHub Login",
            f"1. A browser will open to:\n   {verification_uri}\n\n"
            f"2. Enter this code:\n   {user_code}\n\n"
            f"(Code copied to clipboard)\n\n"
            f"3. Click OK after you authorize.",
        )

        webbrowser.open(verification_uri)

        # Poll for token in background
        def _poll() -> None:
            token = api.poll_for_token(device_code, interval=poll_interval)
            if token:
                self._config["api_key"] = token
                cfg_module.save(self._config)
                logger.info("Token saved via Device Flow.")
                self._do_update()
            else:
                logger.warning("Device Flow: no token obtained.")

        threading.Thread(target=_poll, daemon=True).start()

    def _manual_token_entry(self) -> None:
        """Fallback: manual gho_ token entry."""
        key = _ask_string(
            "Set API Key",
            "Enter your GitHub Copilot token (gho_...):",
        )
        if key is None:
            return
        key = key.strip()
        if not key:
            return
        self._config["api_key"] = key
        cfg_module.save(self._config)
        threading.Thread(target=self._do_update, daemon=True).start()

    def _on_manual_token(
        self, _icon: pystray.Icon, _item: pystray.MenuItem
    ) -> None:
        self._manual_token_entry()

    def _on_toggle_autostart(
        self, _icon: pystray.Icon, _item: pystray.MenuItem
    ) -> None:
        self._config["auto_start"] = not self._config.get("auto_start", False)
        cfg_module.save(self._config)
        _set_autostart(self._config["auto_start"])

    def _autostart_checked(self, _item: pystray.MenuItem) -> bool:
        return bool(self._config.get("auto_start", False))

    def _on_quit(self, icon: pystray.Icon, _item: pystray.MenuItem) -> None:
        self._running = False
        self._stop_event.set()
        icon.stop()

    # ------------------------------------------------------------------
    # Entry point
    # ------------------------------------------------------------------

    def run(self) -> None:
        """Build the tray icon and enter the pystray event loop."""
        self._running = True

        # Start the desktop overlay (wallpaper layer widget)
        self._overlay.start()

        update_thread = threading.Thread(
            target=self._update_loop, daemon=True, name="quota-updater"
        )
        update_thread.start()

        menu = pystray.Menu(
            pystray.MenuItem("Refresh Now", self._on_refresh),
            pystray.MenuItem("Login with GitHub", self._on_set_api_key),
            pystray.MenuItem("Enter Token Manually", self._on_manual_token),
            pystray.MenuItem(
                "Start with Windows",
                self._on_toggle_autostart,
                checked=self._autostart_checked,
            ),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Quit", self._on_quit),
        )

        self._icon = pystray.Icon(
            APP_NAME,
            _make_placeholder_icon(),
            self._tooltip(),
            menu,
        )
        self._icon.run()


# ---------------------------------------------------------------------------
# Entry-point guard
# ---------------------------------------------------------------------------

def main() -> None:
    app = CopilotTrayApp()
    app.run()


if __name__ == "__main__":
    main()
