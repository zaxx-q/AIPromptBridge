"""
Startup Manager for AIPromptBridge

Cross-platform launch-at-login:

- **Windows**: registry ``HKEY_CURRENT_USER\\…\\Run`` (compiled launcher exe only).
- **Linux**: XDG autostart ``~/.config/autostart/aipromptbridge.desktop``
  - Source: current interpreter + ``main.py``, ``Path=`` project root
  - Compiled (Nuitka split): outer ``AIPromptBridge`` shell launcher preferred,
    ``Path=`` deploy root so CWD-relative config works

Supports launcher detection for Windows (``.exe``) and Linux (shell wrapper)
Nuitka split builds, plus local development environments.
"""

from __future__ import annotations

import os
import shlex
import sys
import tempfile
from pathlib import Path
from typing import Optional, Tuple

# Nuitka injects __compiled__ into every compiled module's globals().
from .platform.detect import is_linux, is_windows
from .utils import is_compiled

# Registry key path (Windows)
RUN_KEY_PATH = r"Software\Microsoft\Windows\CurrentVersion\Run"

# App name for startup registry / desktop entry
APP_NAME = "AIPromptBridge"

# XDG autostart desktop filename (Linux)
DESKTOP_FILENAME = "aipromptbridge.desktop"


# ─── Shared helpers ───────────────────────────────────────────────────────────


def get_project_root() -> Path:
    """
    Resolve the portable deploy / project root (config.ini lives here).

    **Compiled** (Nuitka split or single binary):
      - ``…/bin/Internal`` → parent of ``bin/`` (same as ``setup_workspace``)
      - else prefer CWD when it looks like the deploy root (config.ini / icon)
      - else directory of ``sys.executable``

    **Source**:
      - Prefer CWD when ``main.py`` is present (``uv run main.py``)
      - else package parent (``src/`` → repo root)
    """
    if is_compiled():
        exe_path = Path(sys.executable).resolve()
        # Split-build: Internal binary under bin/ → launcher + config at parent
        if exe_path.parent.name.lower() == "bin":
            return exe_path.parent.parent
        cwd = Path.cwd()
        if (cwd / "config.ini").is_file() or (cwd / "icon.ico").is_file() or (cwd / "main.py").is_file():
            return cwd.resolve()
        return exe_path.parent

    cwd = Path.cwd()
    if (cwd / "main.py").is_file():
        return cwd.resolve()
    return Path(__file__).resolve().parent.parent


def get_main_script_path() -> Optional[Path]:
    """Absolute path to ``main.py`` if it exists under the project root (source only)."""
    if is_compiled():
        return None
    main_py = get_project_root() / "main.py"
    return main_py if main_py.is_file() else None


def get_start_executable() -> Optional[str]:
    """
    Absolute path of the process that should be launched at login.

    - **Windows compiled**: outer launcher (``AIPromptBridge.exe`` / NoConsole), never the
      internal ``bin/`` binary alone.
    - **Linux compiled**: same split-layout launcher search if present; else ``sys.executable``.
    - **Source**: ``None`` (use interpreter + ``main.py`` via ``format_start_command``).
    """
    if not is_compiled():
        return None

    # Prefer outer launcher when split layout is present (Windows primary; Linux if ever same layout)
    launcher = get_launcher_path()
    if launcher and not str(launcher).lower().endswith(".py"):
        return str(Path(launcher).resolve())

    return str(Path(sys.executable).resolve())


def format_start_command() -> Optional[str]:
    """
    Shell-safe command that starts the full app (login / autostart).

    Compiled → quoted executable (launcher preferred).
    Source → ``<python> <main.py>``.

    Returns ``None`` if the start target cannot be resolved.
    """
    if is_compiled():
        exe = get_start_executable()
        if not exe:
            return None
        return shlex.quote(exe)

    main_py = get_main_script_path()
    if main_py is None:
        return None
    return f"{shlex.quote(sys.executable)} {shlex.quote(str(main_py))}"


def get_trigger_client_path() -> Optional[Path]:
    """
    Path to the fast stdlib IPC client script when present (source tree).

    Prefer ``scripts/aipb_trigger.py`` so compositor binds avoid loading full ``main.py``.
    """
    if is_compiled():
        return None
    root = get_project_root()
    for candidate in (root / "scripts" / "aipb_trigger.py", root / "aipb_trigger.py"):
        if candidate.is_file():
            return candidate
    return None


