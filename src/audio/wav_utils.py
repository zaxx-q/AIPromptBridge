"""
WAV utilities for TTS audio processing.

Provides functions to convert raw PCM data (as returned by Gemini TTS API)
into WAV format for playback and file saving.

The Gemini TTS API returns 24kHz, 16-bit, mono PCM audio data.
"""

import io
import wave
from typing import Optional

# Default PCM format from Gemini TTS API
TTS_SAMPLE_RATE = 24000
TTS_SAMPLE_WIDTH = 2  # 16-bit = 2 bytes
TTS_CHANNELS = 1  # Mono


def pcm_to_wav(
    pcm_data: bytes,
    channels: int = TTS_CHANNELS,
    rate: int = TTS_SAMPLE_RATE,
    sample_width: int = TTS_SAMPLE_WIDTH
) -> bytes:
    """
    Convert raw PCM data to WAV format in memory.
    
    Args:
        pcm_data: Raw PCM audio bytes
        channels: Number of audio channels (default: 1 mono)
        rate: Sample rate in Hz (default: 24000)
        sample_width: Sample width in bytes (default: 2 for 16-bit)
        
    Returns:
        WAV file bytes (with proper header)
    """
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as wf:
        wf.setnchannels(channels)
        wf.setsampwidth(sample_width)
        wf.setframerate(rate)
        wf.writeframes(pcm_data)
    return buffer.getvalue()


def save_wav(
    filepath: str,
    pcm_data: bytes,
    channels: int = TTS_CHANNELS,
    rate: int = TTS_SAMPLE_RATE,
    sample_width: int = TTS_SAMPLE_WIDTH
) -> Optional[str]:
    """
    Save PCM data as a WAV file.
    
    Args:
        filepath: Output file path (should end with .wav)
        pcm_data: Raw PCM audio bytes
        channels: Number of audio channels (default: 1 mono)
        rate: Sample rate in Hz (default: 24000)
        sample_width: Sample width in bytes (default: 2 for 16-bit)
        
    Returns:
        None on success, error message string on failure
    """
    try:
        with wave.open(filepath, "wb") as wf:
            wf.setnchannels(channels)
            wf.setsampwidth(sample_width)
            wf.setframerate(rate)
            wf.writeframes(pcm_data)
        return None
    except Exception as e:
        return f"Failed to save WAV file: {e}"


def get_pcm_duration(
    pcm_data: bytes,
    channels: int = TTS_CHANNELS,
    rate: int = TTS_SAMPLE_RATE,
    sample_width: int = TTS_SAMPLE_WIDTH
) -> float:
    """
    Calculate duration of PCM audio data in seconds.
    
    Args:
        pcm_data: Raw PCM audio bytes
        channels: Number of audio channels
        rate: Sample rate in Hz
        sample_width: Sample width in bytes
        
    Returns:
        Duration in seconds
    """
    if not pcm_data:
        return 0.0
    num_frames = len(pcm_data) / (channels * sample_width)
    return num_frames / rate
