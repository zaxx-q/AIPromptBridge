#!/usr/bin/env python3
"""
Utility functions for text processing and error detection
"""

import os
import re
import sys
from pathlib import Path
from typing import Optional, Union


def normalize_path_str(path_input: Union[str, Path, None]) -> Optional[str]:
    """
    Normalize a path representation to a POSIX-style string (forward slashes).
    Returns None if input is None, empty string if input is empty string.
    Useful for consistent JSON serialization across Windows and POSIX.
    """
    if path_input is None:
        return None
    if isinstance(path_input, Path):
        return path_input.as_posix()
    return str(path_input).replace("\\", "/")


def resolve_file_path(file_path: Union[str, Path, None], anchor_dir: Optional[str] = None) -> Path:
    """
    Resolve a file path robustly across operating systems and path styles.

    Handles:
    - Backslashes vs forward slashes (e.g. Windows paths loaded on Linux)
    - Absolute paths from other machines containing an anchor folder (e.g. 'session_attachments')
    - String paths and Path objects
    - Path traversal protection (ensures resolved path stays within workspace CWD)

    Args:
        file_path: Relative or absolute path to resolve
        anchor_dir: Optional directory name to slice relative paths from (e.g. 'session_attachments')

    Returns:
        Resolved Path object
    """
    if not file_path:
        return Path("")

    raw_str = str(file_path)
    path = Path(raw_str)

    def is_safe(target_path: Path) -> bool:
        """Verify that resolved target path stays within current working directory."""
        try:
            cwd = Path.cwd().resolve()
            resolved = target_path.resolve()
            return cwd in resolved.parents or resolved == cwd
        except Exception:
            return False

    # 1. Direct check
    if path.exists() and is_safe(path):
        return path

    # 2. Convert backslashes to forward slashes
    norm_str = raw_str.replace("\\", "/")
    norm_path = Path(norm_str)
    if norm_path.exists() and is_safe(norm_path):
        return norm_path

    # 3. Check for anchor directory (e.g. cross-machine absolute paths)
    anchors = [anchor_dir] if anchor_dir else ["session_attachments"]
    for anchor in anchors:
        if anchor:
            anchor_prefix = f"{anchor.rstrip('/')}/"
            # Search from the right (rfind) to use the last occurrence if duplicated
            idx = norm_str.rfind(anchor_prefix)
            if idx != -1:
                rel_str = norm_str[idx:]
                rel_path = Path(rel_str)
                if rel_path.exists() and is_safe(rel_path) and anchor in rel_path.resolve().parts:
                    return rel_path

    # Fallback to normalized Path
    return norm_path


def is_compiled() -> bool:
    """Check if running as a compiled executable (Nuitka/PyInstaller)."""
    return (
        "__compiled__" in globals()
        or getattr(sys, "frozen", False)
        or (sys.executable.lower().endswith(".exe") and "python" not in os.path.basename(sys.executable).lower())
    )


def strip_markdown(text):
    """Convert markdown to plain text by stripping formatting"""
    if not text:
        return text

    result = text

    # Remove code blocks (``` ... ```)
    result = re.sub(r"```[\s\S]*?```", lambda m: m.group(0).replace("```", "").strip(), result)

    # Remove inline code (`code`)
    result = re.sub(r"`([^`]+)`", r"\1", result)

    # Remove bold (**text** or __text__)
    result = re.sub(r"\*\*([^*]+)\*\*", r"\1", result)
    result = re.sub(r"__([^_]+)__", r"\1", result)

    # Remove italic (*text* or _text_)
    result = re.sub(r"\*([^*]+)\*", r"\1", result)
    result = re.sub(r"(?<!\w)_([^_]+)_(?!\w)", r"\1", result)

    # Remove strikethrough (~~text~~)
    result = re.sub(r"~~([^~]+)~~", r"\1", result)

    # Remove headers (# Header)
    result = re.sub(r"^#{1,6}\s+", "", result, flags=re.MULTILINE)

    # Remove blockquotes (> text)
    result = re.sub(r"^>\s+", "", result, flags=re.MULTILINE)

    # Remove horizontal rules
    result = re.sub(r"^[-*_]{3,}\s*$", "", result, flags=re.MULTILINE)

    # Remove link formatting [text](url) -> text
    result = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", result)

    # Remove image formatting ![alt](url) -> alt
    result = re.sub(r"!\[([^\]]*)\]\([^)]+\)", r"\1", result)

    # Remove list markers
    result = re.sub(r"^[\s]*[-*+]\s+", "• ", result, flags=re.MULTILINE)
    result = re.sub(r"^[\s]*\d+\.\s+", "", result, flags=re.MULTILINE)

    return result