def format_trigger_command(trigger: str) -> Optional[str]:
    """
    Shell-safe IPC client command: ``… --trigger <name>`` or fast client.

    Compiled → ``<launcher> --trigger <name>`` (outer shell uses ``aipb_trigger.py``).
    Source → ``python3 scripts/aipb_trigger.py <name>`` when present; else
    ``<python> -m src.platform.ipc <name>``; last resort ``main.py --trigger``.
    """
    name = (trigger or "").strip().lower()
    if not name:
        return None

    if is_compiled():
        exe = get_start_executable()
        if not exe:
            return None
        return f"{shlex.quote(exe)} --trigger {shlex.quote(name)}"

    client = get_trigger_client_path()
    if client is not None:
        # System python3 is fine (stdlib-only client); fall back to current interpreter.
        py = "python3" if is_linux() else sys.executable
        return f"{shlex.quote(py)} {shlex.quote(str(client))} {shlex.quote(name)}"

    # Module form still avoids full main.py import graph when run as -m
    return f"{shlex.quote(sys.executable)} -m src.platform.ipc {shlex.quote(name)}"


def format_trigger_command_display(trigger: str) -> str:
    """
    Short human-readable trigger line for Settings (not necessarily shell-safe).

    Compiled: launcher basename. Source: fast client / module form.
    """
    name = (trigger or "").strip().lower() or "?"
    if is_compiled():
        exe = get_start_executable()
        base = Path(exe).name if exe else "AIPromptBridge"
        return f"{base} --trigger {name}"
    client = get_trigger_client_path()
    if client is not None:
        return f"python3 {client.name} {name}"
    return f"python -m src.platform.ipc {name}"


def list_trigger_commands() -> list[tuple[str, str]]:
    """
    ``(trigger_name, full_command)`` pairs for Settings / docs.

    Uses ``KNOWN_TRIGGERS``; omits entries that cannot be resolved.
    """
    from .platform.ipc import KNOWN_TRIGGERS

    rows: list[tuple[str, str]] = []
    for name in KNOWN_TRIGGERS:
        cmd = format_trigger_command(name)
        if cmd:
            rows.append((name, cmd))
    return rows


# ─── Launcher detection (Windows + Linux split layout) ───────────────────────


def _preferred_launcher_names() -> list[str]:
    """
    Ordered list of outer launcher basenames for the current platform/mode.

    Windows split build uses ``AIPromptBridge.exe`` / ``AIPromptBridge-NoConsole.exe``.
    Linux Nuitka packaging uses a single shell wrapper ``AIPromptBridge`` at deploy root.
    """
    launched_mode = None
    for arg in sys.argv:
        if arg.startswith("--launched-mode="):
            launched_mode = arg.split("=", 1)[1].strip().lower()
            break

    if is_linux():
        # Single console-oriented wrapper; no separate NoConsole binary.
        return ["AIPromptBridge"]

    if launched_mode == "gui":
        return ["AIPromptBridge-NoConsole.exe", "AIPromptBridge.exe"]
    return ["AIPromptBridge.exe", "AIPromptBridge-NoConsole.exe"]


def get_launcher_path() -> Optional[str]:
    """
    Get the absolute path to the appropriate outer launcher executable.

    Deployment structure (Windows and Linux):
    - Root/
      - AIPromptBridge[.exe] (outer launcher / shell wrapper)
      - AIPromptBridge-NoConsole.exe (Windows GUI launcher only)
      - bin/
        - AIPromptBridge_Internal[.exe] (this process when compiled)

    Returns:
        Path to the launcher executable (str) or None if not found.
    """
    launchers_to_check = _preferred_launcher_names()
    preferred_launcher = launchers_to_check[0]

    # 2. Determine potential root directories
    search_roots = []

    if is_compiled():
        exe_path = Path(sys.executable).resolve()

        # PATH STRATEGY 1: Split Structure (bin/Internal -> ../Launcher)
        # This is the standard release structure
        if exe_path.parent.name.lower() == "bin":
            search_roots.append(exe_path.parent.parent)

        # PATH STRATEGY 2: Flat Structure (Internal -> ./Launcher)
        search_roots.append(exe_path.parent)

        # PATH STRATEGY 3: Main Module CWD override
        # main.py sets CWD to root_dir in setup_workspace()
        search_roots.append(Path.cwd())

    else:
        # Development Mode
        # Assuming struct: src/startup_manager.py -> src/launchers/
        current_file = Path(__file__).resolve()
        src_dir = current_file.parent.parent

        search_roots.append(src_dir / "src" / "launchers")
        search_roots.append(src_dir / "launchers")
        search_roots.append(Path.cwd() / "src" / "launchers")

    # 3. Scan for launchers
    for root in search_roots:
        if not root.exists():
            continue

        for launcher_name in launchers_to_check:
            candidate = root / launcher_name
            if candidate.is_file():
                return str(candidate.resolve())

    # 4. Dev Fallback: Return script path if no exe found
    # (Only in dev mode; Windows launchers only)
    if not is_compiled() and not is_linux():
        for root in search_roots:
            if preferred_launcher == "AIPromptBridge-NoConsole.exe":
                candidate = root / "launcher_gui.py"
            else:
                candidate = root / "launcher_console.py"

            if candidate.is_file():
                # In dev, we can't really set registry run to a .py file easily
                # without python.exe, but we return it for info purposes.
                return str(candidate.resolve())

    return None


