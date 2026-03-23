#!/usr/bin/env python3
"""
Audio capture package for AIPromptBridge.

Provides audio recording capabilities using PyAudioWPatch for WASAPI support
on Windows, including loopback device capture for system audio.

Components:
- devices.py: Audio device enumeration and discovery
- ffmpeg_utils.py: Shared FFmpeg binary detection, subprocess helpers, duration extraction
- recorder.py: AudioRecorder class with recording, playback, and level monitoring
"""

from .devices import (
    AudioDevice,
    list_input_devices,
    list_loopback_devices,
    get_default_input_device,
    get_default_loopback_device,
    is_pyaudio_available
)

from .ffmpeg_utils import (
    is_ffmpeg_available,
    is_ffprobe_available,
    is_ffplay_available,
    get_audio_duration,
)

from .recorder import AudioRecorder, COMPRESSION_PRESETS

from .export import (
    sanitize_filename,
    get_format_ext,
    export_audio_file,
    export_audio_from_file,
    build_output_filename,
    CODEC_MAP,
)

__all__ = [
    'AudioDevice',
    'AudioRecorder',
    'COMPRESSION_PRESETS',
    'CODEC_MAP',
    'is_ffmpeg_available',
    'is_ffprobe_available',
    'is_ffplay_available',
    'get_audio_duration',
    'sanitize_filename',
    'get_format_ext',
    'export_audio_file',
    'export_audio_from_file',
    'build_output_filename',
    'list_input_devices',
    'list_loopback_devices',
    'get_default_input_device',
    'get_default_loopback_device',
    'is_pyaudio_available'
]
