"""
Startup Manager for AIPromptBridge

Handles Windows startup registration via registry (HKEY_CURRENT_USER).
Supports robust detection of launchers in both Nuitka compiled builds (split structure)
and local development environments.
"""

import os
import sys
import winreg
from pathlib import Path
from typing import Optional, Tuple

# Nuitka injects __compiled__ into every compiled module's globals().
from .utils import is_compiled

# Registry key path
RUN_KEY_PATH = r"Software\Microsoft\Windows\CurrentVersion\Run"

# App name for startup registry
APP_NAME = "AIPromptBridge"


def get_launcher_path() -> Optional[str]:
    """
    Get the absolute path to the appropriate launcher executable.

    This handles the deployment structure where:
    - Root/
      - AIPromptBridge.exe (Console Launcher)
      - AIPromptBridge-NoConsole.exe (GUI Launcher)
      - bin/
        - AIPromptBridge_Internal.exe (This process, sys.executable)

    Returns:
        Path to the launcher executable (str) or None if not found.
    """
    # 1. Identify which launcher variant we prefer based on current mode
    preferred_launcher = "AIPromptBridge.exe"  # Default
    for arg in sys.argv:
        if arg.startswith("--launched-mode="):
            mode = arg.split("=")[1].strip().lower()
            if mode == "gui":
                preferred_launcher = "AIPromptBridge-NoConsole.exe"
            elif mode == "console":
                preferred_launcher = "AIPromptBridge.exe"
            break

    launchers_to_check = [preferred_launcher]
    # Add the other one as fallback
    if preferred_launcher == "AIPromptBridge.exe":
        launchers_to_check.append("AIPromptBridge-NoConsole.exe")
    else:
        launchers_to_check.append("AIPromptBridge.exe")

    # 2. Determine potential root directories
    search_roots = []

    if is_compiled():
        exe_path = Path(sys.executable).resolve()

        # PATH STRATEGY 1: Split Structure (bin/Internal.exe -> ../Launcher.exe)
        # This is the standard release structure
        if exe_path.parent.name.lower() == "bin":
            search_roots.append(exe_path.parent.parent)

        # PATH STRATEGY 2: Flat Structure (Internal.exe -> ./Launcher.exe)
        search_roots.append(exe_path.parent)

        # PATH STRATEGY 3: Main Module CWD override
        # main.py sets CWD to root_dir in setup_workspace()
        search_roots.append(Path.cwd())

    else:
        # Development Mode
        # Assuming struct: src/startup_manager.py -> src/launchers/
        current_file = Path(__file__).resolve()
        src_dir = current_file.parent.parent

        search_roots.append(src_dir / "src" / "launchers")
        search_roots.append(src_dir / "launchers")
        search_roots.append(Path.cwd() / "src" / "launchers")

    # 3. Scan for launchers
    for root in search_roots:
        if not root.exists():
            continue

        for launcher_name in launchers_to_check:
            candidate = root / launcher_name
            if candidate.is_file():
                return str(candidate.resolve())

    # 4. Dev Fallback: Return script path if no exe found
    # (Only in dev mode)
    if not is_compiled():
        for root in search_roots:
            if preferred_launcher == "AIPromptBridge-NoConsole.exe":
                candidate = root / "launcher_gui.py"
            else:
                candidate = root / "launcher_console.py"

            if candidate.is_file():
                # In dev, we can't really set registry run to a .py file easily
                # without python.exe, but we return it for info purposes.
                return str(candidate.resolve())

    return None


def is_startup_enabled() -> bool:
    """
    Check if the application is set to run at Windows startup.

    Returns:
        True if startup is enabled in registry, False otherwise.
    """
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY_PATH, 0, winreg.KEY_READ) as key:
            value, _ = winreg.QueryValueEx(key, APP_NAME)
            return bool(value)
    except FileNotFoundError:
        return False
    except Exception:
        return False


def set_startup(enabled: bool) -> Tuple[bool, str]:
    """
    Enable or disable startup for the application.

    Args:
        enabled: True to enable startup, False to disable.

    Returns:
        Tuple of (success: bool, message: str)
    """
    if sys.platform != "win32":
        return False, "Startup management is only available on Windows."

    try:
        if enabled:
            launcher_path = get_launcher_path()

            if not launcher_path:
                return (
                    False,
                    "Could not determine launcher path. This feature requires the application to be installed/compiled.",
                )

            # Use abspath to strictly ensure full path
            launcher_path = str(Path(launcher_path).resolve())

            # Check if it's a python script (Dev mode protection)
            if launcher_path.endswith(".py"):
                return False, "Cannot set startup in development mode (launcher is a .py script)."

            # Open key for writing
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY_PATH, 0, winreg.KEY_SET_VALUE) as key:
                # Add quotes around path to handle spaces
                cmd_line = f'"{launcher_path}"'
                winreg.SetValueEx(key, APP_NAME, 0, winreg.REG_SZ, cmd_line)
                return True, f"Added to startup: {APP_NAME}"

        else:
            # Disable
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY_PATH, 0, winreg.KEY_SET_VALUE) as key:
                try:
                    winreg.DeleteValue(key, APP_NAME)
                    return True, f"Removed from startup: {APP_NAME}"
                except FileNotFoundError:
                    return True, "Startup entry not found (already disabled)"

    except PermissionError:
        return False, "Permission denied. Try running as Administrator."
    except Exception as e:
        return False, f"Registry Error: {e!s}"


def get_startup_info() -> dict:
    """
    Get current startup configuration info.

    Returns:
        Dict with 'enabled' (bool), 'path' (str or None), 'mode' (str or None)
    """
    info = {"enabled": is_startup_enabled(), "path": None, "mode": "unknown"}

    # Determine current mode
    for arg in sys.argv:
        if arg.startswith("--launched-mode="):
            info["mode"] = arg.split("=")[1]
            break

    # Get detected launcher path
    info["path"] = get_launcher_path()

    return info
