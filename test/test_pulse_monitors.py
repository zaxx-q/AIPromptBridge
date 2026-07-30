"""Unit tests for Pulse/PipeWire monitor discovery (pactl parsing)."""

from __future__ import annotations

from unittest.mock import patch

from src.audio.pulse_monitors import (
    PulseMonitorSource,
    get_default_sink_name,
    list_pulse_monitor_sources,
)

SAMPLE_PACTL_SOURCES = """
Source #51
	State: RUNNING
	Name: alsa_output.usb-C-Media_Electronics_Inc._USB_Audio_Device-00.analog-stereo.monitor
	Description: Monitor of USB Audio Device Analog Stereo
	Driver: PipeWire
	Sample Specification: s16le 2ch 48000Hz
	Channel Map: front-left,front-right
	Owner Module: n/a
	Mute: no
	Volume: front-left: 65536 / 100% / 0.00 dB,   front-right: 65536 / 100% / 0.00 dB
	Base Volume: 65536 / 100% / 0.00 dB
	Monitor of Sink: alsa_output.usb-C-Media_Electronics_Inc._USB_Audio_Device-00.analog-stereo
	Latency: 0 usec, configured 0 usec
	Flags: DECK HARDWARE DECIBEL_VOLUME LATENCY 

Source #52
	State: SUSPENDED
	Name: alsa_input.usb-C-Media_Electronics_Inc._USB_Audio_Device-00.mono-fallback
	Description: USB Audio Device Mono
	Driver: PipeWire
	Sample Specification: s16le 1ch 48000Hz
	Channel Map: mono
	Owner Module: n/a
	Mute: no
	Volume: mono: 65536 / 100% / 0.00 dB
	Base Volume: 27111 /  41% / -23.00 dB
	Monitor of Sink: n/a
	Latency: 0 usec, configured 0 usec
	Flags: HARDWARE HW_MUTE_CTRL HW_VOLUME_CTRL DECIBEL_VOLUME LATENCY 
"""


def test_list_pulse_monitor_sources_parses_only_monitors():
    with patch("src.audio.pulse_monitors._run_pactl", return_value=SAMPLE_PACTL_SOURCES):
        mons = list_pulse_monitor_sources()

    assert len(mons) == 1
    mon = mons[0]
    assert mon.name.endswith(".analog-stereo.monitor")
    assert mon.sink_name.endswith(".analog-stereo")
    assert mon.channels == 2
    assert mon.sample_rate == 48000
    assert "Monitor of" in mon.description
    # Mic with Monitor of Sink: n/a must be excluded
    assert all("mono" not in m.name.lower() or m.name.endswith(".monitor") for m in mons)


def test_display_label_strips_monitor_of():
    mon = PulseMonitorSource(
        name="alsa_output.foo.analog-stereo.monitor",
        description="Monitor of USB Audio Device Analog Stereo",
        sink_name="alsa_output.foo.analog-stereo",
    )
    assert mon.display_label() == "USB Audio Device Analog Stereo"


def test_list_pulse_monitor_sources_empty_when_pactl_fails():
    with patch("src.audio.pulse_monitors._run_pactl", return_value=None):
        assert list_pulse_monitor_sources() == []


def test_get_default_sink_name():
    with patch(
        "src.audio.pulse_monitors._run_pactl",
        return_value="alsa_output.usb-Device-00.analog-stereo\n",
    ):
        assert get_default_sink_name() == "alsa_output.usb-Device-00.analog-stereo"

    with patch("src.audio.pulse_monitors._run_pactl", return_value=None):
        assert get_default_sink_name() is None
