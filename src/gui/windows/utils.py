#!/usr/bin/env python3
"""
Utility functions for window management.

Provides:
- get_icon_path(): Find the application icon
- set_window_icon(): Set window icon with CTk override handling
- set_dark_titlebar(): Force dark titlebar on Windows 10/11
"""

import os
import sys

# Nuitka injects __compiled__ into every compiled module's globals().
from ...utils import is_compiled


def get_icon_path():
    """Get the path to the application icon."""
    # Handle compiled state (Nuitka/PyInstaller)
    if is_compiled():
        base_dir = os.path.dirname(sys.executable)
        icon_path = os.path.join(base_dir, "icon.ico")
        if os.path.exists(icon_path):
            return icon_path

    # Development mode
    base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
    icon_path = os.path.join(base_dir, "icon.ico")
    if os.path.exists(icon_path):
        return icon_path
    return None


def set_window_icon(window, delay_ms: int = 100):
    """
    Set the window icon to the AIPromptBridge icon.
    
    For CustomTkinter windows, the icon must be set AFTER the window
    is fully initialized, because CTk overrides the icon during setup.
    We use multiple after() calls to ensuring the icon persists.
    
    Args:
        window: The Tk/CTk window
        delay_ms: Initial delay (deprecated, kept for compatibility)
    """
    icon_path = get_icon_path()
    if icon_path and sys.platform == "win32":
        def _set_icon():
            try:
                if window.winfo_exists():
                    window.iconbitmap(icon_path)
            except Exception:
                pass  # Icon setting may fail on some systems

        # Use multiple after() calls to override CTk defaults and race conditions
        try:
            window.after(50, _set_icon)
            window.after(150, _set_icon)
            window.after(300, _set_icon)
            window.after(500, _set_icon)  # Extra check for slower systems/frozen starts
        except Exception:
            pass


def set_dark_titlebar(window):
    """
    Force dark titlebar on Windows 10/11 using DWM API (synchronous).
    
    Call AFTER the window is created but BEFORE deiconify/show.
    Requires the window to have been withdrawn first so the HWND can be
    created via update_idletasks() without showing a white flash.
    
    Typical pattern::
    
        modal = ctk.CTkToplevel(parent)
        modal.withdraw()           # hide before DWM is applied
        set_dark_titlebar(modal)   # applies DWM synchronously
        modal.geometry(...)        # position while hidden
        modal.deiconify()          # show with dark titlebar
    
    Args:
        window: The Tk/CTk window (should be withdrawn)
    """
    if sys.platform != "win32":
        return
    try:
        import ctypes
        # Force HWND creation without mapping to screen
        window.update_idletasks()
        hwnd = ctypes.windll.user32.GetParent(window.winfo_id())
        # DWMWA_USE_IMMERSIVE_DARK_MODE = 20 (Windows 10 20H1+, Windows 11)
        DWMWA_USE_IMMERSIVE_DARK_MODE = 20
        value = ctypes.c_int(1)
        ctypes.windll.dwmapi.DwmSetWindowAttribute(
            hwnd, DWMWA_USE_IMMERSIVE_DARK_MODE,
            ctypes.byref(value), ctypes.sizeof(value)
        )
    except Exception:
        pass
