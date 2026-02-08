#!/usr/bin/env python3
"""
Workspace Manager for AIPromptBridge
Handles file migration and CWD resolution for different deployment modes.
"""

import os
import sys
import shutil
import glob
from pathlib import Path

class WorkspaceManager:
    """
    Manages the application workspace, handling file migration between
    the root directory (Launcher mode) and the bin directory (Direct mode).
    """

    # Files managed by the workspace manager
    MANAGED_FILES = [
        "chat_sessions.json",
        "tools_config.json",
    ]
    
    # Glob patterns for managed files
    MANAGED_GLOBS = [
        "config.ini*",
        "prompts.json*",
        "*file_processor.json",
        ".file_processor_*.json"
    ]

    # Folders managed by the workspace manager
    MANAGED_FOLDERS = [
        "session_attachments"
    ]

    @staticmethod
    def initialize():
        """
        Initialize the workspace.
        
        1. Detects mode (Launcher vs Direct).
        2. Performs necessary file moves.
        3. Returns the target Current Working Directory (CWD).
        
        Returns:
            str: The target CWD that the application should switch to.
        """
        # Robust frozen detection
        # Nuitka usually set sys.frozen, but sometimes (e.g. some Nuitka configs)
        # it might be missing. We also check for .exe extension without 'python' in name.
        is_frozen = (
            getattr(sys, 'frozen', False) or
            (sys.executable.lower().endswith(".exe") and "python" not in os.path.basename(sys.executable).lower())
        )

        # Determine paths
        # Internal executable path (where we are running from right now)
        if is_frozen:
            # Nuitka Standalone / PyInstaller
            bin_dir = Path(sys.executable).parent
        else:
            # Development mode (src/../)
            bin_dir = Path(__file__).parent.parent
            
        root_dir = bin_dir.parent
        
        # Detect mode
        launched_mode = False
        for arg in sys.argv:
            if arg.startswith("--launched-mode"):
                launched_mode = True
                break
        
        target_cwd = None
        
        if launched_mode:
            # Launcher Mode: We want to operate in the Root directory
            # Files should be in Root, moved FROM bin if they exist there
            target_cwd = root_dir
            WorkspaceManager._migrate_files(source=bin_dir, dest=root_dir)
        else:
            # Direct Mode: We want to operate in the Bin directory (Self)
            # Files should be in Bin, moved FROM Root if they exist there
            # Exception: In development (not frozen), we typically stay in root
            if is_frozen:
                target_cwd = bin_dir
                WorkspaceManager._migrate_files(source=root_dir, dest=bin_dir)
            else:
                # Dev mode: Stay in project root (bin_dir is actually project root here)
                target_cwd = bin_dir
                # No migration needed in dev mode usually
        
        return str(target_cwd)

    @staticmethod
    def _migrate_files(source: Path, dest: Path):
        """
        Move managed files and folders from source to destination.
        
        Args:
            source: Source directory
            dest: Destination directory
        """
        if source == dest:
            return

        # Ensure destination exists
        dest.mkdir(parents=True, exist_ok=True)
        
        # 1. Move specific files
        for filename in WorkspaceManager.MANAGED_FILES:
            WorkspaceManager._move_item(source / filename, dest / filename)
            
        # 2. Move glob patterns
        for pattern in WorkspaceManager.MANAGED_GLOBS:
            for file_path in source.glob(pattern):
                WorkspaceManager._move_item(file_path, dest / file_path.name)
                
        # 3. Move folders
        for foldername in WorkspaceManager.MANAGED_FOLDERS:
            WorkspaceManager._move_item(source / foldername, dest / foldername)

    @staticmethod
    def _move_item(source_path: Path, dest_path: Path):
        """
        Move a single file or directory safely.
        """
        try:
            if not source_path.exists():
                return
            
            # If destination exists, we have a conflict.
            # Strategy: Source overwrites destination (most recent active state wins?)
            # The plan implies we move files to the active location.
            # If we simply move, shutil.move might fail if dest exists depending on OS/impl.
            
            if dest_path.exists():
                # Source overwrites Dest.
                
                if dest_path.is_dir():
                    shutil.rmtree(dest_path)
                else:
                    dest_path.unlink()
            
            shutil.move(str(source_path), str(dest_path))
            try:
                print(f"[Workspace] Migrated {source_path.name} to {dest_path.parent.name}")
            except Exception:
                pass
            
        except Exception as e:
            try:
                print(f"[Workspace] Failed to move {source_path.name}: {e}")
            except Exception:
                pass
