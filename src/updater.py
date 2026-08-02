#!/usr/bin/env python3
"""
Self-Update Module for AIPromptBridge

Handles checking GitHub Releases for updates, downloading, extracting,
and triggering the launcher to apply file replacements.

- Compiled users: Full self-update with download + in-place replacement
- Source users: Notification-only with a link to the releases page
"""

import json
import os
import shutil
import sys
import tarfile
import tempfile
import threading
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional, Tuple

from .console import HAVE_RICH, console, print_error, print_info, print_success, print_warning
from .utils import is_compiled
from .version import __version__

# ─── Constants ─────────────────────────────────────────────────────────────────

UPDATE_EXIT_CODE = 42
STAGING_DIR = "_update_staging"
BACKUP_DIR = "_bin_old"
MANIFEST_FILE = "_update_pending.json"
GITHUB_OWNER = "zaxx-q"
GITHUB_REPO = "AIPromptBridge"
GITHUB_API_URL = f"https://api.github.com/repos/{GITHUB_OWNER}/{GITHUB_REPO}/releases"
RELEASES_URL = f"https://github.com/{GITHUB_OWNER}/{GITHUB_REPO}/releases"

# ─── Data Classes ──────────────────────────────────────────────────────────────


@dataclass
class UpdateInfo:
    """Information about an available update."""

    version: str  # e.g. "5.5.0"
    tag_name: str  # e.g. "v5.5.0"
    download_url: str  # Asset browser_download_url
    asset_size: int  # Expected file size in bytes
    asset_name: str  # Filename of the asset
    release_notes: str  # Release body markdown
    release_url: str  # HTML URL to release page
    published_at: str  # ISO timestamp


# ─── Module State ──────────────────────────────────────────────────────────────

# Cached result of the last update check (set by background thread)
_cached_update_info: Optional[UpdateInfo] = None
_check_in_progress = False
_check_lock = threading.Lock()


def get_cached_update_info() -> Optional[UpdateInfo]:
    """Get the cached update info from the last check, if any."""
    return _cached_update_info


def is_check_in_progress() -> bool:
    """Check if an update check is currently running."""
    return _check_in_progress


# ─── Version Parsing ───────────────────────────────────────────────────────────


def parse_version(version_str: str) -> Tuple[int, ...]:
    """
    Parse a version string like 'v5.4.1' or '5.4.1' into a comparable tuple.

    Examples:
        >>> parse_version("v5.4.1")
        (5, 4, 1)
        >>> parse_version("5.10.0")
        (5, 10, 0)
    """
    # Strip leading 'v' or 'V'
    version_str = version_str.lstrip("vV").strip()
    parts = []
    for part in version_str.split("."):
        try:
            parts.append(int(part))
        except ValueError:
            # Take only the numeric prefix of any non-standard part
            numeric = ""
            for ch in part:
                if ch.isdigit():
                    numeric += ch
                else:
                    break
            parts.append(int(numeric) if numeric else 0)
    return tuple(parts)


def is_newer_version(remote_version: str, local_version: str | None = None) -> bool:
    """
    Check if the remote version is newer than the local version.

    Args:
        remote_version: Version string from GitHub (e.g., "v5.5.0")
        local_version: Local version string (default: current __version__)

    Returns:
        True if remote is strictly newer than local
    """
    if local_version is None:
        local_version = __version__
    return parse_version(remote_version) > parse_version(local_version)


# ─── Release asset selection ───────────────────────────────────────────────────


