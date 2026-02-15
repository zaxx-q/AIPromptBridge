#!/usr/bin/env python3
"""
GUI Launcher for AIPromptBridge
This script is compiled as a Onefile executable (AIPromptBridge-NoConsole.exe).
It launches the internal Nuitka Standalone executable (bin/AIPromptBridge_Internal.exe)
in GUI mode (no console).
"""

import sys
import os
import subprocess

# Nuitka Configuration:
# (Moved to .github/workflows/manual_release.yml)

def main():
    # 1. Determine Root Directory (where this launcher resides)
    if getattr(sys, 'frozen', False):
        # In Onefile mode, sys.executable is the temp path, but we need the original location
        # Nuitka provides __compiled__.containing_dir for this
        try:
            root_dir = __compiled__.containing_dir
        except NameError:
             # Fallback if __compiled__ is not available (e.g. PyInstaller)
            root_dir = os.path.dirname(sys.argv[0])
    else:
        # Development mode
        root_dir = os.path.dirname(os.path.abspath(__file__))

    # 2. Construct path to internal executable
    internal_exe = os.path.join(root_dir, "bin", "AIPromptBridge_Internal.exe")
    
    # 3. Validation
    if not os.path.exists(internal_exe):
        # Fallback for dev environment (running from source)
        main_py = os.path.join(root_dir, "main.py")
        if os.path.exists(main_py):
            # We are likely in source, so run main.py
            # But in production, this script is compiled.
            # If we are testing this script as python launcher_gui.py:
            print(f"Internal executable not found at: {internal_exe}")
            print("Assuming development mode, running main.py...")
            subprocess.Popen([sys.executable, "main.py", "--launched-mode=gui"] + sys.argv[1:])
            return

        # Simple exit on error to avoid ctypes dependency
        sys.exit(1)

    # 4. Prepare Arguments
    # Pass through original arguments, prepend our mode flag
    cmd_args = [str(internal_exe), "--launched-mode=gui"] + sys.argv[1:]
    
    # 5. Launch
    try:
        # DETACHED_PROCESS = 0x00000008
        # CREATE_NEW_PROCESS_GROUP = 0x00000200
        # CREATE_NO_WINDOW = 0x08000000
        
        # We want to launch it without a window (since it's now a Console subsystem app)
        # and ensure it's detached from any group.
        # We also need to redirect stdio to DEVNULL to prevents crashes on write when no console exists.
        creation_flags = subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.CREATE_NO_WINDOW
        
        subprocess.Popen(
            cmd_args,
            creationflags=creation_flags,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL
        )
    except Exception as e:
        # Simple exit on error to avoid ctypes dependency
        sys.exit(1)

if __name__ == "__main__":
    main()
