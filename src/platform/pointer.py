"""Best-effort Wayland cursor position lookup.

Tk's X11 pointer query can be stale when an Xwayland window is not focused.
Keep compositor-specific probing here so GUI code can safely fall back to Tk
when a compositor provides no cursor-position IPC.
"""

from __future__ import annotations

import json
import logging
import os
import re
import shutil
import subprocess
from typing import Any, Optional

from .detect import is_linux, is_wayland

logger = logging.getLogger(__name__)

# Cursor lookup is strictly a visual enhancement. Never let a stuck compositor
# command make popup creation feel slow.
_COMMAND_TIMEOUT = 0.05
_COORDINATE_PATTERN = re.compile(r"^\s*(-?\d+(?:\.\d+)?)\s*,\s*(-?\d+(?:\.\d+)?)\s*$")


def _run_command(args: list[str]) -> Optional[str]:
    """Run a short-lived compositor command and return its stdout on success."""
    try:
        result = subprocess.run(args, capture_output=True, text=True, check=False, timeout=_COMMAND_TIMEOUT)
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError) as exc:
        logger.debug("Pointer position command unavailable (%s): %s", args[0], exc)
        return None

    if result.returncode != 0:
        logger.debug("Pointer position command failed (%s): %s", args[0], result.stderr.strip())
        return None
    return result.stdout.strip()


def _parse_coordinate_pair(value: Any) -> Optional[tuple[int, int]]:
    """Parse a compositor coordinate pair without accepting unrelated JSON fields."""
    if isinstance(value, dict):
        x, y = value.get("x"), value.get("y")
        if isinstance(x, (int, float)) and isinstance(y, (int, float)):
            return int(x), int(y)
        return None

    if isinstance(value, str):
        match = _COORDINATE_PATTERN.match(value)
        if match:
            return int(float(match.group(1))), int(float(match.group(2)))
    return None


def _get_hyprland_pointer_position() -> Optional[tuple[int, int]]:
    if not shutil.which("hyprctl"):
        return None
    return _parse_coordinate_pair(_run_command(["hyprctl", "cursorpos"]))


def _find_sway_cursor_position(value: Any) -> Optional[tuple[int, int]]:
    """Find cursor-shaped fields in optional Sway seat JSON, if a version exposes them."""
    if isinstance(value, dict):
        for key in ("cursor", "cursor_position", "pointer_position"):
            position = _parse_coordinate_pair(value.get(key))
            if position is not None:
                return position
        for child in value.values():
            position = _find_sway_cursor_position(child)
            if position is not None:
                return position
    elif isinstance(value, list):
        for child in value:
            position = _find_sway_cursor_position(child)
            if position is not None:
                return position
    return None


def _get_sway_pointer_position() -> Optional[tuple[int, int]]:
    if not shutil.which("swaymsg"):
        return None
    output = _run_command(["swaymsg", "-t", "get_seats", "-r"])
    if not output:
        return None
    try:
        return _find_sway_cursor_position(json.loads(output))
    except json.JSONDecodeError:
        logger.debug("Sway seat query returned invalid JSON")
        return None


def _desktop_names() -> set[str]:
    """Return normalized desktop labels without assuming one environment variable."""
    names = set()
    for key in ("XDG_CURRENT_DESKTOP", "XDG_SESSION_DESKTOP"):
        names.update(part.strip().lower() for part in os.environ.get(key, "").split(":"))
    return names


def _is_niri_session() -> bool:
    """Detect niri so we do not probe unrelated compositor CLIs on its hot path."""
    return bool(os.environ.get("NIRI_SOCKET")) or "niri" in _desktop_names()


def _is_hyprland_session() -> bool:
    return bool(os.environ.get("HYPRLAND_INSTANCE_SIGNATURE")) or "hyprland" in _desktop_names()


def _is_sway_session() -> bool:
    return bool(os.environ.get("SWAYSOCK")) or "sway" in _desktop_names()


def get_pointer_position() -> Optional[tuple[int, int]]:
    """Return compositor cursor coordinates when available, otherwise ``None``.

    Hyprland exposes this directly. Sway is queried only when its seat JSON
    includes cursor fields (many releases do not). niri currently exposes no
    public cursor-position IPC, so it performs no compositor subprocess and
    callers intentionally fall back to Tk.
    """
    if not is_linux() or not is_wayland():
        return None

    if _is_niri_session():
        return None
    if _is_hyprland_session():
        return _get_hyprland_pointer_position()
    if _is_sway_session():
        return _get_sway_pointer_position()
    return None
