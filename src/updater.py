#!/usr/bin/env python3
"""
Self-Update Module for AIPromptBridge

Handles checking GitHub Releases for updates, downloading, extracting,
and triggering the launcher to apply file replacements.

- Compiled users: Full self-update with download + in-place replacement
- Source users: Notification-only with a link to the releases page
"""

import os
import sys
import json
import shutil
import zipfile
import tempfile
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional, Callable, Tuple

from .version import __version__
from .console import console, print_success, print_error, print_warning, print_info, HAVE_RICH
from .utils import is_compiled

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
    version: str           # e.g. "5.5.0"
    tag_name: str          # e.g. "v5.5.0"
    download_url: str      # Asset browser_download_url
    asset_size: int        # Expected file size in bytes
    asset_name: str        # Filename of the asset
    release_notes: str     # Release body markdown
    release_url: str       # HTML URL to release page
    published_at: str      # ISO timestamp


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


def is_newer_version(remote_version: str, local_version: str = None) -> bool:
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

        # Find the correct asset (Windows zip)
        assets = release.get("assets", [])
        download_url = None
        asset_size = 0
        asset_name = ""

        for asset in assets:
            name = asset.get("name", "").lower()
            # Look for Windows zip asset
            if name.endswith(".zip") and ("windows" in name or "win" in name or "aipromptbridge" in name):
                download_url = asset.get("browser_download_url")
                asset_size = asset.get("size", 0)
                asset_name = asset.get("name", "")
                break

        # Fallback: take the first zip asset
        if not download_url:
            for asset in assets:
                name = asset.get("name", "").lower()
                if name.endswith(".zip"):
                    download_url = asset.get("browser_download_url")
                    asset_size = asset.get("size", 0)
                    asset_name = asset.get("name", "")
                    break

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
    update_info: UpdateInfo,
    progress_callback: Optional[Callable[[int, int], None]] = None
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
                f"Download size mismatch: expected {update_info.asset_size}, "
                f"got {actual_size}. File may be corrupted."
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


def prepare_update(zip_path: str, update_info: UpdateInfo) -> bool:
    """
    Extract the downloaded zip to the staging directory and write the manifest.

    Args:
        zip_path: Path to the downloaded zip file
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

        # Extract zip
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

        # Verify staging dir has content
        if not staging_dir.exists() or not any(staging_dir.iterdir()):
            print_error("Extraction produced empty staging directory.")
            return False

        # Write manifest
        _write_manifest(update_info)

        # Cleanup downloaded zip
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

    except zipfile.BadZipFile:
        print_error("Downloaded file is not a valid zip archive.")
        _cleanup_staging()
        return False
    except Exception as e:
        print_error(f"Failed to prepare update: {e}")
        _cleanup_staging()
        return False


def _write_manifest(update_info: UpdateInfo):
    """Write the update manifest file for the launcher."""
    # Determine which launcher to use for relaunch
    launched_mode = None
    for arg in sys.argv:
        if arg.startswith("--launched-mode="):
            launched_mode = arg.split("=")[1]
            break

    if launched_mode == "gui":
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
    Signal the launcher to apply the update.

    - Console mode: exit with code 42 (launcher catches this)
    - GUI mode: spawn the console launcher with --apply-update PID
    """
    launched_mode = None
    for arg in sys.argv:
        if arg.startswith("--launched-mode="):
            launched_mode = arg.split("=")[1]
            break

    if launched_mode == "gui":
        _trigger_update_gui_mode()
    else:
        _trigger_update_console_mode()


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
                    from .gui.core import GUICoordinator, HAVE_GUI
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
            f"[bold green]⬆️  Update available: v{info.version}[/bold green]"
            f" [dim](current: v{__version__})[/dim]"
        )
        if info.release_notes:
            # Show first 2 lines of release notes
            lines = info.release_notes.strip().split("\n")[:2]
            for line in lines:
                console.print(f"   [dim]{line.strip()}[/dim]")
        if is_compiled():
            console.print(
                "   [cyan]Press [bold]U[/bold] in the terminal or use "
                "tray menu to install.[/cyan]"
            )
        else:
            console.print(
                f"   [cyan]Download: [link={info.release_url}]{info.release_url}[/link][/cyan]"
            )
        console.print()
    else:
        print()
        print(f"⬆️  Update available: v{info.version} (current: v{__version__})")
        if is_compiled():
            print("   Press U in the terminal or use tray menu to install.")
        else:
            print(f"   Download: {info.release_url}")
        print()


# ─── Full Update Flow (for UI callbacks) ──────────────────────────────────────


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
        return False, (
            f"Update v{update_info.version} is available!\n"
            f"Download from: {update_info.release_url}"
        )

    if not update_info.download_url:
        return False, (
            f"Update v{update_info.version} found but no downloadable asset.\n"
            f"Visit: {update_info.release_url}"
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
            console.print("[green]✅ You're up to date![/green] "
                          f"[dim](v{__version__})[/dim]\n")
        else:
            print(f"✅ You're up to date! (v{__version__})\n")
        return False

    # Display update info
    if HAVE_RICH:
        console.print(f"\n[bold green]New version available: v{info.version}[/bold green]"
                       f" [dim](current: v{__version__})[/dim]")
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

    if not is_compiled():
        # Source mode — notification only
        if HAVE_RICH:
            console.print(f"[cyan]📦 Running from source. "
                           f"Download: [link={info.release_url}]{info.release_url}[/link][/cyan]\n")
        else:
            print(f"📦 Running from source. Download: {info.release_url}\n")
        return False

    # Compiled mode — prompt for download
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
