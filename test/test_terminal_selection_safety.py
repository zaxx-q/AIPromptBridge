"""Tests for terminal-safe TextEdit selection capture."""

from __future__ import annotations

from unittest.mock import patch

from src.gui.text_handler import TextHandler
from src.platform.input import copy_via_clipboard_shortcut_shifted


def _handler(config: dict) -> TextHandler:
    """Build a handler without creating pynput's real keyboard controller."""
    handler = object.__new__(TextHandler)
    handler.config = config
    return handler


def test_auto_terminal_uses_input_only_capture():
    handler = _handler({"text_edit_terminal_copy_shortcut": "auto"})

    with patch("src.gui.text_handler.is_focused_app_terminal", return_value=True):
        assert handler._get_linux_selection_capture_options() == (False, False, None)


def test_auto_non_terminal_uses_ctrl_c_capture():
    handler = _handler({"text_edit_terminal_copy_shortcut": "auto"})

    with patch("src.gui.text_handler.is_focused_app_terminal", return_value=False):
        assert handler._get_linux_selection_capture_options() == (True, False, None)


def test_explicit_shifted_mode_keeps_injected_copy():
    handler = _handler({"text_edit_terminal_copy_shortcut": "always_ctrl_shift_c"})

    with patch("src.gui.text_handler.is_focused_app_terminal", return_value=True):
        assert handler._get_linux_selection_capture_options() == (
            True,
            False,
            copy_via_clipboard_shortcut_shifted,
        )


def test_auto_terminal_uses_shifted_copy_on_windows():
    """Windows has no Wayland primary selection, so retain Ctrl+Shift+C there."""
    handler = _handler({"text_edit_terminal_copy_shortcut": "auto"})

    with (
        patch("src.gui.text_handler.is_focused_app_terminal", return_value=True),
        patch("src.gui.text_handler.is_windows", return_value=True),
    ):
        assert handler._should_use_shifted_copy() is True


def test_terminal_get_selected_text_skips_all_selection_capture():
    handler = _handler({"text_edit_terminal_copy_shortcut": "auto"})

    with (
        patch("src.gui.text_handler.is_linux", return_value=True),
        patch("src.gui.text_handler.is_focused_app_terminal", return_value=True),
        patch("src.gui.text_handler.capture_selection_for_textedit") as capture,
    ):
        assert handler.get_selected_text() == ""

    capture.assert_not_called()


def test_explicit_clipboard_read_uses_regular_linux_clipboard():
    with (
        patch("src.gui.text_handler.is_linux", return_value=True),
        patch("src.gui.text_handler.platform_paste_text", return_value="copied text") as paste,
    ):
        assert TextHandler.get_clipboard_text() == "copied text"

    paste.assert_called_once_with(primary=False)
