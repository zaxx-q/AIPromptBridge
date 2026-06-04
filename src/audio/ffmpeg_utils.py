#!/usr/bin/env python3
"""
FFmpeg utility functions shared across audio modules.

Provides cached FFmpeg/FFprobe/FFplay binary detection,
subprocess helpers with Windows CREATE_NO_WINDOW support,
version retrieval, and audio duration extraction.

Used by:
- src/audio/recorder.py (compression, playback decoding, duration)
- src/tools/audio_processor.py (effects, chunking, analysis)
- src/gui/windows/audio_analyzer.py (compression checkbox guard)
"""

import io
import logging
import shutil
import subprocess
import tempfile
import wave
from pathlib import Path
from typing import Optional

# =============================================================================
# Cached Binary Detection
# =============================================================================

_ffmpeg_path: Optional[str] = None
_ffprobe_path: Optional[str] = None
_ffplay_path: Optional[str] = None
_checked: bool = False


def _ensure_checked():
    """Populate cached paths on first call using shutil.which (fast PATH lookup)."""
    global _ffmpeg_path, _ffprobe_path, _ffplay_path, _checked
    if not _checked:
        _ffmpeg_path = shutil.which("ffmpeg")
        _ffprobe_path = shutil.which("ffprobe")
        _ffplay_path = shutil.which("ffplay")
        _checked = True


def is_ffmpeg_available() -> bool:
    """Check if FFmpeg is available in PATH (cached).

    Returns:
        True if ffmpeg binary was found on PATH.
    """
    _ensure_checked()
    return _ffmpeg_path is not None


def is_ffprobe_available() -> bool:
    """Check if FFprobe is available in PATH (cached).

    Returns:
        True if ffprobe binary was found on PATH.
    """
    _ensure_checked()
    return _ffprobe_path is not None


def is_ffplay_available() -> bool:
    """Check if FFplay is available in PATH (cached).

    Returns:
        True if ffplay binary was found on PATH.
    """
    _ensure_checked()
    return _ffplay_path is not None


def get_ffmpeg_path() -> Optional[str]:
    """Get cached FFmpeg binary path.

    Returns:
        Absolute path to ffmpeg, or None if not found.
    """
    _ensure_checked()
    return _ffmpeg_path


def get_ffprobe_path() -> Optional[str]:
    """Get cached FFprobe binary path.

    Returns:
        Absolute path to ffprobe, or None if not found.
    """
    _ensure_checked()
    return _ffprobe_path


def get_ffplay_path() -> Optional[str]:
    """Get cached FFplay binary path.

    Returns:
        Absolute path to ffplay, or None if not found.
    """
    _ensure_checked()
    return _ffplay_path


def get_ffmpeg_version() -> Optional[str]:
    """Get FFmpeg version string (first line of ``ffmpeg -version``).

    Returns:
        Version string, or None if FFmpeg is unavailable.
    """
    path = get_ffmpeg_path()
    if not path:
        return None
    try:
        result = subprocess.run(
            [path, "-version"], capture_output=True, text=True, timeout=10, creationflags=get_creation_flags()
        )
        if result.returncode == 0:
            return result.stdout.split("\n")[0]
    except Exception:
        pass
    return None


# =============================================================================
# Subprocess Helpers
# =============================================================================


def get_creation_flags() -> int:
    """Get subprocess creation flags for Windows (hides console window).

    Returns:
        CREATE_NO_WINDOW on Windows, 0 elsewhere.
    """
    return subprocess.CREATE_NO_WINDOW if hasattr(subprocess, "CREATE_NO_WINDOW") else 0


# =============================================================================
# Audio Duration
# =============================================================================


def get_audio_duration(audio_data: bytes) -> float:
    """Get duration of in-memory audio data in seconds.

    Tries WAV header parsing first (fast, no subprocess),
    then falls back to FFprobe for compressed formats.

    Args:
        audio_data: WAV or compressed audio bytes.

    Returns:
        Duration in seconds (0.0 on failure).
    """
    # Try WAV first (fast, no subprocess)
    try:
        wav_buffer = io.BytesIO(audio_data)
        with wave.open(wav_buffer, "rb") as wf:
            return wf.getnframes() / wf.getframerate()
    except Exception:
        pass

    # Try FFprobe for compressed formats
    if is_ffprobe_available():
        try:
            with tempfile.NamedTemporaryFile(suffix=".audio", delete=False) as tmp:
                tmp.write(audio_data)
                tmp_path = tmp.name

            try:
                result = subprocess.run(
                    [
                        get_ffprobe_path(),
                        "-v",
                        "error",
                        "-show_entries",
                        "format=duration",
                        "-of",
                        "default=noprint_wrappers=1:nokey=1",
                        tmp_path,
                    ],
                    capture_output=True,
                    text=True,
                    creationflags=get_creation_flags(),
                )

                if result.returncode == 0:
                    return float(result.stdout.strip())
            finally:
                try:
                    Path(tmp_path).unlink(missing_ok=True)
                except Exception:
                    pass

        except Exception:
            pass

    return 0.0