def _select_release_asset(assets: list) -> Tuple[str, int, str]:
    """
    Pick the best downloadable asset for this OS from a GitHub release assets list.

    Returns:
        (download_url, asset_size, asset_name) — empty strings / 0 when none match.

    Windows: prefer ``*windows*`` / ``*win*`` ``.zip``, else any ``.zip`` with
    ``aipromptbridge`` in the name (legacy single-asset releases).
    Linux: prefer ``*linux*`` ``.tar.gz`` / ``.tgz`` / ``.zip`` for release-page
    links; full in-place self-update apply is still Windows-only for now.
    """
    from .platform.detect import is_linux, is_windows

    def _norm(asset: dict) -> Tuple[str, str, int, str]:
        name = asset.get("name", "") or ""
        return (
            name.lower(),
            asset.get("browser_download_url") or "",
            int(asset.get("size") or 0),
            name,
        )

    ranked: list[Tuple[int, str, int, str]] = []  # priority, url, size, name

    for asset in assets:
        lname, url, size, name = _norm(asset)
        if not url or not lname:
            continue

        if is_windows():
            if lname.endswith(".zip") and ("windows" in lname or "win" in lname):
                ranked.append((0, url, size, name))
            elif lname.endswith(".zip") and "aipromptbridge" in lname and "linux" not in lname:
                ranked.append((1, url, size, name))
            elif lname.endswith(".zip") and "linux" not in lname:
                ranked.append((2, url, size, name))
        elif is_linux():
            if "linux" in lname and (lname.endswith(".tar.gz") or lname.endswith(".tgz")):
                ranked.append((0, url, size, name))
            elif "linux" in lname and lname.endswith(".zip"):
                ranked.append((1, url, size, name))
            elif lname.endswith(".tar.gz") or lname.endswith(".tgz"):
                ranked.append((2, url, size, name))
        else:
            # Other platforms: no auto-selected binary asset
            continue

    if not ranked:
        return "", 0, ""

    ranked.sort(key=lambda t: t[0])
    _, url, size, name = ranked[0]
    return url, size, name


# ─── GitHub API ────────────────────────────────────────────────────────────────


def check_for_update() -> Optional[UpdateInfo]:
    """
    Check GitHub Releases API for a newer version.

    Returns:
        UpdateInfo if a newer version is available, None otherwise
    """
    global _cached_update_info, _check_in_progress

    with _check_lock:
        if _check_in_progress:
            return None
        _check_in_progress = True

    try:
        import requests

        # Fetch releases
        headers = {
            "Accept": "application/vnd.github.v3+json",
            "User-Agent": f"AIPromptBridge/{__version__}",
        }

        # Get only the latest stable release
        url = f"{GITHUB_API_URL}/latest"

        response = requests.get(url, headers=headers, timeout=15)

        if response.status_code == 404:
            # No releases found
            return None

        if response.status_code == 403:
            # Rate limited
            print_warning("GitHub API rate limit reached. Try again later.")
            return None

        response.raise_for_status()

        release = response.json()

        tag_name = release.get("tag_name", "")
        if not tag_name:
            return None

        # Check if this version is newer
        if not is_newer_version(tag_name):
            return None

        # Platform-aware asset selection (Windows zip auto-apply; Linux notify link)
        assets = release.get("assets", [])
        download_url, asset_size, asset_name = _select_release_asset(assets)

        if not download_url:
            # No suitable asset found — still report the update for notification
            download_url = ""
            asset_size = 0
            asset_name = ""

        info = UpdateInfo(
            version=tag_name.lstrip("vV"),
            tag_name=tag_name,
            download_url=download_url,
            asset_size=asset_size,
            asset_name=asset_name,
            release_notes=release.get("body", "") or "",
            release_url=release.get("html_url", RELEASES_URL),
            published_at=release.get("published_at", ""),
        )

        _cached_update_info = info
        return info

    except Exception as e:
        # Silent fail for auto-check; print for manual
        print(f"[Updater] Error checking for updates: {e}")
        return None
    finally:
        with _check_lock:
            _check_in_progress = False


# ─── Download & Prepare ───────────────────────────────────────────────────────


