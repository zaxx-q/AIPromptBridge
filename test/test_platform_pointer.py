"""Tests for best-effort compositor cursor lookup."""

from unittest.mock import patch

from src.platform import pointer


def test_hyprland_cursor_position_is_preferred():
    with (
        patch.object(pointer, "is_linux", return_value=True),
        patch.object(pointer, "is_wayland", return_value=True),
        patch.dict(pointer.os.environ, {"HYPRLAND_INSTANCE_SIGNATURE": "test"}, clear=True),
        patch.object(
            pointer.shutil, "which", side_effect=lambda name: "/usr/bin/hyprctl" if name == "hyprctl" else None
        ),
        patch.object(pointer, "_run_command", return_value="123.8, 456.2") as command,
    ):
        assert pointer.get_pointer_position() == (123, 456)

    command.assert_called_once_with(["hyprctl", "cursorpos"])


def test_sway_cursor_fields_are_used_when_available():
    seats = '[{"name": "seat0", "cursor": {"x": 44, "y": 88}}]'
    with (
        patch.object(pointer, "is_linux", return_value=True),
        patch.object(pointer, "is_wayland", return_value=True),
        patch.dict(pointer.os.environ, {"SWAYSOCK": "/tmp/sway.sock"}, clear=True),
        patch.object(
            pointer.shutil,
            "which",
            side_effect=lambda name: "/usr/bin/swaymsg" if name == "swaymsg" else None,
        ),
        patch.object(pointer, "_run_command", return_value=seats),
    ):
        assert pointer.get_pointer_position() == (44, 88)


def test_missing_compositor_tools_returns_none():
    with (
        patch.object(pointer, "is_linux", return_value=True),
        patch.object(pointer, "is_wayland", return_value=True),
        patch.object(pointer.shutil, "which", return_value=None),
    ):
        assert pointer.get_pointer_position() is None


def test_niri_session_does_not_probe_unrelated_compositor_commands():
    with (
        patch.object(pointer, "is_linux", return_value=True),
        patch.object(pointer, "is_wayland", return_value=True),
        patch.dict(pointer.os.environ, {"NIRI_SOCKET": "/tmp/niri.sock"}, clear=True),
        patch.object(pointer.shutil, "which") as which,
    ):
        assert pointer.get_pointer_position() is None

    which.assert_not_called()
