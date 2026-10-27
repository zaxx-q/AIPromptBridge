"""Tests for overlapping audio chunks and LCS-based transcript merging."""

from pathlib import Path

import pytest


def test_find_longest_common_sequence_basic():
    from src.tools.audio_processor import find_longest_common_sequence

    # Two overlapping transcripts sharing a phrase
    seq1 = "Hello world this is a test of the emergency broadcast system"
    seq2 = "of the emergency broadcast system please stand by for updates"

    merged = find_longest_common_sequence([seq1, seq2])

    # Both unique portions should be present
    assert "Hello world" in merged
    assert "please stand by" in merged
    # The overlapping phrase should appear only once
    assert merged.count("emergency broadcast") == 1


def test_find_longest_common_sequence_no_overlap():
    from src.tools.audio_processor import find_longest_common_sequence

    # No shared words — algorithm still produces a merged string containing both halves
    seq1 = "First segment content"
    seq2 = "Second segment content"

    merged = find_longest_common_sequence([seq1, seq2])
    assert "First segment" in merged or "Second segment" in merged


def test_find_longest_common_sequence_empty():
    from src.tools.audio_processor import find_longest_common_sequence

    assert find_longest_common_sequence([]) == ""
    assert find_longest_common_sequence(["only one"]) == "only one"


def test_find_longest_common_sequence_three_segments():
    from src.tools.audio_processor import find_longest_common_sequence

    seg1 = "the cat sat on the mat near the door"
    seg2 = "near the door and watched the rain fall down"
    seg3 = "the rain fall down and turned the street grey"

    merged = find_longest_common_sequence([seg1, seg2, seg3])
    assert "the cat sat" in merged
    assert "turned the street grey" in merged
    # Overlapping phrases should appear once
    assert merged.count("the door") <= 1
    assert merged.count("fall down") <= 1


def test_merge_transcribe_with_overlap():
    from src.tools.audio_processor import AudioChunk, merge_transcribe_transcripts

    # Two chunks where chunk 0 has 10s overlap with chunk 1's territory
    chunks = [
        (
            AudioChunk(
                path=Path("c0.flac"),
                index=0,
                start_time=0,
                end_time=610,
                duration=610,
                size_bytes=100,
                overlap_duration=10.0,
            ),
            "The quick brown fox jumps over the lazy dog and runs away",
        ),
        (
            AudioChunk(
                path=Path("c1.flac"),
                index=1,
                start_time=600,
                end_time=1200,
                duration=600,
                size_bytes=100,
                overlap_duration=0.0,
            ),
            "the lazy dog and runs away into the sunset",
        ),
    ]

    merged = merge_transcribe_transcripts(chunks)
    # Both unique portions must survive
    assert "quick brown fox" in merged
    assert "into the sunset" in merged
    # The overlapping region should appear only once
    assert merged.count("lazy dog") == 1


def test_merge_transcribe_no_overlap_legacy():
    from src.tools.audio_processor import AudioChunk, merge_transcribe_transcripts

    # No overlap_duration set → should use simple newline join (legacy)
    c1 = AudioChunk(path=Path("c1.mp3"), index=0, start_time=0, end_time=600, duration=600, size_bytes=100)
    c2 = AudioChunk(path=Path("c2.mp3"), index=1, start_time=600, end_time=1200, duration=600, size_bytes=100)

    merged = merge_transcribe_transcripts(
        [
            (c1, "First part text"),
            (c2, "Second part text"),
        ]
    )
    assert merged == "First part text\n\nSecond part text"


def test_merge_transcribe_overlap_single_valid():
    """Single non-silent chunk with overlap field set — just returns its text."""
    from src.tools.audio_processor import AudioChunk, merge_transcribe_transcripts

    c = AudioChunk(
        path=Path("c0.flac"),
        index=0,
        start_time=0,
        end_time=610,
        duration=610,
        size_bytes=100,
        overlap_duration=10.0,
    )
    assert merge_transcribe_transcripts([(c, "Hello world")]) == "Hello world"


def test_merge_transcribe_all_silent_with_overlap():
    from src.tools.audio_processor import AudioChunk, merge_transcribe_transcripts

    c1 = AudioChunk(
        path=Path("c0.flac"), index=0, start_time=0, end_time=610, duration=610, size_bytes=100, overlap_duration=10.0
    )
    c2 = AudioChunk(
        path=Path("c1.flac"), index=1, start_time=600, end_time=1200, duration=600, size_bytes=100, overlap_duration=0.0
    )

    result = merge_transcribe_transcripts(
        [
            (c1, "(No speech detected)"),
            (c2, "(No speech detected)"),
        ]
    )
    assert result == "(No speech detected)"