def download_update(
    update_info: UpdateInfo, progress_callback: Optional[Callable[[int, int], None]] = None
) -> Optional[str]:
    """
    Download the update zip file.

    Args:
        update_info: UpdateInfo from check_for_update()
        progress_callback: Optional callback(bytes_downloaded, total_bytes)

    Returns:
        Path to the downloaded zip file, or None on failure
    """
    if not update_info.download_url:
        print_error("No download URL available for this update.")
        return None

    import requests

    try:
        # Create temp file for download
        temp_dir = tempfile.mkdtemp(prefix="aipb_update_")
        zip_path = os.path.join(temp_dir, update_info.asset_name or "update.zip")

        if HAVE_RICH:
            console.print(f"[dim]Downloading {update_info.asset_name}...[/dim]")
        else:
            print(f"Downloading {update_info.asset_name}...")

        response = requests.get(
            update_info.download_url,
            stream=True,
            timeout=300,
            headers={"User-Agent": f"AIPromptBridge/{__version__}"},
        )
        response.raise_for_status()

        total_size = int(response.headers.get("content-length", 0)) or update_info.asset_size
        downloaded = 0

        with open(zip_path, "wb") as f:
            for chunk in response.iter_content(chunk_size=8192):
                if chunk:
                    f.write(chunk)
                    downloaded += len(chunk)
                    if progress_callback:
                        progress_callback(downloaded, total_size)

        # Verify size if we know it
        actual_size = os.path.getsize(zip_path)
        if update_info.asset_size > 0 and actual_size != update_info.asset_size:
            print_warning(
                f"Download size mismatch: expected {update_info.asset_size}, got {actual_size}. File may be corrupted."
            )
            # Don't fail — size from GitHub API can sometimes be approximate

        return zip_path

    except Exception as e:
        print_error(f"Download failed: {e}")
        # Cleanup temp dir on failure
        try:
            shutil.rmtree(temp_dir, ignore_errors=True)
        except Exception:
            pass
        return None


def _extract_zip(zip_path: str, staging_dir: Path):
    """Extract a .zip archive into the staging directory."""
    with zipfile.ZipFile(zip_path, "r") as zf:
        # Check for a single root directory inside the zip
        top_level = set()
        for name in zf.namelist():
            parts = name.split("/")
            if parts[0]:
                top_level.add(parts[0])

        if len(top_level) == 1:
            # Zip has a single root directory — extract and rename
            root_name = top_level.pop()
            zf.extractall(str(staging_dir.parent))
            extracted_path = staging_dir.parent / root_name
            if extracted_path != staging_dir:
                if staging_dir.exists():
                    shutil.rmtree(staging_dir)
                extracted_path.rename(staging_dir)
        else:
            # Zip contents are at the root level
            zf.extractall(str(staging_dir))


def _extract_tarball(tar_path: str, staging_dir: Path):
    """Extract a .tar.gz / .tgz archive into the staging directory."""
    with tarfile.open(tar_path, "r:gz") as tf:
        # Security: filter out absolute paths and path traversal
        members = tf.getmembers()
        safe_members = []
        for m in members:
            # Skip absolute paths or path traversal attempts
            if m.name.startswith("/") or ".." in m.name.split("/"):
                continue
            safe_members.append(m)

        # Check for a single root directory inside the tarball
        top_level = set()
        for m in safe_members:
            parts = m.name.split("/")
            if parts[0]:
                top_level.add(parts[0])

        if len(top_level) == 1:
            # Tarball has a single root directory — extract and rename
            root_name = top_level.pop()
            tf.extractall(str(staging_dir.parent), members=safe_members)
            extracted_path = staging_dir.parent / root_name
            if extracted_path != staging_dir:
                if staging_dir.exists():
                    shutil.rmtree(staging_dir)
                extracted_path.rename(staging_dir)
        else:
            # Tarball contents are at the root level
            staging_dir.mkdir(parents=True, exist_ok=True)
            tf.extractall(str(staging_dir), members=safe_members)


