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


def test_niri_focused_output_geometry():
    niri_out = '{"name": "eDP-1", "logical": {"x": 100, "y": 200, "width": 1920, "height": 1080}}'
    with (
        patch.object(pointer, "is_linux", return_value=True),
        patch.object(pointer, "is_wayland", return_value=True),
        patch.dict(pointer.os.environ, {"NIRI_SOCKET": "/tmp/niri.sock"}, clear=True),
        patch.object(pointer.shutil, "which", side_effect=lambda name: "/usr/bin/niri" if name == "niri" else None),
        patch.object(pointer, "_run_command", return_value=niri_out) as command,
    ):
        assert pointer.get_focused_output_geometry() == (100, 200, 1920, 1080)

    command.assert_called_once_with(["niri", "msg", "-j", "focused-output"])


def test_sway_focused_output_geometry():
    sway_out = (
        '[{"name": "eDP-1", "active": true, "focused": true, "rect": {"x": 0, "y": 0, "width": 2560, "height": 1440}}]'
    )
    with (
        patch.object(pointer, "is_linux", return_value=True),
        patch.object(pointer, "is_wayland", return_value=True),
        patch.dict(pointer.os.environ, {"SWAYSOCK": "/tmp/sway.sock"}, clear=True),
        patch.object(
            pointer.shutil, "which", side_effect=lambda name: "/usr/bin/swaymsg" if name == "swaymsg" else None
        ),
        patch.object(pointer, "_run_command", return_value=sway_out) as command,
    ):
        assert pointer.get_focused_output_geometry() == (0, 0, 2560, 1440)

    command.assert_called_once_with(["swaymsg", "-t", "get_outputs", "-r"])


def test_hyprland_focused_output_geometry():
    hypr_out = '[{"id": 0, "name": "DP-1", "focused": true, "x": 1920, "y": 0, "width": 1920, "height": 1080}]'
    with (
        patch.object(pointer, "is_linux", return_value=True),
        patch.object(pointer, "is_wayland", return_value=True),
        patch.dict(pointer.os.environ, {"HYPRLAND_INSTANCE_SIGNATURE": "hypr"}, clear=True),
        patch.object(
            pointer.shutil, "which", side_effect=lambda name: "/usr/bin/hyprctl" if name == "hyprctl" else None
        ),
        patch.object(pointer, "_run_command", return_value=hypr_out) as command,
    ):
        assert pointer.get_focused_output_geometry() == (1920, 0, 1920, 1080)

    command.assert_called_once_with(["hyprctl", "monitors", "-j"])


def test_focused_output_geometry_not_wayland():
    with (
        patch.object(pointer, "is_linux", return_value=True),
        patch.object(pointer, "is_wayland", return_value=False),
    ):
        assert pointer.get_focused_output_geometry() is None


def test_get_popup_position_wayland_focused_output():
    from unittest.mock import MagicMock

    from src.gui.popups import _get_popup_position

    mock_root = MagicMock()
    mock_root.winfo_reqwidth.return_value = 400
    mock_root.winfo_reqheight.return_value = 300
    mock_root.winfo_pointerx.side_effect = AssertionError("Should not query winfo_pointerx on Wayland")

    with (
        patch("src.gui.popups.is_wayland", return_value=True),
        patch("src.gui.popups.get_pointer_position", return_value=None),
        patch("src.gui.popups.get_focused_output_geometry", return_value=(0, 0, 1920, 1080)),
    ):
        x, y = _get_popup_position(mock_root)
        # Centered horizontally: (1920 - 400) // 2 = 760
        # Upper-centered vertically: (1080 - 300) // 3 = 260
        assert (x, y) == (760, 260)


def test_get_popup_position_wayland_screen_fallback():
    from unittest.mock import MagicMock

    from src.gui.popups import _get_popup_position

    mock_root = MagicMock()
    mock_root.winfo_reqwidth.return_value = 400
    mock_root.winfo_reqheight.return_value = 300
    mock_root.winfo_screenwidth.return_value = 1920
    mock_root.winfo_screenheight.return_value = 1080
    mock_root.winfo_pointerx.side_effect = AssertionError("Should not query winfo_pointerx on Wayland")

    with (
        patch("src.gui.popups.is_wayland", return_value=True),
        patch("src.gui.popups.get_pointer_position", return_value=None),
        patch("src.gui.popups.get_focused_output_geometry", return_value=None),
    ):
        x, y = _get_popup_position(mock_root)
        assert (x, y) == (760, 260)


def test_get_popup_position_non_wayland_falls_back_to_pointer():
    from unittest.mock import MagicMock

    from src.gui.popups import _get_popup_position

    mock_root = MagicMock()
    mock_root.winfo_pointerx.return_value = 500
    mock_root.winfo_pointery.return_value = 300

    with (
        patch("src.gui.popups.is_wayland", return_value=False),
        patch("src.gui.popups.get_pointer_position", return_value=None),
    ):
        x, y = _get_popup_position(mock_root, offset_x=5, offset_y=20)
        assert (x, y) == (505, 320)


def test_setup_popup_window_linux():
    from unittest.mock import MagicMock

    from src.gui.popups import setup_popup_window

    mock_win = MagicMock()
    with patch("sys.platform", "linux"):
        setup_popup_window(mock_win)
        mock_win.attributes.assert_any_call("-type", "splash")
        mock_win.attributes.assert_any_call("-topmost", True)
        mock_win.overrideredirect.assert_not_called()


def test_setup_popup_window_windows():
    from unittest.mock import MagicMock

    from src.gui.popups import setup_popup_window

    mock_win = MagicMock()
    with patch("sys.platform", "win32"):
        setup_popup_window(mock_win)
        mock_win.overrideredirect.assert_called_once_with(True)
        mock_win.attributes.assert_called_once_with("-topmost", True)


def test_reposition_window_linux_skips_geometry():
    """On Linux, _reposition_window updates idle tasks without calling geometry()."""
    from unittest.mock import MagicMock

    from src.gui.popups import AttachedPromptPopup

    mock_popup = MagicMock(spec=AttachedPromptPopup)
    mock_popup.root = MagicMock()

    with patch("sys.platform", "linux"):
        AttachedPromptPopup._reposition_window(mock_popup)

    mock_popup.root.update_idletasks.assert_called_once()
    mock_popup.root.geometry.assert_not_called()
