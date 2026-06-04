#!/usr/bin/env python3
"""
Console Launcher for AIPromptBridge
This script is compiled as a Onefile executable (AIPromptBridge).
It launches the internal Nuitka Standalone executable (bin/AIPromptBridge_Internal.exe)
in Console mode (with console visible).

Also handles self-update application (Phase 2):
  - Exit code 42 from Internal.exe → apply staged update and relaunch
  - --apply-update <PID> → wait for process exit, apply update, relaunch
"""

import json
import os
import shutil
import subprocess
import sys
import time

# ─── Update Constants ──────────────────────────────────────────────────────────

UPDATE_EXIT_CODE = 42
MANIFEST_FILE = "_update_pending.json"
STAGING_DIR = "_update_staging"
BACKUP_DIR = "_bin_old"

# Allowlist of root-level files/dirs to update from staging
ROOT_UPDATE_ALLOWLIST = [
    "AIPromptBridge.exe",
    "AIPromptBridge-NoConsole.exe",
    "python313.dll",
    "lib",
    "frozen_application_license.txt",
]

# Nuitka Configuration:
# (Moved to .github/workflows/manual_release.yml)


# ─── Update Functions (stdlib only) ────────────────────────────────────────────

def cleanup_old_files(root_dir):
    """Remove .old files left by a previous update. Called at launcher startup."""
    for name in ROOT_UPDATE_ALLOWLIST:
        old_path = os.path.join(root_dir, name + ".old")
        try:
            if os.path.isdir(old_path):
                shutil.rmtree(old_path)
            elif os.path.isfile(old_path):
                os.remove(old_path)
        except OSError:
            pass  # Still locked, will try next launch


def wait_for_process_exit(pid, timeout=30):
    """Wait for a process to exit (cross-platform, stdlib only)."""
    if sys.platform == "win32":
        # Use ctypes to wait on the process handle
        try:
            import ctypes
            kernel32 = ctypes.windll.kernel32
            SYNCHRONIZE = 0x00100000
            WAIT_TIMEOUT = 0x00000102
            handle = kernel32.OpenProcess(SYNCHRONIZE, False, pid)
            if handle:
                # Wait up to timeout seconds (timeout in milliseconds)
                kernel32.WaitForSingleObject(handle, timeout * 1000)
                kernel32.CloseHandle(handle)
            else:
                # Process may already be gone
                time.sleep(2)
        except Exception:
            # Fallback: poll
            for _ in range(timeout * 2):
                try:
                    os.kill(pid, 0)  # Check if process exists
                    time.sleep(0.5)
                except OSError:
                    break  # Process is gone
    else:
        # Linux/Mac: poll with os.kill
        for _ in range(timeout * 2):
            try:
                os.kill(pid, 0)
                time.sleep(0.5)
            except OSError:
                break


def update_root_files(root_dir, staging_dir):
    """Update root-level application files from staging."""
    for name in ROOT_UPDATE_ALLOWLIST:
        staging_path = os.path.join(staging_dir, name)
        target_path = os.path.join(root_dir, name)

        if not os.path.exists(staging_path):
            continue  # Not in this release, skip

        if sys.platform == "win32":
            # Windows: cannot delete running exe/dll, but CAN rename it
            if os.path.exists(target_path):
                old_path = target_path + ".old"
                try:
                    if os.path.exists(old_path):
                        # Previous .old exists - try to delete
                        if os.path.isdir(old_path):
                            shutil.rmtree(old_path, ignore_errors=True)
                        else:
                            os.remove(old_path)
                    os.rename(target_path, old_path)
                except OSError:
                    continue  # File locked, skip (will be updated next time)

            # Copy new file/dir in
            if os.path.isdir(staging_path):
                shutil.copytree(staging_path, target_path)
            else:
                shutil.copy2(staging_path, target_path)
        else:
            # Linux/Mac: no file locking, just overwrite
            if os.path.exists(target_path):
                if os.path.isdir(target_path):
                    shutil.rmtree(target_path)
                else:
                    os.remove(target_path)
            if os.path.isdir(staging_path):
                shutil.copytree(staging_path, target_path)
            else:
                shutil.copy2(staging_path, target_path)


