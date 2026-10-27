"""Tests for Groq size-based audio chunking."""

from pathlib import Path
from types import SimpleNamespace

import pytest

from src.tools.audio_processor import GROQ_TARGET_CHUNK_BYTES, AudioInfo, AudioProcessor


def _info(path: Path, *, duration: float, size: int, bitrate: float = 128.0) -> AudioInfo:
    return AudioInfo(
        path=path,
        duration_seconds=duration,
        bitrate_kbps=bitrate,
        size_bytes=size,
        format="test",
        sample_rate=48000,
        channels=2,
    )


def test_small_supported_file_skips_transcode(tmp_path, monkeypatch):
    source = tmp_path / "sample.mp3"
    source.write_bytes(b"audio")
    processor = AudioProcessor()
    audio_info = _info(source, duration=25.0, size=5)
    monkeypatch.setattr(processor, "is_available", lambda: True)
    monkeypatch.setattr(processor, "get_audio_info", lambda _path: audio_info)
    monkeypatch.setattr(
        "src.tools.audio_processor.subprocess.run", lambda *args, **kwargs: pytest.fail("FFmpeg should not run")
    )

    result = processor.split_audio_for_groq(source)

    assert result.success
    assert result.temp_dir is None
    assert len(result.chunks) == 1
    assert result.chunks[0].path == source
    assert result.chunks[0].size_bytes == 5


def test_large_file_uses_estimated_chunk_count_and_flac(tmp_path, monkeypatch):
    source = tmp_path / "large.wav"
    source.write_bytes(b"audio")
    processor = AudioProcessor()
    duration = 2000.0
    audio_info = _info(source, duration=duration, size=30 * 1024 * 1024, bitrate=320.0)
    monkeypatch.setattr(processor, "is_available", lambda: True)
    monkeypatch.setattr(processor, "get_audio_info", lambda _path: audio_info)

    commands = []

    def fake_ffmpeg(cmd, **kwargs):
        commands.append(cmd)
        Path(cmd[-1]).write_bytes(b"flac")
        return SimpleNamespace(returncode=0, stderr="")

    monkeypatch.setattr("src.tools.audio_processor.subprocess.run", fake_ffmpeg)

    result = processor.split_audio_for_groq(source)
    try:
        assert result.success
        # At 32 kB/s + 10% safety, chunk duration is 710s; 2000s is split into 3.
        assert len(result.chunks) == 3
        assert all(chunk.path.suffix == ".flac" for chunk in result.chunks)
        assert all(chunk.size_bytes == 4 for chunk in result.chunks)
        assert len(commands) == 3
        assert all("16000" in cmd and "-ac" in cmd and "1" in cmd for cmd in commands)
        assert all("flac" in cmd for cmd in commands)
        assert result.chunks[0].start_time == 0.0
        assert result.chunks[-1].end_time == duration
    finally:
        result.cleanup()


def test_small_unsupported_container_transcodes_as_single_flac(tmp_path, monkeypatch):
    source = tmp_path / "legacy.aiff"
    source.write_bytes(b"audio")
    processor = AudioProcessor()
    audio_info = _info(source, duration=3600.0, size=5)
    monkeypatch.setattr(processor, "is_available", lambda: True)
    monkeypatch.setattr(processor, "get_audio_info", lambda _path: audio_info)

    commands = []

    def fake_ffmpeg(cmd, **kwargs):
        commands.append(cmd)
        Path(cmd[-1]).write_bytes(b"flac")
        return SimpleNamespace(returncode=0, stderr="")

    monkeypatch.setattr("src.tools.audio_processor.subprocess.run", fake_ffmpeg)

    result = processor.split_audio_for_groq(source)
    try:
        assert result.success
        assert len(result.chunks) == 1
        assert result.chunks[0].path.suffix == ".flac"
        assert result.chunks[0].start_time == 0.0
        assert result.chunks[0].end_time == 3600.0
        assert len(commands) == 1
    finally:
        result.cleanup()


def test_chunk_target_is_under_groq_free_tier_limit():
    assert GROQ_TARGET_CHUNK_BYTES == 24 * 1024 * 1024
    assert GROQ_TARGET_CHUNK_BYTES < 25 * 1024 * 1024
