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
    "BACKEND_PORTAUDIO",
    "BACKEND_PULSE",
    "AudioDevice",
    "find_device_by_name",
    "get_all_devices",
    "get_default_input_device",
    "get_default_loopback_device",
    "is_monitor_device_name",
    "is_pyaudio_available",
    "is_virtual_alsa_device_name",
    "list_input_devices",
    "list_loopback_devices",
]

# Capture backends for AudioRecorder
BACKEND_PORTAUDIO = "portaudio"
BACKEND_PULSE = "pulse"

# ALSA/PipeWire virtual PCMs and card aliases — not useful mic choices.
# PortAudio also lists every JACK/PipeWire *client* (browsers, cava, ffmpeg) which
# come and go and often crash when opened as capture devices.
_VIRTUAL_ALSA_DEVICE_NAMES = frozenset(
    {
        "default",
        "pipewire",
        "pulse",
        "sysdefault",
        "spdif",
        "hdmi",
        "dmix",
        "dsnoop",
        "front",
        "rear",
        "side",
        "center_lfe",
        "iec958",
        "phoneline",
        "modem",
        "null",
        "surround",
        "surround21",
        "surround40",
        "surround41",
        "surround50",
        "surround51",
        "surround71",
    }
)

# PortAudio virtual devices advertise absurd channel counts (e.g. 128).
_MAX_REASONABLE_INPUT_CHANNELS = 8


@dataclass
class AudioDevice:
    """Represents an audio input device."""

    name: str
    index: int
    is_loopback: bool
    channels: int
    sample_rate: int
    host_api: int = 0
    # "portaudio" (default PyAudio stream) or "pulse" (ffmpeg -f pulse on Linux)
    backend: str = BACKEND_PORTAUDIO
    # Pulse/PipeWire source name when backend == "pulse"
    pulse_name: Optional[str] = None

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

    @property
    def uses_pulse_capture(self) -> bool:
        """True when capture must go through ffmpeg pulse (not PortAudio index)."""
        return self.backend == BACKEND_PULSE and bool(self.pulse_name)