def is_rate_limit_error(error_msg, status_code=None):
    """Check if error indicates rate limiting"""
    if status_code == 429:
        return True
    error_str = str(error_msg).lower()
    patterns = [
        "too many requests",
        "rate limit",
        "rate_limit",
        "quota exceeded",
        "429",
        "throttl",
        "resource exhausted",
        "resource_exhausted",
    ]
    return any(p in error_str for p in patterns)


def is_insufficient_credits_error(error_msg, response_json=None):
    """Check if error indicates insufficient credits"""
    error_str = str(error_msg).lower()
    patterns = [
        "insufficient credits",
        "insufficient funds",
        "not enough credits",
        "credit balance",
        "out of credits",
        "no credits",
        "payment required",
        "billing",
        "exceeded your current quota",
    ]
    if any(p in error_str for p in patterns):
        return True
    if response_json and isinstance(response_json, dict):
        try:
            msg = str(response_json.get("error", {}).get("message", "")).lower()
            if any(p in msg for p in patterns):
                return True
        except Exception:
            pass
    return False


def is_invalid_key_error(error_msg, status_code=None):
    """Check if error indicates invalid API key"""
    if status_code in [401, 403]:
        return True
    error_str = str(error_msg).lower()
    patterns = [
        "invalid api key",
        "invalid key",
        "api key invalid",
        "unauthorized",
        "authentication",
        "forbidden",
        "not authorized",
    ]
    return any(p in error_str for p in patterns)


def _resolve_sound_path(path: str):
    """Resolve a sound asset path (CWD, then compiled layout if applicable)."""
    from pathlib import Path

    sound_path = Path(path)

    if is_compiled():
        # In compiled split-build mode, CWD is the launcher directory,
        # but assets are bundled next to the internal executable in bin/
        exe_dir = Path(sys.executable).parent
        compiled_path = exe_dir / path
        if compiled_path.exists():
            sound_path = compiled_path

    return sound_path


def _play_sound_linux(sound_path, async_play: bool = True) -> bool:
    """
    Play a sound on Linux via paplay / pw-play / ffplay (first found on PATH).

    Uses subprocess.Popen so playback does not block the caller when async.
    """
    import logging
    import shutil
    import subprocess

    players = (
        ("paplay", [str(sound_path)]),
        ("pw-play", [str(sound_path)]),
        ("ffplay", ["-nodisp", "-autoexit", "-loglevel", "quiet", str(sound_path)]),
    )

    for name, args in players:
        binary = shutil.which(name)
        if not binary:
            continue
        try:
            if async_play:
                subprocess.Popen(
                    [binary, *args],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
            else:
                subprocess.run(
                    [binary, *args],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    check=False,
                    timeout=30,
                )
            return True
        except Exception as e:
            logging.debug(f"[Sound] {name} failed for {sound_path}: {e}")
            continue

    logging.debug(f"[Sound] No Linux audio player found (tried paplay, pw-play, ffplay); skipping {sound_path}")
    return False


def play_sound(path: str, async_play: bool = True) -> bool:
    """
    Play a WAV sound file.

    **Windows:** native winsound.
    **Linux:** paplay, then pw-play, then ffplay -nodisp -autoexit.
    **Other:** no-op (returns False).

    Args:
        path: Path to the .wav file
        async_play: If True, play asynchronously (non-blocking)

    Returns:
        True if sound played successfully, False otherwise
    """
    import logging

    try:
        sound_path = _resolve_sound_path(path)

        if not sound_path.exists():
            logging.debug(f"[Sound] File not found: {path} (Checked {sound_path.absolute()})")
            return False

        if sys.platform == "win32":
            import winsound

            flags = winsound.SND_FILENAME
            if async_play:
                flags |= winsound.SND_ASYNC

            winsound.PlaySound(str(sound_path), flags)
            return True

        if sys.platform.startswith("linux"):
            return _play_sound_linux(sound_path, async_play=async_play)

        return False

    except Exception as e:
        logging.debug(f"[Sound] Failed to play {path}: {e}")
        return False
