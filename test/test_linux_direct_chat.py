"""Regression tests for Linux Direct Chat trigger routing."""

from unittest.mock import MagicMock, patch

import main
from src.gui.snip_tool import SnipToolApp
from src.gui.text_edit_tool import TextEditToolApp
from src.tray import TrayApp


def test_show_direct_chat_bypasses_selection_capture():
    config = {"text_edit_tool_enabled": True, "tts_enabled": False}
    with (
        patch("src.gui.text_edit_tool.TextHandler") as mock_handler_class,
        patch("src.gui.core.GUICoordinator") as mock_coordinator_class,
        patch("src.platform.pointer.get_pointer_position", return_value=(100, 200)),
    ):
        coordinator = MagicMock()
        mock_coordinator_class.get_instance.return_value = coordinator
        handler = mock_handler_class.return_value
        app = TextEditToolApp(config=config, ai_params={}, key_managers={})

        app.show_direct_chat()

    handler.get_selected_text.assert_not_called()
    handler.get_selected_text_with_retry.assert_not_called()
    coordinator.request_input_popup.assert_called_once()
    kwargs = coordinator.request_input_popup.call_args.kwargs
    assert (kwargs["x"], kwargs["y"]) == (100, 220)
    assert kwargs["on_tts"] is None


def test_clipboard_textedit_uses_clipboard_without_selection_capture():
    config = {"text_edit_tool_enabled": True, "tts_enabled": False}
    with (
        patch("src.gui.text_edit_tool.TextHandler") as mock_handler_class,
        patch("src.gui.core.GUICoordinator") as mock_coordinator_class,
        patch("src.platform.pointer.get_pointer_position", return_value=(100, 200)),
    ):
        coordinator = MagicMock()
        mock_coordinator_class.get_instance.return_value = coordinator
        handler = mock_handler_class.return_value
        handler.get_clipboard_text.return_value = "intentionally copied text"
        app = TextEditToolApp(config=config, ai_params={}, key_managers={})

        app._show_clipboard_popup()

    handler.get_clipboard_text.assert_called_once()
    handler.get_selected_text.assert_not_called()
    handler.get_selected_text_with_retry.assert_not_called()
    kwargs = coordinator.request_prompt_popup.call_args.kwargs
    assert kwargs["selected_text"] == "intentionally copied text"
    assert (kwargs["x"], kwargs["y"]) == (100, 220)


def test_tray_direct_chat_uses_explicit_direct_chat_path():
    app = MagicMock()
    with patch("src.gui.text_edit_tool.get_instance", return_value=app):
        TrayApp(allow_console_toggle=False)._on_direct_chat(None)

    app.show_direct_chat.assert_called_once()
    app._on_hotkey_pressed.assert_not_called()


def test_chat_textedit_and_clipboard_triggers_take_separate_routes(monkeypatch):
    app = MagicMock()
    monkeypatch.setattr(main, "_TOOLS_READY", True)

    with patch("src.gui.text_edit_tool.get_instance", return_value=app):
        assert main.dispatch_trigger("chat") == (True, "")
        assert main.dispatch_trigger("textedit") == (True, "")
        assert main.dispatch_trigger("textedit-clipboard") == (True, "")

    app.show_direct_chat.assert_called_once()
    app._on_hotkey_pressed.assert_called_once()
    app._on_clipboard_hotkey_pressed.assert_called_once()


def test_linux_compare_confirmation_reuses_textedit_trigger():
    config = {"text_edit_tool_enabled": True, "tts_enabled": False}
    captured = []
    cancelled = []

    with (
        patch("src.gui.text_edit_tool.TextHandler") as mock_handler_class,
        patch("src.gui.text_edit_tool.is_linux", return_value=True),
        patch("src.platform.notifications.send_desktop_notification"),
        patch("src.gui.core.GUICoordinator") as mock_coordinator_class,
    ):
        coordinator = MagicMock()
        coordinator.run_on_gui_thread.side_effect = lambda callback: callback()
        mock_coordinator_class.get_instance.return_value = coordinator
        handler = mock_handler_class.return_value
        handler.get_selected_text.return_value = "second selection"
        app = TextEditToolApp(config=config, ai_params={}, key_managers={})

        app._on_request_compare_text(captured.append, lambda: cancelled.append(True))
        assert app._has_pending_linux_compare()
        app._capture_pending_linux_compare()

    handler.get_selected_text.assert_called_once()
    assert captured == ["second selection"]
    assert cancelled == []
    assert not app._has_pending_linux_compare()


def test_linux_compare_without_selection_restores_popup_callback():
    config = {"text_edit_tool_enabled": True, "tts_enabled": False}
    cancelled = []

    with (
        patch("src.gui.text_edit_tool.TextHandler") as mock_handler_class,
        patch("src.gui.text_edit_tool.is_linux", return_value=True),
        patch("src.platform.notifications.send_desktop_notification"),
        patch("src.gui.core.GUICoordinator") as mock_coordinator_class,
    ):
        coordinator = MagicMock()
        coordinator.run_on_gui_thread.side_effect = lambda callback: callback()
        mock_coordinator_class.get_instance.return_value = coordinator
        handler = mock_handler_class.return_value
        handler.get_selected_text.return_value = ""
        app = TextEditToolApp(config=config, ai_params={}, key_managers={})

        app._on_request_compare_text(MagicMock(), lambda: cancelled.append(True))
        app._capture_pending_linux_compare()

    assert cancelled == [True]


def test_snip_popup_receives_compositor_cursor_position():
    capture = MagicMock(width=640, height=480)
    with (
        patch("src.gui.snip_tool.PromptsConfig") as _mock_prompts_class,
        patch("src.gui.core.GUICoordinator") as mock_coordinator_class,
        patch("src.platform.pointer.get_pointer_position", return_value=(300, 400)),
    ):
        coordinator = MagicMock()
        mock_coordinator_class.get_instance.return_value = coordinator
        app = SnipToolApp(config={}, ai_params={}, key_managers={})
        app._get_combined_prompts = MagicMock(return_value={"snip_tool": {}})

        app._on_image_captured(capture)

    kwargs = coordinator.request_snip_popup.call_args.kwargs
    assert (kwargs["x"], kwargs["y"]) == (300, 420)
