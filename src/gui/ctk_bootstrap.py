#!/usr/bin/env python3
"""
CustomTkinter platform bootstrap — Linux rendering & font health.

uv/python-build-standalone ships Tk built **without Xft** (`no-xft`). On those
interpreters Tk only exposes the bitmap ``fixed`` font, so:

* CustomTkinter's default ``font_shapes`` corner drawing corrupts every widget
* UI text collapses to a horrendous bitmap face

This module probes the live Tk font stack once, forces ``circle_shapes`` when
the shapes font is unusable, installs CTk asset fonts into standard Linux font
dirs (helps once Xft Tk is available), and caches a sensible UI font family.

Windows / macOS are no-ops. Safe to call multiple times (idempotent).
"""

from __future__ import annotations

import shutil
import subprocess
import sys
import threading
from pathlib import Path
from typing import Optional

_lock = threading.Lock()
_configured = False  # True after a live-root font probe
_safe_default_applied = False  # True after root=None Linux circle_shapes default

# Results filled by configure_ctk_rendering()
_shapes_font_usable: bool = False
_font_stack_degraded: bool = False
_drawing_method: Optional[str] = None
_ui_font_family: Optional[str] = None
_font_family_count: int = 0

_SHAPES_FONT_NAME = "CustomTkinter_shapes_font"
_PROBE_FONT_NAME = "_aipb_ctk_shapes_probe"

# Preference order when Xft/fontconfig fonts are available
_LINUX_FONT_PREFERENCE = (
    "Roboto",
    "Inter",
    "Inter Variable",
    "Noto Sans",
    "Cantarell",
    "DejaVu Sans",
    "Ubuntu",
    "Open Sans",
)

_LINUX_FONT_DIRS = (
    Path.home() / ".fonts",
    Path.home() / ".local" / "share" / "fonts",
)


def is_configured() -> bool:
    return _configured


def get_linux_ui_font_family() -> Optional[str]:
    """Return the cached Linux UI font family, or None if not configured / N/A."""
    return _ui_font_family


def font_stack_is_degraded() -> bool:
    """True when Tk exposes essentially only bitmap ``fixed`` (no-xft builds)."""
    return _font_stack_degraded


def configure_ctk_rendering(root=None) -> None:
    """
    Probe Tk and fix CustomTkinter drawing/fonts for the current platform.

    Args:
        root: Live Tk/CTk widget whose ``.tk`` interpreter is used for probes.
            **Preferred.** When None, applies a safe Linux default
            (``circle_shapes``) without creating a temporary ``Tk()`` — full
            probe runs later once a real root exists (GUICoordinator / window).
    """
    global _configured, _safe_default_applied, _shapes_font_usable, _font_stack_degraded
    global _drawing_method, _ui_font_family, _font_family_count

    if not sys.platform.startswith("linux"):
        _configured = True
        _safe_default_applied = True
        return

    with _lock:
        # Import here so non-Linux / no-ctk hosts never pay the cost at module load
        try:
            from customtkinter.windows.widgets.core_rendering.draw_engine import DrawEngine
        except ImportError:
            _configured = True
            _safe_default_applied = True
            return

        # No live root yet: apply safe default only (do NOT create a second Tk).
        # A later call with root= re-probes and may upgrade to font_shapes.
        if root is None:
            if _configured or _safe_default_applied:
                return
            DrawEngine.preferred_drawing_method = "circle_shapes"
            _drawing_method = "circle_shapes"
            _install_ctk_fonts()
            _safe_default_applied = True
            # Not fully configured — allow re-entry with a real root
            return

        if _configured:
            # Already probed with a live interpreter
            return

        try:
            families = _list_font_families(root)
            _font_family_count = len(families)
            families_lower = {f.lower() for f in families}

            # Degraded = only fixed/bitmap, or nothing useful
            non_fixed = [f for f in families if f.lower() not in ("fixed", "default", "cursor", "browser")]
            _font_stack_degraded = len(non_fixed) == 0

            _shapes_font_usable = _probe_shapes_font(root, families_lower)
            _ui_font_family = _pick_ui_font_family(families)

            if not _shapes_font_usable:
                DrawEngine.preferred_drawing_method = "circle_shapes"
                _drawing_method = "circle_shapes"
            else:
                # Shapes font works — prefer CTk's antialiased path
                DrawEngine.preferred_drawing_method = "font_shapes"
                _drawing_method = "font_shapes"

            _install_ctk_fonts()
            _log_status()
            _configured = True
        except Exception as exc:
            # Last-resort: force circle_shapes so corners are not totally broken
            DrawEngine.preferred_drawing_method = "circle_shapes"
            _drawing_method = "circle_shapes"
            _font_stack_degraded = True
            _ui_font_family = _ui_font_family or "DejaVu Sans"
            _configured = True
            try:
                from ..console import print_warning

                print_warning(f"CustomTkinter Linux bootstrap failed ({exc}); using circle_shapes")
            except Exception:
                pass


def _list_font_families(root) -> list[str]:
    raw = root.tk.call("font", "families")
    if isinstance(raw, str):
        return [raw] if raw else []
    return [str(f) for f in raw]


