"""
Platform clipboard service (Wayland primary + clipboard).

Linux: uses ``wl-copy`` / ``wl-paste`` from wl-clipboard (no X11, no hard PyPI deps).
Windows: text helpers can fall through to call-site pyperclip / Win32 paths;
this module does not pull GUI or Win32 code.

Intentionally free of GUI / audio / provider imports.
"""

from __future__ import annotations

import logging
import shutil
import subprocess
import threading
from typing import Optional

from .detect import is_linux

logger = logging.getLogger(__name__)

# Subprocess timeouts — never hang forever waiting on a compositor.
_DEFAULT_TIMEOUT = 3.0
_LIST_TYPES_TIMEOUT = 2.0

# MIME defaults
_TEXT_MIME = "text/plain;charset=utf-8"
_IMAGE_PNG_MIME = "image/png"

# Cached binary availability (process-lifetime)
_wl_copy_path: Optional[str] = None
_wl_paste_path: Optional[str] = None
_availability_checked = False
_availability_lock = threading.Lock()
_missing_warned = False


def _refresh_binary_cache() -> None:
    """Resolve wl-copy / wl-paste paths once (thread-safe)."""
    global _wl_copy_path, _wl_paste_path, _availability_checked, _missing_warned
    with _availability_lock:
        if _availability_checked:
            return
        _wl_copy_path = shutil.which("wl-copy")
        _wl_paste_path = shutil.which("wl-paste")
        _availability_checked = True
        if not (_wl_copy_path and _wl_paste_path) and is_linux() and not _missing_warned:
            _missing_warned = True
            logger.warning(
                "wl-clipboard not found (need wl-copy and wl-paste). "
                "Install package 'wl-clipboard' for Wayland clipboard/selection support. "
                "Clipboard and primary-selection features will degrade gracefully."
            )


def is_wl_clipboard_available() -> bool:
    """Return True when both ``wl-copy`` and ``wl-paste`` are on PATH."""
    if not is_linux():
        return False
    _refresh_binary_cache()
    return bool(_wl_copy_path and _wl_paste_path)


def has_primary_selection() -> bool:
    """
    True when primary selection can be read on this platform.

    Wayland/Linux with wl-paste available → True. Otherwise False.
    """
    return is_wl_clipboard_available()


def _wl_args(base: list[str], *, primary: bool = False, mime: Optional[str] = None) -> list[str]:
    """Build wl-copy / wl-paste argv with optional --primary and MIME type."""
    args = list(base)
    if primary:
        args.append("--primary")
    if mime:
        args.extend(["--type", mime])
    return args


def _run_paste(
    args: list[str],
    *,
    timeout: float = _DEFAULT_TIMEOUT,
) -> subprocess.CompletedProcess[bytes]:
    """Run wl-paste (needs stdout)."""
    return subprocess.run(
        args,
        capture_output=True,
        check=False,
        timeout=timeout,
    )


def _run_copy(
    args: list[str],
    *,
    input_data: bytes,
    timeout: float = _DEFAULT_TIMEOUT,
) -> subprocess.CompletedProcess[bytes]:
    """
    Run wl-copy.

    Do **not** capture stdout/stderr: default wl-copy forks a background
    server that keeps inherited pipes open, so capture_output would hang
    until the selection is replaced.
    """
    return subprocess.run(
        args,
        input=input_data,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
        timeout=timeout,
    )


def copy_text(text: str, *, primary: bool = False) -> bool:
    """
    Copy UTF-8 text to the clipboard (or primary selection).

    On non-Linux, returns False (call sites should use pyperclip / Tk).
    """
    if not is_linux():
        return False
    if not is_wl_clipboard_available():
        return False
    try:
        args = _wl_args([_wl_copy_path or "wl-copy"], primary=primary)
        # Let wl-copy default MIME for plain text (widest client compatibility).
        result = _run_copy(args, input_data=text.encode("utf-8"), timeout=_DEFAULT_TIMEOUT)
        if result.returncode != 0:
            logger.debug("wl-copy failed (rc=%s)", result.returncode)
            return False
        return True
    except subprocess.TimeoutExpired:
        logger.warning("wl-copy timed out after %ss", _DEFAULT_TIMEOUT)
        return False
    except FileNotFoundError:
        return False
    except Exception as e:
        logger.debug("copy_text failed: %s", e)
        return False


