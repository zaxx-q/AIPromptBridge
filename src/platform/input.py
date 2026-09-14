"""
Platform virtual-keyboard input service (Wayland / wlroots).

Linux: uses ``wlrctl`` (virtual-keyboard protocol) for typing and key chords.
No root required. Intentionally free of GUI / audio / provider imports.

Windows call sites keep SendInput / pynput; this module returns False on non-Linux.
"""

from __future__ import annotations

import atexit
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

# Cached binary paths (process-lifetime)
_wtype_path: Optional[str] = None
_wlrctl_path: Optional[str] = None
_availability_checked = False
_availability_lock = threading.Lock()
_missing_warned = False

# Active typing subprocess tracking for immediate abort & clean shutdown
_active_typing_proc: Optional[subprocess.Popen] = None
_proc_lock = threading.Lock()


def abort_typing() -> None:
    """Immediately terminate any currently active virtual keyboard typing subprocess."""
    global _active_typing_proc
    with _proc_lock:
        if _active_typing_proc is not None:
            try:
                if _active_typing_proc.poll() is None:
                    _active_typing_proc.terminate()
                    try:
                        _active_typing_proc.wait(timeout=0.1)
                    except subprocess.TimeoutExpired:
                        _active_typing_proc.kill()
            except Exception as e:
                logger.debug("abort_typing failed to terminate proc: %s", e)
            finally:
                _active_typing_proc = None


# Ensure any spawned typing process is killed if the app exits or restarts
atexit.register(abort_typing)

# Canonical modifier names accepted by wlrctl
_VALID_MODIFIERS = frozenset({"SHIFT", "CTRL", "ALT", "SUPER"})


def _refresh_binary_cache() -> None:
    """Resolve wtype / wlrctl paths once (thread-safe)."""
    global _wtype_path, _wlrctl_path, _availability_checked, _missing_warned
    with _availability_lock:
        if _availability_checked:
            return
        found_wtype = shutil.which("wtype")
        if found_wtype and "wtype" in found_wtype.lower():
            _wtype_path = found_wtype
        else:
            _wtype_path = None

        found_wlrctl = shutil.which("wlrctl")
        if found_wlrctl and "wlrctl" in found_wlrctl.lower():
            _wlrctl_path = found_wlrctl
        else:
            _wlrctl_path = None

        _availability_checked = True
        if not (_wtype_path or _wlrctl_path) and is_linux() and not _missing_warned:
            _missing_warned = True
            logger.warning(
                "Virtual keyboard binary not found on PATH (tried 'wtype', 'wlrctl'). "
                "Install package 'wtype' (recommended) or 'wlrctl' for Wayland "
                "virtual-keyboard type/paste (wlroots compositors such as Sway/niri/Hyprland). "
                "Replace/type/paste into focused apps will fail until one is available."
            )


def is_keyboard_input_available() -> bool:
    """Return True when a virtual keyboard backend (wtype or wlrctl) is on PATH (Linux only)."""
    if not is_linux():
        return False
    _refresh_binary_cache()
    return bool(_wtype_path or _wlrctl_path)


def is_wlrctl_available() -> bool:
    """Return True when virtual keyboard input is available (backwards-compatible alias)."""
    return is_keyboard_input_available()


def get_keyboard_backend() -> str:
    """Return active keyboard backend name: 'wtype', 'wlrctl', or 'none'."""
    if not is_linux():
        return "none"
    _refresh_binary_cache()
    if _wtype_path:
        return "wtype"
    if _wlrctl_path:
        return "wlrctl"
    return "none"


def backend_supports_keystroke_delay() -> bool:
    """Return True if active backend handles per-keystroke delay internally (wtype -d)."""
    return get_keyboard_backend() == "wtype"


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


