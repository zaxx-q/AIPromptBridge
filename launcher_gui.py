#!/usr/bin/env python3
"""
GUI Launcher for AIPromptBridge
This script is compiled as a Onefile executable (AIPromptBridge.exe).
It launches the internal Nuitka Standalone executable (bin/AIPromptBridge_Internal.exe)
in GUI mode (no console).
"""

import sys
import os
import subprocess
from pathlib import Path

# Nuitka Configuration:
# (Moved to .github/workflows/manual_release.yml)

def main():
    # 1. Determine Root Directory (where this launcher resides)
    if getattr(sys, 'frozen', False):
        # In Onefile mode, sys.executable is the temp path, but we need the original location
        # Nuitka provides __compiled__.containing_dir for this
        try:
            root_dir = Path(__compiled__.containing_dir)
        except NameError:
             # Fallback if __compiled__ is not available (e.g. PyInstaller)
            root_dir = Path(sys.argv[0]).parent
    else:
        # Development mode
        root_dir = Path(__file__).parent

    # 2. Construct path to internal executable
    internal_exe = root_dir / "bin" / "AIPromptBridge_Internal.exe"
    
    # 3. Validation
    if not internal_exe.exists():
        # Fallback for dev environment (running from source)
        if (root_dir / "main.py").exists():
            # We are likely in source, so run main.py
            # But in production, this script is compiled. 
            # If we are testing this script as python launcher_gui.py:
            print(f"Internal executable not found at: {internal_exe}")
            print("Assuming development mode, running main.py...")
            subprocess.Popen([sys.executable, "main.py", "--launched-mode=gui"] + sys.argv[1:])
            return

        import ctypes
        ctypes.windll.user32.MessageBoxW(0, f"Critical Error: Could not find application binary at:\n{internal_exe}", "AIPromptBridge Error", 0x10)
        sys.exit(1)

    # 4. Prepare Arguments
    # Pass through original arguments, prepend our mode flag
    cmd_args = [str(internal_exe), "--launched-mode=gui"] + sys.argv[1:]
    
    # 5. Launch
    try:
        # DETACHED_PROCESS = 0x00000008
        # CREATE_NEW_PROCESS_GROUP = 0x00000200
        # We want to launch it without attaching a console, letting it manage itself.
        # Since this launcher has no console (--windows-console-mode=disable),
        # Popen should inherit that (no console).
        subprocess.Popen(cmd_args, creationflags=subprocess.CREATE_NEW_PROCESS_GROUP)
    except Exception as e:
        import ctypes
        ctypes.windll.user32.MessageBoxW(0, f"Failed to launch application:\n{e}", "AIPromptBridge Error", 0x10)
        sys.exit(1)

if __name__ == "__main__":
    main()
