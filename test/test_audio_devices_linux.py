"""Unit tests for Linux audio device classification and enumeration (mocked PortAudio)."""

from __future__ import annotations

from contextlib import contextmanager
from typing import Any
from unittest.mock import patch

import pytest

from src.audio.devices import (
    AudioDevice,
    get_default_loopback_device,
    is_monitor_device_name,
    list_input_devices,
    list_loopback_devices,
)

# ---------------------------------------------------------------------------
# is_monitor_device_name
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "name",
    [
        "alsa_output.pci-0000_00_1f.3.analog-stereo.monitor",
        "bluez_output.XX_XX.1.monitor",
        "Monitor of Built-in Audio Analog Stereo",
        "MONITOR OF HDMI Output",
        "Speakers monitor",
        "Some Device.monitor",
        "monitor",
        "  alsa_output.foo.monitor  ",
    ],
)
def test_is_monitor_device_name_true(name: str):
    assert is_monitor_device_name(name) is True


@pytest.mark.parametrize(
    "name",
    [
        "Built-in Audio Analog Stereo",
        "USB Microphone",
        "alsa_input.usb-Device-00.analog-stereo",
        "default",
        "pipewire",
        "",
        "monitoring station mic",  # contains "monitor" mid-word phrase but not our patterns
        "FooMonitorBar",
    ],
)
def test_is_monitor_device_name_false(name: str):
    assert is_monitor_device_name(name) is False


# ---------------------------------------------------------------------------
# Mocked PortAudio enumeration
# ---------------------------------------------------------------------------


def _device_info(
    index: int,
    name: str,
    *,
    max_input: int = 2,
    rate: float = 48000.0,
    host_api: int = 0,
    is_loopback: bool = False,
) -> dict[str, Any]:
    info: dict[str, Any] = {
        "index": index,
        "name": name,
        "maxInputChannels": max_input,
        "maxOutputChannels": 0 if max_input else 2,
        "defaultSampleRate": rate,
        "hostApi": host_api,
    }
    if is_loopback:
        info["isLoopbackDevice"] = True
    return info


SAMPLE_LINUX_DEVICES = [
    _device_info(0, "HDA Intel PCH: ALC897 Analog (hw:0,0)", max_input=2),
    _device_info(1, "USB Microphone", max_input=1, rate=44100.0),
    _device_info(2, "alsa_output.pci-0000_00_1f.3.analog-stereo.monitor", max_input=2),
    _device_info(3, "Monitor of HDMI / DisplayPort 3 Output", max_input=2),
    _device_info(4, "HD Audio Speaker", max_input=0),  # output-only — ignored
    _device_info(5, "pipewire", max_input=64),  # virtual default input
]


class _FakePyAudio:
    """Minimal PyAudio stand-in for device enumeration tests."""

    def __init__(self, devices: list[dict[str, Any]]):
        self._devices = devices

    def terminate(self):
        return None

    def get_device_count(self) -> int:
        return len(self._devices)

    def get_device_info_by_index(self, i: int) -> dict[str, Any]:
        return dict(self._devices[i])

    def get_default_input_device_info(self) -> dict[str, Any]:
        for d in self._devices:
            if d.get("maxInputChannels", 0) > 0 and not is_monitor_device_name(d["name"]):
                return dict(d)
        raise OSError("No default input")

    def get_loopback_device_info_generator(self):
        raise AssertionError("Windows-only loopback generator must not be called on Linux")

    def get_default_wasapi_loopback(self):
        raise AssertionError("Windows-only WASAPI loopback must not be called on Linux")


@contextmanager
def _patch_linux_backend(devices: list[dict[str, Any]], *, pulse_monitors: list | None = None):
    """Patch PortAudio enumeration; pulse_monitors defaults to [] (no pactl)."""
    fake = _FakePyAudio(devices)
    if pulse_monitors is None:
        pulse_monitors = []

    @contextmanager
    def _open_pyaudio():
        yield fake

    with (
        patch("src.audio.devices.HAVE_PYAUDIO", True),
        patch("src.audio.devices.open_pyaudio", _open_pyaudio),
        patch("src.audio.devices.sys.platform", "linux"),
        patch("src.audio.devices._list_pulse_monitor_devices", return_value=pulse_monitors),
    ):
        yield fake


def test_list_input_devices_excludes_monitors_on_linux():
    with _patch_linux_backend(SAMPLE_LINUX_DEVICES):
        mics = list_input_devices()

    names = [d.name for d in mics]
    assert "USB Microphone" in names
    assert "HDA Intel PCH: ALC897 Analog (hw:0,0)" in names
    assert "pipewire" in names
    assert all(not d.is_loopback for d in mics)
    assert not any("monitor" in n.lower() and is_monitor_device_name(n) for n in names)
    # Output-only device excluded
    assert "HD Audio Speaker" not in names


def test_list_loopback_devices_finds_monitors_on_linux():
    with _patch_linux_backend(SAMPLE_LINUX_DEVICES):
        monitors = list_loopback_devices()

    names = [d.name for d in monitors]
    assert len(monitors) == 2
    assert any(n.endswith(".monitor") for n in names)
    assert any("Monitor of" in n for n in names)
    assert all(d.is_loopback for d in monitors)
    assert all(d.sample_rate == 48000 for d in monitors)