def _press_chord_wtype(modifiers: list[str], key: str) -> bool:
    """Send chord via wtype -M <mod> -k <key> -m <mod>."""
    if not _wtype_path:
        return False
    wtype_mods: list[str] = []
    for mod in modifiers:
        name = str(mod).strip().upper()
        if name in ("CONTROL", "CTL", "CTRL"):
            wtype_mods.append("ctrl")
        elif name in ("SHIFT",):
            wtype_mods.append("shift")
        elif name in ("ALT",):
            wtype_mods.append("alt")
        elif name in ("SUPER", "WIN", "META", "CMD", "COMMAND", "LOGO"):
            wtype_mods.append("logo")
        elif name.lower() in ("capslock", "altgr"):
            wtype_mods.append(name.lower())
        else:
            logger.debug("Unknown modifier for wtype: %r", mod)
            return False

    cmd = [_wtype_path]
    for m in wtype_mods:
        cmd.extend(["-M", m])

    k = key
    if k == "\n":
        k = "Return"
    elif k == "\t":
        k = "Tab"
    elif k == " ":
        k = "space"
    cmd.extend(["-k", k])

    for m in reversed(wtype_mods):
        cmd.extend(["-m", m])

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            check=False,
            timeout=_CHORD_TIMEOUT,
        )
        return result.returncode == 0
    except subprocess.TimeoutExpired:
        logger.warning("wtype chord timed out")
        return False
    except FileNotFoundError:
        return False
    except Exception as e:
        logger.debug("wtype chord failed: %s", e)
        return False


def _press_chord_wlrctl(modifiers: list[str], key: str) -> bool:
    """Send chord via wlrctl keyboard type <key> modifiers <MODS>."""
    try:
        mod_str = _normalize_modifiers(modifiers)
    except ValueError as e:
        logger.debug("press_chord (wlrctl): %s", e)
        return False

    args = ["keyboard", "type", key]
    if mod_str:
        args.extend(["modifiers", mod_str])
    return _run_wlrctl(args, timeout=_CHORD_TIMEOUT)


def press_chord(modifiers: list[str], key: str) -> bool:
    """
    Type a single key while holding modifiers (e.g. Ctrl+V).

    Uses ``wtype`` if available, otherwise ``wlrctl``.

    Args:
        modifiers: e.g. ``["CTRL"]`` or ``["SHIFT"]``
        key: Single character / short string to type under those modifiers
             (e.g. ``"v"``, ``"c"``, ``"\\n"``).

    Returns:
        True if virtual keyboard reported success.
    """
    if not is_linux():
        return False
    if not key:
        return False

    backend = get_keyboard_backend()
    if backend == "wtype":
        return _press_chord_wtype(modifiers, key)
    elif backend == "wlrctl":
        return _press_chord_wlrctl(modifiers, key)
    return False


def _press_chord_prefer_wlrctl(modifiers: list[str], key: str) -> bool:
    """Send a key chord preferring wlrctl over wtype.

    wtype can emit a spurious Escape event when sending modifier chords like
    Ctrl+C, which confuses some applications. wlrctl does not have this quirk,
    so clipboard shortcuts (copy/paste) prefer wlrctl when available and only
    fall back to wtype.
    """
    if not is_linux():
        return False
    if not key:
        return False
    _refresh_binary_cache()
    if _wlrctl_path:
        return _press_chord_wlrctl(modifiers, key)
    if _wtype_path:
        return _press_chord_wtype(modifiers, key)
    return False


def paste_via_clipboard_shortcut() -> bool:
    """Send Ctrl+V into the focused client (clipboard must already hold the text)."""
    return _press_chord_prefer_wlrctl(["CTRL"], "v")


def copy_via_clipboard_shortcut() -> bool:
    """Send Ctrl+C into the focused client (optional hybrid capture helper)."""
    return _press_chord_prefer_wlrctl(["CTRL"], "c")


def copy_via_clipboard_shortcut_shifted() -> bool:
    """Send Ctrl+Shift+C into the focused client (terminal-safe copy).

    Terminal emulators use Ctrl+Shift+C for copy (Ctrl+C sends SIGINT).
    """
    return _press_chord_prefer_wlrctl(["CTRL", "SHIFT"], "c")


def _type_segment(segment: str, *, timeout: float = _TYPE_TIMEOUT) -> bool:
    """Type a plain string segment (no modifiers) via wlrctl. Empty segment is a no-op success."""
    if not segment:
        return True
    return _run_wlrctl(["keyboard", "type", segment], timeout=timeout)


