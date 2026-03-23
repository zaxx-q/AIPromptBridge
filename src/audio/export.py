#!/usr/bin/env python3
"""
Centralized audio export utilities.

Provides shared logic for saving audio files across all tools
(Audio Analyzer, TTS, etc.):
- Filename sanitization from text
- Format-to-codec mapping
- FFmpeg-based encoding with metadata embedding
- WAV direct save

Used by:
- src/gui/tts_tool.py (TTS save)
- src/gui/windows/audio_analyzer.py (Audio Analyzer save)
"""

import logging
import os
import re
import subprocess
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Optional

from .ffmpeg_utils import get_ffmpeg_path, get_creation_flags, is_ffmpeg_available
from .wav_utils import save_wav, pcm_to_wav


# =============================================================================
# Codec Configuration
# =============================================================================

# Format → (codec, extra_args) mapping for FFmpeg
# Used when encoding from WAV/PCM to target format
CODEC_MAP = {
    "ogg": (["-c:a", "libopus", "-b:a", "64k"], ".ogg"),
    "mp3": (["-c:a", "libmp3lame", "-b:a", "128k"], ".mp3"),
    "m4a": (["-c:a", "aac", "-b:a", "64k"], ".m4a"),
    "flac": (["-c:a", "flac"], ".flac"),
    "wav": ([], ".wav"),
}


def sanitize_filename(text: str, max_words: int = 5, max_len: int = 50) -> str:
    """
    Create a safe filename slug from text (first few words).
    
    Args:
        text: Input text to derive filename from.
        max_words: Maximum number of words to use.
        max_len: Maximum character length for the slug.
        
    Returns:
        Sanitized filename string (lowercase, underscored).
        Empty string if text is empty/None.
    """
    if not text:
        return ""
    # Take first N words
    words = text.split()[:max_words]
    slug = "_".join(words)
    # Remove non-alphanumeric chars (keep underscores)
    slug = re.sub(r'[^\w]', '_', slug)
    # Collapse multiple underscores
    slug = re.sub(r'_+', '_', slug).strip('_').lower()
    return slug[:max_len]


def get_format_ext(format_name: str) -> str:
    """
    Map a format name to its file extension.
    
    Args:
        format_name: Format name (ogg, mp3, aac, m4a, flac, wav).
        
    Returns:
        File extension without dot (e.g., "ogg", "m4a").
    """
    fmt = format_name.lower()
    if fmt == "aac":
        return "m4a"
    return fmt


def export_audio_file(
    wav_data: bytes,
    output_path: str,
    format_ext: str,
    metadata_comment: Optional[str] = None,
    extra_input_args: Optional[list] = None
) -> Optional[str]:
    """
    Export WAV audio data to a file in the specified format via FFmpeg.
    
    For WAV output, writes directly without FFmpeg.
    For other formats, uses FFmpeg with the appropriate codec from CODEC_MAP.
    
    Args:
        wav_data: Input audio as WAV bytes.
        output_path: Full path for the output file.
        format_ext: Target format extension (ogg, mp3, m4a, flac, wav).
        metadata_comment: Optional text to embed as metadata comment tag.
        extra_input_args: Optional extra FFmpeg args inserted after input
                         (e.g., filter chains like ["-af", "silenceremove=..."]).
        
    Returns:
        Error message string on failure, None on success.
    """
    if format_ext == "wav":
        # WAV: write directly, no FFmpeg needed
        try:
            os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
            with open(output_path, 'wb') as f:
                f.write(wav_data)
            return None
        except Exception as e:
            return str(e)
    
    # Compressed formats require FFmpeg
    ffmpeg_path = get_ffmpeg_path()
    if not ffmpeg_path:
        return "FFmpeg not available for conversion"
    
    codec_args, _ = CODEC_MAP.get(format_ext, CODEC_MAP["ogg"])
    
    try:
        # Base command: read WAV from stdin
        cmd = [ffmpeg_path, "-y", "-i", "pipe:0", "-v", "error"]
        
        # Insert extra args (filters, etc.) before codec
        if extra_input_args:
            cmd.extend(extra_input_args)
        
        # Codec settings
        cmd.extend(codec_args)
        
        # Metadata embedding
        if metadata_comment:
            cmd.extend(["-metadata", f"comment={metadata_comment}"])
        
        cmd.append(output_path)
        
        result = subprocess.run(
            cmd,
            input=wav_data,
            capture_output=True,
            creationflags=get_creation_flags()
        )
        
        if result.returncode != 0:
            return f"FFmpeg: {result.stderr.decode('utf-8', errors='replace')}"
        
        return None
        
    except Exception as e:
        return str(e)


def export_audio_from_file(
    input_path: str,
    output_path: str,
    format_ext: str,
    ffmpeg_filter_args: Optional[str] = None,
    codec_override: Optional[list] = None,
    metadata_comment: Optional[str] = None
) -> Optional[str]:
    """
    Export audio from a file path to another format via FFmpeg.
    
    Useful when the source is already a temp file (e.g., Audio Analyzer
    recordings that need preset processing).
    
    Args:
        input_path: Path to input audio file.
        output_path: Path for output file.
        format_ext: Target format extension.
        ffmpeg_filter_args: Optional audio filter string (e.g., "-af silenceremove=...").
                           Will be split and inserted into the command.
        codec_override: Optional explicit codec args (overrides CODEC_MAP).
        metadata_comment: Optional text to embed as metadata comment.
        
    Returns:
        Error message string on failure, None on success.
    """
    ffmpeg_path = get_ffmpeg_path()
    if not ffmpeg_path:
        return "FFmpeg not available"
    
    # Determine codec
    if codec_override:
        codec_args = codec_override
    else:
        codec_args, _ = CODEC_MAP.get(format_ext, CODEC_MAP["ogg"])
    
    try:
        cmd = [ffmpeg_path, "-y", "-i", input_path, "-v", "error"]
        
        # Audio filters
        if ffmpeg_filter_args:
            cmd.extend(ffmpeg_filter_args.split())
        
        # Codec
        cmd.extend(codec_args)
        
        # Metadata
        if metadata_comment:
            cmd.extend(["-metadata", f"comment={metadata_comment}"])
        
        cmd.append(output_path)
        
        result = subprocess.run(
            cmd,
            capture_output=True,
            creationflags=get_creation_flags()
        )
        
        if result.returncode != 0:
            return f"FFmpeg: {result.stderr.decode('utf-8', errors='replace')}"
        
        return None
        
    except Exception as e:
        return str(e)


def build_output_filename(
    prefix: str,
    text_source: Optional[str] = None,
    fallback_name: Optional[str] = None,
    format_ext: str = "ogg",
    max_words: int = 5
) -> str:
    """
    Build a descriptive output filename with timestamp.
    
    Priority: text_source slug → fallback_name slug → prefix only.
    
    Args:
        prefix: Filename prefix (e.g., "tts", "audio").
        text_source: Primary text to derive name from (e.g., transcript).
        fallback_name: Fallback text if text_source is empty (e.g., device name).
        format_ext: File extension without dot.
        max_words: Max words for the slug.
        
    Returns:
        Filename string like "tts_hello_world_20260323_110100.ogg"
    """
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    
    slug = sanitize_filename(text_source, max_words=max_words)
    if not slug and fallback_name:
        slug = sanitize_filename(fallback_name, max_words=3, max_len=30)
    
    if slug:
        return f"{prefix}_{slug}_{timestamp}.{format_ext}"
    else:
        return f"{prefix}_{timestamp}.{format_ext}"
