#!/usr/bin/env python3
"""
Utility functions for text processing and error detection
"""

import os
import re
import sys


def is_compiled() -> bool:
    """Check if running as a compiled executable (Nuitka/PyInstaller)."""
    return (
        "__compiled__" in globals() or
        getattr(sys, "frozen", False) or
        (sys.executable.lower().endswith(".exe") and
         "python" not in os.path.basename(sys.executable).lower())
    )


def strip_markdown(text):
    """Convert markdown to plain text by stripping formatting"""
    if not text:
        return text

    result = text

    # Remove code blocks (``` ... ```)
    result = re.sub(r'```[\s\S]*?```', lambda m: m.group(0).replace('```', '').strip(), result)

    # Remove inline code (`code`)
    result = re.sub(r'`([^`]+)`', r'\1', result)

    # Remove bold (**text** or __text__)
    result = re.sub(r'\*\*([^*]+)\*\*', r'\1', result)
    result = re.sub(r'__([^_]+)__', r'\1', result)

    # Remove italic (*text* or _text_)
    result = re.sub(r'\*([^*]+)\*', r'\1', result)
    result = re.sub(r'(?<!\w)_([^_]+)_(?!\w)', r'\1', result)

    # Remove strikethrough (~~text~~)
    result = re.sub(r'~~([^~]+)~~', r'\1', result)

    # Remove headers (# Header)
    result = re.sub(r'^#{1,6}\s+', '', result, flags=re.MULTILINE)

    # Remove blockquotes (> text)
    result = re.sub(r'^>\s+', '', result, flags=re.MULTILINE)

    # Remove horizontal rules
    result = re.sub(r'^[-*_]{3,}\s*$', '', result, flags=re.MULTILINE)

    # Remove link formatting [text](url) -> text
    result = re.sub(r'\[([^\]]+)\]\([^)]+\)', r'\1', result)

    # Remove image formatting ![alt](url) -> alt
    result = re.sub(r'!\[([^\]]*)\]\([^)]+\)', r'\1', result)

    # Remove list markers
    result = re.sub(r'^[\s]*[-*+]\s+', '• ', result, flags=re.MULTILINE)
    result = re.sub(r'^[\s]*\d+\.\s+', '', result, flags=re.MULTILINE)

    return result


def is_rate_limit_error(error_msg, status_code=None):
    """Check if error indicates rate limiting"""
    if status_code == 429:
        return True
    error_str = str(error_msg).lower()
    patterns = ["too many requests", "rate limit", "rate_limit", "quota exceeded",
                "429", "throttl", "resource exhausted", "resource_exhausted"]
    return any(p in error_str for p in patterns)


def is_insufficient_credits_error(error_msg, response_json=None):
    """Check if error indicates insufficient credits"""
    error_str = str(error_msg).lower()
    patterns = ["insufficient credits", "insufficient funds", "not enough credits",
                "credit balance", "out of credits", "no credits", "payment required",
                "billing", "exceeded your current quota"]
    if any(p in error_str for p in patterns):
        return True
    if response_json and isinstance(response_json, dict):
        try:
            msg = str(response_json.get("error", {}).get("message", "")).lower()
            if any(p in msg for p in patterns):
                return True
        except:
            pass
    return False


def is_invalid_key_error(error_msg, status_code=None):
    """Check if error indicates invalid API key"""
    if status_code in [401, 403]:
        return True
    error_str = str(error_msg).lower()
    patterns = ["invalid api key", "invalid key", "api key invalid",
                "unauthorized", "authentication", "forbidden", "not authorized"]
    return any(p in error_str for p in patterns)


def play_sound(path: str, async_play: bool = True) -> bool:
    """
    Play a WAV sound file using Windows native winsound.
    
    Args:
        path: Path to the .wav file
        async_play: If True, play asynchronously (non-blocking)
        
    Returns:
        True if sound played successfully, False otherwise
    """
    import logging

    if sys.platform != "win32":
        return False

    try:
        import winsound
        from pathlib import Path

        sound_path = Path(path)

        if is_compiled():
            # In compiled split-build mode, CWD is the launcher directory,
            # but assets are bundled next to the internal executable in bin/
            exe_dir = Path(sys.executable).parent
            compiled_path = exe_dir / path
            if compiled_path.exists():
                sound_path = compiled_path

        if not sound_path.exists():
            logging.debug(f"[Sound] File not found: {path} (Checked {sound_path.absolute()})")
            return False

        flags = winsound.SND_FILENAME
        if async_play:
            flags |= winsound.SND_ASYNC

        winsound.PlaySound(str(sound_path), flags)
        return True

    except Exception as e:
        logging.debug(f"[Sound] Failed to play {path}: {e}")
        return False
