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


def test_defaults_include_new_audio_settings_and_prompts():
    from src.tools.defaults import DEFAULT_TOOLS_CONFIG

    # Check disable_files_api setting
    assert "disable_files_api" in DEFAULT_TOOLS_CONFIG["_settings"]
    assert DEFAULT_TOOLS_CONFIG["_settings"]["disable_files_api"] is False

    # Check transcribe prompts
    prompts = DEFAULT_TOOLS_CONFIG["file_processor"]["prompts"]
    assert "Transcribe (Native Verbatim)" in prompts
    assert prompts["Transcribe (Native Verbatim)"]["transcribe_model"] is True
    assert prompts["Transcribe (Native Verbatim)"]["transcribe_mode"] == "VERBATIM"

    assert "Transcribe (Native Smart)" in prompts
    assert prompts["Transcribe (Native Smart)"]["transcribe_model"] is True
    assert prompts["Transcribe (Native Smart)"]["transcribe_mode"] == "SMART"


def test_checkpoint_transcribe_config_serialization():
    from src.tools.checkpoint import CheckpointManager, FileProcessorCheckpoint

    cp = FileProcessorCheckpoint(
        session_id="test_id",
        created_at="2026-01-01T00:00:00",
        updated_at="2026-01-01T00:00:00",
        input_path="/tmp/audio.mp3",
        input_files=["/tmp/audio.mp3"],
        prompt_key="Transcribe (Native Verbatim)",
        prompt_text="",
        output_mode="individual",
        output_path="/tmp/output",
        naming_template="{filename}_transcript",
        output_extension=".txt",
        profile_name="Default",
        delay_between_requests=1.0,
        transcribe_config={
            "model": "gemini-3.5-transcribe",
            "mode": "VERBATIM",
            "diarization": True,
            "word_timestamp": False,
            "language_codes": ["en-US"],
            "custom_vocabulary": ["Kubernetes"],
        },
    )

    data = cp.to_dict()
    assert data["transcribe_config"]["diarization"] is True
    assert data["transcribe_config"]["language_codes"] == ["en-US"]

    restored = FileProcessorCheckpoint.from_dict(data)
    assert restored.transcribe_config == cp.transcribe_config

    # Test create_retry_checkpoint preserves transcribe_config
    cp.mark_failed("/tmp/audio.mp3", "Network timeout")
    retry_cp = (
        CheckpointManager.create_retry_checkpoint(None, cp)
        if hasattr(CheckpointManager, "create_retry_checkpoint")
        else FileProcessorCheckpoint.create_retry_checkpoint(cp)
    )
    assert retry_cp is not None
    assert retry_cp.transcribe_config == cp.transcribe_config


def test_disable_files_api_large_file_mode():
    from src.tools.file_processor import LARGE_FILE_MODE_SKIP

    tool = FileProcessor()
    tool.tools_config = {"_settings": {"disable_files_api": True}}
    test_file = Path("test_audio.mp3")

    # Interactive: choice 1 should now be chunking (since Files API is disabled)
    with (
        patch.object(tool.audio_processor, "is_available", return_value=True),
        patch("builtins.input", side_effect=["1", "n"]),
    ):
        mode = tool._get_large_file_mode(test_file, is_audio=True, interactive=True)
        assert mode == LARGE_FILE_MODE_CHUNKING

    # Non-interactive audio: chunking
    tool._large_file_mode.clear()
    mode_non_interactive_audio = tool._get_large_file_mode(test_file, is_audio=True, interactive=False)
    assert mode_non_interactive_audio == LARGE_FILE_MODE_CHUNKING

    # Non-interactive non-audio: skip
    tool._large_file_mode.clear()
    mode_non_interactive_doc = tool._get_large_file_mode(Path("test_doc.pdf"), is_audio=False, interactive=False)
    assert mode_non_interactive_doc == LARGE_FILE_MODE_SKIP


def test_gemini_generate_transcription():
    from unittest.mock import MagicMock

    from src.providers.gemini_native import GeminiNativeProvider

    mock_key_mgr = MagicMock()
    mock_key_mgr.has_keys.return_value = True
    mock_key_mgr.get_current_key.return_value = "fake_gemini_key"
    mock_key_mgr.get_key_label.return_value = "Key-1"

    provider = GeminiNativeProvider(key_manager=mock_key_mgr, config={"request_timeout": 60})

    mock_response_data = {
        "candidates": [
            {
                "content": {"parts": [{"text": "Hello world from transcribe model."}]},
                "finishReason": "STOP",
            }
        ],
        "usageMetadata": {"promptTokenCount": 100, "totalTokenCount": 110},
    }

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = mock_response_data

    with patch("requests.post", return_value=mock_resp) as mock_post:
        transcript, error = provider.generate_transcription(
            file_uri="https://generativelanguage.googleapis.com/v1beta/files/test123",
            mime_type="audio/mp3",
            transcribe_config={
                "model": "gemini-3.5-transcribe",
                "mode": "VERBATIM",
                "diarization": False,
                "word_timestamp": False,
                "language_codes": ["en-US"],
                "custom_vocabulary": ["AI"],
            },
        )

        assert error is None
        assert transcript == "Hello world from transcribe model."
        assert mock_post.called

        # Verify request body
        call_kwargs = mock_post.call_args[1]
        sent_body = call_kwargs["json"]
        assert sent_body["generationConfig"]["audioTranscriptionConfig"]["mode"] == "VERBATIM"
        assert sent_body["generationConfig"]["audioTranscriptionConfig"]["languageCodes"] == ["en-US"]
        assert sent_body["generationConfig"]["audioTranscriptionConfig"]["customVocabulary"] == ["AI"]
        assert (
            sent_body["contents"][0]["parts"][0]["fileData"]["fileUri"]
            == "https://generativelanguage.googleapis.com/v1beta/files/test123"
        )


