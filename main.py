"""Windows 11 taskbar tray widget that displays GitHub Copilot quota.

Usage
-----
Run directly with Python::

    python main.py

Or as a compiled executable built with PyInstaller (see ``build.spec``).

The first time you run the app, right-click the tray icon and choose
**Set API Key** to enter your GitHub OAuth token (``gho_...``).
"""

import logging
import os
import sys
import threading
import tkinter as tk
from typing import Optional

import pystray
from PIL import Image, ImageDraw, ImageFont

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

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
APP_NAME = cfg_module.APP_NAME
UPDATE_INTERVAL = 300  # seconds between automatic refreshes
ICON_SIZE = (64, 64)
_DIALOG_FOCUS_DELAY_MS = 150  # ms to wait before grab_set; allows window to render

# Windows registry key for startup programs
_STARTUP_KEY = r"SOFTWARE\Microsoft\Windows\CurrentVersion\Run"


# ---------------------------------------------------------------------------
# Icon helpers
# ---------------------------------------------------------------------------

def _make_icon(text: str) -> Image.Image:
    """Render *text* onto a small RGBA image suitable as a tray icon."""
    img = Image.new("RGBA", ICON_SIZE, (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    # Try Windows system font; fall back to built-in bitmap font
    font: ImageFont.ImageFont | ImageFont.FreeTypeFont
    for font_name in ("segoeui.ttf", "arial.ttf", "DejaVuSans.ttf"):
        try:
            font = ImageFont.truetype(font_name, 11)
            break
        except (IOError, OSError):
            pass
    else:
        font = ImageFont.load_default()

    # Centre the text inside the icon
    bbox = draw.textbbox((0, 0), text, font=font)
    tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
    x = max(0, (ICON_SIZE[0] - tw) // 2)
    y = max(0, (ICON_SIZE[1] - th) // 2)
    draw.text((x, y), text, fill=(255, 255, 255, 255), font=font)
    return img


def _make_placeholder_icon() -> Image.Image:
    """Solid blue square used before the first quota fetch completes."""
    img = Image.new("RGBA", ICON_SIZE, (0, 120, 212, 255))
    return img


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
    """Show an input dialog that reliably supports clipboard shortcuts.

    ``simpledialog.askstring`` may lose Ctrl-C / Ctrl-V bindings when
    called from a *pystray* callback thread on Windows.  This lightweight
    replacement explicitly binds the standard clipboard virtual events so
    that copy, paste, cut and select-all always work.
    """

    result: list[Optional[str]] = [None]

    logger.debug("[_ask_string] Creating Tk root window (title=%r)", title)
    root = tk.Tk()
    root.title(title)
    root.attributes("-topmost", True)
    root.resizable(False, False)

    logger.debug("[_ask_string] Building UI elements")
    tk.Label(root, text=prompt).pack(padx=20, pady=(20, 5))

    entry = tk.Entry(root, width=50)
    entry.pack(padx=20, pady=5)

    # Explicitly bind clipboard / selection shortcuts
    entry.bind("<Control-v>", lambda e: (e.widget.event_generate("<<Paste>>"), "break")[-1])
    entry.bind("<Control-V>", lambda e: (e.widget.event_generate("<<Paste>>"), "break")[-1])
    entry.bind("<Control-c>", lambda e: (e.widget.event_generate("<<Copy>>"), "break")[-1])
    entry.bind("<Control-C>", lambda e: (e.widget.event_generate("<<Copy>>"), "break")[-1])
    entry.bind("<Control-x>", lambda e: (e.widget.event_generate("<<Cut>>"), "break")[-1])
    entry.bind("<Control-X>", lambda e: (e.widget.event_generate("<<Cut>>"), "break")[-1])
    entry.bind("<Control-a>", lambda e: (e.widget.select_range(0, tk.END), "break")[-1])
    entry.bind("<Control-A>", lambda e: (e.widget.select_range(0, tk.END), "break")[-1])

    def _on_ok(_event: object = None) -> None:
        result[0] = entry.get()
        logger.debug("[_ask_string] OK pressed, value length=%d", len(result[0] or ""))
        root.destroy()

    def _on_cancel(_event: object = None) -> None:
        logger.debug("[_ask_string] Cancel/close pressed")
        root.destroy()

    btn_frame = tk.Frame(root)
    btn_frame.pack(pady=(5, 20))
    tk.Button(btn_frame, text="OK", command=_on_ok, width=10).pack(side=tk.LEFT, padx=5)
    tk.Button(btn_frame, text="Cancel", command=_on_cancel, width=10).pack(side=tk.LEFT, padx=5)

    entry.bind("<Return>", _on_ok)
    root.bind("<Escape>", _on_cancel)
    root.protocol("WM_DELETE_WINDOW", _on_cancel)

    # Delay grab_set and focus until the window is fully rendered.
    # Calling grab_set() immediately can block keyboard/mouse input when
    # the dialog is created from a pystray callback thread on Windows.
    def _delayed_focus() -> None:
        logger.debug("[_ask_string] Running delayed focus / grab_set")
        try:
            root.lift()
            root.focus_force()
            entry.focus_set()
            root.grab_set()
            logger.debug("[_ask_string] grab_set succeeded")
        except tk.TclError as exc:
            logger.warning("[_ask_string] grab_set failed: %s", exc)

    root.after(_DIALOG_FOCUS_DELAY_MS, _delayed_focus)

    logger.debug("[_ask_string] Entering mainloop")
    root.mainloop()
    logger.debug(
        "[_ask_string] mainloop exited, result=%s",
        "set" if result[0] is not None else "None",
    )

    return result[0]


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
        self._quota_text: str = "..."
        self._icon: Optional[pystray.Icon] = None
        self._running = False
        self._stop_event = threading.Event()

    # ------------------------------------------------------------------
    # Quota helpers
    # ------------------------------------------------------------------

    def _quota_display(self) -> str:
        return self._quota_text

    def _tooltip(self) -> str:
        return f"Copilot Left  {self._quota_text}"

    def _refresh_icon(self) -> None:
        if self._icon is not None:
            self._icon.icon = _make_icon(self._quota_text)
            self._icon.title = self._tooltip()

    def _do_update(self) -> None:
        """Fetch quota and update the tray icon."""
        key = self._config.get("api_key", "")
        if not key:
            self._quota_text = "No key"
        else:
            used, total = api.fetch_quota(key)
            if used is not None and total is not None:
                # Format: omit decimals when usage is a whole number
                used_str = f"{used:.1f}" if used != int(used) else str(int(used))
                self._quota_text = f"{used_str}/{total}"
            else:
                self._quota_text = "Error"
        self._refresh_icon()

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
        logger.debug("[_on_set_api_key] Opening API key dialog")
        key = _ask_string(
            "Set API Key",
            "Enter your GitHub Copilot token (starts with gho_):",
        )

        if key is None:
            logger.debug("[_on_set_api_key] User cancelled the dialog")
            return
        key = key.strip()
        logger.debug(
            "[_on_set_api_key] Key entered, length=%d, starts_with_gho=%s",
            len(key),
            key.startswith("gho_"),
        )
        if not key.startswith("gho_"):
            logger.debug("[_on_set_api_key] Invalid key, showing error dialog")
            _show_error(
                "Invalid Token",
                "The token must start with 'gho_'.\nPlease try again.",
            )
            return

        logger.debug("[_on_set_api_key] Saving key and triggering refresh")
        self._config["api_key"] = key
        cfg_module.save(self._config)
        threading.Thread(target=self._do_update, daemon=True).start()

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

        update_thread = threading.Thread(
            target=self._update_loop, daemon=True, name="quota-updater"
        )
        update_thread.start()

        menu = pystray.Menu(
            pystray.MenuItem("Refresh Now", self._on_refresh),
            pystray.MenuItem("Set API Key", self._on_set_api_key),
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