# ─── Linux XDG autostart ──────────────────────────────────────────────────────


def _autostart_dir() -> Path:
    """XDG autostart directory (``$XDG_CONFIG_HOME/autostart`` or ``~/.config/autostart``)."""
    xdg = os.environ.get("XDG_CONFIG_HOME", "").strip()
    if xdg:
        return Path(xdg) / "autostart"
    return Path.home() / ".config" / "autostart"


def get_autostart_desktop_path() -> Path:
    """Full path to the AIPromptBridge XDG autostart desktop file."""
    return _autostart_dir() / DESKTOP_FILENAME


def _parse_desktop_disabled(content: str) -> bool:
    """
    Return True if the desktop entry is explicitly disabled.

    Honors ``Hidden=true`` and ``X-GNOME-Autostart-enabled=false`` (case-insensitive).
    """
    for raw in content.splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or line.startswith("["):
            continue
        if "=" not in line:
            continue
        key, _, value = line.partition("=")
        key_l = key.strip().lower()
        val_l = value.strip().lower()
        if key_l == "hidden" and val_l in ("true", "1", "yes"):
            return True
        if key_l == "x-gnome-autostart-enabled" and val_l in ("false", "0", "no"):
            return True
    return False


def _is_linux_startup_enabled() -> bool:
    path = get_autostart_desktop_path()
    if not path.is_file():
        return False
    try:
        content = path.read_text(encoding="utf-8")
    except OSError:
        return False
    return not _parse_desktop_disabled(content)


def _build_desktop_entry() -> Tuple[Optional[str], Optional[str]]:
    """
    Build desktop file body and error message.

    Compiled: ``Exec=<launcher|binary>``, ``Path=<deploy root>``.
    Source: ``Exec=<python> <main.py>``, ``Path=<project root>``.

    Returns:
        (content, None) on success, or (None, error_message) on failure.
    """
    root = get_project_root()
    exec_line = format_start_command()
    if not exec_line:
        if is_compiled():
            return None, "Could not determine compiled executable path for autostart."
        return None, "Could not find main.py (is the project root correct?)"

    path_line = str(root.resolve())

    lines = [
        "[Desktop Entry]",
        "Type=Application",
        "Version=1.0",
        f"Name={APP_NAME}",
        "Comment=AI Desktop Tools & Integration Bridge",
        f"Exec={exec_line}",
        f"Path={path_line}",
        "Terminal=false",
        "Categories=Utility;",
        "StartupNotify=false",
        "X-GNOME-Autostart-enabled=true",
    ]

    icon = root / "icon.ico"
    if icon.is_file():
        lines.append(f"Icon={icon.resolve()}")

    lines.append("")  # trailing newline
    return "\n".join(lines), None


