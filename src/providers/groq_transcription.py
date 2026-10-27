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


def _format_timestamp(value: Any) -> str:
    """Format a Groq timestamp consistently with Gemini transcript output."""
    try:
        return f"{float(value):.3f}s"
    except (TypeError, ValueError):
        return str(value)


def _format_verbose_transcript(payload: Dict[str, Any]) -> str:
    """Render Groq verbose JSON as a timestamped transcript.

    The File Processor and Audio Tool both consume text rather than raw provider
    payloads. Keep the word/segment timing in that text using the same
    ``(start->end) text`` convention as Gemini transcription so it survives
    chunk timestamp adjustment and merging.
    """
    words = payload.get("words")
    if isinstance(words, list) and words:
        timed_words = []
        for entry in words:
            if not isinstance(entry, dict):
                continue
            word = str(entry.get("word") or "").strip()
            start, end = entry.get("start"), entry.get("end")
            if not word:
                continue
            if start is not None and end is not None:
                timed_words.append(f"({_format_timestamp(start)}->{_format_timestamp(end)}) {word}")
            else:
                timed_words.append(word)
        if timed_words:
            return " ".join(timed_words)

    segments = payload.get("segments")
    if isinstance(segments, list) and segments:
        timed_segments = []
        for entry in segments:
            if not isinstance(entry, dict):
                continue
            text = str(entry.get("text") or "").strip()
            start, end = entry.get("start"), entry.get("end")
            if not text:
                continue
            if start is not None and end is not None:
                timed_segments.append(f"({_format_timestamp(start)}->{_format_timestamp(end)}) {text}")
            else:
                timed_segments.append(text)
        if timed_segments:
            return "\n".join(timed_segments)

    return str(payload.get("text") or "").strip()


def _format_srt_timestamp(value: Any) -> str:
    """Format seconds as an SRT timestamp (``HH:MM:SS,mmm``)."""
    try:
        milliseconds = max(0, round(float(value) * 1000))
    except (TypeError, ValueError):
        milliseconds = 0
    hours, milliseconds = divmod(milliseconds, 3_600_000)
    minutes, milliseconds = divmod(milliseconds, 60_000)
    seconds, milliseconds = divmod(milliseconds, 1_000)
    return f"{hours:02}:{minutes:02}:{seconds:02},{milliseconds:03}"


def _group_words_into_cues(
    words: list,
    *,
    max_words: int = 8,
    max_chars: int = 52,
    max_duration: float = 5.5,
) -> list:
    """Group word entries into readable SRT cues from exact word timings."""
    cues = []
    current = []
    for entry in words:
        if not isinstance(entry, dict):
            continue
        word = str(entry.get("word") or "").strip()
        if not word:
            continue
        try:
            start = float(entry.get("start", 0))
            end = float(entry.get("end", start))
        except (TypeError, ValueError):
            continue
        if current:
            previous = current[-1]
            text = " ".join(item[0] for item in current)
            gap = start - previous[2]
            sentence_end = previous[0].endswith((".", "!", "?"))
            should_break = (
                len(current) >= max_words
                or gap >= 0.65
                or (sentence_end and len(text) >= 20)
                or len(text) + len(word) + 1 > max_chars
                or end - current[0][1] >= max_duration
            )
            if should_break:
                cues.append(current)
                current = []
        current.append((word, start, end))
    if current:
        cues.append(current)
    return cues


def _format_srt(words: list, words_per_cue: int = 8) -> str:
    """Render word timestamp entries as a readable SRT document."""
    blocks = []
    for number, cue in enumerate(_group_words_into_cues(words, max_words=words_per_cue), start=1):
        text = " ".join(word for word, _, _ in cue)
        blocks.append(f"{number}\n{_format_srt_timestamp(cue[0][1])} --> {_format_srt_timestamp(cue[-1][2])}\n{text}")
    return "\n\n".join(blocks)


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
    words_per_cue: int = 8,
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
        words_per_cue: Words per subtitle cue when ``response_format`` is ``srt``.
        timeout: Request timeout in seconds.

    Returns:
        (transcript_text, None) on success or (None, error_message) on failure.
    """
    if not api_key:
        return None, "No Groq API key available"

    # SRT is generated client-side from Groq's word timestamps: Groq has no
    # native SRT response format or cue/grouping parameter.
    request_format = "verbose_json" if response_format == "srt" else response_format
    if response_format == "srt":
        timestamp_granularity = "word"

    data: Dict[str, Any] = {"model": model, "response_format": request_format}
    if language:
        data["language"] = _to_iso639_1(language)
    if prompt:
        # Groq prompt is capped ~224 tokens; approximate 1 token ~ 4 chars.
        data["prompt"] = prompt[:GROQ_PROMPT_MAX_CHARS]
    if temperature is not None:
        data["temperature"] = temperature
    if request_format == "verbose_json":
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

    if request_format == "text":
        return resp.text.strip(), None

    try:
        payload = resp.json()
    except ValueError:
        return None, "Invalid JSON response from Groq"

    if isinstance(payload.get("error"), dict):
        return None, f"Groq API error: {payload['error'].get('message', 'unknown')}"

    if response_format == "srt":
        words = payload.get("words")
        if not isinstance(words, list) or not words:
            return None, "Groq did not return word timestamps for SRT output"
        transcript = _format_srt(words, words_per_cue)
        if not transcript.strip():
            return None, "Groq returned no timed words for SRT output"
        return transcript, None

    if request_format == "verbose_json":
        # Render timing metadata into text so existing transcription consumers
        # preserve it through chunk offset adjustment and transcript merging.
        transcript = _format_verbose_transcript(payload)
        logging.debug(
            "[GroqTranscription] %d segments, %d word entries returned",
            len(payload.get("segments", [])) if isinstance(payload.get("segments"), list) else 0,
            len(payload.get("words", [])) if isinstance(payload.get("words"), list) else 0,
        )
        return transcript, None

    return (payload.get("text") or "").strip(), None