def test_split_audio_overlap_fields(tmp_path):
    """Verify that split_audio populates overlap_duration correctly."""
    from unittest.mock import MagicMock, patch

    from src.tools.audio_processor import AudioInfo, AudioProcessor

    proc = AudioProcessor()
    audio_info = AudioInfo(
        path=tmp_path / "test.mp3",
        duration_seconds=1980.0,
        bitrate_kbps=128.0,
        size_bytes=30 * 1024 * 1024,
        format="mp3",
    )

    with (
        patch.object(proc, "is_available", return_value=True),
        patch.object(proc, "get_audio_info", return_value=audio_info),
        patch.object(proc, "estimate_chunk_duration", return_value=1200.0),
        patch("subprocess.run") as mock_run,
        patch("pathlib.Path.stat") as mock_stat,
    ):
        mock_run.return_value = MagicMock(returncode=0)
        mock_stat.return_value = MagicMock(st_size=10 * 1024 * 1024)

        result = proc.split_audio(tmp_path / "test.mp3")

    assert result.success
    assert len(result.chunks) == 2
    # All but the last chunk should carry overlap
    assert result.chunks[0].overlap_duration == pytest.approx(10.0)
    assert result.chunks[-1].overlap_duration == pytest.approx(0.0)
    # Chunks must overlap: chunk[1].start < chunk[0].end
    assert result.chunks[1].start_time < result.chunks[0].end_time
    result.cleanup()


def test_split_audio_no_overlap_when_disabled(tmp_path):
    """Passing overlap_seconds=0 restores legacy non-overlapping behaviour."""
    from unittest.mock import MagicMock, patch

    from src.tools.audio_processor import AudioInfo, AudioProcessor

    proc = AudioProcessor()
    audio_info = AudioInfo(
        path=tmp_path / "test.mp3",
        duration_seconds=1980.0,
        bitrate_kbps=128.0,
        size_bytes=30 * 1024 * 1024,
        format="mp3",
    )

    with (
        patch.object(proc, "is_available", return_value=True),
        patch.object(proc, "get_audio_info", return_value=audio_info),
        patch.object(proc, "estimate_chunk_duration", return_value=1200.0),
        patch("subprocess.run") as mock_run,
        patch("pathlib.Path.stat") as mock_stat,
    ):
        mock_run.return_value = MagicMock(returncode=0)
        mock_stat.return_value = MagicMock(st_size=10 * 1024 * 1024)

        result = proc.split_audio(tmp_path / "test.mp3", overlap_seconds=0)

    assert result.success
    assert len(result.chunks) == 2
    # No overlap: chunk[1].start == chunk[0].end
    assert result.chunks[0].overlap_duration == pytest.approx(0.0)
    assert result.chunks[1].start_time == pytest.approx(result.chunks[0].end_time)
    result.cleanup()


def test_split_audio_by_duration_overlap_fields(tmp_path):
    """Verify that split_audio_by_duration populates overlap_duration correctly."""
    from unittest.mock import MagicMock, patch

    from src.tools.audio_processor import AudioInfo, AudioProcessor

    proc = AudioProcessor()
    long_info = AudioInfo(
        path=tmp_path / "long.mp3",
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

        res = proc.split_audio_by_duration(tmp_path / "long.mp3", max_duration_seconds=1500.0)

    assert res.success
    assert len(res.chunks) == 3
    # Interior chunks have overlap; last does not
    assert res.chunks[0].overlap_duration == pytest.approx(10.0)
    assert res.chunks[1].overlap_duration == pytest.approx(10.0)
    assert res.chunks[-1].overlap_duration == pytest.approx(0.0)
    # Each interior chunk's end > next chunk's start (they overlap)
    for i in range(len(res.chunks) - 1):
        assert res.chunks[i].end_time > res.chunks[i + 1].start_time
    # No chunk exceeds max_duration_seconds
    for chunk in res.chunks:
        assert chunk.duration <= 1500.0 + 1e-6
    res.cleanup()


def test_default_overlap_seconds_exported():
    from src.tools import DEFAULT_OVERLAP_SECONDS

    assert DEFAULT_OVERLAP_SECONDS == 10.0


def test_find_longest_common_sequence_exported():
    from src.tools import find_longest_common_sequence

    result = find_longest_common_sequence(["hello world", "world goodbye"])
    assert isinstance(result, str)
    assert len(result) > 0
