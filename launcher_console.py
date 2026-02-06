#!/usr/bin/env python3
"""
Console Launcher for AIPromptBridge
This script is compiled as a Onefile executable (AIPromptBridge-Console.exe).
It launches the internal Nuitka Standalone executable (bin/AIPromptBridge_Internal.exe)
in Console mode (with console visible).
"""

import sys
import os
import subprocess
import shutil
from pathlib import Path

# Nuitka Configuration:
# nuitka-project: --onefile
# nuitka-project: --windows-console-mode=force
# nuitka-project: --windows-icon-from-ico={MAIN_DIRECTORY}/icon.ico
# nuitka-project: --output-filename=AIPromptBridge-Console.exe

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
    wt_path = shutil.which("wt.exe")
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
            root_dir = Path(__compiled__.containing_dir)
        except NameError:
            root_dir = Path(sys.argv[0]).parent
    else:
        root_dir = Path(__file__).parent

    # 3. Construct path to internal executable
    internal_exe = root_dir / "bin" / "AIPromptBridge_Internal.exe"
    
    # 4. Validation
    if not internal_exe.exists():
        # Fallback for dev environment
        if (root_dir / "main.py").exists():
            print(f"Internal executable not found at: {internal_exe}")
            print("Assuming development mode, running main.py...")
            subprocess.call([sys.executable, "main.py", "--launched-mode=console", "--show-console"] + sys.argv[1:])
            return

        print(f"❌ Critical Error: Could not find application binary at:\n{internal_exe}")
        input("Press Enter to exit...")
        sys.exit(1)

    # 5. Prepare Arguments
    # --launched-mode=console tells main.py to behave in console mode
    # --show-console tells tray.py to show console on start
    cmd_args = [str(internal_exe), "--launched-mode=console", "--show-console"] + sys.argv[1:]
    
    # 6. Launch (Blocking)
    # We use subprocess.call (or run) because we want this launcher to stay alive 
    # as long as the internal app is running? 
    # Actually, in Onefile mode, if we block, we keep the onefile temp dir alive?
    # No, Onefile extracts, runs, then cleans up when process exits.
    # If we exit immediately, the console window might close if it was owned by THIS process.
    # But Internal.exe will attach to THIS console. 
    # If this process dies, the console (conhost/wt) might close if it has no other processes attached?
    # It's safer to block until child exits.
    
    try:
        subprocess.call(cmd_args)
    except Exception as e:
        print(f"❌ Failed to launch application: {e}")
        input("Press Enter to exit...")
        sys.exit(1)

if __name__ == "__main__":
    main()
