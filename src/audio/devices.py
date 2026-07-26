#!/usr/bin/env python3
"""
Audio device enumeration using PyAudio / PyAudioWPatch.

Provides discovery and listing of audio input devices including:
- Microphones (input devices)
- System/desktop capture: WASAPI loopback on Windows, PipeWire/Pulse
  monitor sources on Linux
"""

from __future__ import annotations

import logging
import sys
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from .backend import HAVE_PYAUDIO, is_pyaudio_available, open_pyaudio, pyaudio

__all__ = [
    "HAVE_PYAUDIO",
    "AudioDevice",
    "find_device_by_name",
    "get_all_devices",
    "get_default_input_device",
    "get_default_loopback_device",
    "is_monitor_device_name",
    "is_pyaudio_available",
    "list_input_devices",
    "list_loopback_devices",
]


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


def is_monitor_device_name(name: str) -> bool:
    """
    Detect PipeWire/PulseAudio monitor sources used as desktop/system capture.

    PortAudio on Linux typically exposes monitors as input devices with names like:
    - ``alsa_output.pci-....analog-stereo.monitor``
    - ``Monitor of Built-in Audio Analog Stereo``
    """
    if not name:
        return False
    lower = name.lower().strip()
    if lower.endswith(".monitor") or lower.endswith(" monitor"):
        return True
    if "monitor of" in lower:
        return True
    if lower == "monitor":
        return True
    return False


def _device_from_info(info: Dict[str, Any], *, is_loopback: bool) -> AudioDevice:
    """Build AudioDevice from a PortAudio device-info dict."""
    index = int(info.get("index", -1))
    return AudioDevice(
        name=str(info.get("name", f"Device {index}")),
        index=index,
        is_loopback=is_loopback,
        channels=max(1, int(info.get("maxInputChannels", 1) or 1)),
        sample_rate=int(info.get("defaultSampleRate", 44100) or 44100),
        host_api=int(info.get("hostApi", 0) or 0),
    )


def _iter_input_infos(p: Any):
    """Yield PortAudio device-info dicts that have input channels."""
    for i in range(p.get_device_count()):
        try:
            info = p.get_device_info_by_index(i)
            if info.get("maxInputChannels", 0) > 0:
                # Ensure index is present for callers
                if "index" not in info:
                    info = dict(info)
                    info["index"] = i
                yield info
        except Exception as e:
            logging.debug(f"[AudioDevices] Error reading device {i}: {e}")
            continue


def list_input_devices() -> List[AudioDevice]:
    """
    List available microphones (non-loopback / non-monitor inputs).

    Returns:
        List of AudioDevice objects for input devices.
    """
    if not HAVE_PYAUDIO:
        logging.warning("[AudioDevices] PyAudio not available")
        return []

    devices: List[AudioDevice] = []

    try:
        with open_pyaudio() as p:
            if sys.platform == "win32":
                for info in _iter_input_infos(p):
                    # WPatch marks WASAPI loopbacks with isLoopbackDevice
                    if info.get("isLoopbackDevice", False):
                        continue
                    try:
                        devices.append(_device_from_info(info, is_loopback=False))
                    except Exception as e:
                        logging.debug(f"[AudioDevices] Error building input device: {e}")
            else:
                for info in _iter_input_infos(p):
                    name = str(info.get("name", ""))
                    if is_monitor_device_name(name):
                        continue
                    try:
                        devices.append(_device_from_info(info, is_loopback=False))
                    except Exception as e:
                        logging.debug(f"[AudioDevices] Error building input device: {e}")

        logging.debug(f"[AudioDevices] Listed {len(devices)} microphone device(s)")

    except Exception as e:
        logging.error(f"[AudioDevices] Error listing input devices: {e}")

    return devices


def list_loopback_devices() -> List[AudioDevice]:
    """
    List system/desktop audio capture devices.

    Windows: WASAPI loopback devices via PyAudioWPatch.
    Linux: PipeWire/Pulse monitor sources (name heuristics).

    Returns:
        List of AudioDevice objects for loopback/monitor devices.
    """
    if not HAVE_PYAUDIO:
        logging.warning("[AudioDevices] PyAudio not available")
        return []

    devices: List[AudioDevice] = []

    try:
        with open_pyaudio() as p:
            if sys.platform == "win32":
                # WPatch-only generator
                for info in p.get_loopback_device_info_generator():
                    try:
                        devices.append(_device_from_info(info, is_loopback=True))
                    except Exception as e:
                        logging.debug(f"[AudioDevices] Error reading loopback device: {e}")
            else:
                for info in _iter_input_infos(p):
                    name = str(info.get("name", ""))
                    if not is_monitor_device_name(name):
                        continue
                    try:
                        devices.append(_device_from_info(info, is_loopback=True))
                    except Exception as e:
                        logging.debug(f"[AudioDevices] Error building monitor device: {e}")

        if devices:
            logging.debug(f"[AudioDevices] Listed {len(devices)} loopback/monitor device(s)")
        else:
            logging.debug(
                "[AudioDevices] No loopback/monitor devices found "
                "(on Linux, PipeWire may expose *.monitor sources when audio is active; "
                "PortAudio only lists them if built with PulseAudio support)"
            )

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
        with open_pyaudio() as p:
            try:
                info = p.get_default_input_device_info()
                name = str(info.get("name", "Default Input"))
                # On Linux, default may theoretically be a monitor — still return it
                # as an input default; UI separates mic vs system via list_* helpers.
                return _device_from_info(
                    info, is_loopback=is_monitor_device_name(name) if sys.platform != "win32" else False
                )
            except OSError:
                logging.debug("[AudioDevices] No default input device found")
                return None

    except Exception as e:
        logging.error(f"[AudioDevices] Error getting default input: {e}")
        return None


def get_default_loopback_device() -> Optional[AudioDevice]:
    """
    Get the default system/desktop audio capture device.

    Windows: default WASAPI loopback via PyAudioWPatch.
    Linux: first monitor source from enumeration, or None.

    Returns:
        AudioDevice for the default loopback/monitor, or None if not available.
    """
    if not HAVE_PYAUDIO:
        return None

    try:
        if sys.platform == "win32":
            with open_pyaudio() as p:
                try:
                    info = p.get_default_wasapi_loopback()
                    return _device_from_info(info, is_loopback=True)
                except (OSError, LookupError):
                    logging.debug("[AudioDevices] No default WASAPI loopback device found")
                    return None

        # Linux / other: first monitor source
        monitors = list_loopback_devices()
        if monitors:
            return monitors[0]
        logging.debug("[AudioDevices] No default monitor/loopback device found")
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
