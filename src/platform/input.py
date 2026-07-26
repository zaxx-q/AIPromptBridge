"""
Platform virtual-keyboard input service (Wayland / wlroots).

Linux: uses ``wlrctl`` (virtual-keyboard protocol) for typing and key chords.
No root required. Intentionally free of GUI / audio / provider imports.

Windows call sites keep SendInput / pynput; this module returns False on non-Linux.
"""

from __future__ import annotations

import logging
import shutil
import subprocess
import threading
import time
from collections.abc import Callable
from typing import Optional

from .detect import is_linux

logger = logging.getLogger(__name__)

# Subprocess timeouts — never hang forever waiting on a compositor.
_CHORD_TIMEOUT = 5.0
_TYPE_TIMEOUT = 15.0

# Long strings are split so one hung compositor cannot block forever on a
# single giant argv, and so abort checks can run between chunks.
_TYPE_CHUNK_SIZE = 400

# Cached binary path (process-lifetime)
_wlrctl_path: Optional[str] = None
_availability_checked = False
_availability_lock = threading.Lock()
_missing_warned = False

# Canonical modifier names accepted by wlrctl
_VALID_MODIFIERS = frozenset({"SHIFT", "CTRL", "ALT", "SUPER"})


def _refresh_binary_cache() -> None:
    """Resolve wlrctl path once (thread-safe)."""
    global _wlrctl_path, _availability_checked, _missing_warned
    with _availability_lock:
        if _availability_checked:
            return
        _wlrctl_path = shutil.which("wlrctl")
        _availability_checked = True
        if not _wlrctl_path and is_linux() and not _missing_warned:
            _missing_warned = True
            logger.warning(
                "wlrctl not found on PATH. Install package 'wlrctl' for Wayland "
                "virtual-keyboard type/paste (wlroots compositors such as niri). "
                "Replace/type/paste into focused apps will fail until it is available."
            )


def is_wlrctl_available() -> bool:
    """Return True when ``wlrctl`` is on PATH (Linux only)."""
    if not is_linux():
        return False
    _refresh_binary_cache()
    return bool(_wlrctl_path)


def _normalize_modifiers(modifiers: list[str] | tuple[str, ...] | None) -> str:
    """
    Normalize modifier names to wlrctl's comma-separated uppercase form.

    Raises ValueError on unknown modifier names.
    """
    if not modifiers:
        return ""
    parts: list[str] = []
    for mod in modifiers:
        name = str(mod).strip().upper()
        # Accept common aliases
        if name in ("CONTROL", "CTL"):
            name = "CTRL"
        if name in ("WIN", "META", "CMD", "COMMAND"):
            name = "SUPER"
        if name not in _VALID_MODIFIERS:
            raise ValueError(f"Unknown modifier: {mod!r} (want SHIFT/CTRL/ALT/SUPER)")
        if name not in parts:
            parts.append(name)
    return ",".join(parts)


def _run_wlrctl(args: list[str], *, timeout: float) -> bool:
    """
    Run ``wlrctl`` with an argv list (never shell=True).

    Returns True on exit code 0.
    """
    if not is_wlrctl_available():
        return False
    cmd = [_wlrctl_path or "wlrctl", *args]
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            check=False,
            timeout=timeout,
        )
        if result.returncode != 0:
            stderr = (result.stderr or b"").decode("utf-8", errors="replace").strip()
            logger.debug(
                "wlrctl failed (rc=%s) cmd=%s stderr=%s",
                result.returncode,
                cmd,
                stderr or "(empty)",
            )
            return False
        return True
    except subprocess.TimeoutExpired:
        logger.warning("wlrctl timed out after %ss (cmd=%s)", timeout, cmd)
        return False
    except FileNotFoundError:
        return False
    except Exception as e:
        logger.debug("wlrctl run failed: %s", e)
        return False