def test_gemini_generate_transcription_with_diarization_and_timestamps():
    from unittest.mock import MagicMock

    from src.providers.gemini_native import GeminiNativeProvider

    mock_key_mgr = MagicMock()
    mock_key_mgr.has_keys.return_value = True
    mock_key_mgr.get_current_key.return_value = "fake_gemini_key"
    mock_key_mgr.get_key_label.return_value = "Key-1"

    provider = GeminiNativeProvider(key_manager=mock_key_mgr)

    mock_response_data = {
        "candidates": [
            {
                "content": {
                    "parts": [
                        {
                            "audioTranscription": {
                                "speakerLabel": "spk_1",
                                "words": [
                                    {"word": "Hello", "startOffset": "0.100s", "endOffset": "0.450s"},
                                    {"word": "there", "startOffset": "0.500s", "endOffset": "0.850s"},
                                ],
                            }
                        },
                        {
                            "audioTranscription": {
                                "speakerLabel": "spk_2",
                                "words": [{"word": "Hi", "startOffset": "1.000s", "endOffset": "1.300s"}],
                            }
                        },
                    ]
                }
            }
        ]
    }

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = mock_response_data

    with patch("requests.post", return_value=mock_resp):
        transcript, error = provider.generate_transcription(
            file_uri="https://generativelanguage.googleapis.com/v1beta/files/test123",
            mime_type="audio/mp3",
            transcribe_config={
                "model": "gemini-3.5-transcribe",
                "mode": "VERBATIM",
                "diarization": True,
                "word_timestamp": True,
            },
        )

        assert error is None
        assert "[spk_1] (0.100s->0.450s) Hello (0.500s->0.850s) there" in transcript
        assert "[spk_2] (1.000s->1.300s) Hi" in transcript


def test_even_chunk_distribution_calculation():
    from unittest.mock import MagicMock

    from src.tools.audio_processor import AudioInfo, AudioProcessor

    proc = AudioProcessor()

    # 33 minutes = 1980 seconds
    audio_info = AudioInfo(
        path=Path("test.mp3"),
        duration_seconds=1980.0,
        bitrate_kbps=128.0,
        size_bytes=30 * 1024 * 1024,
        format="mp3",
        sample_rate=44100,
        channels=2,
    )

    # estimate_chunk_duration gives e.g. 1200 seconds (20 minutes)
    with (
        patch.object(proc, "is_available", return_value=True),
        patch.object(proc, "get_audio_info", return_value=audio_info),
        patch.object(proc, "estimate_chunk_duration", return_value=1200.0),
        patch("subprocess.run") as mock_run,
        patch("pathlib.Path.stat") as mock_stat,
    ):
        mock_run.return_value = MagicMock(returncode=0)
        mock_stat.return_value = MagicMock(st_size=10 * 1024 * 1024)

        result = proc.split_audio(Path("test.mp3"))

        assert result.success is True
        # Total duration 1980s / 1200s target -> ceil(1980/1200) = 2 chunks
        # Each chunk duration should be 1980 / 2 = 990 seconds (16.5 minutes)
        assert len(result.chunks) == 2
        assert result.chunks[0].duration == pytest.approx(990.0)
        assert result.chunks[1].duration == pytest.approx(990.0)
        result.cleanup()


def test_audio_tool_process_transcription():
    from unittest.mock import MagicMock

    from src.connection_profiles import ConnectionProfile, ProfileStore
    from src.gui.audio_tool import AudioToolApp

    ProfileStore.reset_instance()
    store = ProfileStore.get_instance()
    profile = ConnectionProfile(
        provider="transcription",
        model="gemini-3.5-transcribe",
        transcribe_mode="VERBATIM",
        transcribe_diarization=True,
    )
    store._profiles["TranscriptionProf"] = profile.to_dict()

    mock_google_km = MagicMock()
    app = AudioToolApp(config={}, ai_params={}, key_managers={"google": mock_google_km})

    mock_resolved = MagicMock()
    mock_resolved.model = "gemini-3.5-transcribe"
    mock_resolved.key_managers = {"google": mock_google_km}
    mock_resolved.config = {}

    mock_uploaded = MagicMock()
    mock_uploaded.uri = "https://files.example.com/audio1"
    mock_uploaded.name = "audio1"
    mock_uploaded.mime_type = "audio/wav"

    mock_provider = MagicMock()
    mock_provider.upload_file.return_value = (mock_uploaded, None)
    mock_provider.generate_transcription.return_value = ("[spk_1] Hello world", None)

    progress_calls = []
    success_calls = []
    error_calls = []

    with (
        patch("src.gui.audio_tool.create_provider", return_value=mock_provider),
        patch("os.path.exists", return_value=False),
    ):
        app._process_transcription(
            audio_data=b"fake_wav_bytes",
            mime_type="audio/wav",
            resolved=mock_resolved,
            profile_name="TranscriptionProf",
            callback_progress=lambda msg: progress_calls.append(msg),
            callback_success=lambda text, tokens: success_calls.append((text, tokens)),
            callback_error=lambda err: error_calls.append(err),
        )

        assert len(error_calls) == 0
        assert len(success_calls) == 1
        assert success_calls[0][0] == "[spk_1] Hello world"
        assert mock_provider.upload_file.called
        assert mock_provider.generate_transcription.called
        assert mock_provider.delete_file.called
