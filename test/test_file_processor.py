"""Unit tests for FileProcessorTool keyboard listener and interactive prompts."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

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


def test_gemini_generate_transcription_smart_mode_audio_transcription_text():
    from unittest.mock import MagicMock

    from src.providers.gemini_native import GeminiNativeProvider

    mock_key_mgr = MagicMock()
    mock_key_mgr.has_keys.return_value = True
    mock_key_mgr.get_current_key.return_value = "fake_gemini_key"
    mock_key_mgr.get_key_label.return_value = "Key-1"

    provider = GeminiNativeProvider(key_manager=mock_key_mgr, config={"request_timeout": 60})

    # In SMART mode, the API returns audioTranscription.text inside parts
    mock_response_data = {
        "candidates": [
            {
                "content": {
                    "parts": [
                        {"audioTranscription": {"text": "Heaven calls my name. I lay down, I close my eyes at night."}}
                    ],
                    "role": "model",
                },
                "finishReason": "STOP",
            }
        ],
        "usageMetadata": {"promptTokenCount": 376, "totalTokenCount": 376},
    }

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = mock_response_data

    with patch("requests.post", return_value=mock_resp):
        transcript, error = provider.generate_transcription(
            file_uri="https://generativelanguage.googleapis.com/v1beta/files/test123",
            mime_type="audio/ogg",
            transcribe_config={
                "model": "gemini-3.5-transcribe",
                "mode": "SMART",
            },
        )

        assert error is None
        assert transcript == "Heaven calls my name. I lay down, I close my eyes at night."


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


def test_gemini_generate_transcription_no_speech_detected():
    from unittest.mock import MagicMock

    from src.providers.gemini_native import GeminiNativeProvider

    mock_key_mgr = MagicMock()
    mock_key_mgr.has_keys.return_value = True
    mock_key_mgr.get_current_key.return_value = "fake_gemini_key"
    mock_key_mgr.get_key_label.return_value = "Key-1"

    provider = GeminiNativeProvider(key_manager=mock_key_mgr)

    # API returns STOP with empty parts when no words are detected
    mock_response_data = {
        "candidates": [
            {
                "content": {
                    "parts": [],
                },
                "finishReason": "STOP",
            }
        ]
    }

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = mock_response_data

    with patch("requests.post", return_value=mock_resp):
        transcript, error = provider.generate_transcription(
            file_uri="https://generativelanguage.googleapis.com/v1beta/files/test123",
            mime_type="audio/ogg",
            transcribe_config={
                "model": "gemini-3.5-transcribe",
                "mode": "SMART",
            },
        )

        assert error is None
        assert transcript == "(No speech detected)"


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


def test_get_transcribe_max_duration():
    from src.tools.audio_processor import (
        TRANSCRIBE_ADVANCED_MAX_DURATION,
        TRANSCRIBE_STANDARD_MAX_DURATION,
        get_transcribe_max_duration,
    )

    assert get_transcribe_max_duration(None) == TRANSCRIBE_STANDARD_MAX_DURATION
    assert get_transcribe_max_duration({}) == TRANSCRIBE_STANDARD_MAX_DURATION
    assert get_transcribe_max_duration({"mode": "SMART"}) == TRANSCRIBE_STANDARD_MAX_DURATION
    assert get_transcribe_max_duration({"mode": "VERBATIM"}) == TRANSCRIBE_STANDARD_MAX_DURATION
    assert get_transcribe_max_duration({"diarization": True}) == TRANSCRIBE_ADVANCED_MAX_DURATION
    assert get_transcribe_max_duration({"word_timestamp": True}) == TRANSCRIBE_ADVANCED_MAX_DURATION
    assert (
        get_transcribe_max_duration({"diarization": True, "word_timestamp": True}) == TRANSCRIBE_ADVANCED_MAX_DURATION
    )


def test_split_audio_by_duration():
    from unittest.mock import MagicMock

    from src.tools.audio_processor import AudioInfo, AudioProcessor

    proc = AudioProcessor()

    # 1. Short audio (under max duration 1500s) -> single chunk returned without splitting
    short_info = AudioInfo(
        path=Path("short.mp3"),
        duration_seconds=1200.0,
        bitrate_kbps=128.0,
        size_bytes=10 * 1024 * 1024,
        format="mp3",
    )
    with (
        patch.object(proc, "is_available", return_value=True),
        patch.object(proc, "get_audio_info", return_value=short_info),
    ):
        res = proc.split_audio_by_duration(Path("short.mp3"), max_duration_seconds=1500.0)
        assert res.success is True
        assert len(res.chunks) == 1
        assert res.chunks[0].start_time == 0.0
        assert res.chunks[0].duration == 1200.0
        res.cleanup()

    # 2. Long audio (3600s with max duration 1500s) -> 3 chunks of 1200s each
    long_info = AudioInfo(
        path=Path("long.mp3"),
        duration_seconds=3600.0,
        bitrate_kbps=128.0,
        size_bytes=30 * 1024 * 1024,
        format="mp3",
    )
    with (
        patch.object(proc, "is_available", return_value=True),
        patch.object(proc, "get_audio_info", return_value=long_info),
        patch("subprocess.run") as mock_run,
        patch("pathlib.Path.stat") as mock_stat,
    ):
        mock_run.return_value = MagicMock(returncode=0)
        mock_stat.return_value = MagicMock(st_size=10 * 1024 * 1024)

        res = proc.split_audio_by_duration(Path("long.mp3"), max_duration_seconds=1500.0)
        assert res.success is True
        assert len(res.chunks) == 3
        assert res.chunks[0].start_time == pytest.approx(0.0)
        assert res.chunks[0].duration == pytest.approx(1200.0)
        assert res.chunks[1].start_time == pytest.approx(1200.0)
        assert res.chunks[1].duration == pytest.approx(1200.0)
        assert res.chunks[2].start_time == pytest.approx(2400.0)
        assert res.chunks[2].duration == pytest.approx(1200.0)
        res.cleanup()


def test_adjust_transcript_timestamps():
    from src.tools.audio_processor import adjust_transcript_timestamps

    # Offset 0 -> unchanged
    t1 = "[spk_1] (0.100s->0.450s) Hello (0.500s->0.850s) there"
    assert adjust_transcript_timestamps(t1, 0.0) == t1

    # Seconds offset (e.g. 1500.0s = 25m)
    res1 = adjust_transcript_timestamps(t1, 1500.0)
    assert res1 == "[spk_1] (1500.100s->1500.450s) Hello (1500.500s->1500.850s) there"

    # Timecode format MM:SS
    t2 = "(00:10 -> 00:15) Hello"
    res2 = adjust_transcript_timestamps(t2, 1500.0)
    assert res2 == "(25:10 -> 25:15) Hello"

    # Millisecond timecode format
    t3 = "(00:10.250 -> 00:15.750) Hello"
    res3 = adjust_transcript_timestamps(t3, 1500.0)
    assert res3 == "(25:10.250 -> 25:15.750) Hello"

    # Timecode format promoting to HH:MM:SS
    t4 = "(45:00 -> 45:30) Hello"
    res4 = adjust_transcript_timestamps(t4, 1500.0)
    assert res4 == "(01:10:00 -> 01:10:30) Hello"

    # Non-timestamp parentheses and text should remain unaffected
    t5 = "(applause) (No speech detected) (state-of-the-art) [spk_1] (1.000s->2.000s) text"
    res5 = adjust_transcript_timestamps(t5, 100.0)
    assert res5 == "(applause) (No speech detected) (state-of-the-art) [spk_1] (101.000s->102.000s) text"


def test_merge_transcribe_transcripts():
    from src.tools.audio_processor import AudioChunk, merge_transcribe_transcripts

    c1 = AudioChunk(path=Path("c1.mp3"), index=0, start_time=0.0, end_time=1200.0, duration=1200.0, size_bytes=100)
    c2 = AudioChunk(path=Path("c2.mp3"), index=1, start_time=1200.0, end_time=2400.0, duration=1200.0, size_bytes=100)
    c3 = AudioChunk(path=Path("c3.mp3"), index=2, start_time=2400.0, end_time=3600.0, duration=1200.0, size_bytes=100)

    # Empty
    assert merge_transcribe_transcripts([]) == ""

    # Single
    assert merge_transcribe_transcripts([(c1, "Single chunk text")]) == "Single chunk text"

    # Multi with speech
    merged = merge_transcribe_transcripts(
        [
            (c2, "[spk_1] (1200.0s->1201.0s) Middle"),
            (c1, "[spk_1] (0.0s->1.0s) Start"),
            (c3, "[spk_1] (2400.0s->2401.0s) End"),
        ]
    )
    expected = "[spk_1] (0.0s->1.0s) Start\n\n[spk_1] (1200.0s->1201.0s) Middle\n\n[spk_1] (2400.0s->2401.0s) End"
    assert merged == expected

    # Filtering (No speech detected) when other chunks have speech
    merged_filtered = merge_transcribe_transcripts(
        [
            (c1, "Speech in chunk 1"),
            (c2, "(No speech detected)"),
            (c3, "Speech in chunk 3"),
        ]
    )
    assert merged_filtered == "Speech in chunk 1\n\nSpeech in chunk 3"

    # All (No speech detected)
    all_silent = merge_transcribe_transcripts(
        [
            (c1, "(No speech detected)"),
            (c2, "(No speech detected)"),
        ]
    )
    assert all_silent == "(No speech detected)"


def test_file_processor_transcribe_long_audio_chunking():
    from src.tools.audio_processor import AudioChunk, AudioInfo, ChunkingResult
    from src.tools.checkpoint import FileProcessorCheckpoint
    from src.tools.file_processor import FileProcessor

    fp = FileProcessor()
    long_file = Path("interview_45m.mp3")

    audio_info = AudioInfo(
        path=long_file,
        duration_seconds=2700.0,  # 45 minutes
        bitrate_kbps=128.0,
        size_bytes=40 * 1024 * 1024,
        format="mp3",
    )

    c1 = AudioChunk(path=Path("/tmp/c1.mp3"), index=0, start_time=0.0, end_time=1350.0, duration=1350.0, size_bytes=100)
    c2 = AudioChunk(
        path=Path("/tmp/c2.mp3"), index=1, start_time=1350.0, end_time=2700.0, duration=1350.0, size_bytes=100
    )
    split_result = ChunkingResult(success=True, chunks=[c1, c2], original_info=audio_info)

    mock_cp = FileProcessorCheckpoint(
        session_id="chk_1",
        created_at="2026-01-01T00:00:00",
        updated_at="2026-01-01T00:00:00",
        input_path=str(long_file),
        input_files=[str(long_file)],
        prompt_key="Transcribe (Native Verbatim)",
        prompt_text="",
        output_mode="individual",
        output_path="/tmp/output",
        naming_template="{filename}",
        output_extension=".txt",
        profile_name="Default",
        delay_between_requests=0.0,
        transcribe_config={
            "model": "gemini-3.5-transcribe",
            "mode": "VERBATIM",
            "diarization": True,
            "word_timestamp": True,
        },
    )

    mock_google_km = MagicMock()
    mock_google_km.has_keys.return_value = True

    mock_uploaded_1 = MagicMock(uri="uri_1", name="name_1", mime_type="audio/mp3")
    mock_uploaded_2 = MagicMock(uri="uri_2", name="name_2", mime_type="audio/mp3")

    mock_provider = MagicMock()
    mock_provider.upload_file.side_effect = [(mock_uploaded_1, None), (mock_uploaded_2, None)]
    mock_provider.generate_transcription.side_effect = [
        ("[spk_1] (0.100s->0.450s) Hello", None),
        ("[spk_1] (0.200s->0.600s) Goodbye", None),
    ]

    with (
        patch.object(fp.audio_processor, "is_available", return_value=True),
        patch.object(fp.audio_processor, "get_audio_info", return_value=audio_info),
        patch.object(fp.audio_processor, "split_audio_by_duration", return_value=split_result),
        patch.object(
            fp,
            "_resolve_execution_settings",
            return_value=(
                "google",
                None,
                MagicMock(key_managers={"google": mock_google_km}, config={}),
            ),
        ),
        patch("src.providers.create_provider", return_value=mock_provider),
    ):
        transcript = fp._process_with_transcribe_model(
            filepath=long_file,
            transcribe_config=mock_cp.transcribe_config,
            checkpoint=mock_cp,
            interactive=False,
        )

        assert fp.audio_processor.split_audio_by_duration.called
        assert mock_provider.upload_file.call_count == 2
        assert mock_provider.generate_transcription.call_count == 2
        assert mock_provider.delete_file.call_count == 2
        # Verify timestamps adjusted by chunk 2 start_time (1350.0s)
        assert "[spk_1] (0.100s->0.450s) Hello" in transcript
        assert "[spk_1] (1350.200s->1350.600s) Goodbye" in transcript


def test_file_processor_transcribe_force_no_chunking():
    from src.tools.audio_processor import AudioInfo
    from src.tools.checkpoint import FileProcessorCheckpoint
    from src.tools.file_processor import FileProcessor

    fp = FileProcessor()
    fp._audio_preprocessing = {"force_no_chunking": True}

    long_file = Path("interview_45m.mp3")
    audio_info = AudioInfo(
        path=long_file,
        duration_seconds=2700.0,
        bitrate_kbps=128.0,
        size_bytes=40 * 1024 * 1024,
        format="mp3",
    )

    mock_cp = FileProcessorCheckpoint(
        session_id="chk_2",
        created_at="2026-01-01T00:00:00",
        updated_at="2026-01-01T00:00:00",
        input_path=str(long_file),
        input_files=[str(long_file)],
        prompt_key="Transcribe (Native Verbatim)",
        prompt_text="",
        output_mode="individual",
        output_path="/tmp/output",
        naming_template="{filename}",
        output_extension=".txt",
        profile_name="Default",
        delay_between_requests=0.0,
        transcribe_config={
            "model": "gemini-3.5-transcribe",
            "mode": "VERBATIM",
            "diarization": True,
        },
    )

    mock_google_km = MagicMock()
    mock_google_km.has_keys.return_value = True

    mock_uploaded = MagicMock(uri="uri_single", name="name_single", mime_type="audio/mp3")
    mock_provider = MagicMock()
    mock_provider.upload_file.return_value = (mock_uploaded, None)
    mock_provider.generate_transcription.return_value = ("[spk_1] Single upload text", None)

    with (
        patch.object(fp.audio_processor, "is_available", return_value=True),
        patch.object(fp.audio_processor, "get_audio_info", return_value=audio_info),
        patch.object(fp.audio_processor, "split_audio_by_duration") as mock_split,
        patch.object(
            fp,
            "_resolve_execution_settings",
            return_value=(
                "google",
                None,
                MagicMock(key_managers={"google": mock_google_km}, config={}),
            ),
        ),
        patch("src.providers.create_provider", return_value=mock_provider),
    ):
        transcript = fp._process_with_transcribe_model(
            filepath=long_file,
            transcribe_config=mock_cp.transcribe_config,
            checkpoint=mock_cp,
            interactive=False,
        )

        assert not mock_split.called
        assert mock_provider.upload_file.call_count == 1
        assert transcript == "[spk_1] Single upload text"


def test_audio_tool_process_transcription_long_audio_chunking():
    from src.connection_profiles import ConnectionProfile, ProfileStore
    from src.gui.audio_tool import AudioToolApp
    from src.tools.audio_processor import AudioChunk, AudioInfo, ChunkingResult

    ProfileStore.reset_instance()
    store = ProfileStore.get_instance()
    profile = ConnectionProfile(
        provider="transcription",
        model="gemini-3.5-transcribe",
        transcribe_mode="VERBATIM",
        transcribe_diarization=True,
        transcribe_timestamps=True,
    )
    store._profiles["TranscriptionLong"] = profile.to_dict()

    mock_google_km = MagicMock()
    app = AudioToolApp(config={}, ai_params={}, key_managers={"google": mock_google_km})

    mock_resolved = MagicMock()
    mock_resolved.model = "gemini-3.5-transcribe"
    mock_resolved.key_managers = {"google": mock_google_km}
    mock_resolved.config = {}

    audio_info = AudioInfo(
        path=Path("dummy.wav"),
        duration_seconds=2700.0,
        bitrate_kbps=128.0,
        size_bytes=40 * 1024 * 1024,
        format="wav",
    )

    c1 = AudioChunk(path=Path("/tmp/c1.wav"), index=0, start_time=0.0, end_time=1350.0, duration=1350.0, size_bytes=100)
    c2 = AudioChunk(
        path=Path("/tmp/c2.wav"), index=1, start_time=1350.0, end_time=2700.0, duration=1350.0, size_bytes=100
    )
    split_result = ChunkingResult(success=True, chunks=[c1, c2], original_info=audio_info)

    mock_uploaded_1 = MagicMock(uri="uri_1", name="name_1", mime_type="audio/wav")
    mock_uploaded_2 = MagicMock(uri="uri_2", name="name_2", mime_type="audio/wav")

    mock_provider = MagicMock()
    mock_provider.upload_file.side_effect = [(mock_uploaded_1, None), (mock_uploaded_2, None)]
    mock_provider.generate_transcription.side_effect = [
        ("[spk_1] (0.100s->0.450s) Hello", None),
        ("[spk_1] (0.200s->0.600s) Goodbye", None),
    ]

    progress_calls = []
    success_calls = []
    error_calls = []

    with (
        patch("src.gui.audio_tool.create_provider", return_value=mock_provider),
        patch("src.tools.audio_processor.AudioProcessor.is_available", return_value=True),
        patch("src.tools.audio_processor.AudioProcessor.get_audio_info", return_value=audio_info),
        patch("src.tools.audio_processor.AudioProcessor.split_audio_by_duration", return_value=split_result),
        patch("os.path.exists", return_value=False),
    ):
        app._process_transcription(
            audio_data=b"fake_wav_bytes",
            mime_type="audio/wav",
            resolved=mock_resolved,
            profile_name="TranscriptionLong",
            callback_progress=lambda msg: progress_calls.append(msg),
            callback_success=lambda text, tokens: success_calls.append((text, tokens)),
            callback_error=lambda err: error_calls.append(err),
        )

        assert len(error_calls) == 0
        assert len(success_calls) == 1
        result_text = success_calls[0][0]
        assert "[spk_1] (0.100s->0.450s) Hello" in result_text
        assert "[spk_1] (1350.200s->1350.600s) Goodbye" in result_text
        assert mock_provider.upload_file.call_count == 2
        assert mock_provider.generate_transcription.call_count == 2
        assert mock_provider.delete_file.call_count == 2