def prepare_update(zip_path: str, update_info: UpdateInfo) -> bool:
    """
    Extract the downloaded archive to the staging directory and write the manifest.

    Supports .zip (Windows) and .tar.gz/.tgz (Linux) archives.

    Args:
        zip_path: Path to the downloaded archive file
        update_info: UpdateInfo for this update

    Returns:
        True if staging was successful
    """
    staging_dir = Path(STAGING_DIR)

    try:
        # Clean any previous staging
        if staging_dir.exists():
            shutil.rmtree(staging_dir)

        if HAVE_RICH:
            console.print("[dim]Extracting update...[/dim]")
        else:
            print("Extracting update...")

        # Determine archive type and extract
        lower_path = zip_path.lower()
        if lower_path.endswith((".tar.gz", ".tgz")):
            _extract_tarball(zip_path, staging_dir)
        elif lower_path.endswith(".zip"):
            _extract_zip(zip_path, staging_dir)
        else:
            print_error(f"Unsupported archive format: {zip_path}")
            return False

        # Verify staging dir has content
        if not staging_dir.exists() or not any(staging_dir.iterdir()):
            print_error("Extraction produced empty staging directory.")
            return False

        # Write manifest
        _write_manifest(update_info)

        # Cleanup downloaded archive
        try:
            temp_dir = os.path.dirname(zip_path)
            shutil.rmtree(temp_dir, ignore_errors=True)
        except Exception:
            pass

        if HAVE_RICH:
            print_success(f"Update v{update_info.version} staged successfully.")
        else:
            print(f"✅ Update v{update_info.version} staged successfully.")

        return True

    except (zipfile.BadZipFile, tarfile.TarError) as e:
        print_error(f"Archive is corrupted or invalid: {e}")
        _cleanup_staging()
        return False
    except Exception as e:
        print_error(f"Failed to prepare update: {e}")
        _cleanup_staging()
        return False


def _write_manifest(update_info: UpdateInfo):
    """Write the update manifest file for the launcher."""
    from .platform.detect import is_linux

    # Determine which launcher to use for relaunch
    launched_mode = None
    for arg in sys.argv:
        if arg.startswith("--launched-mode="):
            launched_mode = arg.split("=")[1]
            break

    if is_linux():
        # Linux: shell launcher is just "AIPromptBridge" (no .exe, no gui variant)
        launcher_name = "AIPromptBridge"
    elif launched_mode == "gui":
        launcher_name = "AIPromptBridge-NoConsole.exe"
    else:
        launcher_name = "AIPromptBridge.exe"

    # Collect original args (without --launched-mode)
    original_args = [arg for arg in sys.argv[1:] if not arg.startswith("--launched-mode")]

    manifest = {
        "version": update_info.version,
        "staging_dir": STAGING_DIR,
        "launcher_to_relaunch": launcher_name,
        "launched_mode": launched_mode or "console",
        "original_args": original_args,
    }

    with open(MANIFEST_FILE, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2)


def _cleanup_staging():
    """Clean up staging directory and manifest on failure."""
    try:
        staging = Path(STAGING_DIR)
        if staging.exists():
            shutil.rmtree(staging, ignore_errors=True)
    except Exception:
        pass
    try:
        manifest = Path(MANIFEST_FILE)
        if manifest.exists():
            manifest.unlink()
    except Exception:
        pass


# ─── Trigger Update ───────────────────────────────────────────────────────────


def trigger_update():
    """
    Signal/perform the update apply and restart.

    - Windows console mode: exit with code 42 (cx_Freeze launcher catches this)
    - Windows GUI mode: spawn the console launcher with --apply-update PID
    - Linux: apply the update in-process, then os.execv the outer launcher
    """
    from .platform.detect import is_linux

    if is_linux():
        _trigger_update_linux()
    else:
        launched_mode = None
        for arg in sys.argv:
            if arg.startswith("--launched-mode="):
                launched_mode = arg.split("=")[1]
                break

        if launched_mode == "gui":
            _trigger_update_gui_mode()
        else:
            _trigger_update_console_mode()


