"""
Focused window classifier for terminal-safe clipboard shortcuts.

Detects whether the currently focused application is a terminal emulator
so that selection capture can use Ctrl+Shift+C instead of Ctrl+C
(which would send SIGINT to terminal foreground processes).

Linux/Wayland: compositor IPC (niri, Sway, Hyprland) to query app_id/app_name.
Windows: GetForegroundWindow + process executable name.

Intentionally free of GUI / audio / provider imports.
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
from typing import Optional

from .detect import is_linux, is_wayland, is_windows

logger = logging.getLogger(__name__)

# Subprocess timeout — never block the capture path.
_QUERY_TIMEOUT = 0.15

# Known terminal emulator identifiers (lowercase).
# Matches against app_id (Wayland), process name (Windows), or title heuristics.
_TERMINAL_APP_IDS: frozenset[str] = frozenset(
    {
        # Linux terminal emulators (Wayland app_id / X11 WM_CLASS)
        "foot",
        "footclient",
        "kitty",
        "alacritty",
        "ghostty",
        "com.mitchellh.ghostty",
        "wezterm",
        "wezterm-gui",
        "org.wezfurlong.wezterm",
        "gnome-terminal",
        "gnome-terminal-server",
        "org.gnome.terminal",
        "org.gnome.console",
        "console",
        "kgx",  # GNOME Console
        "konsole",
        "org.kde.konsole",
        "xfce4-terminal",
        "mate-terminal",
        "lxterminal",
        "sakura",
        "terminator",
        "tilix",
        "guake",
        "yakuake",
        "tilda",
        "urxvt",
        "rxvt",
        "xterm",
        "st",
        "st-256color",
        "contour",
        "rio",
        "cosmic-term",
        "com.system76.cosmicterm",
        "ptyxis",  # GNOME Ptyxis
        "org.gnome.ptyxis",
        "blackbox",
        "com.raggesilver.blackbox",
        # Windows terminal emulators (process basenames without .exe)
        "windowsterminal",
        "cmd",
        "powershell",
        "pwsh",
        "conhost",
        "mintty",
        "putty",
        "mobaxterm",
        "hyper",
        "tabby",
        "terminus",
        "wt",  # Windows Terminal (wt.exe)
        # tmux / screen inside any terminal
        "tmux",
        "screen",
    }
)

# User-configurable overrides are merged at runtime.
_user_terminal_ids: set[str] = set()


def set_user_terminal_ids(ids: list[str] | set[str] | None) -> None:
    """Set user-configured extra terminal app IDs (call once at startup)."""
    global _user_terminal_ids
    _user_terminal_ids = {s.strip().lower() for s in (ids or []) if s and s.strip()}


def _is_known_terminal(app_id: str) -> bool:
    """Check if an app_id matches any known terminal emulator.

    Also checks the last segment of dotted reverse-DNS app_ids
    (e.g. ``com.mitchellh.ghostty`` matches ``ghostty``).
    """
    lower = app_id.strip().lower()
    if lower in _TERMINAL_APP_IDS or lower in _user_terminal_ids:
        return True
    # Try the last segment of reverse-DNS identifiers (e.g. com.mitchellh.ghostty -> ghostty)
    if "." in lower:
        last_segment = lower.rsplit(".", 1)[-1]
        if last_segment and (last_segment in _TERMINAL_APP_IDS or last_segment in _user_terminal_ids):
            return True
    return False


def _run_command(args: list[str]) -> Optional[str]:
    """Run a short-lived command and return stdout on success."""
    try:
        result = subprocess.run(args, capture_output=True, text=True, check=False, timeout=_QUERY_TIMEOUT)
        if result.returncode != 0:
            return None
        return result.stdout.strip()
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError) as exc:
        logger.debug("focused_window query failed (%s): %s", args[0], exc)
        return None


# ── Compositor-specific focused window queries ────────────────────────────


def _get_niri_focused_app_id() -> Optional[str]:
    """Query niri for the focused window's app_id."""
    if not os.environ.get("NIRI_SOCKET") and "niri" not in _desktop_names():
        return None
    if not shutil.which("niri"):
        return None
    output = _run_command(["niri", "msg", "-j", "focused-window"])
    if not output:
        return None
    try:
        data = json.loads(output)
        return data.get("app_id") or None
    except (json.JSONDecodeError, TypeError):
        return None