def apply_update(root_dir):
    """
    Apply a pending update. Called by the launcher AFTER Internal.exe has exited.
    Uses only stdlib: json, shutil, os, sys, time.
    """
    manifest_path = os.path.join(root_dir, MANIFEST_FILE)
    staging_dir = os.path.join(root_dir, STAGING_DIR)
    bin_dir = os.path.join(root_dir, "bin")
    backup_dir = os.path.join(root_dir, BACKUP_DIR)

    # 1. Read manifest
    try:
        with open(manifest_path, "r") as f:
            manifest = json.load(f)
    except Exception as e:
        print(f"❌ Failed to read update manifest: {e}")
        return False

    version = manifest.get("version", "unknown")
    print(f"\n⬆️  Applying update to v{version}...")

    # 2. Verify staging dir exists
    staging_bin = os.path.join(staging_dir, "bin")
    if not os.path.exists(staging_bin):
        print(f"❌ Staging directory missing: {staging_bin}")
        # Clean up stale manifest
        try:
            os.remove(manifest_path)
        except OSError:
            pass
        return False

    # 3. Backup current bin/
    print("   Backing up current installation...")
    try:
        if os.path.exists(backup_dir):
            shutil.rmtree(backup_dir, ignore_errors=True)
        if os.path.exists(bin_dir):
            # Retry rename up to 3 times (files may take a moment to unlock)
            for attempt in range(3):
                try:
                    os.rename(bin_dir, backup_dir)
                    break
                except OSError:
                    if attempt < 2:
                        print(f"   Waiting for files to unlock (attempt {attempt + 1}/3)...")
                        time.sleep(2)
                    else:
                        print("❌ Failed to rename bin/ directory. Files may still be locked.")
                        return False
    except Exception as e:
        print(f"❌ Backup failed: {e}")
        return False

    # 4. Deploy new bin/
    print("   Installing update...")
    try:
        shutil.move(staging_bin, bin_dir)
    except Exception as e:
        print(f"❌ Failed to deploy new bin/: {e}")
        # Try to rollback
        if os.path.exists(backup_dir) and not os.path.exists(bin_dir):
            try:
                os.rename(backup_dir, bin_dir)
                print("   ↩ Rolled back to previous version.")
            except OSError:
                print("   ⚠️  Rollback also failed! Manual recovery may be needed.")
        return False

    # 5. Update root files (launchers, python313.dll, lib/)
    print("   Updating root files...")
    update_root_files(root_dir, staging_dir)

    # 6. Cleanup
    print("   Cleaning up...")
    try:
        shutil.rmtree(backup_dir, ignore_errors=True)
    except Exception:
        pass  # Will be cleaned on next launch
    try:
        shutil.rmtree(staging_dir, ignore_errors=True)
    except Exception:
        pass
    try:
        os.remove(manifest_path)
    except OSError:
        pass

    print(f"✅ Updated to v{version} successfully!\n")
    return True


def relaunch_from_manifest(root_dir, manifest=None):
    """Relaunch the appropriate launcher after an update."""
    if manifest is None:
        manifest_path = os.path.join(root_dir, MANIFEST_FILE)
        try:
            with open(manifest_path, "r") as f:
                manifest = json.load(f)
        except Exception:
            manifest = {}

    launcher_name = manifest.get("launcher_to_relaunch", "AIPromptBridge.exe")
    launched_mode = manifest.get("launched_mode", "console")
    original_args = manifest.get("original_args", [])

    launcher_path = os.path.join(root_dir, launcher_name)

    if not os.path.exists(launcher_path):
        # Fallback to console launcher
        launcher_path = os.path.join(root_dir, "AIPromptBridge.exe")
        if not os.path.exists(launcher_path):
            print("⚠️  Could not find launcher to relaunch.")
            return

    print(f"🔄 Relaunching {launcher_name}...")
    try:
        if launched_mode == "gui":
            subprocess.Popen(
                [launcher_path] + original_args,
                creationflags=getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0),
            )
        else:
            # For console mode, use os.execv to replace current process
            if sys.platform == "win32":
                subprocess.Popen(
                    [launcher_path] + original_args,
                    creationflags=subprocess.CREATE_NEW_PROCESS_GROUP,
                )
            else:
                os.execv(launcher_path, [launcher_path] + original_args)
    except Exception as e:
        print(f"⚠️  Failed to relaunch: {e}")


