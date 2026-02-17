"""
Startup Manager for AIPromptBridge

Handles Windows startup registration via registry (HKEY_CURRENT_USER).
Supports both launcher types:
- AIPromptBridge.exe (console mode)
- AIPromptBridge-NoConsole.exe (GUI mode)
"""

import os
import sys
import winreg
from typing import Optional


# Registry key path
RUN_KEY_PATH = r"Software\Microsoft\Windows\CurrentVersion\Run"

# App name for startup registry
APP_NAME = "AIPromptBridge"


def get_launcher_path() -> Optional[str]:
    """
    Get the path to the appropriate launcher executable.
    
    Returns:
        Path to AIPromptBridge.exe or AIPromptBridge-NoConsole.exe,
        or None if running in development mode (no launchers found).
    """
    # Check if we're in compiled mode (frozen)
    if getattr(sys, 'frozen', False):
        # Running as compiled executable - find the launcher
        # In production, the launcher is in the same directory as the internal exe
        root_dir = os.path.dirname(sys.executable)
        
        # Check for launchers based on launched mode
        for arg in sys.argv:
            if arg.startswith("--launched-mode="):
                mode = arg.split("=")[1]
                if mode == "console":
                    launcher = os.path.join(root_dir, "AIPromptBridge.exe")
                else:  # gui mode
                    launcher = os.path.join(root_dir, "AIPromptBridge-NoConsole.exe")
                
                if os.path.exists(launcher):
                    return launcher
                break
        
        # Fallback: try both launchers
        for name in ["AIPromptBridge.exe", "AIPromptBridge-NoConsole.exe"]:
            launcher = os.path.join(root_dir, name)
            if os.path.exists(launcher):
                return launcher
        
        return None
    else:
        # Development mode - look for launchers in launchers directory
        # Assume we're in src/ directory
        current_dir = os.getcwd()
        launchers_dir = os.path.join(current_dir, "src", "launchers")
        
        # Check launched mode
        for arg in sys.argv:
            if arg.startswith("--launched-mode="):
                mode = arg.split("=")[1]
                if mode == "console":
                    launcher = os.path.join(launchers_dir, "AIPromptBridge.exe")
                else:  # gui mode
                    launcher = os.path.join(launchers_dir, "AIPromptBridge-NoConsole.exe")
                
                # In dev mode, we might not have compiled launchers
                # Try to use the launcher script instead
                if not os.path.exists(launcher):
                    if mode == "console":
                        launcher = os.path.join(launchers_dir, "launcher_console.py")
                    else:
                        launcher = os.path.join(launchers_dir, "launcher_gui.py")
                
                if os.path.exists(launcher):
                    return launcher
                break
        
        return None


def is_startup_enabled() -> bool:
    """
    Check if the application is set to run at Windows startup.
    
    Returns:
        True if startup is enabled, False otherwise.
    """
    try:
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY_PATH, 0, winreg.KEY_READ)
        try:
            value, _ = winreg.QueryValueEx(key, APP_NAME)
            winreg.CloseKey(key)
            return bool(value)
        except FileNotFoundError:
            winreg.CloseKey(key)
            return False
    except Exception:
        return False


def set_startup(enabled: bool) -> tuple[bool, str]:
    """
    Enable or disable startup for the application.
    
    Args:
        enabled: True to enable startup, False to disable.
    
    Returns:
        Tuple of (success: bool, message: str)
    """
    try:
        launcher_path = get_launcher_path()
        
        if launcher_path is None:
            return False, "Could not determine launcher path. Are you running in development mode without compiled launchers?"
        
        # Get absolute path
        launcher_path = os.path.abspath(launcher_path)
        
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY_PATH, 0, winreg.KEY_SET_VALUE)
        
        try:
            if enabled:
                # Set the value with quotes to handle paths with spaces
                winreg.SetValueEx(key, APP_NAME, 0, winreg.REG_SZ, f'"{launcher_path}"')
                winreg.CloseKey(key)
                return True, f"Added to startup: {APP_NAME}"
            else:
                try:
                    winreg.DeleteValue(key, APP_NAME)
                    winreg.CloseKey(key)
                    return True, f"Removed from startup: {APP_NAME}"
                except FileNotFoundError:
                    winreg.CloseKey(key)
                    return True, f"Startup entry not found (already disabled)"
        except Exception:
            winreg.CloseKey(key)
            raise
        
    except PermissionError:
        return False, "Permission denied. Try running as Administrator if HKCU is restricted."
    except Exception as e:
        return False, f"Error: {e}"


def get_startup_info() -> dict:
    """
    Get current startup configuration info.
    
    Returns:
        Dict with 'enabled' (bool), 'path' (str or None), 'mode' (str or None)
    """
    info = {
        "enabled": is_startup_enabled(),
        "path": None,
        "mode": None
    }
    
    # Determine current mode from command line
    for arg in sys.argv:
        if arg.startswith("--launched-mode="):
            info["mode"] = arg.split("=")[1]
            break
    
    # Try to get the launcher path
    launcher = get_launcher_path()
    if launcher:
        info["path"] = launcher
    
    return info
