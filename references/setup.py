#!/usr/bin/env python3
"""
cx_Freeze setup script for AIPromptBridge
Creates a standalone Windows executable with console window (can be hidden/shown via tray)

Build commands:
    python setup.py build        # Build executable
    python setup.py bdist_msi    # Build MSI installer (Windows)

Output:
    build/exe.win-amd64-3.x/     # Executable folder
"""

import sys
import os
import shutil
from pathlib import Path
import customtkinter
from cx_Freeze import setup, Executable
from cx_Freeze.command.build_exe import build_exe

# ─── Custom Build Command ─────────────────────────────────────────────────────

class CustomBuildExe(build_exe):
    """Custom build_exe command to clean up unnecessary Tcl/Tk files"""
    
    def run(self):
        # Run the standard build process
        super().run()
        
        # Cleanup Tcl/Tk directories
        self._cleanup_tcl_tk()
    
    def _cleanup_tcl_tk(self):
        print("Cleaning up unnecessary Tcl/Tk files...")
        build_dir = self.build_exe
        share_dir = os.path.join(build_dir, "share")
        
        if not os.path.exists(share_dir):
            return

        # List of paths to remove relative to share/
        # Note: Versions (tcl8.6) might change, so we walk or use wildcards if needed,
        # but hardcoding current version is safer for now.
        paths_to_remove = [
            os.path.join(share_dir, "tcl8", "tcl8.6", "tzdata"), # Timezone data
            os.path.join(share_dir, "tcl8", "tcl8.6", "msgs"),   # Tcl messages
            os.path.join(share_dir, "tk8.6", "demos"),           # Tk demos
            os.path.join(share_dir, "tk8.6", "msgs"),            # Tk messages
            os.path.join(share_dir, "tk8.6", "images"),          # Tk images
        ]
        
        for path in paths_to_remove:
            if os.path.exists(path):
                print(f"  Removing: {path}")
                try:
                    shutil.rmtree(path)
                except Exception as e:
                    print(f"  Warning: Failed to remove {path}: {e}")

# ─── Build Options ────────────────────────────────────────────────────────────

# Dependencies are automatically detected, but we need to fine-tune
build_exe_options = {
    # Packages to include
    "packages": [
        "flask",
        "requests",
        "pynput",
        "pyperclip",
        "darkdetect",
        "tkinter",
        "customtkinter",
        "emoji",
        "PIL",
        "json",
        "threading",
        "logging",
        "rich",
        "infi.systray",
    ],
    
    # Modules to exclude (reduce size)
    "excludes": [
        "unittest",
        "test",
        "tests",
        "numpy",
        "pandas",
        "scipy",
        "matplotlib",
        "cv2",
        "email",
        "xml.dom",
        "xmlrpc",
        "curses",
    ],
    
    # Files to include
    "include_files": [
        ("icon.ico", "icon.ico"),
        (os.path.dirname(customtkinter.__file__), "lib/customtkinter"),
        # Emoji assets for color emoji support in GUI
        ("assets/emojis.zip", "assets/emojis.zip"),
        ("assets/snip.wav", "assets/snip.wav"),
        # Note: config.ini is generated on first run if not exists
    ],
    
    # Optimize bytecode
    "optimize": 2,
    
    # Include all source files in a zip (cleaner output)
    "zip_include_packages": ["*"],
    "zip_exclude_packages": ["customtkinter", "emoji"],
}

# ─── Executable Configuration ─────────────────────────────────────────────────

# Use "console" base to keep the console window (can be hidden/shown via tray)
# This is different from "gui" which has no console at all
base = "console"

executables = [
    Executable(
        script="main.py",
        base=base,
        target_name="AIPromptBridge.exe",
        icon="icon.ico",
        copyright="AIPromptBridge",
        # Windows-specific options
        shortcut_name="AIPromptBridge",
        shortcut_dir="DesktopFolder",
    )
]

# ─── Setup ────────────────────────────────────────────────────────────────────

setup(
    name="AIPromptBridge",
    version="3.2.0",
    description="Multi-modal System-wide AI Integration",
    author="AIPromptBridge",
    options={"build_exe": build_exe_options},
    executables=executables,
    cmdclass={"build_exe": CustomBuildExe},
)