def ensure_windows_terminal() -> bool:
    """
    Check if running in legacy Windows Console and relaunch in Windows Terminal if available.
    """
    # Check for user opt-out
    if "--no-wt" in sys.argv:
        return False

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
    # 0. Determine Root Directory (needed early for update checks)
    if getattr(sys, 'frozen', False):
        try:
            root_dir = __compiled__.containing_dir
        except NameError:
            root_dir = os.path.dirname(sys.argv[0])
    else:
        root_dir = os.path.dirname(os.path.abspath(__file__))

    # 0a. Clean up .old files from a previous update
    cleanup_old_files(root_dir)

    # 0b. Handle --apply-update <PID> mode (spawned by GUI mode)
    if "--apply-update" in sys.argv:
        try:
            pid_index = sys.argv.index("--apply-update") + 1
            pid = int(sys.argv[pid_index])
            print(f"⏳ Waiting for process {pid} to exit...")
            wait_for_process_exit(pid, timeout=30)
        except (IndexError, ValueError) as e:
            print(f"⚠️  Invalid --apply-update argument: {e}")
            time.sleep(3)

        # Read manifest before applying (need it for relaunch info)
        manifest_path = os.path.join(root_dir, MANIFEST_FILE)
        manifest = None
        try:
            with open(manifest_path, "r") as f:
                manifest = json.load(f)
        except Exception:
            pass

        if apply_update(root_dir):
            relaunch_from_manifest(root_dir, manifest)
        return

    # 0c. Check for pending update on startup (e.g., stale manifest from crash)
    manifest_path = os.path.join(root_dir, MANIFEST_FILE)
    staging_dir = os.path.join(root_dir, STAGING_DIR)
    if os.path.exists(manifest_path) and os.path.exists(staging_dir):
        print("📦 Found pending update from previous session. Applying...")
        if apply_update(root_dir):
            # Don't relaunch here — just continue to normal startup
            # The update has been applied, and we're about to launch anyway
            pass

    # 1. Windows Terminal Check
    # If we relaunch, we exit this process.
    if ensure_windows_terminal():
        return

    # 2. Construct path to internal executable
    internal_exe = os.path.join(root_dir, "bin", "AIPromptBridge_Internal.exe")

    # 3. Validation
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

    # 4. Prepare Arguments
    # --launched-mode=console tells main.py to behave in console mode
    # Filter out --no-wt as it's handled by the launcher and not recognized by main.py
    app_args = [arg for arg in sys.argv[1:] if arg != "--no-wt"]
    cmd_args = [str(internal_exe), "--launched-mode=console"] + app_args

    # 5. Launch (Blocking)
    # We use subprocess.call (or run) because we want this launcher to stay alive
    # It's safer to block until child exits.

    try:
        exit_code = subprocess.call(cmd_args)
    except Exception as e:
        print(f"❌ Failed to launch application: {e}")
        input("Press Enter to exit...")
        sys.exit(1)
        return  # unreachable but helps static analysis

    # 6. Check for update exit code
    if exit_code == UPDATE_EXIT_CODE:
        # Read manifest before applying (need it for relaunch info)
        manifest = None
        try:
            with open(manifest_path, "r") as f:
                manifest = json.load(f)
        except Exception:
            pass

        if apply_update(root_dir):
            relaunch_from_manifest(root_dir, manifest)
        else:
            print("⚠️  Update failed. Relaunching previous version...")
            # Relaunch anyway so the user doesn't lose their app
            try:
                subprocess.Popen(
                    [sys.argv[0]] + app_args,
                    creationflags=getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0),
                )
            except Exception:
                pass

if __name__ == "__main__":
    main()