def paste_text(*, primary: bool = False) -> str:
    """
    Paste UTF-8 text from the clipboard (or primary selection).

    Returns empty string on failure / missing binary / non-Linux.
    """
    if not is_linux():
        return ""
    if not is_wl_clipboard_available():
        return ""
    try:
        args = _wl_args([_wl_paste_path or "wl-paste", "--no-newline"], primary=primary)
        result = _run_paste(args, timeout=_DEFAULT_TIMEOUT)
        if result.returncode != 0:
            # Empty selection often exits non-zero; treat as empty.
            return ""
        return (result.stdout or b"").decode("utf-8", errors="replace")
    except subprocess.TimeoutExpired:
        logger.warning("wl-paste timed out after %ss", _DEFAULT_TIMEOUT)
        return ""
    except FileNotFoundError:
        return ""
    except Exception as e:
        logger.debug("paste_text failed: %s", e)
        return ""


def list_types(*, primary: bool = False) -> list[str]:
    """
    List MIME types available on the clipboard (or primary selection).

    Returns an empty list on failure / non-Linux.
    """
    if not is_linux():
        return []
    if not is_wl_clipboard_available():
        return []
    try:
        args = _wl_args([_wl_paste_path or "wl-paste", "--list-types"], primary=primary)
        result = _run_paste(args, timeout=_LIST_TYPES_TIMEOUT)
        if result.returncode != 0:
            return []
        out = (result.stdout or b"").decode("utf-8", errors="replace")
        return [line.strip() for line in out.splitlines() if line.strip()]
    except subprocess.TimeoutExpired:
        logger.warning("wl-paste --list-types timed out")
        return []
    except FileNotFoundError:
        return []
    except Exception as e:
        logger.debug("list_types failed: %s", e)
        return []


def paste_bytes(mime: str, *, primary: bool = False) -> bytes:
    """
    Paste raw bytes for a given MIME type (e.g. ``image/png``).

    Returns empty bytes on failure / non-Linux.
    """
    if not is_linux() or not mime:
        return b""
    if not is_wl_clipboard_available():
        return b""
    try:
        args = _wl_args([_wl_paste_path or "wl-paste"], primary=primary, mime=mime)
        result = _run_paste(args, timeout=_DEFAULT_TIMEOUT)
        if result.returncode != 0:
            return b""
        return result.stdout or b""
    except subprocess.TimeoutExpired:
        logger.warning("wl-paste (mime=%s) timed out", mime)
        return b""
    except FileNotFoundError:
        return b""
    except Exception as e:
        logger.debug("paste_bytes failed: %s", e)
        return b""


def copy_bytes(data: bytes, mime: str, *, primary: bool = False) -> bool:
    """
    Copy raw bytes with an explicit MIME type (best-effort for images).

    Returns False on failure / non-Linux.
    """
    if not is_linux() or not mime:
        return False
    if not is_wl_clipboard_available():
        return False
    try:
        args = _wl_args([_wl_copy_path or "wl-copy"], primary=primary, mime=mime)
        result = _run_copy(args, input_data=data, timeout=_DEFAULT_TIMEOUT)
        if result.returncode != 0:
            logger.debug("wl-copy (mime=%s) failed (rc=%s)", mime, result.returncode)
            return False
        return True
    except subprocess.TimeoutExpired:
        logger.warning("wl-copy (mime=%s) timed out", mime)
        return False
    except FileNotFoundError:
        return False
    except Exception as e:
        logger.debug("copy_bytes failed: %s", e)
        return False


def get_selected_text_wayland() -> str:
    """
    Read currently selected text on Wayland.

    Prefers **primary selection** (mouse highlight, no clipboard pollution).
    If primary is empty, falls back to a **read-only** clipboard paste
    (user may have already copied). Does **not** inject Ctrl+C.
    """
    if not is_linux():
        return ""

    primary = paste_text(primary=True)
    if primary and primary.strip():
        return primary

    # Optional read-only fallback: clipboard already filled by the user.
    clipboard = paste_text(primary=False)
    if clipboard and clipboard.strip():
        return clipboard

    return ""


def paste_image_png(*, primary: bool = False) -> bytes:
    """
    Convenience: paste PNG image bytes if available.

    Checks list_types for image/png (or any image/*) first when possible.
    """
    types = list_types(primary=primary)
    if types:
        if _IMAGE_PNG_MIME in types:
            return paste_bytes(_IMAGE_PNG_MIME, primary=primary)
        # Some apps offer image/png under slightly different labels
        for t in types:
            if t == "image/png" or t.startswith("image/png"):
                return paste_bytes(t, primary=primary)
        # No PNG offered
        return b""
    # list_types empty or failed — still try image/png directly
    return paste_bytes(_IMAGE_PNG_MIME, primary=primary)


# Public MIME constants for callers
TEXT_MIME = _TEXT_MIME
IMAGE_PNG_MIME = _IMAGE_PNG_MIME
