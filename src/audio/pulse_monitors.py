#!/usr/bin/env python3
"""
PipeWire / PulseAudio monitor source discovery for Linux desktop capture.

PortAudio on many Linux builds only exposes ALSA (+ sometimes JACK) host APIs.
It does **not** list Pulse/PipeWire ``*.monitor`` sources by name, so system
audio (loopback equivalent) is invisible to name-heuristic enumeration alone.

This module queries ``pactl`` (Pulse protocol; works on PipeWire's pulse
server) for sources that are monitors of sinks. Capture itself is handled by
``AudioRecorder`` via ``ffmpeg -f pulse`` — verified more reliable than
PortAudio JACK dual-I/O devices on PipeWire (which can crash).

No GUI imports. Subprocess argv-only; timeouts; once-only missing-binary warning.
"""

from __future__ import annotations

import logging
import re
import shutil
import subprocess
import threading
from dataclasses import dataclass
from typing import List, Optional

__all__ = [
    "PulseMonitorSource",
    "get_default_sink_name",
    "is_pactl_available",
    "list_pulse_monitor_sources",
]

logger = logging.getLogger(__name__)

_PACTL_TIMEOUT = 5.0
_pactl_path: Optional[str] = None
_availability_checked = False
_availability_lock = threading.Lock()
_missing_warned = False

# Stable synthetic PortAudio-style index base for pulse-backed devices
# (negative so they never collide with real PortAudio indices).
PULSE_DEVICE_INDEX_BASE = -1000


@dataclass(frozen=True)
class PulseMonitorSource:
    """A PipeWire/Pulse source that monitors a sink (desktop/system audio)."""

    name: str
    """Pulse source name, e.g. ``alsa_output....analog-stereo.monitor``."""

    description: str
    """Human-readable description from pactl (often ``Monitor of …``)."""

    sink_name: str
    """Name of the sink being monitored."""

    channels: int = 2
    sample_rate: int = 48000

    def display_label(self) -> str:
        """
        Friendly label for UI dropdowns.

        Strips a leading ``Monitor of `` so the name matches the sink the user
        knows (e.g. ``USB Audio Device Analog Stereo``).
        """
        desc = (self.description or "").strip()
        lower = desc.lower()
        if lower.startswith("monitor of "):
            return desc[len("Monitor of ") :].strip() or self.name
        if desc:
            return desc
        # Fall back: last segment of pulse name without .monitor
        base = self.name
        if base.endswith(".monitor"):
            base = base[: -len(".monitor")]
        return base.split(".")[-1] if base else self.name


def _refresh_pactl_cache() -> None:
    global _pactl_path, _availability_checked, _missing_warned
    with _availability_lock:
        if _availability_checked:
            return
        _pactl_path = shutil.which("pactl")
        _availability_checked = True
        if _pactl_path is None and not _missing_warned:
            _missing_warned = True
            # Only relevant on Linux; callers gate on platform
            logger.warning(
                "[PulseMonitors] pactl not found on PATH. "
                "Install pulseaudio-utils / PipeWire pulse tools for system-audio "
                "(monitor) capture in Audio Analyzer."
            )


def is_pactl_available() -> bool:
    """Return True if ``pactl`` is on PATH."""
    _refresh_pactl_cache()
    return _pactl_path is not None


def _run_pactl(*args: str) -> Optional[str]:
    """Run pactl with argv-only args; return stdout text or None."""
    _refresh_pactl_cache()
    if not _pactl_path:
        return None
    try:
        result = subprocess.run(
            [_pactl_path, *args],
            capture_output=True,
            text=True,
            timeout=_PACTL_TIMEOUT,
            check=False,
        )
        if result.returncode != 0:
            logging.debug(
                "[PulseMonitors] pactl %s failed rc=%s stderr=%s",
                args,
                result.returncode,
                (result.stderr or "").strip()[:200],
            )
            return None
        return result.stdout or ""
    except subprocess.TimeoutExpired:
        logging.warning("[PulseMonitors] pactl timed out: %s", args)
        return None
    except Exception as e:
        logging.debug("[PulseMonitors] pactl error: %s", e)
        return None


def get_default_sink_name() -> Optional[str]:
    """Return the default Pulse/PipeWire sink name, or None."""
    out = _run_pactl("get-default-sink")
    if not out:
        return None
    name = out.strip().splitlines()[0].strip() if out.strip() else ""
    return name or None


def _parse_channel_count(block: str) -> int:
    """Best-effort channel count from a pactl source block."""
    # Sample Specification: s16le 2ch 48000Hz
    m = re.search(r"Sample Specification:\s*\S+\s+(\d+)ch\s+(\d+)Hz", block, re.I)
    if m:
        try:
            return max(1, int(m.group(1)))
        except ValueError:
            pass
    # Channel Map: front-left,front-right
    m = re.search(r"Channel Map:\s*(.+)", block)
    if m:
        parts = [p.strip() for p in m.group(1).split(",") if p.strip()]
        if parts:
            return max(1, len(parts))
    return 2


def _parse_sample_rate(block: str) -> int:
    m = re.search(r"Sample Specification:\s*\S+\s+\d+ch\s+(\d+)Hz", block, re.I)
    if m:
        try:
            return int(m.group(1))
        except ValueError:
            pass
    return 48000


def list_pulse_monitor_sources() -> List[PulseMonitorSource]:
    """
    List Pulse/PipeWire sources that monitor a sink (system audio).

    Parses ``pactl list sources``. Sources with ``Monitor of Sink: n/a``
    (real microphones) are excluded.
    """
    text = _run_pactl("list", "sources")
    if not text:
        return []

    sources: List[PulseMonitorSource] = []
    # Split on "Source #" headers (pactl list sources)
    blocks = re.split(r"\n(?=Source #)", text)
    for block in blocks:
        name_m = re.search(r"^\s*Name:\s*(\S+)\s*$", block, re.M)
        if not name_m:
            continue
        mon_m = re.search(r"^\s*Monitor of Sink:\s*(\S+)\s*$", block, re.M)
        if not mon_m:
            continue
        sink = mon_m.group(1).strip()
        if not sink or sink.lower() == "n/a":
            continue

        desc_m = re.search(r"^\s*Description:\s*(.+)\s*$", block, re.M)
        description = desc_m.group(1).strip() if desc_m else name_m.group(1)

        sources.append(
            PulseMonitorSource(
                name=name_m.group(1),
                description=description,
                sink_name=sink,
                channels=_parse_channel_count(block),
                sample_rate=_parse_sample_rate(block),
            )
        )

    if sources:
        logging.debug("[PulseMonitors] Found %d monitor source(s)", len(sources))
    else:
        logging.debug("[PulseMonitors] No monitor sources from pactl")

    return sources