def is_monitor_device_name(name: str) -> bool:
    """
    Detect PipeWire/PulseAudio monitor sources used as desktop/system capture.

    PortAudio on Linux *sometimes* exposes monitors as input devices with names like:
    - ``alsa_output.pci-....analog-stereo.monitor``
    - ``Monitor of Built-in Audio Analog Stereo``

    Many builds (ALSA/JACK host APIs only) never list these — see pulse_monitors.
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


def is_virtual_alsa_device_name(name: str) -> bool:
    """True for ALSA/PipeWire virtual PCMs (default, pipewire, sysdefault, …)."""
    if not name:
        return False
    lower = name.lower().strip()
    if lower in _VIRTUAL_ALSA_DEVICE_NAMES:
        return True
    # Parameterized aliases: hdmi:0, surround51:CARD=…
    base = lower.split(":", 1)[0].strip()
    if base in _VIRTUAL_ALSA_DEVICE_NAMES:
        return True
    if base.startswith("surround") or base.startswith("hdmi"):
        return True
    return False


def _device_from_info(info: Dict[str, Any], *, is_loopback: bool) -> AudioDevice:
    """Build AudioDevice from a PortAudio device-info dict."""
    index = int(info.get("index", -1))
    raw_ch = max(1, int(info.get("maxInputChannels", 1) or 1))
    # Cap to mono/stereo for open — virtual devices claim 64–128 channels.
    channels = max(1, min(raw_ch, 2))
    return AudioDevice(
        name=str(info.get("name", f"Device {index}")),
        index=index,
        is_loopback=is_loopback,
        channels=channels,
        sample_rate=int(info.get("defaultSampleRate", 44100) or 44100),
        host_api=int(info.get("hostApi", 0) or 0),
        backend=BACKEND_PORTAUDIO,
        pulse_name=None,
    )


def _host_api_name(p: Any, host_api_index: int) -> str:
    try:
        info = p.get_host_api_info_by_index(int(host_api_index))
        return str(info.get("name", "") or "")
    except Exception:
        return ""


def _is_linux_portaudio_mic_candidate(p: Any, info: Dict[str, Any]) -> bool:
    """
    Filter PortAudio rows suitable as microphones on Linux.

    Drops: monitors, ALSA virtuals, absurd channel counts, and the entire JACK
    host API (PipeWire exposes every running client — Zen, cava, Lavf, … — which
    are not mics and frequently crash PortAudio on open).
    """
    name = str(info.get("name", ""))
    if is_monitor_device_name(name):
        return False
    if is_virtual_alsa_device_name(name):
        return False

    max_in = int(info.get("maxInputChannels", 0) or 0)
    max_out = int(info.get("maxOutputChannels", 0) or 0)
    if max_in < 1 or max_in > _MAX_REASONABLE_INPUT_CHANNELS:
        return False

    api_name = _host_api_name(p, int(info.get("hostApi", 0) or 0)).lower()
    if "jack" in api_name:
        return False

    # Dual I/O with many outs is usually a sink///virtual, not a mic
    if max_out > 0 and max_in >= 2 and "hw:" not in name.lower():
        return False

    return True


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


def _list_pulse_input_devices() -> List[AudioDevice]:
    """Linux: real mics from pactl → ffmpeg pulse capture (stable vs JACK clients)."""
    try:
        from .pulse_monitors import PULSE_INPUT_INDEX_BASE, list_pulse_input_sources
    except ImportError:
        return []

    devices: List[AudioDevice] = []
    for i, src in enumerate(list_pulse_input_sources()):
        devices.append(
            AudioDevice(
                name=src.display_label(),
                index=PULSE_INPUT_INDEX_BASE - i,
                is_loopback=False,
                channels=max(1, min(2, int(src.channels or 1))),
                sample_rate=int(src.sample_rate or 48000),
                host_api=-1,
                backend=BACKEND_PULSE,
                pulse_name=src.name,
            )
        )
    return devices


def list_input_devices() -> List[AudioDevice]:
    """
    List available microphones (non-loopback / non-monitor inputs).

    Linux: prefer Pulse/PipeWire recording sources (pactl) plus filtered ALSA
    hardware nodes. Virtual PCMs (default/pipewire/sysdefault) and JACK client
    streams (browsers, visualizers, ffmpeg) are excluded — they clutter the UI
    and often crash PortAudio when selected.

    Returns:
        List of AudioDevice objects for input devices.
    """
    devices: List[AudioDevice] = []

    try:
        if sys.platform == "win32":
            if not HAVE_PYAUDIO:
                logging.warning("[AudioDevices] PyAudio not available")
                return []
            with open_pyaudio() as p:
                for info in _iter_input_infos(p):
                    # WPatch marks WASAPI loopbacks with isLoopbackDevice
                    if info.get("isLoopbackDevice", False):
                        continue
                    try:
                        devices.append(_device_from_info(info, is_loopback=False))
                    except Exception as e:
                        logging.debug(f"[AudioDevices] Error building input device: {e}")
        else:
            # 1) Stable pulse sources (real mics) — capture via ffmpeg
            pulse_mics = _list_pulse_input_devices()
            devices.extend(pulse_mics)
            seen = {d.name.lower() for d in devices}
            for d in pulse_mics:
                if d.pulse_name:
                    seen.add(d.pulse_name.lower())

            # 2) Filtered PortAudio ALSA hw devices (skip JACK app zoo)
            if HAVE_PYAUDIO:
                try:
                    with open_pyaudio() as p:
                        for info in _iter_input_infos(p):
                            if not _is_linux_portaudio_mic_candidate(p, info):
                                continue
                            try:
                                dev = _device_from_info(info, is_loopback=False)
                            except Exception as e:
                                logging.debug(f"[AudioDevices] Error building input device: {e}")
                                continue
                            if dev.name.lower() in seen:
                                continue
                            # Skip ALSA hw duplicates of pulse labels (rough)
                            if any(dev.name.lower() in s or s in dev.name.lower() for s in seen if len(s) > 5):
                                # Keep distinct hw: names like "USB Audio Device: - (hw:0,0)"
                                if "hw:" not in dev.name.lower():
                                    continue
                            devices.append(dev)
                            seen.add(dev.name.lower())
                except Exception as e:
                    logging.debug(f"[AudioDevices] PortAudio mic scan failed: {e}")
            elif not devices:
                logging.warning("[AudioDevices] PyAudio not available and no pulse mics")

        logging.debug(f"[AudioDevices] Listed {len(devices)} microphone device(s)")

    except Exception as e:
        logging.error(f"[AudioDevices] Error listing input devices: {e}")

    return devices


def _list_portaudio_monitor_devices() -> List[AudioDevice]:
    """Linux: PortAudio devices whose names look like monitor sources."""
    if not HAVE_PYAUDIO:
        return []

    devices: List[AudioDevice] = []
    try:
        with open_pyaudio() as p:
            for info in _iter_input_infos(p):
                name = str(info.get("name", ""))
                if not is_monitor_device_name(name):
                    continue
                try:
                    devices.append(_device_from_info(info, is_loopback=True))
                except Exception as e:
                    logging.debug(f"[AudioDevices] Error building monitor device: {e}")
    except Exception as e:
        logging.debug(f"[AudioDevices] PortAudio monitor scan failed: {e}")
    return devices


def _list_pulse_monitor_devices() -> List[AudioDevice]:
    """
    Linux: PipeWire/Pulse monitor sources via pactl → synthetic AudioDevices.

    Used when PortAudio does not expose ``*.monitor`` names (common ALSA-only
    builds). Capture goes through ffmpeg ``-f pulse``.
    """
    try:
        from .pulse_monitors import (
            PULSE_DEVICE_INDEX_BASE,
            list_pulse_monitor_sources,
        )
    except ImportError:
        return []

    devices: List[AudioDevice] = []
    for i, mon in enumerate(list_pulse_monitor_sources()):
        devices.append(
            AudioDevice(
                name=mon.display_label(),
                index=PULSE_DEVICE_INDEX_BASE - i,
                is_loopback=True,
                channels=max(1, mon.channels),
                sample_rate=int(mon.sample_rate or 48000),
                host_api=-1,
                backend=BACKEND_PULSE,
                pulse_name=mon.name,
            )
        )
    return devices


def list_loopback_devices() -> List[AudioDevice]:
    """
    List system/desktop audio capture devices.

    Windows: WASAPI loopback devices via PyAudioWPatch.
    Linux: PortAudio monitor-name matches, plus Pulse/PipeWire monitors from
    ``pactl`` (ffmpeg pulse capture) when PortAudio does not list them.

    Returns:
        List of AudioDevice objects for loopback/monitor devices.
    """
    devices: List[AudioDevice] = []

    try:
        if sys.platform == "win32":
            if not HAVE_PYAUDIO:
                logging.warning("[AudioDevices] PyAudio not available")
                return []
            with open_pyaudio() as p:
                # WPatch-only generator
                for info in p.get_loopback_device_info_generator():
                    try:
                        devices.append(_device_from_info(info, is_loopback=True))
                    except Exception as e:
                        logging.debug(f"[AudioDevices] Error reading loopback device: {e}")
        else:
            # 1) PortAudio name heuristics (when Pulse host API / names exist)
            pa_monitors = _list_portaudio_monitor_devices()
            devices.extend(pa_monitors)

            # 2) pactl monitors — primary path on ALSA-only PortAudio builds
            pulse_monitors = _list_pulse_monitor_devices()
            # Dedupe by pulse source name / display against PortAudio monitor names
            existing_keys: set[str] = set()
            for d in devices:
                existing_keys.add(d.name.lower())
                if d.pulse_name:
                    existing_keys.add(d.pulse_name.lower())

            for d in pulse_monitors:
                keys = {d.name.lower()}
                if d.pulse_name:
                    keys.add(d.pulse_name.lower())
                if keys & existing_keys:
                    continue
                devices.append(d)
                existing_keys |= keys

        if devices:
            logging.debug(f"[AudioDevices] Listed {len(devices)} loopback/monitor device(s)")
        else:
            logging.debug(
                "[AudioDevices] No loopback/monitor devices found "
                "(on Linux, need pactl + ffmpeg for PipeWire monitors when "
                "PortAudio has no Pulse host API)"
            )

    except Exception as e:
        logging.error(f"[AudioDevices] Error listing loopback devices: {e}")

    return devices


def get_default_input_device() -> Optional[AudioDevice]:
    """
    Get the default input device (microphone).

    Linux: prefer the Pulse/PipeWire default source when it is a real mic
    (not a monitor), matched against ``list_input_devices()``. Avoids PortAudio's
    virtual ``default``/``pipewire`` (128-ch) devices that crash on open.

    Returns:
        AudioDevice for the default input, or None if not available.
    """
    if sys.platform != "win32":
        try:
            mics = list_input_devices()
            if not mics:
                return None
            try:
                from .pulse_monitors import get_default_source_name

                default_src = get_default_source_name()
            except ImportError:
                default_src = None

            if default_src and not str(default_src).endswith(".monitor"):
                for d in mics:
                    if d.pulse_name and d.pulse_name == default_src:
                        return d
            # First listed real mic (pulse sources are sorted first)
            return mics[0]
        except Exception as e:
            logging.error(f"[AudioDevices] Error getting default input: {e}")
            return None

    if not HAVE_PYAUDIO:
        return None

    try:
        with open_pyaudio() as p:
            try:
                info = p.get_default_input_device_info()
                return _device_from_info(info, is_loopback=False)
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
    Linux: monitor of the default Pulse/PipeWire sink when available,
    otherwise the first listed loopback/monitor device.

    Returns:
        AudioDevice for the default loopback/monitor, or None if not available.
    """
    if sys.platform == "win32":
        if not HAVE_PYAUDIO:
            return None
        try:
            with open_pyaudio() as p:
                try:
                    info = p.get_default_wasapi_loopback()
                    return _device_from_info(info, is_loopback=True)
                except (OSError, LookupError):
                    logging.debug("[AudioDevices] No default WASAPI loopback device found")
                    return None
        except Exception as e:
            logging.error(f"[AudioDevices] Error getting default loopback: {e}")
            return None

    # Linux / other
    try:
        monitors = list_loopback_devices()
        if not monitors:
            logging.debug("[AudioDevices] No default monitor/loopback device found")
            return None

        # Prefer monitor of the default sink (matches user's active headphones/speakers)
        try:
            from .pulse_monitors import get_default_sink_name

            default_sink = get_default_sink_name()
        except ImportError:
            default_sink = None

        if default_sink:
            expected = f"{default_sink}.monitor"
            for d in monitors:
                if d.pulse_name and d.pulse_name == expected:
                    return d
                if d.pulse_name and d.pulse_name.startswith(default_sink):
                    return d
                # PortAudio path may expose full .monitor name
                if d.name == expected or (d.name.endswith(".monitor") and default_sink in d.name):
                    return d

        return monitors[0]

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
