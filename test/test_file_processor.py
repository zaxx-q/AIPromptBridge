"""Unit tests for FileProcessorTool keyboard listener and interactive prompts."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from src.platform import console_input as ci
from src.tools.file_processor import (
    LARGE_FILE_MODE_CHUNKING,
    LARGE_FILE_MODE_FILES_API,
    FileProcessor,
)


@pytest.fixture(autouse=True)
def _reset_console_input_state():
    """Reset process-wide raw-mode depths between tests."""
    with ci._lock:
        ci._raw_depth = 0
        ci._suspend_depth = 0
        ci._saved_attrs = None
        ci._fd = None
        ci._msvcrt = None
        ci._msvcrt_checked = False
        ci._atexit_registered = False
    yield
    with ci._lock:
        ci._raw_depth = 0
        ci._suspend_depth = 0
        ci._saved_attrs = None
        ci._fd = None
        ci._msvcrt = None
        ci._msvcrt_checked = False


def test_start_and_stop_keyboard_listener():
    tool = FileProcessor()
    with patch("src.tools.file_processor.is_console_input_available", return_value=True):
        thread = tool._start_keyboard_listener()
        assert thread is not None
        assert tool._keyboard_thread is not None
        assert tool._keyboard_stop_event is not None
        assert tool._stop_requested is False

        tool._stop_keyboard_listener()
        assert tool._keyboard_thread is None
        assert tool._keyboard_stop_event is None


def test_interactive_prompt_suspends_and_resumes_listener():
    tool = FileProcessor()
    with patch("src.tools.file_processor.is_console_input_available", return_value=True):
        tool._start_keyboard_listener()
        assert tool._keyboard_thread is not None

        # Entering interactive prompt should stop listener
        with tool._interactive_prompt(interactive=True):
            assert tool._keyboard_thread is None
            assert tool._keyboard_stop_event is None

        # Exiting should restore listener
        assert tool._keyboard_thread is not None
        assert tool._keyboard_stop_event is not None

        tool._stop_keyboard_listener()


def test_get_large_file_mode_user_input_files_api():
    tool = FileProcessor()
    test_file = Path("test_audio.mp3")

    with (
        patch("src.tools.file_processor.is_console_input_available", return_value=True),
        patch("builtins.input", side_effect=["1", "n"]),
    ):
        tool._start_keyboard_listener()
        mode = tool._get_large_file_mode(test_file, is_audio=True, interactive=True)
        assert mode == LARGE_FILE_MODE_FILES_API
        assert tool._stop_requested is False
        tool._stop_keyboard_listener()


def test_get_large_file_mode_user_input_chunking():
    tool = FileProcessor()
    test_file = Path("test_audio.mp3")

    with (
        patch("src.tools.file_processor.is_console_input_available", return_value=True),
        patch.object(tool.audio_processor, "is_available", return_value=True),
        patch("builtins.input", side_effect=["2", "y"]),
    ):
        tool._start_keyboard_listener()
        mode = tool._get_large_file_mode(test_file, is_audio=True, interactive=True)
        assert mode == LARGE_FILE_MODE_CHUNKING
        assert tool._large_file_mode["_default"] == LARGE_FILE_MODE_CHUNKING
        assert tool._stop_requested is False
        tool._stop_keyboard_listener()


def test_prompt_per_file_instructions_suspends_listener():
    tool = FileProcessor()
    test_file = Path("test_doc.txt")

    with (
        patch("src.tools.file_processor.is_console_input_available", return_value=True),
        patch("builtins.input", side_effect=["y", "Specific instruction for this file", ""]),
    ):
        tool._start_keyboard_listener()
        result = tool._prompt_per_file_instructions(test_file, file_index=0, total_files=1)
        assert result == "Specific instruction for this file"
        assert tool._stop_requested is False
        tool._stop_keyboard_listener()