def _set_linux_startup(enabled: bool) -> Tuple[bool, str]:
    desktop_path = get_autostart_desktop_path()

    if not enabled:
        try:
            if desktop_path.is_file():
                desktop_path.unlink()
                return True, f"Removed autostart: {desktop_path}"
            return True, "Autostart entry not found (already disabled)"
        except OSError as e:
            return False, f"Failed to remove autostart file: {e}"

    content, err = _build_desktop_entry()
    if content is None:
        return False, err or "Failed to build desktop entry"

    try:
        desktop_path.parent.mkdir(parents=True, exist_ok=True)
        # Atomic write: temp in same dir then replace
        fd, tmp_name = tempfile.mkstemp(
            prefix=".aipromptbridge-",
            suffix=".desktop.tmp",
            dir=str(desktop_path.parent),
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                fh.write(content)
            Path(tmp_name).replace(desktop_path)
        except Exception:
            try:
                os.unlink(tmp_name)
            except OSError:
                pass
            raise
        return True, f"Added to autostart: {desktop_path}"
    except PermissionError:
        return False, f"Permission denied writing {desktop_path}"
    except OSError as e:
        return False, f"Failed to write autostart file: {e}"


def _linux_startup_info() -> dict:
    info: dict = {
        "enabled": _is_linux_startup_enabled(),
        "path": None,
        "mode": "compiled" if is_compiled() else "source",
    }
    # Mirror Windows: surface launched-mode when present
    for arg in sys.argv:
        if arg.startswith("--launched-mode="):
            info["mode"] = arg.split("=", 1)[1]
            break

    cmd = format_start_command()
    root = get_project_root()
    if cmd:
        info["path"] = f"{cmd}  (Path={root})"
    else:
        info["path"] = None
    return info


# ─── Windows registry ─────────────────────────────────────────────────────────


def _is_windows_startup_enabled() -> bool:
    import winreg

    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY_PATH, 0, winreg.KEY_READ) as key:
            value, _ = winreg.QueryValueEx(key, APP_NAME)
            return bool(value)
    except FileNotFoundError:
        return False
    except Exception:
        return False


def _set_windows_startup(enabled: bool) -> Tuple[bool, str]:
    import winreg

    try:
        if enabled:
            launcher_path = get_launcher_path()

            if not launcher_path:
                return (
                    False,
                    "Could not determine launcher path. This feature requires the application to be installed/compiled.",
                )

            # Use abspath to strictly ensure full path
            launcher_path = str(Path(launcher_path).resolve())

            # Check if it's a python script (Dev mode protection)
            if launcher_path.endswith(".py"):
                return False, "Cannot set startup in development mode (launcher is a .py script)."

            # Open key for writing
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY_PATH, 0, winreg.KEY_SET_VALUE) as key:
                # Add quotes around path to handle spaces
                cmd_line = f'"{launcher_path}"'
                winreg.SetValueEx(key, APP_NAME, 0, winreg.REG_SZ, cmd_line)
                return True, f"Added to startup: {APP_NAME}"

        else:
            # Disable
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY_PATH, 0, winreg.KEY_SET_VALUE) as key:
                try:
                    winreg.DeleteValue(key, APP_NAME)
                    return True, f"Removed from startup: {APP_NAME}"
                except FileNotFoundError:
                    return True, "Startup entry not found (already disabled)"

    except PermissionError:
        return False, "Permission denied. Try running as Administrator."
    except Exception as e:
        return False, f"Registry Error: {e!s}"


def _windows_startup_info() -> dict:
    info: dict = {"enabled": _is_windows_startup_enabled(), "path": None, "mode": "unknown"}

    for arg in sys.argv:
        if arg.startswith("--launched-mode="):
            info["mode"] = arg.split("=")[1]
            break

    info["path"] = get_launcher_path()
    return info


# ─── Public API ───────────────────────────────────────────────────────────────


def is_startup_enabled() -> bool:
    """
    Check if the application is set to run at login / OS startup.

    Returns:
        True if startup is enabled, False otherwise.
    """
    if is_windows():
        return _is_windows_startup_enabled()
    if is_linux():
        return _is_linux_startup_enabled()
    return False


def set_startup(enabled: bool) -> Tuple[bool, str]:
    """
    Enable or disable launch-at-login for the application.

    Args:
        enabled: True to enable startup, False to disable.

    Returns:
        Tuple of (success: bool, message: str)
    """
    if is_windows():
        return _set_windows_startup(enabled)
    if is_linux():
        return _set_linux_startup(enabled)
    return False, "Startup management is only available on Windows and Linux."


def get_startup_info() -> dict:
    """
    Get current startup configuration info.

    Returns:
        Dict with 'enabled' (bool), 'path' (str or None), 'mode' (str or None)
    """
    if is_windows():
        return _windows_startup_info()
    if is_linux():
        return _linux_startup_info()
    return {"enabled": False, "path": None, "mode": "unsupported"}
