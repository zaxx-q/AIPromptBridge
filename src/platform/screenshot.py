"""
Platform screenshot service (Wayland / wlroots).

Linux: uses ``slurp`` for interactive region selection and ``grim`` for PNG
capture to stdout. No GUI imports — pure subprocess + timeouts.

Windows call sites keep PIL.ImageGrab + Tk overlay; this module returns
None / False on non-Linux.

Design (Option A from Phase 4 plan):
    This module returns raw PNG ``bytes`` only. Callers in the GUI layer
    convert to ``CaptureResult`` so the platform package stays free of
    GUI types and CaptureResult location assumptions.
"""

from __future__ import annotations

import logging
import shutil
import subprocess
import threading
from typing import Optional

from .detect import is_linux

logger = logging.getLogger(__name__)

# grim should finish quickly once geometry is known.
_GRIM_TIMEOUT = 15.0

# slurp blocks until the user selects a region or cancels (Escape).
# Do not use a short timeout — allow a long interactive wait.
_SLURP_TIMEOUT = 600.0  # 10 minutes; effectively "until user acts"

# Cached binary paths (process-lifetime)
_grim_path: Optional[str] = None
_slurp_path: Optional[str] = None
_availability_checked = False
_availability_lock = threading.Lock()
_missing_warned = False


def _refresh_binary_cache() -> None:
    """Resolve grim / slurp paths once (thread-safe)."""
    global _grim_path, _slurp_path, _availability_checked, _missing_warned
    with _availability_lock:
        if _availability_checked:
            return
        _grim_path = shutil.which("grim")
        _slurp_path = shutil.which("slurp")
        _availability_checked = True
        if not (_grim_path and _slurp_path) and is_linux() and not _missing_warned:
            _missing_warned = True
            logger.warning(
                "grim/slurp not found on PATH (need both). "
                "Install packages 'grim' and 'slurp' for Wayland region screenshots "
                "(wlroots compositors such as niri). SnipTool capture will be unavailable."
            )


def is_grim_slurp_available() -> bool:
    """Return True when both ``grim`` and ``slurp`` are on PATH (Linux only)."""
    if not is_linux():
        return False
    _refresh_binary_cache()
    return bool(_grim_path and _slurp_path)


def capture_region_interactive() -> bytes | None:
    """
    Run ``slurp`` then ``grim -g <geom> -`` for interactive region capture.

    Returns PNG bytes, or None if the user cancelled, tools are missing,
    or an error occurred.

    Notes:
        - ``slurp`` blocks until the user selects a region or presses Escape.
        - Geometry is passed as an argv element (never shell-interpolated).
        - Call from a background thread so the GUI/terminal loop is not frozen.
    """
    if not is_grim_slurp_available():
        logger.error(
            "Cannot capture region: grim and/or slurp not available. "
            "Install 'grim' and 'slurp' system packages."
        )
        return None

    geom = _run_slurp()
    if geom is None:
        return None

    return _run_grim_geometry(geom)


def capture_full_screen() -> bytes | None:
    """
    Capture all outputs via ``grim -`` (compositor-dependent composite).

    Returns PNG bytes, or None on failure / missing tools / non-Linux.
    Full-screen only needs ``grim`` (slurp is not required).
    """
    if not is_linux():
        return None

    _refresh_binary_cache()
    if not _grim_path:
        logger.error(
            "Cannot capture full screen: grim not available. "
            "Install the 'grim' system package."
        )
        return None

    return _run_grim_full()


def capture_output(output_name: str) -> bytes | None:
    """
    Capture a single output by name via ``grim -o <name> -``.

    Returns PNG bytes, or None on failure / missing tools / non-Linux.
    """
    if not is_linux():
        return None
    if not output_name or not str(output_name).strip():
        return None

    _refresh_binary_cache()
    if not _grim_path:
        logger.error(
            "Cannot capture output: grim not available. "
            "Install the 'grim' system package."
        )
        return None

    return _run_grim(["-o", str(output_name).strip(), "-"])


def _run_slurp() -> str | None:
    """
    Run interactive ``slurp``; return geometry string or None on cancel/error.

    slurp prints geometry like ``x,y WxH`` on stdout. Cancel (Escape) yields
    non-zero exit and/or empty stdout.
    """
    cmd = [_slurp_path or "slurp"]
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            check=False,
            timeout=_SLURP_TIMEOUT,
        )
    except subprocess.TimeoutExpired:
        logger.warning("slurp timed out after %ss", _SLURP_TIMEOUT)
        return None
    except FileNotFoundError:
        logger.error("slurp binary disappeared from PATH")
        return None
    except Exception as e:
        logger.error("slurp failed: %s", e)
        return None

    if result.returncode != 0:
        # User cancel (Escape) is the common non-zero case — log at debug.
        stderr = (result.stderr or "").strip()
        logger.debug(
            "slurp cancelled or failed (rc=%s) stderr=%s",
            result.returncode,
            stderr or "(empty)",
        )
        return None

    geom = (result.stdout or "").strip()
    if not geom:
        logger.debug("slurp returned empty geometry (treated as cancel)")
        return None

    return geom


def _run_grim_geometry(geom: str) -> bytes | None:
    """Run ``grim -g <geom> -`` and return PNG bytes."""
    return _run_grim(["-g", geom, "-"])


def _run_grim_full() -> bytes | None:
    """Run ``grim -`` (all outputs composite) and return PNG bytes."""
    return _run_grim(["-"])


def _run_grim(extra_args: list[str]) -> bytes | None:
    """
    Run grim with argv extras; capture PNG on stdout.

    Never uses shell=True. Geometry / names are always argv elements.
    """
    _refresh_binary_cache()
    if not _grim_path:
        return None

    cmd = [_grim_path, *extra_args]
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            check=False,
            timeout=_GRIM_TIMEOUT,
        )
    except subprocess.TimeoutExpired:
        logger.warning("grim timed out after %ss (cmd=%s)", _GRIM_TIMEOUT, cmd)
        return None
    except FileNotFoundError:
        logger.error("grim binary disappeared from PATH")
        return None
    except Exception as e:
        logger.error("grim failed: %s", e)
        return None

    if result.returncode != 0:
        stderr = (result.stderr or b"").decode("utf-8", errors="replace").strip()
        logger.error(
            "grim failed (rc=%s) cmd=%s stderr=%s",
            result.returncode,
            cmd,
            stderr or "(empty)",
        )
        return None

    png = result.stdout or b""
    if not png:
        logger.error("grim returned empty stdout (no PNG data)")
        return None

    # Basic PNG magic check
    if not png.startswith(b"\x89PNG\r\n\x1a\n"):
        logger.error("grim stdout does not look like a PNG (%d bytes)", len(png))
        return None

    logger.debug("grim captured %d PNG bytes", len(png))
    return png
