"""
OS / session environment detection.

Kept free of GUI, audio, and provider imports so it is safe at early startup.
"""

from __future__ import annotations

import os
import sys


def is_windows() -> bool:
    """Return True when running on Windows."""
    return sys.platform == "win32"


def is_linux() -> bool:
    """Return True when running on Linux (including WSL kernel reports)."""
    return sys.platform.startswith("linux")


def is_wayland() -> bool:
    """
    Best-effort Wayland session detection.

    Checks XDG_SESSION_TYPE and WAYLAND_DISPLAY. Returns False on non-Linux.
    """
    if not is_linux():
        return False

    session_type = os.environ.get("XDG_SESSION_TYPE", "").strip().lower()
    if session_type == "wayland":
        return True
    if session_type == "x11":
        return False

    return bool(os.environ.get("WAYLAND_DISPLAY"))