def press_chord(modifiers: list[str], key: str) -> bool:
    """
    Type a single key while holding modifiers (e.g. Ctrl+V).

    Uses: ``wlrctl keyboard type <key> modifiers <MODS>``

    Args:
        modifiers: e.g. ``["CTRL"]`` or ``["SHIFT"]``
        key: Single character / short string to type under those modifiers
             (e.g. ``"v"``, ``"c"``, ``"\\n"``).

    Returns:
        True if wlrctl reported success.
    """
    if not is_linux():
        return False
    if not key:
        return False
    try:
        mod_str = _normalize_modifiers(modifiers)
    except ValueError as e:
        logger.debug("press_chord: %s", e)
        return False

    args = ["keyboard", "type", key]
    if mod_str:
        args.extend(["modifiers", mod_str])
    return _run_wlrctl(args, timeout=_CHORD_TIMEOUT)


def paste_via_clipboard_shortcut() -> bool:
    """Send Ctrl+V into the focused client (clipboard must already hold the text)."""
    return press_chord(["CTRL"], "v")


def copy_via_clipboard_shortcut() -> bool:
    """Send Ctrl+C into the focused client (optional hybrid capture helper)."""
    return press_chord(["CTRL"], "c")


def _type_segment(segment: str, *, timeout: float = _TYPE_TIMEOUT) -> bool:
    """Type a plain string segment (no modifiers). Empty segment is a no-op success."""
    if not segment:
        return True
    return _run_wlrctl(["keyboard", "type", segment], timeout=timeout)


def _type_newline_shift_enter() -> bool:
    """
    Insert a newline as Shift+Enter to avoid form-submit in chat-like targets.

    Mirrors Windows TextEdit streaming behavior (Shift+Enter for ``\\n``).
    """
    return press_chord(["SHIFT"], "\n")


def type_text(
    text: str,
    *,
    delay_ms: int = 0,
    abort_check: Optional[Callable[[], bool]] = None,
) -> bool:
    """
    Type a Unicode string into the focused client via ``wlrctl keyboard type``.

    Long strings are split into chunks (default ~400 chars). Newlines are sent
    as Shift+Enter (same intent as Windows streaming type). Carriage returns
    (``\\r``) are skipped.

    ``delay_ms`` sleeps between **chunks** only (per-character delay is
    approximate on Linux — one subprocess per chunk, not per character).

    Args:
        text: Text to type
        delay_ms: Optional delay between chunks (milliseconds)
        abort_check: Optional callable; if it returns True, stop and return False

    Returns:
        True if all chunks succeeded (or text was empty). False on failure / abort.
    """
    if not is_linux():
        return False
    if not is_wlrctl_available():
        return False
    if text is None:
        return False
    if text == "":
        return True

    # Normalize Windows line endings; keep \\n for Shift+Enter handling.
    normalized = text.replace("\r\n", "\n").replace("\r", "")

    # Build work units: plain segments (further size-chunked) and newline markers.
    # Using split keeps empty segments for leading/trailing/consecutive newlines.
    parts = normalized.split("\n")
    units: list[tuple[str, str]] = []  # ("text", segment) | ("nl", "")
    for i, part in enumerate(parts):
        if part:
            # Size-chunk plain text
            for start in range(0, len(part), _TYPE_CHUNK_SIZE):
                units.append(("text", part[start : start + _TYPE_CHUNK_SIZE]))
        if i < len(parts) - 1:
            units.append(("nl", ""))

    if not units:
        return True

    delay_s = max(0, int(delay_ms)) / 1000.0 if delay_ms else 0.0

    for idx, (kind, payload) in enumerate(units):
        if abort_check is not None:
            try:
                if abort_check():
                    logger.debug("type_text aborted by abort_check")
                    return False
            except Exception as e:
                logger.debug("type_text abort_check raised: %s", e)
                return False

        if kind == "nl":
            ok = _type_newline_shift_enter()
        else:
            ok = _type_segment(payload)
        if not ok:
            return False

        # Sleep between chunks only (not after the last unit)
        if delay_s > 0 and idx < len(units) - 1:
            time.sleep(delay_s)

    return True
