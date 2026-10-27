#!/usr/bin/env python3
"""
Groq Transcription Service (speech-to-text).

Focused transcription backend for Groq's OpenAI-compatible multipart API,
mirroring how ``gemini_services.py`` is a side-module next to the Gemini
provider. This is NOT a full ``BaseProvider`` chat provider.

Reference: https://console.groq.com/docs/speech-to-text
"""

import logging
import os
from typing import Any, Dict, Optional, Tuple, Union

import requests

# Groq transcription endpoint (OpenAI-compatible)
GROQ_TRANSCRIPTION_URL = "https://api.groq.com/openai/v1/audio/transcriptions"

# Per-request upload size limit is 25 MB on the free tier. Stay conservatively
# below it so chunked uploads never trip a 413.
GROQ_MAX_FILE_BYTES = 24 * 1024 * 1024

# Groq-supported upload container extensions
GROQ_SUPPORTED_EXTS = {".flac", ".mp3", ".mp4", ".mpeg", ".mpga", ".m4a", ".ogg", ".wav", ".webm"}

# Groq's `prompt` parameter is capped at ~224 tokens (~4 chars/token)
GROQ_PROMPT_MAX_CHARS = 900


def _to_iso639_1(code: str) -> str:
    """Normalize a BCP-47-ish language code (e.g. ``en-US``) to ISO-639-1 (``en``).

    Groq expects ISO-639-1 codes while the transcription profiles store
    BCP-47 (Gemini convention); take the primary subtag and lowercase it.
    """
    if not code:
        return ""
    return code.strip().split("-")[0].split("_")[0].lower()


def transcribe_file(
    filepath: Union[str, os.PathLike],
    *,
    api_key: str,
    model: str,
    language: str = "",
    prompt: str = "",
    temperature: Optional[float] = None,
    response_format: str = "text",
    timestamp_granularity: str = "segment",
    timeout: int = 300,
) -> Tuple[Optional[str], Optional[str]]:
    """
    Transcribe a local audio file via Groq.

    Args:
        filepath: Path to the audio file (must be a Groq-supported container).
        api_key: Groq API key (starts with ``gsk_``).
        model: Groq Whisper model ID (``whisper-large-v3`` / ``whisper-large-v3-turbo``).
        language: Optional language hint (BCP-47 or ISO-639-1; normalized here).
        prompt: Optional style/context guidance (truncated to the ~224-token cap).
        temperature: Optional 0-1 sampling temperature. None = API default (0).
        response_format: ``text`` | ``json`` | ``verbose_json``.
        timestamp_granularity: ``segment`` | ``word`` (only sent for verbose_json).
        timeout: Request timeout in seconds.

    Returns:
        (transcript_text, None) on success or (None, error_message) on failure.
    """
    if not api_key:
        return None, "No Groq API key available"

    data: Dict[str, Any] = {"model": model, "response_format": response_format}
    if language:
        data["language"] = _to_iso639_1(language)
    if prompt:
        # Groq prompt is capped ~224 tokens; approximate 1 token ~ 4 chars.
        data["prompt"] = prompt[:GROQ_PROMPT_MAX_CHARS]
    if temperature is not None:
        data["temperature"] = temperature
    if response_format == "verbose_json":
        data["timestamp_granularities[]"] = timestamp_granularity

    headers = {"Authorization": f"Bearer {api_key}"}

    try:
        with open(filepath, "rb") as fh:
            files = {"file": (os.path.basename(str(filepath)), fh)}
            try:
                resp = requests.post(GROQ_TRANSCRIPTION_URL, headers=headers, data=data, files=files, timeout=timeout)
            except requests.RequestException as e:
                return None, f"Network error: {e}"
    except OSError as e:
        return None, f"Failed to read audio file: {e}"

    if resp.status_code == 401 or resp.status_code == 403:
        return None, f"Groq API error {resp.status_code} (invalid/unauthorized key): {resp.text[:300]}"
    if resp.status_code == 429:
        return None, f"Groq API rate limited (429): {resp.text[:300]}"
    if resp.status_code != 200:
        return None, f"Groq API error {resp.status_code}: {resp.text[:300]}"

    if response_format == "text":
        return resp.text.strip(), None

    try:
        payload = resp.json()
    except ValueError:
        return None, "Invalid JSON response from Groq"

    if isinstance(payload.get("error"), dict):
        return None, f"Groq API error: {payload['error'].get('message', 'unknown')}"

    if response_format == "verbose_json":
        # Log segment metadata for debugging; the merged text is the return
        # value so it stays compatible with merge_transcribe_transcripts().
        segments = payload.get("segments")
        if segments and isinstance(segments, list):
            logging.debug(f"[GroqTranscription] {len(segments)} segments returned")
        words = payload.get("words")
        if words and isinstance(words, list):
            logging.debug(f"[GroqTranscription] {len(words)} word entries returned")

    return (payload.get("text") or "").strip(), None