def _trigger_update_linux():
    """
    Linux: apply the staged update in-process, then os.execv the launcher.

    Since the shell launcher used `exec` to replace itself with the Nuitka
    binary, there is no parent process to coordinate with. We do the entire
    apply + relaunch from here.
    """
    if HAVE_RICH:
        console.print("\n[bold cyan]🔄 Applying update...[/bold cyan]")
    else:
        print("\n🔄 Applying update...")

    try:
        success = _apply_update_linux()
    except Exception as e:
        print_error(f"Update apply failed: {e}")
        print_info("Update has been staged. It will be applied on next launch.")
        return

    if not success:
        print_info("Update has been staged. It will be applied on next launch.")
        return

    # Determine the outer launcher path for relaunch
    if is_compiled():
        bin_dir = Path(sys.executable).parent
        root_dir = bin_dir.parent
    else:
        root_dir = Path.cwd()

    # Read manifest for relaunch info before it's cleaned up
    manifest_path = root_dir / MANIFEST_FILE
    launcher_name = "AIPromptBridge"
    original_args = []
    try:
        if manifest_path.exists():
            with open(manifest_path, "r") as f:
                manifest = json.load(f)
            launcher_name = manifest.get("launcher_to_relaunch", "AIPromptBridge")
            original_args = manifest.get("original_args", [])
            # Clean up manifest
            manifest_path.unlink(missing_ok=True)
    except Exception:
        pass

    launcher_path = root_dir / launcher_name
    if not launcher_path.exists():
        print_warning(f"Launcher not found at {launcher_path}. Please restart manually.")
        os._exit(0)

    if HAVE_RICH:
        console.print(f"[bold cyan]🔄 Restarting via {launcher_name}...[/bold cyan]\n")
    else:
        print(f"🔄 Restarting via {launcher_name}...\n")

    # os.execv replaces the current process with the launcher
    launcher_str = str(launcher_path)
    os.execv(launcher_str, [launcher_str, *original_args])


def _apply_update_linux() -> bool:
    """
    Apply a staged update on Linux: swap bin/ and update root files.

    Returns True on success, False on failure (with rollback attempted).
    """
    if is_compiled():
        bin_dir_parent = Path(sys.executable).parent.parent
    else:
        bin_dir_parent = Path.cwd()

    staging_dir = bin_dir_parent / STAGING_DIR
    bin_dir = bin_dir_parent / "bin"
    backup_dir = bin_dir_parent / BACKUP_DIR
    manifest_path = bin_dir_parent / MANIFEST_FILE

    # Read manifest
    try:
        with open(manifest_path, "r") as f:
            manifest = json.load(f)
    except Exception as e:
        print_error(f"Failed to read update manifest: {e}")
        return False

    version = manifest.get("version", "unknown")

    # Verify staging
    staging_bin = staging_dir / "bin"
    if not staging_bin.exists():
        print_error(f"Staging directory missing: {staging_bin}")
        try:
            manifest_path.unlink(missing_ok=True)
        except Exception:
            pass
        return False

    # Backup current bin/
    if HAVE_RICH:
        console.print("   [dim]Backing up current installation...[/dim]")
    else:
        print("   Backing up current installation...")

    try:
        if backup_dir.exists():
            shutil.rmtree(backup_dir, ignore_errors=True)
        if bin_dir.exists():
            os.rename(str(bin_dir), str(backup_dir))
    except Exception as e:
        print_error(f"Backup failed: {e}")
        return False

    # Deploy new bin/
    if HAVE_RICH:
        console.print("   [dim]Installing update...[/dim]")
    else:
        print("   Installing update...")

    try:
        shutil.move(str(staging_bin), str(bin_dir))
    except Exception as e:
        print_error(f"Failed to deploy new bin/: {e}")
        # Rollback
        if backup_dir.exists() and not bin_dir.exists():
            try:
                os.rename(str(backup_dir), str(bin_dir))
                print_info("Rolled back to previous version.")
            except OSError:
                print_error("Rollback also failed! Manual recovery may be needed.")
        return False

    # Update root files (launcher script, aipb_trigger.py, etc.)
    _update_root_files_linux(str(bin_dir_parent), str(staging_dir))

    # Cleanup
    try:
        shutil.rmtree(backup_dir, ignore_errors=True)
    except Exception:
        pass
    try:
        shutil.rmtree(staging_dir, ignore_errors=True)
    except Exception:
        pass

    if HAVE_RICH:
        print_success(f"Updated to v{version} successfully!")
    else:
        print(f"✅ Updated to v{version} successfully!")

    return True


