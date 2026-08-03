"""Unit tests for Linux streaming typing delay and buffer size settings."""

from unittest.mock import MagicMock, patch

from src.gui import snip_tool, text_edit_tool
from src.gui.text_edit_tool import TextEditToolApp
from src.gui.windows.settings_window.tab_tools import ToolsTabMixin


def test_stream_buffer_chars_platform_sensitive():
    with patch("src.gui.text_edit_tool.is_linux", return_value=True):
        assert text_edit_tool._STREAM_BUFFER_CHARS == 80
    with patch("src.gui.snip_tool.is_linux", return_value=True):
        assert snip_tool._STREAM_BUFFER_CHARS == 80


def test_type_text_chunk_linux_proportional_delay_applied():
    config = {"typing_delay_ms": 50}
    app = TextEditToolApp(config=config, ai_params={}, key_managers={})
    app.typing_delay_ms = 50
    app.streaming_aborted = False

    text_80 = "a" * 80  # 80 characters -> 80 * 50 / 1000 = 4.0 seconds

    with (
        patch("src.gui.text_edit_tool.is_linux", return_value=True),
        patch("src.gui.text_edit_tool.platform_type_text", return_value=True) as mock_type,
        patch("src.gui.text_edit_tool.time.sleep") as mock_sleep,
    ):
        result = app._type_text_chunk(text_80)

        assert result is True
        mock_type.assert_called_once_with(text_80, delay_ms=50, abort_check=mock_type.call_args.kwargs["abort_check"])
        mock_sleep.assert_called_once_with(4.0)


def test_type_text_chunk_linux_no_delay_when_zero():
    config = {"typing_delay_ms": 0}
    app = TextEditToolApp(config=config, ai_params={}, key_managers={})
    app.typing_delay_ms = 0
    app.streaming_aborted = False

    text_80 = "a" * 80

    with (
        patch("src.gui.text_edit_tool.is_linux", return_value=True),
        patch("src.gui.text_edit_tool.platform_type_text", return_value=True),
        patch("src.gui.text_edit_tool.time.sleep") as mock_sleep,
    ):
        result = app._type_text_chunk(text_80)

        assert result is True
        mock_sleep.assert_not_called()


def test_type_text_chunk_linux_no_delay_when_aborted():
    config = {"typing_delay_ms": 50}
    app = TextEditToolApp(config=config, ai_params={}, key_managers={})
    app.typing_delay_ms = 50
    app.streaming_aborted = True

    text_80 = "a" * 80

    with (
        patch("src.gui.text_edit_tool.is_linux", return_value=True),
        patch("src.gui.text_edit_tool.platform_type_text", return_value=True),
        patch("src.gui.text_edit_tool.time.sleep") as mock_sleep,
    ):
        result = app._type_text_chunk(text_80)

        assert result is True
        mock_sleep.assert_not_called()


def test_settings_tab_tools_spinbox_max_range():
    tab = ToolsTabMixin()
    tab.config_data = MagicMock()
    tab.config_data.config = {"streaming_typing_delay": 0}
    tab.use_ctk = False
    tab.colors = MagicMock()
    tab._create_tab_scroll_frame = MagicMock(return_value=MagicMock())
    tab._add_spinbox_field = MagicMock()
    tab._add_dropdown_field = MagicMock()
    tab._add_toggle_field = MagicMock()
    tab._add_entry_field = MagicMock()
    tab._add_linux_trigger_reference = MagicMock()

    with (
        patch("src.gui.windows.settings_window.tab_tools.create_section_header"),
        patch("src.gui.windows.settings_window.tab_tools.get_tk_font"),
        patch("src.gui.windows.settings_window.tab_tools.tk"),
    ):
        tab._create_tools_tab(MagicMock())

    spinbox_calls = tab._add_spinbox_field.call_args_list
    delay_call = next(call for call in spinbox_calls if call.args[1] == "streaming_typing_delay")
    assert delay_call.args[4] == 0  # min
    assert delay_call.args[5] == 500  # max
