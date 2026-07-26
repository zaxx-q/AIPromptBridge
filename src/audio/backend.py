#!/usr/bin/env python3
"""
Shared PyAudio backend import for AIPromptBridge.

Windows uses PyAudioWPatch (WASAPI loopback support).
Linux (and other non-Windows) uses stock PyAudio (PortAudio → PipeWire/Pulse).

System build deps when installing wheels from source (if needed):
  Fedora:  portaudio-devel  (or system python3-pyaudio)
  Debian:  portaudio19-dev, python3-pyaudio
"""

from __future__ import annotations

import sys
from contextlib import contextmanager
from typing import Any, Iterator, Optional

pyaudio: Optional[Any]
HAVE_PYAUDIO: bool

try:
    if sys.platform == "win32":
        import pyaudiowpatch as pyaudio  # type: ignore[no-redef]
    else:
        import pyaudio  # type: ignore[no-redef]
    HAVE_PYAUDIO = True
except ImportError:
    pyaudio = None
    HAVE_PYAUDIO = False


def is_pyaudio_available() -> bool:
    """Return True if a PyAudio-compatible backend is importable."""
    return HAVE_PYAUDIO


def get_pyaudio_install_hint() -> str:
    """User-facing install hint for the current platform."""
    if sys.platform == "win32":
        return "pip install PyAudioWPatch"
    return "pip install PyAudio  (may need system PortAudio: portaudio-devel / portaudio19-dev)"


@contextmanager
def open_pyaudio() -> Iterator[Any]:
    """
    Open a PyAudio instance and always terminate it.

    Stock PyAudio does **not** implement the context-manager protocol
    (``with PyAudio() as p`` fails). PyAudioWPatch may. This helper works for both.
    """
    if not HAVE_PYAUDIO or pyaudio is None:
        raise RuntimeError(f"PyAudio is not installed. Install with: {get_pyaudio_install_hint()}")

    pa = pyaudio.PyAudio()
    try:
        yield pa
    finally:
        try:
            pa.terminate()
        except Exception:
            pass
