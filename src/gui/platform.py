#!/usr/bin/env python3
"""
Platform-specific GUI availability logic.
Centralizes the check for CustomTkinter availability and the force-fallback configuration.
"""

import sys
from pathlib import Path

# Nuitka injects __compiled__ into every compiled module's globals().
from ..utils import is_compiled


def _read_force_standard_tk() -> bool:
    """
    Read *only* the ui_force_standard_tk flag from config.ini.

    This runs at import time — potentially before setup_workspace() has fixed
    the CWD.  When launched from the Windows startup registry the CWD is
    typically C:\\Windows\\System32, so a simple relative-path check would fail
    and trigger a spurious "[Warning] Config file not found" from load_config().

    Instead we resolve the config path ourselves:
      - Compiled: config lives next to the *launcher*,
        which is the parent of the bin/ directory containing the executable.
      - Source (python main.py): config lives in the current working directory.
    """
    if is_compiled():
        # App is always deployed in split-build layout (launcher + bin/Internal.exe).
        # Internal.exe refuses to run without launcher args, so config is always
        # in the parent directory of the executable's folder.
        config_path = Path(sys.executable).resolve().parent.parent / "config.ini"
    else:
        config_path = Path("config.ini")

    if not config_path.is_file():
        return False  # default: don't force standard tk

    try:
        for line in config_path.read_text(encoding="utf-8").splitlines():
            stripped = line.strip().lower()
            if stripped.startswith("ui_force_standard_tk"):
                _, _, value = stripped.partition("=")
                return value.strip() in ("true", "1", "yes")
    except Exception:
        pass

    return False


_force_standard_tk = _read_force_standard_tk()

HAVE_CTK = False
ctk = None
CTkImage = None

if not _force_standard_tk:
    try:
        import customtkinter as ctk
        from customtkinter import CTkImage as _CTkImage

        HAVE_CTK = True
        CTkImage = _CTkImage

        # Increase CTk system theme update loop interval from 30ms (which spawns 33 gsettings/sec on Linux)
        # to 10000ms (10s) to eliminate idle CPU drain while still supporting system theme changes.
        try:
            ctk.AppearanceModeTracker.update_loop_interval = 10000
        except Exception:
            pass

        # Safe Linux default only (no temporary Tk — that races the real CTk root).
        # Full font probe runs in GUICoordinator / ensure_ctk_window_ready().
        if sys.platform.startswith("linux"):
            try:
                from .ctk_bootstrap import configure_ctk_rendering

                configure_ctk_rendering(root=None)
            except Exception:
                pass
    except ImportError:
        HAVE_CTK = False
        ctk = None
        CTkImage = None
else:
    # Forced fallback
    HAVE_CTK = False
    ctk = None
    CTkImage = None
