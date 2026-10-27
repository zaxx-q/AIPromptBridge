"""Unit tests for the Groq transcription service (src/providers/groq_transcription.py)."""

from unittest.mock import MagicMock, patch

from src.providers import groq_transcription
from src.providers.groq_transcription import (
    GROQ_TRANSCRIPTION_URL,
    _to_iso639_1,
    transcribe_file,
)


class TestToIso6391:
    def test_bcp47_us(self):
        assert _to_iso639_1("en-US") == "en"

    def test_bcp47_underscore(self):
        assert _to_iso639_1("tr_TR") == "tr"

    def test_plain_code(self):
        assert _to_iso639_1("tr") == "tr"

    def test_uppercase(self):
        assert _to_iso639_1("ES") == "es"

    def test_empty(self):
        assert _to_iso639_1("") == ""

    def test_whitespace(self):
        assert _to_iso639_1("  ja-JP  ") == "ja"


def _make_response(status_code=200, text='{"text": "hello"}', raw_text=None):
    resp = MagicMock()
    resp.status_code = status_code
    resp.text = raw_text if raw_text is not None else text
    resp.json.return_value = {"text": "hello"}
    return resp


class TestTranscribeFileRequestConstruction:
    """Verify multipart request construction via a patched requests.post."""

    def _invoke(self, resp, tmp_path, **kwargs):
        audio = tmp_path / "sample.wav"
        audio.write_bytes(b"RIFF-fake")
        params = dict(api_key="gsk_test", model="whisper-large-v3-turbo")
        params.update(kwargs)
        with patch.object(groq_transcription.requests, "post", return_value=resp) as mock_post:
            result = transcribe_file(audio, **params)
        return result, mock_post.call_args

    def test_text_format_omits_granularity(self, tmp_path):
        resp = _make_response(raw_text="hello world")
        (text, err), call = self._invoke(resp, tmp_path, response_format="text")

        assert err is None
        assert text == "hello world"

        assert call.args[0] == GROQ_TRANSCRIPTION_URL
        data = call.kwargs["data"]
        assert data["model"] == "whisper-large-v3-turbo"
        assert data["response_format"] == "text"
        assert "timestamp_granularities[]" not in data
        assert "language" not in data
        assert "temperature" not in data
        assert call.kwargs["headers"] == {"Authorization": "Bearer gsk_test"}
        # multipart file tuple carries the basename
        assert call.kwargs["files"]["file"][0] == "sample.wav"

    def test_verbose_json_sends_granularity(self, tmp_path):
        resp = _make_response()
        (text, err), call = self._invoke(resp, tmp_path, response_format="verbose_json", timestamp_granularity="word")
        assert err is None
        assert text == "hello"
        assert call.kwargs["data"]["timestamp_granularities[]"] == "word"

    def test_json_format_omits_granularity(self, tmp_path):
        resp = _make_response()
        (_, err), call = self._invoke(resp, tmp_path, response_format="json")
        assert err is None
        assert "timestamp_granularities[]" not in call.kwargs["data"]

    def test_language_normalized_to_iso639_1(self, tmp_path):
        resp = _make_response()
        _, call = self._invoke(resp, tmp_path, language="en-US")
        assert call.kwargs["data"]["language"] == "en"

    def test_temperature_sent_when_set(self, tmp_path):
        resp = _make_response()
        _, call = self._invoke(resp, tmp_path, temperature=0.5)
        assert call.kwargs["data"]["temperature"] == 0.5

    def test_prompt_truncated(self, tmp_path):
        resp = _make_response()
        _, call = self._invoke(resp, tmp_path, prompt="x" * 5000)
        assert len(call.kwargs["data"]["prompt"]) == groq_transcription.GROQ_PROMPT_MAX_CHARS


class TestTranscribeFileErrors:
    def test_non_200_error(self, tmp_path):
        resp = _make_response(status_code=500, raw_text="boom")
        audio = tmp_path / "a.wav"
        audio.write_bytes(b"x")
        with patch.object(groq_transcription.requests, "post", return_value=resp):
            text, err = transcribe_file(audio, api_key="gsk_test", model="whisper-large-v3-turbo")
        assert text is None
        assert "500" in err

    def test_rate_limit_error(self, tmp_path):
        resp = _make_response(status_code=429, raw_text="rate limited")
        audio = tmp_path / "a.wav"
        audio.write_bytes(b"x")
        with patch.object(groq_transcription.requests, "post", return_value=resp):
            text, err = transcribe_file(audio, api_key="gsk_test", model="whisper-large-v3-turbo")
        assert text is None
        assert "429" in err

    def test_unauthorized_error(self, tmp_path):
        resp = _make_response(status_code=401, raw_text="bad key")
        audio = tmp_path / "a.wav"
        audio.write_bytes(b"x")
        with patch.object(groq_transcription.requests, "post", return_value=resp):
            text, err = transcribe_file(audio, api_key="gsk_test", model="whisper-large-v3-turbo")
        assert text is None
        assert "401" in err

    def test_network_error(self, tmp_path):
        import requests as requests_mod

        audio = tmp_path / "a.wav"
        audio.write_bytes(b"x")
        with patch.object(groq_transcription.requests, "post", side_effect=requests_mod.RequestException("conn reset")):
            text, err = transcribe_file(audio, api_key="gsk_test", model="whisper-large-v3-turbo")
        assert text is None
        assert "Network error" in err

    def test_missing_api_key(self, tmp_path):
        audio = tmp_path / "a.wav"
        audio.write_bytes(b"x")
        text, err = transcribe_file(audio, api_key="", model="whisper-large-v3-turbo")
        assert text is None
        assert "No Groq API key" in err

    def test_missing_file(self, tmp_path):
        text, err = transcribe_file(tmp_path / "missing.wav", api_key="gsk_test", model="whisper-large-v3-turbo")
        assert text is None
        assert "Failed to read" in err

    def test_invalid_json(self, tmp_path):
        resp = MagicMock()
        resp.status_code = 200
        resp.json.side_effect = ValueError("not json")
        audio = tmp_path / "a.wav"
        audio.write_bytes(b"x")
        with patch.object(groq_transcription.requests, "post", return_value=resp):
            text, err = transcribe_file(
                audio, api_key="gsk_test", model="whisper-large-v3-turbo", response_format="json"
            )
        assert text is None
        assert "Invalid JSON" in err