def _get_sway_focused_app_id() -> Optional[str]:
    """Query Sway for the focused window's app_id."""
    if not os.environ.get("SWAYSOCK") and "sway" not in _desktop_names():
        return None
    if not shutil.which("swaymsg"):
        return None
    output = _run_command(["swaymsg", "-t", "get_tree", "-r"])
    if not output:
        return None
    try:
        tree = json.loads(output)
        return _find_sway_focused_app_id(tree)
    except (json.JSONDecodeError, TypeError):
        return None


def _find_sway_focused_app_id(node: dict) -> Optional[str]:
    """Recursively find the focused leaf node in a Sway tree."""
    if not isinstance(node, dict):
        return None
    # Leaf focused node
    if node.get("focused") and node.get("app_id"):
        return node["app_id"]
    if node.get("focused") and node.get("window_properties", {}).get("class"):
        return node["window_properties"]["class"]
    # Recurse into child nodes
    for key in ("nodes", "floating_nodes"):
        children = node.get(key)
        if isinstance(children, list):
            for child in children:
                result = _find_sway_focused_app_id(child)
                if result:
                    return result
    return None


def _get_hyprland_focused_app_id() -> Optional[str]:
    """Query Hyprland for the focused window's class."""
    if not os.environ.get("HYPRLAND_INSTANCE_SIGNATURE") and "hyprland" not in _desktop_names():
        return None
    if not shutil.which("hyprctl"):
        return None
    output = _run_command(["hyprctl", "activewindow", "-j"])
    if not output:
        return None
    try:
        data = json.loads(output)
        return data.get("class") or data.get("initialClass") or None
    except (json.JSONDecodeError, TypeError):
        return None


def _desktop_names() -> set[str]:
    """Return normalized desktop labels."""
    names: set[str] = set()
    for key in ("XDG_CURRENT_DESKTOP", "XDG_SESSION_DESKTOP"):
        names.update(part.strip().lower() for part in os.environ.get(key, "").split(":"))
    return names


# ── Windows focused window query ──────────────────────────────────────────


def _get_windows_focused_process_name() -> Optional[str]:
    """Get the process name of the foreground window on Windows."""
    if not is_windows():
        return None
    try:
        import ctypes

        user32 = ctypes.windll.user32
        hwnd = user32.GetForegroundWindow()
        if not hwnd:
            return None

        # Get process ID
        pid = ctypes.c_ulong()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        if not pid.value:
            return None

        # Open process and get executable name
        import ctypes.wintypes

        kernel32 = ctypes.windll.kernel32
        PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
        handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid.value)
        if not handle:
            return None

        try:
            buf = ctypes.create_unicode_buffer(260)
            size = ctypes.c_ulong(260)
            if kernel32.QueryFullProcessImageNameW(handle, 0, buf, ctypes.byref(size)):
                # Extract basename without extension
                path = buf.value
                name = path.rsplit("\\", 1)[-1]
                if name.lower().endswith(".exe"):
                    name = name[:-4]
                return name.lower()
        finally:
            kernel32.CloseHandle(handle)
    except Exception as e:
        logger.debug("Windows focused process query failed: %s", e)
    return None


# ── Public API ────────────────────────────────────────────────────────────


def get_focused_app_id() -> Optional[str]:
    """Return the app_id / process name of the currently focused window.

    Returns None if detection is not available or fails.
    """
    if is_linux() and is_wayland():
        for getter in (_get_niri_focused_app_id, _get_sway_focused_app_id, _get_hyprland_focused_app_id):
            result = getter()
            if result:
                return result
        return None

    if is_windows():
        return _get_windows_focused_process_name()

    return None


def is_focused_app_terminal() -> bool:
    """Return True if the currently focused application is a terminal emulator.

    Used to decide whether to send Ctrl+Shift+C (terminal-safe) instead of
    Ctrl+C (which sends SIGINT in terminals).
    """
    app_id = get_focused_app_id()
    if not app_id:
        return False
    return _is_known_terminal(app_id)