# Files at the package root that should be updated from staging
_LINUX_ROOT_UPDATE_FILES = [
    "AIPromptBridge",  # outer shell launcher
    "aipb_trigger.py",  # fast IPC client
    "README-linux.txt",  # readme
    "icon.ico",  # icon (if present)
]


def _update_root_files_linux(root_dir: str, staging_dir: str):
    """Update root-level files from staging on Linux (simple overwrite)."""
    for name in _LINUX_ROOT_UPDATE_FILES:
        staging_path = os.path.join(staging_dir, name)
        target_path = os.path.join(root_dir, name)

        if not os.path.exists(staging_path):
            continue

        try:
            # Linux: no file locking, just overwrite
            if os.path.exists(target_path):
                if os.path.isdir(target_path):
                    shutil.rmtree(target_path)
                else:
                    os.remove(target_path)
            if os.path.isdir(staging_path):
                shutil.copytree(staging_path, target_path)
            else:
                shutil.copy2(staging_path, target_path)

            # Preserve execute permission for scripts
            if name in ("AIPromptBridge", "aipb_trigger.py"):
                os.chmod(target_path, 0o755)
        except Exception as e:
            print_warning(f"Failed to update root file {name}: {e}")


def _trigger_update_console_mode():
    """Exit with UPDATE_EXIT_CODE so the console launcher applies the update."""
    if HAVE_RICH:
        console.print("\n[bold cyan]🔄 Restarting to apply update...[/bold cyan]\n")
    else:
        print("\n🔄 Restarting to apply update...\n")
    os._exit(UPDATE_EXIT_CODE)


def _trigger_update_gui_mode():
    """
    Spawn the console launcher with --apply-update to handle the update
    while we (Internal.exe) exit normally.
    """
    import subprocess

    my_pid = os.getpid()

    # Find the console launcher
    if is_compiled():
        bin_dir = Path(sys.executable).parent
        root_dir = bin_dir.parent
    else:
        root_dir = Path.cwd()

    console_launcher = root_dir / "AIPromptBridge.exe"

    if not console_launcher.exists():
        print_error(f"Console launcher not found at: {console_launcher}")
        print_info("Update has been staged. It will be applied on next launch.")
        return

    if HAVE_RICH:
        console.print("\n[bold cyan]🔄 Applying update in background...[/bold cyan]\n")
    else:
        print("\n🔄 Applying update in background...\n")

    try:
        # Spawn the console launcher to wait for us and apply
        subprocess.Popen(
            [str(console_launcher), "--apply-update", str(my_pid)],
            creationflags=getattr(subprocess, "CREATE_NEW_CONSOLE", 0x00000010),
        )
    except Exception as e:
        print_error(f"Failed to spawn updater process: {e}")
        print_info("Update has been staged. It will be applied on next launch.")
        return

    # Exit so the launcher can work on bin/
    os._exit(0)


# ─── Startup Recovery ─────────────────────────────────────────────────────────