def _probe_shapes_font(root, families_lower: set[str]) -> bool:
    """Return True only if Tk can actually resolve CustomTkinter_shapes_font."""
    # Fast path: family not even listed and we already know stack is empty of real fonts
    try:
        # Destroy leftover probe font from a previous crashed run
        try:
            root.tk.call("font", "delete", _PROBE_FONT_NAME)
        except Exception:
            pass

        root.tk.call(
            "font",
            "create",
            _PROBE_FONT_NAME,
            "-family",
            _SHAPES_FONT_NAME,
            "-size",
            12,
        )
        actual = root.tk.call("font", "actual", _PROBE_FONT_NAME)
        # actual is alternating key/value list: -family name -size N ...
        family = _parse_font_actual_family(actual)
        try:
            root.tk.call("font", "delete", _PROBE_FONT_NAME)
        except Exception:
            pass

        if not family:
            return False
        # Success only if Tk did not silently substitute fixed/default
        fl = family.lower()
        if fl in ("fixed", "default", "cursor", "browser"):
            return False
        # Accept exact or substring match (some Tk builds report slightly different names)
        if _SHAPES_FONT_NAME.lower() in fl or fl in families_lower and "customtkinter" in fl:
            return True
        # If family name changed but is not a known bitmap fallback, still treat as usable
        return "customtkinter" in fl or "shapes" in fl
    except Exception:
        return False


def _parse_font_actual_family(actual) -> str:
    if actual is None:
        return ""
    if isinstance(actual, str):
        # Unlikely, but be defensive
        return actual
    seq = list(actual)
    for i, item in enumerate(seq):
        if str(item) in ("-family", "family") and i + 1 < len(seq):
            return str(seq[i + 1])
    return ""


def _pick_ui_font_family(families: list[str]) -> str:
    by_lower = {f.lower(): f for f in families}
    for pref in _LINUX_FONT_PREFERENCE:
        if pref.lower() in by_lower:
            return by_lower[pref.lower()]
    # Any non-bitmap family
    for f in families:
        if f.lower() not in ("fixed", "default", "cursor", "browser"):
            return f
    return "fixed" if families else "DejaVu Sans"


def _ctk_assets_font_dir() -> Optional[Path]:
    try:
        import customtkinter

        base = Path(customtkinter.__file__).resolve().parent
        fonts = base / "assets" / "fonts"
        return fonts if fonts.is_dir() else None
    except Exception:
        return None


def _install_ctk_fonts() -> None:
    """Copy CTk Roboto + shapes fonts into user font dirs; refresh fontconfig cache."""
    assets = _ctk_assets_font_dir()
    if assets is None:
        return

    files: list[Path] = []
    shapes = assets / "CustomTkinter_shapes_font.otf"
    if shapes.is_file():
        files.append(shapes)
    roboto = assets / "Roboto"
    if roboto.is_dir():
        files.extend(sorted(roboto.glob("*.ttf")))

    if not files:
        return

    installed_dirs: list[Path] = []
    for directory in _LINUX_FONT_DIRS:
        try:
            directory.mkdir(parents=True, exist_ok=True)
        except OSError:
            continue
        copied_any = False
        for src in files:
            dest = directory / src.name
            try:
                if dest.is_file() and dest.stat().st_size == src.stat().st_size:
                    continue
                shutil.copy2(src, dest)
                copied_any = True
            except OSError:
                continue
        if copied_any or directory.is_dir():
            installed_dirs.append(directory)

    if not installed_dirs:
        return

    fc_cache = shutil.which("fc-cache")
    if not fc_cache:
        return
    for directory in installed_dirs:
        try:
            subprocess.run(
                [fc_cache, "-f", str(directory)],
                check=False,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=15,
            )
        except (OSError, subprocess.SubprocessError):
            pass


def _log_status() -> None:
    try:
        from ..console import print_info, print_warning
    except Exception:
        return

    method = _drawing_method or "?"
    if _font_stack_degraded:
        print_warning(
            "Tk font stack is degraded (only bitmap 'fixed' — likely a no-xft Tk build, "
            "common with uv's standalone Python). Widget corners use "
            f"'{method}'; text will look poor until you use distro Python + tkinter with Xft."
        )
        print_warning(
            "Fix on Fedora/RHEL:  sudo dnf install python3.13 python3.13-tkinter  &&  "
            "uv venv --python /usr/bin/python3.13  &&  uv pip install -r requirements.txt"
        )
        print_info("See docs/LINUX.md § CustomTkinter / Tk fonts for details.")
    elif not _shapes_font_usable:
        print_warning(
            f"CustomTkinter shapes font not usable in Tk; using DrawEngine '{method}' "
            f"(font families seen: {_font_family_count})."
        )
    else:
        print_info(
            f"CustomTkinter Linux rendering OK "
            f"(method={method}, ui_font={_ui_font_family!r}, families={_font_family_count})."
        )


def ensure_configured(root=None) -> None:
    """Public alias used by themes / windows — configures once if needed."""
    configure_ctk_rendering(root=root)


def ensure_ctk_window_ready(root) -> None:
    """
    Call immediately after creating a standalone ``CTk()`` / ``Tk()`` root
    (settings, prompt editor, etc. when not using GUICoordinator).
    """
    if root is None:
        return
    configure_ctk_rendering(root=root)
