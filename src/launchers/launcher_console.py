#!/usr/bin/env python3
"""
Console Launcher for AIPromptBridge
This script is compiled as a Onefile executable (AIPromptBridge).
It launches the internal Nuitka Standalone executable (bin/AIPromptBridge_Internal.exe)
in Console mode (with console visible).
"""

import sys
import os
import subprocess

# Nuitka Configuration:
# (Moved to .github/workflows/manual_release.yml)

def which(program):
    """
    Minimal implementation of shutil.which to avoid importing shutil (and its dependencies).
    """
    def is_exe(fpath):
        return os.path.isfile(fpath) and os.access(fpath, os.X_OK)

    fpath, fname = os.path.split(program)
    if fpath:
        if is_exe(program):
            return program
    else:
        # Use PATH environment variable
        for path in os.environ.get("PATH", "").split(os.pathsep):
            path = path.strip('"')
            exe_file = os.path.join(path, program)
            if is_exe(exe_file):
                return exe_file
            # Check with .exe extension if not provided
            if not program.lower().endswith(".exe"):
                 exe_file_ext = os.path.join(path, program + ".exe")
                 if is_exe(exe_file_ext):
                     return exe_file_ext
    return None

def ensure_windows_terminal() -> bool:
    """
    Check if running in legacy Windows Console and relaunch in Windows Terminal if available.
    """
    # Only applies to Windows
    if sys.platform != 'win32':
        return False
    
    # Check if already running in Windows Terminal
    if os.environ.get("WT_SESSION"):
        return False
    
    # Check if Windows Terminal is installed
    wt_path = which("wt.exe")
    if not wt_path:
        return False
    
    # Prevent infinite relaunch loops
    if os.environ.get("AI_PROMPT_BRIDGE_WT_LAUNCHED"):
        return False
    
    print("🔄 Relaunching in Windows Terminal for full emoji support...")
    
    # Build the command to relaunch self
    args = sys.argv[1:]
    env = os.environ.copy()
    env["AI_PROMPT_BRIDGE_WT_LAUNCHED"] = "1"
    
    try:
        cmd = [wt_path, "-w", "0", "-d", os.getcwd()]
        
        # Determine self path
        if getattr(sys, 'frozen', False):
            # Compiled (Onefile): sys.argv[0] is usually the full path to the exe
            self_exe = sys.argv[0] 
            cmd.append(self_exe)
        else:
            # Script
            cmd.append(sys.executable)
            cmd.append(os.path.abspath(__file__))
            
        cmd.extend(args)
        
        subprocess.Popen(cmd, env=env, creationflags=subprocess.CREATE_NEW_PROCESS_GROUP)
        return True
        
    except Exception as e:
        print(f"⚠️  Failed to relaunch in Windows Terminal: {e}")
        return False

def main():
    # 1. Windows Terminal Check
    # If we relaunch, we exit this process.
    if ensure_windows_terminal():
        return

    # 2. Determine Root Directory
    if getattr(sys, 'frozen', False):
        try:
            root_dir = __compiled__.containing_dir
        except NameError:
            root_dir = os.path.dirname(sys.argv[0])
    else:
        root_dir = os.path.dirname(os.path.abspath(__file__))

    # 3. Construct path to internal executable
    internal_exe = os.path.join(root_dir, "bin", "AIPromptBridge_Internal.exe")
    
    # 4. Validation
    if not os.path.exists(internal_exe):
        # Fallback for dev environment
        main_py = os.path.join(root_dir, "main.py")
        if os.path.exists(main_py):
            print(f"Internal executable not found at: {internal_exe}")
            print("Assuming development mode, running main.py...")
            subprocess.call([sys.executable, "main.py", "--launched-mode=console"] + sys.argv[1:])
            return

        print(f"❌ Critical Error: Could not find application binary at:\n{internal_exe}")
        input("Press Enter to exit...")
        sys.exit(1)

    # 5. Prepare Arguments
    # --launched-mode=console tells main.py to behave in console mode
    cmd_args = [str(internal_exe), "--launched-mode=console"] + sys.argv[1:]
    
    # 6. Launch (Blocking)
    # We use subprocess.call (or run) because we want this launcher to stay alive 
    # It's safer to block until child exits.
    
    try:
        subprocess.call(cmd_args)
    except Exception as e:
        print(f"❌ Failed to launch application: {e}")
        input("Press Enter to exit...")
        sys.exit(1)

if __name__ == "__main__":
    main()
