#!/usr/bin/env python3
"""Tests for conditional tray menu updates and text edit tool popup TTS integration."""

from unittest.mock import MagicMock, patch

from src.gui.text_edit_tool import TextEditToolApp
from src.tray import TrayApp


class TestTrayAndPopupsConditional:
    """Test tray dynamic menu updates and popups based on configuration."""

    @patch("src.tray.HAVE_SYSTRAY", True)
    @patch("src.tray.SysTrayIcon")
    def test_tray_menu_conditional_and_dynamic_updates(self, mock_systray_class):
        """Test tray menu options match config.ini enabled states and update dynamically."""
        mock_systray_instance = MagicMock()
        mock_systray_class.return_value = mock_systray_instance

        # Mock web_server.CONFIG
        config_mock = {
            "text_edit_tool_enabled": True,
            "screen_snip_enabled": False,
            "audio_tool_enabled": True,
            "tts_enabled": False,
        }

        with patch("src.web_server.CONFIG", config_mock):
            tray = TrayApp(allow_console_toggle=False)
            # Call build_menu_options directly to test logic
            opts = tray.build_menu_options()
            opt_names = [o[0] for o in opts]

            # Direct Chat (Text Edit) and Audio Analyzer should be present
            # Screen Snip and TTS should be absent
            assert "💬 Direct Chat" in opt_names or "Direct Chat" in opt_names
            assert "🎤 Audio Analyzer" in opt_names or "Audio Analyzer" in opt_names
            assert not any("Snip" in name for name in opt_names)
            assert not any("TTS" in name for name in opt_names)

            # Test dynamic update upon config change event
            tray.systray = mock_systray_instance
            config_mock["tts_enabled"] = True
            config_mock["text_edit_tool_enabled"] = False

            # Simulate config change notification callback
            tray._on_config_changed("tts_enabled", True)

            # Verify that update_menu_options was called on mock_systray_instance
            assert mock_systray_instance.update_menu_options.called
            new_opts = mock_systray_instance.update_menu_options.call_args[0][0]
            new_opt_names = [o[0] for o in new_opts]

            # TTS should now be present, Direct Chat should be absent
            assert "🔊 TTS" in new_opt_names or "TTS" in new_opt_names
            assert not any("Direct Chat" in name for name in new_opt_names)

    @patch("src.gui.core.GUICoordinator")
    @patch("src.gui.text_edit_tool.TextHandler")
    def test_text_edit_tool_popup_tts_conditional(self, mock_text_handler_class, mock_coordinator_class):
        """Test that TextEditTool popup hides TTS button if TTS is disabled."""
        mock_coordinator_instance = MagicMock()
        mock_coordinator_class.get_instance.return_value = mock_coordinator_instance

        mock_text_handler = MagicMock()
        mock_text_handler_class.return_value = mock_text_handler

        config = {
            "tts_enabled": False,
            "text_edit_tool_enabled": True,
        }

        # Mock selected text to be "hello"
        mock_text_handler.get_selected_text.return_value = "hello"
        mock_text_handler.get_selected_text_with_retry.return_value = "hello"

        app = TextEditToolApp(config=config, ai_params={}, key_managers={})
        app._show_popup()

        # Check prompt popup call
        mock_coordinator_instance.request_prompt_popup.assert_called_once()
        _, kwargs = mock_coordinator_instance.request_prompt_popup.call_args
        assert kwargs["on_tts"] is None

        # Reset mock
        mock_coordinator_instance.reset_mock()

        # Now test with tts_enabled = True
        config["tts_enabled"] = True
        app._show_popup()

        # Check prompt popup call
        mock_coordinator_instance.request_prompt_popup.assert_called_once()
        _, kwargs = mock_coordinator_instance.request_prompt_popup.call_args
        assert kwargs["on_tts"] == app._on_tts_requested