def startup_recovery():
    """
    Check for interrupted updates and recover.
    Called early in main() before anything else.
    """
    bin_dir = Path("bin")
    backup_dir = Path(BACKUP_DIR)
    manifest = Path(MANIFEST_FILE)
    staging = Path(STAGING_DIR)

    # Case 1: bin/ is missing but backup exists → rollback
    if backup_dir.exists() and not bin_dir.exists():
        print_warning("Detected interrupted update. Rolling back...")
        try:
            shutil.move(str(backup_dir), str(bin_dir))
            print_success("Rollback successful.")
        except Exception as e:
            print_error(f"Rollback failed: {e}")

    # Case 2: Stale manifest without staging → clean up
    if manifest.exists() and not staging.exists():
        try:
            manifest.unlink()
        except Exception:
            pass

    # Case 3: Leftover staging without manifest → clean up
    if staging.exists() and not manifest.exists():
        try:
            shutil.rmtree(staging, ignore_errors=True)
        except Exception:
            pass

    # Case 4: Leftover backup after successful update → clean up
    if backup_dir.exists() and bin_dir.exists():
        try:
            shutil.rmtree(backup_dir, ignore_errors=True)
        except Exception:
            pass


# ─── Background Check ─────────────────────────────────────────────────────────


def background_update_check(config: dict):
    """
    Run an update check in the background (non-blocking).
    Called from main.py after initialization.

    Args:
        config: Application configuration dict
    """
    if not config.get("update_check_enabled", True):
        return

    def _check():
        import time

        # Delay to prevent import lock and GIL contention from blocking tray initialization
        time.sleep(3)
        try:
            info = check_for_update()
            if info:
                _print_update_notification(info)

                # Show the GUI popup if GUI is available and we are not in terminal mode
                try:
                    from .gui.core import HAVE_GUI, GUICoordinator

                    if HAVE_GUI:
                        coordinator = GUICoordinator.get_instance()

                        def _show_update_dialog():
                            from .gui.windows.update_dialogs import show_update_available_dialog

                            show_update_available_dialog(info, __version__)

                        coordinator.run_on_gui_thread(_show_update_dialog)
                except Exception as e:
                    print(f"[Error] Failed to show startup update dialog: {e}")
        except Exception:
            pass  # Silent fail on background check

    threading.Thread(target=_check, daemon=True).start()


def _print_update_notification(info: UpdateInfo):
    """Print a console notification about an available update."""
    if HAVE_RICH:
        console.print()
        console.print(
            f"[bold green]⬆️  Update available: v{info.version}[/bold green] [dim](current: v{__version__})[/dim]"
        )
        if info.release_notes:
            # Show first 2 lines of release notes
            lines = info.release_notes.strip().split("\n")[:2]
            for line in lines:
                console.print(f"   [dim]{line.strip()}[/dim]")
        if is_compiled() and _supports_in_place_update():
            console.print("   [cyan]Press [bold]U[/bold] in the terminal or use tray menu to install.[/cyan]")
        else:
            console.print(f"   [cyan]Download: [link={info.release_url}]{info.release_url}[/link][/cyan]")
        console.print()
    else:
        print()
        print(f"⬆️  Update available: v{info.version} (current: v{__version__})")
        if is_compiled() and _supports_in_place_update():
            print("   Press U in the terminal or use tray menu to install.")
        else:
            print(f"   Download: {info.release_url}")
        print()


# ─── Full Update Flow (for UI callbacks) ──────────────────────────────────────


def _supports_in_place_update() -> bool:
    """True when compiled self-update can download + apply in-place."""
    # Compiled installs on Windows (launcher exit code 42 + bin swap) and
    # Linux (Python-driven bin swap + os.execv relaunch) are both supported.
    return is_compiled()