def _type_segment_wtype(
    segment: str,
    *,
    delay_ms: int = 0,
    timeout: float = _TYPE_TIMEOUT,
    abort_check: Optional[Callable[[], bool]] = None,
) -> bool:
    """Type a string segment via wtype using stdin with native per-keystroke delay.

    Checks ``abort_check`` periodically during typing so that high delays can be
    cancelled immediately without typing remaining characters.
    """
    global _active_typing_proc
    if not segment:
        return True
    if not _wtype_path:
        return False
    args = [_wtype_path]
    if delay_ms and delay_ms > 0:
        args.extend(["-d", str(int(delay_ms))])
    args.append("-")
    try:
        expected_time = (len(segment) * max(0, delay_ms)) / 1000.0
        effective_timeout = max(timeout, expected_time + 5.0)

        proc = subprocess.Popen(
            args,
            stdin=subprocess.PIPE,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
        )
        with _proc_lock:
            _active_typing_proc = proc

        try:
            proc.stdin.write(segment.encode("utf-8"))
            proc.stdin.close()
        except (BrokenPipeError, OSError):
            pass

        start = time.time()
        while proc.poll() is None:
            if abort_check is not None:
                try:
                    if abort_check():
                        logger.debug("wtype aborted by abort_check during typing")
                        abort_typing()
                        return False
                except Exception as e:
                    logger.debug("wtype abort_check error: %s", e)
                    abort_typing()
                    return False

            if (time.time() - start) > effective_timeout:
                logger.warning("wtype timed out after %ss", effective_timeout)
                abort_typing()
                return False

            time.sleep(0.015)

        with _proc_lock:
            _active_typing_proc = None

        if proc.returncode != 0:
            stderr = proc.stderr.read() if proc.stderr else b""
            logger.debug(
                "wtype failed (rc=%s) stderr=%s",
                proc.returncode,
                stderr.decode("utf-8", errors="replace").strip() or "(empty)",
            )
            return False
        return True
    except subprocess.TimeoutExpired:
        logger.warning("wtype timed out after %ss", timeout)
        abort_typing()
        return False
    except FileNotFoundError:
        return False
    except Exception as e:
        logger.debug("wtype run failed: %s", e)
        abort_typing()
        return False


def _paste_segment_fallback(segment: str) -> bool:
    """
    Fallback: paste segment via wl-copy + Ctrl+V when wlrctl cannot type Unicode.

    Restores previous clipboard content afterward.
    """
    from .clipboard import copy_text, paste_text

    try:
        backup = paste_text(primary=False)
    except Exception:
        backup = ""

    try:
        if not copy_text(segment, primary=False):
            return False
        time.sleep(0.01)
        return paste_via_clipboard_shortcut()
    finally:
        try:
            time.sleep(0.02)
            copy_text(backup, primary=False)
        except Exception:
            pass


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
    Type a Unicode string into the focused client via ``wtype`` or ``wlrctl``.

    With ``wtype``, keystrokes are naturally delayed via ``-d <delay_ms>`` for smooth,
    word-by-word typing with full Unicode and emoji support.
    With ``wlrctl``, chunks are sent via ``wlrctl keyboard type`` with clipboard paste
    fallback for non-ASCII characters to prevent unfinished stream drops.

    Newlines are sent as Shift+Enter (same intent as Windows streaming type). Carriage
    returns (``\\r``) are skipped.

    Args:
        text: Text to type
        delay_ms: Optional delay between keystrokes (wtype) or between chunks (wlrctl)
        abort_check: Optional callable; if it returns True, stop and return False

    Returns:
        True if all chunks succeeded (or text was empty). False on failure / abort.
    """
    if not is_linux():
        return False
    if not is_keyboard_input_available():
        return False
    if text is None:
        return False
    if text == "":
        return True

    # Normalize Windows line endings; keep \\n for Shift+Enter handling.
    normalized = text.replace("\r\n", "\n").replace("\r", "")

    # Build work units: plain segments (further size-chunked) and newline markers.
    parts = normalized.split("\n")
    units: list[tuple[str, str]] = []  # ("text", segment) | ("nl", "")
    for i, part in enumerate(parts):
        if part:
            for start in range(0, len(part), _TYPE_CHUNK_SIZE):
                units.append(("text", part[start : start + _TYPE_CHUNK_SIZE]))
        if i < len(parts) - 1:
            units.append(("nl", ""))

    if not units:
        return True

    backend = get_keyboard_backend()
    delay_s = max(0, int(delay_ms)) / 1000.0 if delay_ms else 0.0

    if backend == "wtype":
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
                ok = _type_segment_wtype(payload, delay_ms=delay_ms, abort_check=abort_check)
            if not ok:
                return False
        return True

    # Fallback: wlrctl
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
                # wlrctl failed (e.g. non-ASCII string). Fall back to paste so
                # typing is not left unfinished.
                logger.debug("wlrctl typing failed; falling back to clipboard paste for segment")
                ok = _paste_segment_fallback(payload)
        if not ok:
            return False

        # Sleep between chunks only for wlrctl (which lacks per-keystroke internal delay)
        if delay_s > 0 and idx < len(units) - 1:
            time.sleep(delay_s)

    return True
