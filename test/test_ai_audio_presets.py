"""Unit tests for AI-powered audio presets (arnndn and DeepFilterNet)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

from src.audio import ffmpeg_utils
from src.tools.audio_processor import (
    ARNNDN_MODELS,
    AudioProcessor,
    Intensity,
    _get_arnndn_model_path,
    get_preset,
    get_presets_by_category,
)
from src.tools.file_processor import FileProcessor


def test_arnndn_model_files_exist():
    """Verify all 6 arnndn model files exist in assets/models/arnndn."""
    expected_models = ["sh", "cb", "bd", "std", "mp", "lq"]
    assert set(ARNNDN_MODELS.keys()) == set(expected_models)

    for model_name in expected_models:
        path = _get_arnndn_model_path(model_name)
        assert path is not None, f"Model {model_name}.rnnn not found"
        assert path.exists()
        assert path.stat().st_size > 100_000, f"Model {model_name}.rnnn too small"

        info = ARNNDN_MODELS[model_name]
        assert "name" in info
        assert "description" in info
        assert "signal" in info
        assert "noise" in info
        assert "recommended_for" in info

    assert _get_arnndn_model_path("non_existent_model") is None


def test_deep_filter_detection():
    """Test is_deep_filter_available and get_deep_filter_path."""
    with (
        patch("shutil.which", side_effect=lambda x: "/usr/bin/deep-filter" if x == "deep-filter" else None),
        patch.object(ffmpeg_utils, "_deep_filter_checked", False),
        patch.object(ffmpeg_utils, "_deep_filter_path", None),
    ):
        assert ffmpeg_utils.is_deep_filter_available() is True
        assert ffmpeg_utils.get_deep_filter_path() == "/usr/bin/deep-filter"

    with (
        patch("shutil.which", side_effect=lambda x: "/usr/local/bin/deepFilter" if x == "deepFilter" else None),
        patch.object(ffmpeg_utils, "_deep_filter_checked", False),
        patch.object(ffmpeg_utils, "_deep_filter_path", None),
    ):
        assert ffmpeg_utils.is_deep_filter_available() is True
        assert ffmpeg_utils.get_deep_filter_path() == "/usr/local/bin/deepFilter"

    with (
        patch("shutil.which", return_value=None),
        patch.object(ffmpeg_utils, "_deep_filter_checked", False),
        patch.object(ffmpeg_utils, "_deep_filter_path", None),
    ):
        assert ffmpeg_utils.is_deep_filter_available() is False
        assert ffmpeg_utils.get_deep_filter_path() is None


def test_is_arnndn_available():
    """Test is_arnndn_available detection with FFmpeg."""
    mock_success = MagicMock(returncode=0, stdout="TS arnndn A->A Reduce noise...")
    with (
        patch.object(ffmpeg_utils, "_arnndn_available", None),
        patch.object(ffmpeg_utils, "get_ffmpeg_path", return_value="/usr/bin/ffmpeg"),
        patch("subprocess.run", return_value=mock_success),
    ):
        assert ffmpeg_utils.is_arnndn_available() is True

    mock_missing = MagicMock(returncode=0, stdout="loudnorm A->A...")
    with (
        patch.object(ffmpeg_utils, "_arnndn_available", None),
        patch.object(ffmpeg_utils, "get_ffmpeg_path", return_value="/usr/bin/ffmpeg"),
        patch("subprocess.run", return_value=mock_missing),
    ):
        assert ffmpeg_utils.is_arnndn_available() is False


def test_ai_presets_registered():
    """Verify all three AI presets are registered in AUDIO_PRESETS."""
    ai_presets = get_presets_by_category("ai")
    ai_ids = {p.id for p in ai_presets}
    assert {"ai_noise_reduction", "ai_lecture_cleanup", "ai_deep_denoise"}.issubset(ai_ids)

    # Check ai_noise_reduction
    p1 = get_preset("ai_noise_reduction")
    assert p1 is not None
    assert p1.category == "ai"
    assert "RNNoise" in p1.description
    for intensity in (Intensity.LOW, Intensity.MEDIUM, Intensity.HIGH):
        effects = p1.get_effects(intensity)
        assert any(e.name == "arnndn" for e in effects)
        assert any(e.name == "loudnorm" for e in effects)

    # Check ai_lecture_cleanup
    p2 = get_preset("ai_lecture_cleanup")
    assert p2 is not None
    assert p2.category == "ai"
    for intensity in (Intensity.LOW, Intensity.MEDIUM, Intensity.HIGH):
        effects = p2.get_effects(intensity)
        assert any(e.name == "arnndn" for e in effects)
        assert any(e.name == "highpass" for e in effects)

    # Check ai_deep_denoise
    p3 = get_preset("ai_deep_denoise")
    assert p3 is not None
    assert p3.category == "ai"
    for intensity in (Intensity.LOW, Intensity.MEDIUM, Intensity.HIGH):
        effects = p3.get_effects(intensity)
        assert effects[0].name == "__DEEPFILTER__"


def test_resolve_arnndn_model():
    """Test placeholder replacement with real model path."""
    ap = AudioProcessor()
    chain = "arnndn=m=__ARNNDN_MODEL__:mix=0.85,loudnorm=I=-16:LRA=11:TP=-1.5"

    resolved_sh = ap._resolve_arnndn_model(chain, "sh")
    assert "__ARNNDN_MODEL__" not in resolved_sh
    assert "sh.rnnn" in resolved_sh

    resolved_cb = ap._resolve_arnndn_model(chain, "cb")
    assert "__ARNNDN_MODEL__" not in resolved_cb
    assert "cb.rnnn" in resolved_cb

    # Without placeholder
    plain_chain = "highpass=f=80,loudnorm"
    assert ap._resolve_arnndn_model(plain_chain, "sh") == plain_chain

    # Missing model raises FileNotFoundError
    import pytest

    with pytest.raises(FileNotFoundError):
        ap._resolve_arnndn_model(chain, "does_not_exist")


def test_apply_preset_arnndn_real_audio(tmp_path):
    """Test actual execution of arnndn presets using assets/snip.wav if ffmpeg is available."""
    ap = AudioProcessor()
    if not ap.is_available() or not ap.is_arnndn_available():
        return

    snip_wav = Path("assets/snip.wav").resolve()
    assert snip_wav.exists()

    out_path = tmp_path / "snip_cleaned.wav"
    result = ap.apply_preset(
        snip_wav,
        "ai_noise_reduction",
        intensity=Intensity.MEDIUM,
        output_path=out_path,
        arnndn_model="sh",
    )

    assert result.success is True
    assert out_path.exists()
    assert out_path.stat().st_size > 0


def test_apply_preset_deepfilter_not_installed():
    """Test that DeepFilterNet preset returns descriptive error when not installed."""
    ap = AudioProcessor()
    with patch.object(ap, "is_deep_filter_available", return_value=False):
        result = ap.apply_preset(
            Path("assets/snip.wav"),
            "ai_deep_denoise",
            intensity=Intensity.MEDIUM,
        )
        assert result.success is False
        assert "DeepFilterNet not installed" in (result.error or "")


def test_apply_deepfilter_preset_pipeline_mocked(tmp_path):
    """Test DeepFilterNet 3-step pipeline when deep-filter is present."""
    ap = AudioProcessor()
    fake_audio = tmp_path / "lecture.mp3"
    fake_audio.write_bytes(b"dummy mp3 data")

    from src.tools.audio_processor import AudioInfo

    audio_info = AudioInfo(
        path=fake_audio,
        duration_seconds=10.0,
        bitrate_kbps=128.0,
        size_bytes=1000,
        format="mp3",
        sample_rate=44100,
        channels=2,
    )

    executed_cmds = []

    def mock_subprocess_run(cmd, *args, **kwargs):
        executed_cmds.append(cmd)
        mock_res = MagicMock()
        mock_res.returncode = 0
        mock_res.stderr = ""

        # Step 2 simulation: deep-filter creates output wav in output dir
        if cmd[0] == "/mock/deep-filter":
            out_dir = Path(cmd[4])
            cleaned_file = out_dir / "input_clean.wav"
            cleaned_file.write_bytes(b"cleaned wav data")

        # Step 3 simulation: ffmpeg filter chain creates final file
        if len(cmd) > 2 and cmd[0] == "ffmpeg" and "-af" in cmd:
            out_target = Path(cmd[-1])
            out_target.write_bytes(b"final processed data")

        return mock_res

    preset = get_preset("ai_deep_denoise")
    assert preset is not None
    effects = preset.get_effects(Intensity.MEDIUM)

    with (
        patch.object(ap, "is_deep_filter_available", return_value=True),
        patch("src.tools.audio_processor._get_deep_filter_path", return_value="/mock/deep-filter"),
        patch.object(ap, "get_audio_info", return_value=audio_info),
        patch.object(ap, "is_available", return_value=True),
        patch("src.tools.audio_processor.get_ffmpeg_path", return_value="ffmpeg"),
        patch("subprocess.run", side_effect=mock_subprocess_run),
    ):
        result = ap._apply_deepfilter_preset(fake_audio, effects)
        assert result.success is True
        assert result.output_path is not None
        assert result.output_path.exists()
        # Verify step 1 (convert to 48kHz mono WAV)
        assert executed_cmds[0][0] == "ffmpeg"
        assert "-ar" in executed_cmds[0]
        assert "48000" in executed_cmds[0]
        assert "-ac" in executed_cmds[0]
        assert "1" in executed_cmds[0]

        # Verify step 2 (deep-filter)
        assert executed_cmds[1][0] == "/mock/deep-filter"

        # Verify step 3 (remaining filters)
        assert executed_cmds[2][0] == "ffmpeg"
        assert "-af" in executed_cmds[2]

        result.cleanup()


def test_file_processor_select_arnndn_model():
    """Test model selection sub-menu in FileProcessor."""
    fp = FileProcessor()

    # User selects "1" (Speech Recording / sh)
    with patch("builtins.input", return_value="1"):
        assert fp._select_arnndn_model() == "sh"

    # User selects "3" (Crowd/Chatter / cb)
    with patch("builtins.input", return_value="3"):
        assert fp._select_arnndn_model() == "cb"

    # User presses Enter (default "1")
    with patch("builtins.input", return_value=""):
        assert fp._select_arnndn_model() == "sh"

    # User types 'b' (back)
    with patch("builtins.input", return_value="b"):
        assert fp._select_arnndn_model() == ""

    # User cancels (EOFError)
    with patch("builtins.input", side_effect=EOFError):
        assert fp._select_arnndn_model() is None


def test_file_processor_select_preset_intensity_arnndn():
    """Test selecting intensity for arnndn preset includes arnndn_model in config."""
    fp = FileProcessor()

    # User selects model "sh" (choice "1"), then intensity "medium" (choice "2")
    with patch("builtins.input", side_effect=["1", "2"]):
        config = fp._select_preset_intensity("ai_noise_reduction")
        assert config == {
            "type": "preset",
            "preset_id": "ai_noise_reduction",
            "intensity": "medium",
            "arnndn_model": "sh",
        }


def test_file_processor_select_preset_intensity_deepfilter_not_installed():
    """Test selecting DeepFilterNet when not installed shows warning and returns {}."""
    fp = FileProcessor()

    with (
        patch.object(fp.audio_processor, "is_deep_filter_available", return_value=False),
        patch("builtins.input", return_value=""),
    ):
        config = fp._select_preset_intensity("ai_deep_denoise")
        assert config == {}


def test_file_processor_preprocess_audio_passes_arnndn_model():
    """Test that _preprocess_audio_if_needed passes arnndn_model to apply_preset."""
    fp = FileProcessor()
    fp._audio_preprocessing = {
        "type": "preset",
        "preset_id": "ai_noise_reduction",
        "intensity": "high",
        "arnndn_model": "bd",
    }

    mock_result = MagicMock(success=True, output_path=Path("/tmp/cleaned.mp3"))

    with patch.object(fp.audio_processor, "apply_preset", return_value=mock_result) as mock_apply:
        out_path, res = fp._preprocess_audio_if_needed(Path("/tmp/test.mp3"), interactive=False)
        assert out_path == Path("/tmp/cleaned.mp3")
        assert res is mock_result
        mock_apply.assert_called_once_with(
            Path("/tmp/test.mp3"),
            "ai_noise_reduction",
            intensity=Intensity.HIGH,
            optimization=None,
            arnndn_model="bd",
        )


def test_audio_processor_preview_preset_arnndn():
    """Test preview_preset resolves arnndn model in filter chain before playing."""
    ap = AudioProcessor()
    with patch.object(ap, "preview_filter_chain", return_value=True) as mock_pfc:
        res = ap.preview_preset(
            Path("assets/snip.wav"),
            "ai_noise_reduction",
            intensity=Intensity.MEDIUM,
            arnndn_model="sh",
        )
        assert res is True
        mock_pfc.assert_called_once()
        filter_chain_arg = mock_pfc.call_args[0][1]
        assert "sh.rnnn" in filter_chain_arg
        assert "__ARNNDN_MODEL__" not in filter_chain_arg


def test_audio_processor_preview_preset_deepfilter_not_installed():
    """Test preview_preset fails cleanly when DeepFilterNet is not installed."""
    ap = AudioProcessor()
    with patch.object(ap, "is_deep_filter_available", return_value=False):
        res = ap.preview_preset(
            Path("assets/snip.wav"),
            "ai_deep_denoise",
            intensity=Intensity.MEDIUM,
        )
        assert res is False


def test_file_processor_display_and_preview_ai_settings(capsys):
    """Test _display_preprocessing_settings and _preview_audio_settings with AI presets."""
    fp = FileProcessor()

    # Test display settings
    cfg = {
        "type": "preset",
        "preset_id": "ai_noise_reduction",
        "intensity": "medium",
        "arnndn_model": "cb",
    }
    fp._display_preprocessing_settings(cfg)
    captured = capsys.readouterr().out
    assert "AI Noise Reduction [cb] (medium)" in captured

    # Test preview settings calls preview_preset with arnndn_model
    with (
        patch("builtins.input", return_value="5"),
        patch.object(fp.audio_processor, "preview_preset") as mock_prev,
    ):
        fp._preview_audio_settings(Path("test.mp3"), cfg)
        mock_prev.assert_called_once_with(
            Path("test.mp3"),
            "ai_noise_reduction",
            intensity=Intensity.MEDIUM,
            duration_seconds=5.0,
            arnndn_model="cb",
        )
