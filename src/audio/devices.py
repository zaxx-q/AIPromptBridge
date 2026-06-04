#!/usr/bin/env python3
"""
Audio device enumeration using PyAudioWPatch.

Provides discovery and listing of audio input devices including
WASAPI loopback devices for system audio capture.
"""

import logging
from dataclasses import dataclass
from typing import List, Optional

# Try to import PyAudioWPatch
try:
    import pyaudiowpatch as pyaudio

    HAVE_PYAUDIO = True
except ImportError:
    HAVE_PYAUDIO = False
    pyaudio = None


@dataclass
class AudioDevice:
    """Represents an audio input device."""

    name: str
    index: int
    is_loopback: bool
    channels: int
    sample_rate: int
    host_api: int = 0

    def __str__(self) -> str:
        loopback_marker = " [Loopback]" if self.is_loopback else ""
        return f"{self.name}{loopback_marker}"

    def get_display_name(self) -> str:
        """Get a user-friendly display name."""
        # Truncate long names
        name = self.name
        if len(name) > 50:
            name = name[:47] + "..."
        if self.is_loopback:
            return f"🔊 {name}"
        return f"🎤 {name}"


def is_pyaudio_available() -> bool:
    """Check if PyAudioWPatch is available."""
    return HAVE_PYAUDIO


def list_input_devices() -> List[AudioDevice]:
    """
    List all available input devices (microphones).

    Returns:
        List of AudioDevice objects for input devices.
    """
    if not HAVE_PYAUDIO:
        logging.warning("[AudioDevices] PyAudioWPatch not available")
        return []

    devices = []

    try:
        with pyaudio.PyAudio() as p:
            for i in range(p.get_device_count()):
                try:
                    info = p.get_device_info_by_index(i)

                    # Only include devices with input channels that aren't loopback
                    if info.get("maxInputChannels", 0) > 0 and not info.get("isLoopbackDevice", False):
                        devices.append(
                            AudioDevice(
                                name=info.get("name", f"Device {i}"),
                                index=info.get("index", i),
                                is_loopback=False,
                                channels=int(info.get("maxInputChannels", 1)),
                                sample_rate=int(info.get("defaultSampleRate", 44100)),
                                host_api=int(info.get("hostApi", 0)),
                            )
                        )
                except Exception as e:
                    logging.debug(f"[AudioDevices] Error reading device {i}: {e}")
                    continue

    except Exception as e:
        logging.error(f"[AudioDevices] Error listing input devices: {e}")

    return devices


def list_loopback_devices() -> List[AudioDevice]:
    """
    List all available WASAPI loopback devices (system audio capture).

    Returns:
        List of AudioDevice objects for loopback devices.
    """
    if not HAVE_PYAUDIO:
        logging.warning("[AudioDevices] PyAudioWPatch not available")
        return []

    devices = []

    try:
        with pyaudio.PyAudio() as p:
            # Use the loopback device generator
            for info in p.get_loopback_device_info_generator():
                try:
                    devices.append(
                        AudioDevice(
                            name=info.get("name", "Unknown Loopback"),
                            index=info.get("index", -1),
                            is_loopback=True,
                            channels=int(info.get("maxInputChannels", 2)),
                            sample_rate=int(info.get("defaultSampleRate", 44100)),
                            host_api=int(info.get("hostApi", 0)),
                        )
                    )
                except Exception as e:
                    logging.debug(f"[AudioDevices] Error reading loopback device: {e}")
                    continue

    except Exception as e:
        logging.error(f"[AudioDevices] Error listing loopback devices: {e}")

    return devices


def get_default_input_device() -> Optional[AudioDevice]:
    """
    Get the default input device (microphone).

    Returns:
        AudioDevice for the default input, or None if not available.
    """
    if not HAVE_PYAUDIO:
        return None

    try:
        with pyaudio.PyAudio() as p:
            try:
                info = p.get_default_input_device_info()
                return AudioDevice(
                    name=info.get("name", "Default Input"),
                    index=info.get("index", 0),
                    is_loopback=False,
                    channels=int(info.get("maxInputChannels", 1)),
                    sample_rate=int(info.get("defaultSampleRate", 44100)),
                    host_api=int(info.get("hostApi", 0)),
                )
            except OSError:
                # No default input device
                logging.debug("[AudioDevices] No default input device found")
                return None

    except Exception as e:
        logging.error(f"[AudioDevices] Error getting default input: {e}")
        return None


def get_default_loopback_device() -> Optional[AudioDevice]:
    """
    Get the default WASAPI loopback device (system audio).

    Returns:
        AudioDevice for the default loopback, or None if not available.
    """
    if not HAVE_PYAUDIO:
        return None

    try:
        with pyaudio.PyAudio() as p:
            try:
                info = p.get_default_wasapi_loopback()
                return AudioDevice(
                    name=info.get("name", "Default Loopback"),
                    index=info.get("index", 0),
                    is_loopback=True,
                    channels=int(info.get("maxInputChannels", 2)),
                    sample_rate=int(info.get("defaultSampleRate", 44100)),
                    host_api=int(info.get("hostApi", 0)),
                )
            except (OSError, LookupError):
                # WASAPI not available or no loopback device
                logging.debug("[AudioDevices] No default loopback device found")
                return None

    except Exception as e:
        logging.error(f"[AudioDevices] Error getting default loopback: {e}")
        return None


def get_all_devices() -> List[AudioDevice]:
    """
    Get all available audio devices (both input and loopback).

    Returns:
        Combined list of input and loopback devices.
    """
    devices = list_input_devices()
    devices.extend(list_loopback_devices())
    return devices


def find_device_by_name(name: str, prefer_loopback: bool = False) -> Optional[AudioDevice]:
    """
    Find a device by name.

    Args:
        name: Device name to search for (partial match supported)
        prefer_loopback: If True, search loopback devices first

    Returns:
        Matching AudioDevice or None
    """
    if prefer_loopback:
        devices = list_loopback_devices() + list_input_devices()
    else:
        devices = list_input_devices() + list_loopback_devices()

    # Exact match first
    for device in devices:
        if device.name == name:
            return device

    # Partial match
    name_lower = name.lower()
    for device in devices:
        if name_lower in device.name.lower():
            return device

    return None