def test_linux_loopback_does_not_call_windows_apis():
    """get_loopback_device_info_generator / get_default_wasapi_loopback must not run on Linux."""
    with _patch_linux_backend(SAMPLE_LINUX_DEVICES) as fake:
        # Would raise AssertionError if Windows APIs were used
        list_loopback_devices()
        get_default_loopback_device()
        # Also ensure generator was never accessed via the mock module path
        assert not hasattr(fake, "_windows_called")


def test_get_default_loopback_device_linux_returns_first_monitor():
    with _patch_linux_backend(SAMPLE_LINUX_DEVICES):
        default = get_default_loopback_device()

    assert default is not None
    assert default.is_loopback is True
    assert is_monitor_device_name(default.name)


def test_get_default_loopback_device_linux_none_when_empty():
    only_mics = [
        _device_info(0, "USB Microphone", max_input=1),
    ]
    with _patch_linux_backend(only_mics):
        assert get_default_loopback_device() is None
        assert list_loopback_devices() == []


def test_list_devices_empty_when_pyaudio_missing_and_no_pulse():
    with (
        patch("src.audio.devices.HAVE_PYAUDIO", False),
        patch("src.audio.devices.sys.platform", "linux"),
        patch("src.audio.devices._list_pulse_monitor_devices", return_value=[]),
    ):
        assert list_input_devices() == []
        assert list_loopback_devices() == []
        assert get_default_loopback_device() is None


def test_list_loopback_includes_pulse_monitors_when_portaudio_has_none():
    """ALSA-only PortAudio: no *.monitor names; pactl supplies loopback devices."""
    only_mics = [
        _device_info(0, "USB Microphone", max_input=1),
        _device_info(1, "pipewire", max_input=64),
    ]
    pulse = [
        AudioDevice(
            name="USB Audio Device Analog Stereo",
            index=-1000,
            is_loopback=True,
            channels=2,
            sample_rate=48000,
            host_api=-1,
            backend="pulse",
            pulse_name="alsa_output.usb-Device-00.analog-stereo.monitor",
        )
    ]
    with _patch_linux_backend(only_mics, pulse_monitors=pulse):
        loops = list_loopback_devices()
        default = get_default_loopback_device()

    assert len(loops) == 1
    assert loops[0].name == "USB Audio Device Analog Stereo"
    assert loops[0].uses_pulse_capture is True
    assert loops[0].pulse_name.endswith(".monitor")
    assert default is not None
    assert default.pulse_name == loops[0].pulse_name


def test_default_loopback_prefers_default_sink_monitor():
    pulse = [
        AudioDevice(
            name="HDMI",
            index=-1000,
            is_loopback=True,
            channels=2,
            sample_rate=48000,
            backend="pulse",
            pulse_name="alsa_output.pci-hdmi.monitor",
        ),
        AudioDevice(
            name="USB Audio Device Analog Stereo",
            index=-1001,
            is_loopback=True,
            channels=2,
            sample_rate=48000,
            backend="pulse",
            pulse_name="alsa_output.usb-headphones.analog-stereo.monitor",
        ),
    ]
    # get_default_loopback_device does a late import from pulse_monitors
    with (
        _patch_linux_backend([], pulse_monitors=pulse),
        patch(
            "src.audio.pulse_monitors.get_default_sink_name",
            return_value="alsa_output.usb-headphones.analog-stereo",
        ),
    ):
        default = get_default_loopback_device()

    assert default is not None
    assert default.name == "USB Audio Device Analog Stereo"
    assert "usb-headphones" in (default.pulse_name or "")


def test_windows_path_uses_loopback_generator_not_monitor_names():
    """On win32, loopback list uses WPatch generator; monitor names alone are not enough."""
    win_devices = [
        _device_info(0, "Microphone", max_input=1),
        # Name looks like a monitor but Windows path ignores name heuristics for loopback list
        _device_info(1, "Speakers (loopback)", max_input=2, is_loopback=True),
    ]
    loopback_only = [
        _device_info(1, "Speakers (loopback)", max_input=2, is_loopback=True),
    ]

    class _WinPyAudio(_FakePyAudio):
        def get_loopback_device_info_generator(self):
            yield from loopback_only

        def get_default_wasapi_loopback(self):
            return dict(loopback_only[0])

    fake = _WinPyAudio(win_devices)

    @contextmanager
    def _open_pyaudio():
        yield fake

    with (
        patch("src.audio.devices.HAVE_PYAUDIO", True),
        patch("src.audio.devices.open_pyaudio", _open_pyaudio),
        patch("src.audio.devices.sys.platform", "win32"),
    ):
        mics = list_input_devices()
        loops = list_loopback_devices()
        default_loop = get_default_loopback_device()

    assert [d.name for d in mics] == ["Microphone"]
    assert [d.name for d in loops] == ["Speakers (loopback)"]
    assert all(d.is_loopback for d in loops)
    assert default_loop is not None
    assert default_loop.name == "Speakers (loopback)"


def test_audio_device_display_name():
    mic = AudioDevice("Mic", 0, False, 1, 44100)
    loop = AudioDevice("System", 1, True, 2, 48000)
    assert "🎤" in mic.get_display_name()
    assert "🔊" in loop.get_display_name()
    assert "[Loopback]" in str(loop)