def perform_update(
    update_info: UpdateInfo,
    progress_callback: Optional[Callable[[str, int, int], None]] = None,
) -> Tuple[bool, str]:
    """
    Perform the full update flow: download → extract → trigger.

    Args:
        update_info: UpdateInfo from check_for_update()
        progress_callback: Optional callback(stage, current, total)
            stage is "download" or "extract"

    Returns:
        (success, message) tuple
    """
    if not is_compiled():
        return False, (f"Update v{update_info.version} is available!\nDownload from: {update_info.release_url}")

    if not _supports_in_place_update():
        url = update_info.download_url or update_info.release_url
        return False, (
            f"Update v{update_info.version} is available!\n"
            f"Automatic install is not supported on this platform yet.\n"
            f"Download: {url}"
        )

    if not update_info.download_url:
        return False, (
            f"Update v{update_info.version} found but no downloadable asset.\nVisit: {update_info.release_url}"
        )

    # Download
    def dl_progress(downloaded, total):
        if progress_callback:
            progress_callback("download", downloaded, total)

    zip_path = download_update(update_info, progress_callback=dl_progress)
    if not zip_path:
        return False, "Download failed. Please try again."

    # Prepare (extract + manifest)
    if progress_callback:
        progress_callback("extract", 0, 0)

    if not prepare_update(zip_path, update_info):
        return False, "Failed to extract update. The download may be corrupted."

    # Trigger
    trigger_update()

    # If we reach here, trigger didn't exit (GUI mode non-blocking path)
    return True, f"Update v{update_info.version} will be applied shortly."


def check_and_prompt_terminal(config: dict) -> bool:
    """
    Interactive terminal update flow. Called when user presses 'U'.

    Returns:
        True if an update was initiated, False otherwise
    """
    if HAVE_RICH:
        console.print("\n[bold]⬆️  Checking for updates...[/bold]")
    else:
        print("\n⬆️  Checking for updates...")

    info = check_for_update()

    if not info:
        if HAVE_RICH:
            console.print(f"[green]✅ You're up to date![/green] [dim](v{__version__})[/dim]\n")
        else:
            print(f"✅ You're up to date! (v{__version__})\n")
        return False

    # Display update info
    if HAVE_RICH:
        console.print(
            f"\n[bold green]New version available: v{info.version}[/bold green] [dim](current: v{__version__})[/dim]"
        )
        if info.published_at:
            console.print(f"   [dim]Published: {info.published_at[:10]}[/dim]")
        if info.release_notes:
            lines = info.release_notes.strip().split("\n")[:5]
            console.print("   [dim]─── Release Notes ───[/dim]")
            for line in lines:
                console.print(f"   [dim]{line.strip()}[/dim]")
            if len(info.release_notes.strip().split("\n")) > 5:
                console.print("   [dim]...(truncated)[/dim]")
        console.print()
    else:
        print(f"\nNew version available: v{info.version} (current: v{__version__})")
        if info.published_at:
            print(f"   Published: {info.published_at[:10]}")
        if info.release_notes:
            lines = info.release_notes.strip().split("\n")[:5]
            for line in lines:
                print(f"   {line.strip()}")
        print()

    if not _supports_in_place_update():
        # Source mode — notification only
        url = info.download_url or info.release_url
        if HAVE_RICH:
            console.print(f"[cyan]📦 Download: [link={url}]{url}[/link][/cyan]\n")
        else:
            print(f"📦 Download: {url}\n")
        return False

    # Compiled install — prompt for download
    if info.asset_size > 0:
        size_mb = info.asset_size / (1024 * 1024)
        size_str = f" ({size_mb:.1f} MB)"
    else:
        size_str = ""

    try:
        prompt_text = f"   Download and install v{info.version}{size_str}? [Y/N]: "
        choice = input(prompt_text).strip().lower()
    except (EOFError, KeyboardInterrupt):
        print()
        return False

    if choice not in ("y", "yes"):
        print("   Update cancelled.\n")
        return False

    # Perform update
    def progress(stage, current, total):
        if stage == "download" and total > 0:
            pct = int(current / total * 100)
            if pct % 20 == 0:  # Print every 20%
                if HAVE_RICH:
                    console.print(f"   [dim]Downloading... {pct}%[/dim]")
                else:
                    print(f"   Downloading... {pct}%")

    success, message = perform_update(info, progress_callback=progress)
    if not success:
        print_error(message)
    return success
