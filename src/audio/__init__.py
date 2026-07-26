#!/usr/bin/env python3
"""
Audio capture package for AIPromptBridge.

Provides audio recording via PyAudio:
- Windows: PyAudioWPatch (WASAPI loopback for system audio)
- Linux: stock PyAudio / PortAudio (PipeWire/Pulse monitor sources)

Components:
- backend.py: Platform-specific PyAudio import
- devices.py: Audio device enumeration and discovery
- ffmpeg_utils.py: Shared FFmpeg binary detection, subprocess helpers, duration extraction
- recorder.py: AudioRecorder class with recording, playback, and level monitoring
"""

from .backend import HAVE_PYAUDIO, is_pyaudio_available
from .devices import (
    AudioDevice,
    get_default_input_device,
    get_default_loopback_device,
    list_input_devices,
    list_loopback_devices,
)
from .export import (
    CODEC_MAP,
    build_output_filename,
    export_audio_file,
    export_audio_from_file,
    get_format_ext,
    sanitize_filename,
)
from .ffmpeg_utils import (
    get_audio_duration,
    is_ffmpeg_available,
    is_ffplay_available,
    is_ffprobe_available,
)
from .recorder import COMPRESSION_PRESETS, AudioRecorder

__all__ = [
    "CODEC_MAP",
    "COMPRESSION_PRESETS",
    "HAVE_PYAUDIO",
    "AudioDevice",
    "AudioRecorder",
    "build_output_filename",
    "export_audio_file",
    "export_audio_from_file",
    "get_audio_duration",
    "get_default_input_device",
    "get_default_loopback_device",
    "get_format_ext",
    "is_ffmpeg_available",
    "is_ffplay_available",
    "is_ffprobe_available",
    "is_pyaudio_available",
    "list_input_devices",
    "list_loopback_devices",
    "sanitize_filename",
]
