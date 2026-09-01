"""
Google Gemini Specific Services (Files, Batch, and TTS APIs).
Extracted from gemini_native.py to keep the main provider focused on content generation.
"""

import base64
import json
import mimetypes
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import requests

from .base import CallbackType, ProviderResult, RetryReason

# Base URL for Gemini API
GEMINI_BASE_URL = "https://generativelanguage.googleapis.com/v1beta"
MAX_INLINE_SIZE_BYTES = 15 * 1024 * 1024


@dataclass
class UploadedFile:
    """Represents a file uploaded to the Gemini Files API"""

    name: str
    uri: str
    mime_type: str
    size_bytes: int
    display_name: Optional[str] = None

    def to_file_data_part(self) -> Dict:
        """Convert to fileData part for generateContent request"""
        return {"fileData": {"mimeType": self.mime_type, "fileUri": self.uri}}


def upload_file(
    provider, filepath: Path, display_name: Optional[str] = None
) -> Tuple[Optional[UploadedFile], Optional[str]]:
    """
    Upload a file to Gemini Files API using resumable upload.
    Files are automatically deleted after 48 hours.
    """
    if not provider.key_manager or not provider.key_manager.has_keys():
        return None, "No API keys configured for Gemini"

    current_key = provider.key_manager.get_current_key()
    if not current_key:
        return None, "No API key available"

    filepath = Path(filepath)
    if not filepath.exists():
        return None, f"File not found: {filepath}"

    # Detect MIME type
    mime_type = mimetypes.guess_type(str(filepath))[0]
    if not mime_type:
        ext_to_mime = {
            ".mp3": "audio/mp3",
            ".wav": "audio/wav",
            ".aiff": "audio/aiff",
            ".aac": "audio/aac",
            ".ogg": "audio/ogg",
            ".flac": "audio/flac",
            ".m4a": "audio/mp4",
            ".wma": "audio/x-ms-wma",
        }
        mime_type = ext_to_mime.get(filepath.suffix.lower(), "application/octet-stream")

    file_size = filepath.stat().st_size
    if display_name is None:
        display_name = filepath.name

    provider.log("info", f"Uploading file: {filepath.name} ({file_size / (1024 * 1024):.1f} MB)")

    try:
        base = provider.base_url
        if base.endswith("/v1beta"):
            base = base[:-7]

        init_url = f"{base}/upload/v1beta/files"

        init_headers = {
            "x-goog-api-key": current_key,
            "X-Goog-Upload-Protocol": "resumable",
            "X-Goog-Upload-Command": "start",
            "X-Goog-Upload-Header-Content-Length": str(file_size),
            "X-Goog-Upload-Header-Content-Type": mime_type,
            "Content-Type": "application/json",
        }

        init_body = {"file": {"display_name": display_name}}

        init_response = requests.post(init_url, headers=init_headers, json=init_body, timeout=60)

        if init_response.status_code != 200:
            return None, f"Failed to initiate upload ({init_response.status_code}): {init_response.text[:200]}"

        upload_url = init_response.headers.get("x-goog-upload-url") or init_response.headers.get("X-Goog-Upload-URL")

        if not upload_url:
            return None, "Failed to get upload URL from response headers"

        with open(filepath, "rb") as f:
            file_data = f.read()

        upload_headers = {
            "Content-Length": str(file_size),
            "X-Goog-Upload-Offset": "0",
            "X-Goog-Upload-Command": "upload, finalize",
        }

        upload_response = requests.post(upload_url, headers=upload_headers, data=file_data, timeout=300)

        if upload_response.status_code != 200:
            return None, f"Failed to upload file ({upload_response.status_code}): {upload_response.text[:200]}"

        file_info = upload_response.json()
        file_obj = file_info.get("file", {})

        uploaded = UploadedFile(
            name=file_obj.get("name", ""),
            uri=file_obj.get("uri", ""),
            mime_type=mime_type,
            size_bytes=file_size,
            display_name=display_name,
        )

        provider._uploaded_files[str(filepath)] = uploaded

        provider.log("info", f"File uploaded successfully: {uploaded.uri}")
        return uploaded, None

    except requests.exceptions.Timeout:
        return None, "Upload timed out"
    except requests.exceptions.RequestException as e:
        return None, f"Upload failed: {e}"
    except Exception as e:
        return None, f"Unexpected error during upload: {e}"


def get_file_info(provider, file_name: str) -> Tuple[Optional[Dict], Optional[str]]:
    """Get metadata for an uploaded file."""
    if not provider.key_manager or not provider.key_manager.has_keys():
        return None, "No API keys configured"

    current_key = provider.key_manager.get_current_key()
    if not current_key:
        return None, "No API key available"

    url = f"{provider.base_url}/{file_name}"
    headers = {"x-goog-api-key": current_key}

    try:
        response = requests.get(url, headers=headers, timeout=30)
        if response.status_code != 200:
            return None, f"Failed to get file info ({response.status_code}): {response.text[:200]}"
        return response.json(), None
    except Exception as e:
        return None, f"Error getting file info: {e}"


def delete_file(provider, file_name: str) -> Tuple[bool, Optional[str]]:
    """Delete an uploaded file."""
    if not provider.key_manager or not provider.key_manager.has_keys():
        return False, "No API keys configured"

    current_key = provider.key_manager.get_current_key()
    if not current_key:
        return False, "No API key available"

    url = f"{provider.base_url}/{file_name}"
    headers = {"x-goog-api-key": current_key}

    try:
        response = requests.delete(url, headers=headers, timeout=30)
        if response.status_code not in (200, 204):
            return False, f"Failed to delete file ({response.status_code}): {response.text[:200]}"
        provider.log("info", f"File deleted: {file_name}")
        return True, None
    except Exception as e:
        return False, f"Error deleting file: {e}"


def list_files(provider, page_size: int = 100) -> Tuple[Optional[List[Dict]], Optional[str]]:
    """List all uploaded files."""
    if not provider.key_manager or not provider.key_manager.has_keys():
        return None, "No API keys configured"

    current_key = provider.key_manager.get_current_key()
    if not current_key:
        return None, "No API key available"

    url = f"{provider.base_url}/files?pageSize={page_size}"
    headers = {"x-goog-api-key": current_key}

    try:
        response = requests.get(url, headers=headers, timeout=30)
        if response.status_code != 200:
            return None, f"Failed to list files ({response.status_code}): {response.text[:200]}"
        data = response.json()
        return data.get("files", []), None
    except Exception as e:
        return None, f"Error listing files: {e}"


def create_batch(
    provider, messages: List[Dict], model: str, params: Dict, display_name: Optional[str] = None
) -> Tuple[Optional[Dict], Optional[str]]:
    """Create a batch job."""
    if not provider.key_manager or not provider.key_manager.has_keys():
        return None, "No API keys configured"

    current_key = provider.key_manager.get_current_key()
    if not current_key:
        return None, "No API key available"

    url = f"{provider.base_url}/models/{model}:batchGenerateContent"
    gen_req_body = provider._build_request_body(messages, model, params, thinking_enabled=False)

    req_body = {"displayName": display_name or f"batch_{int(time.time())}", "requests": [{"request": gen_req_body}]}

    try:
        response = requests.post(
            url, headers={"Content-Type": "application/json", "x-goog-api-key": current_key}, json=req_body, timeout=30
        )
        if response.status_code != 200:
            return None, f"Failed to create batch ({response.status_code}): {response.text[:200]}"
        return response.json(), None
    except Exception as e:
        return None, f"Error creating batch: {e}"


def get_batch(provider, batch_name: str) -> Tuple[Optional[Dict], Optional[str]]:
    """Get batch status"""
    if not provider.key_manager or not provider.key_manager.has_keys():
        return None, "No API keys configured"

    current_key = provider.key_manager.get_current_key()
    url = f"{provider.base_url}/{batch_name}"

    try:
        response = requests.get(url, headers={"x-goog-api-key": current_key}, timeout=30)
        if response.status_code != 200:
            return None, f"Failed to get batch ({response.status_code}): {response.text[:200]}"
        return response.json(), None
    except Exception as e:
        return None, f"Error getting batch: {e}"


def list_batches(provider, page_size: int = 50) -> Tuple[Optional[List[Dict]], Optional[str]]:
    """List batches"""
    if not provider.key_manager or not provider.key_manager.has_keys():
        return None, "No API keys configured"

    current_key = provider.key_manager.get_current_key()
    url = f"{provider.base_url}/batches?pageSize={page_size}"

    try:
        response = requests.get(url, headers={"x-goog-api-key": current_key}, timeout=30)
        if response.status_code != 200:
            return None, f"Failed to list batches ({response.status_code}): {response.text[:200]}"
        return response.json().get("batches", []), None
    except Exception as e:
        return None, f"Error listing batches: {e}"


def cancel_batch(provider, batch_name: str) -> Tuple[bool, Optional[str]]:
    """Cancel batch"""
    if not provider.key_manager or not provider.key_manager.has_keys():
        return False, "No API keys configured"

    current_key = provider.key_manager.get_current_key()
    url = f"{provider.base_url}/{batch_name}:cancel"

    try:
        response = requests.post(url, headers={"x-goog-api-key": current_key}, timeout=30)
        if response.status_code != 200:
            return False, f"Failed to cancel batch ({response.status_code}): {response.text[:200]}"
        return True, None
    except Exception as e:
        return False, f"Error cancelling batch: {e}"


def generate_tts(
    provider,
    text: str,
    model: str,
    voice_name: str,
    multi_speaker_config: Optional[List[Dict]] = None,
    retry_count: int = 0,
) -> Tuple[Optional[bytes], Optional[str]]:
    """Generate TTS audio using Gemini TTS models."""
    if not provider.key_manager or not provider.key_manager.has_keys():
        return None, "No API keys configured for Gemini"

    current_key = provider.key_manager.get_current_key()
    if not current_key:
        return None, "No API key available"

    key_label = provider.key_manager.get_key_label()
    timeout = provider.config.get("request_timeout", 120)

    if provider.config.get("tts_use_official_endpoint", False):
        url = f"{GEMINI_BASE_URL}/models/{model}:generateContent"
    else:
        url = provider._get_url(model, streaming=False)
    headers = {"Content-Type": "application/json", "x-goog-api-key": current_key}

    body = _build_tts_request_body(text, voice_name, multi_speaker_config)

    key_str = str(key_label)
    if not key_str.startswith("#"):
        key_str = f"'{key_str}'"

    provider.log(
        "info",
        f"[TTS] Request: model={model}, voice={voice_name}, "
        f"multi_speaker={'yes' if multi_speaker_config else 'no'}, "
        f"key={key_str}, retry={retry_count}",
    )

    try:
        response = requests.post(url, headers=headers, json=body, timeout=timeout)

        if response.status_code != 200:
            error_text = response.text[:500]
            status_code = response.status_code

            reason = provider.get_retry_reason(status_code, error_text)

            if provider.should_retry(reason, retry_count):
                delay = provider.get_retry_delay(reason)
                error_brief = provider.sanitize_api_error(error_text, status_code)
                provider.log_retry(reason, retry_count + 1, delay, error_brief)

                if reason in (RetryReason.RATE_LIMITED, RetryReason.AUTH_ERROR):
                    provider.rotate_key_if_possible(f"({reason.value})")

                if delay > 0:
                    time.sleep(delay)

                return generate_tts(provider, text, model, voice_name, multi_speaker_config, retry_count + 1)

            provider.log_error(f"[TTS] API error: {error_text}", status_code)
            return None, f"TTS API error ({status_code}): {provider.sanitize_api_error(error_text, status_code)}"

        data = response.json()

        try:
            inline_data = data["candidates"][0]["content"]["parts"][0]["inlineData"]
            audio_b64 = inline_data["data"]
            pcm_bytes = base64.b64decode(audio_b64)
        except (KeyError, IndexError) as e:
            candidates = data.get("candidates", [])
            if candidates and candidates[0].get("finishReason") == "SAFETY":
                return None, "TTS generation blocked by safety filters"

            provider.log_error(f"[TTS] Failed to extract audio data: {e}")

            if provider.should_retry(RetryReason.EMPTY_RESPONSE, retry_count):
                delay = provider.get_retry_delay(RetryReason.EMPTY_RESPONSE)
                provider.log_retry(RetryReason.EMPTY_RESPONSE, retry_count + 1, delay, "no audio data in response")

                if delay > 0:
                    time.sleep(delay)

                return generate_tts(provider, text, model, voice_name, multi_speaker_config, retry_count + 1)

            return None, f"No audio data in TTS response: {e}"

        usage_meta = data.get("usageMetadata", {})
        prompt_tokens = usage_meta.get("promptTokenCount", 0)
        total_tokens = usage_meta.get("totalTokenCount", 0)

        provider.log(
            "info",
            f"[TTS] Success: {len(pcm_bytes)} bytes PCM audio, "
            f"{prompt_tokens} prompt tokens, {total_tokens} total tokens",
        )

        return pcm_bytes, None

    except requests.exceptions.Timeout:
        provider.log_error(f"[TTS] Request timeout after {timeout}s")

        if provider.should_retry(RetryReason.NETWORK_ERROR, retry_count):
            delay = provider.get_retry_delay(RetryReason.NETWORK_ERROR)
            provider.log_retry(RetryReason.NETWORK_ERROR, retry_count + 1, delay, f"timeout after {timeout}s")
            provider.rotate_key_if_possible("(timeout)")

            if delay > 0:
                time.sleep(delay)

            return generate_tts(provider, text, model, voice_name, multi_speaker_config, retry_count + 1)

        return None, f"TTS request timeout after {timeout}s"

    except requests.exceptions.RequestException as e:
        error_msg = str(e)
        provider.log_error(f"[TTS] Network error: {error_msg}")

        if provider.should_retry(RetryReason.NETWORK_ERROR, retry_count):
            delay = provider.get_retry_delay(RetryReason.NETWORK_ERROR)
            provider.log_retry(RetryReason.NETWORK_ERROR, retry_count + 1, delay, error_msg[:100])
            provider.rotate_key_if_possible("(network error)")

            if delay > 0:
                time.sleep(delay)

            return generate_tts(provider, text, model, voice_name, multi_speaker_config, retry_count + 1)

        return None, f"TTS network error: {error_msg}"

    except Exception as e:
        error_msg = str(e)
        provider.log_error(f"[TTS] Unexpected error: {error_msg}")
        return None, f"TTS unexpected error: {error_msg}"


def _build_tts_request_body(text: str, voice_name: str, multi_speaker_config: Optional[List[Dict]] = None) -> Dict:
    """Build the TTS-specific request body."""
    if multi_speaker_config and len(multi_speaker_config) > 0:
        speaker_voice_configs = []
        for speaker_cfg in multi_speaker_config:
            speaker_voice_configs.append(
                {
                    "speaker": speaker_cfg["speaker"],
                    "voiceConfig": {"prebuiltVoiceConfig": {"voiceName": speaker_cfg["voice_name"]}},
                }
            )

        speech_config = {"multiSpeakerVoiceConfig": {"speakerVoiceConfigs": speaker_voice_configs}}
    else:
        speech_config = {"voiceConfig": {"prebuiltVoiceConfig": {"voiceName": voice_name}}}

    body = {
        "contents": [{"parts": [{"text": text}]}],
        "generationConfig": {"responseModalities": ["AUDIO"], "speechConfig": speech_config},
    }

    return body


def generate_transcription(
    provider,
    file_uri: str,
    mime_type: str,
    transcribe_config: Dict[str, Any],
    retry_count: int = 0,
) -> Tuple[Optional[str], Optional[str]]:
    """
    Generate transcription using gemini-3.5-transcribe.

    Uses audio_transcription_config instead of regular prompts.

    Args:
        provider: GeminiNativeProvider instance
        file_uri: URI of uploaded file (from Files API)
        mime_type: MIME type of the audio
        transcribe_config: Dict with keys: model, mode, diarization,
                          word_timestamp, language_codes, custom_vocabulary
        retry_count: Current retry attempt count

    Returns:
        (transcript_text, error) tuple
    """
    if not provider.key_manager or not provider.key_manager.has_keys():
        return None, "No API keys configured for Gemini"

    current_key = provider.key_manager.get_current_key()
    if not current_key:
        return None, "No API key available"

    model = transcribe_config.get("model", "gemini-3.5-transcribe")
    timeout = provider.config.get("request_timeout", 120)

    url = f"{provider.base_url}/models/{model}:generateContent"
    headers = {"Content-Type": "application/json", "x-goog-api-key": current_key}

    # Build audio_transcription_config
    audio_config: Dict[str, Any] = {}

    mode = transcribe_config.get("mode", "VERBATIM")
    if mode:
        audio_config["mode"] = mode

    if transcribe_config.get("diarization"):
        audio_config["diarization"] = True

    if transcribe_config.get("word_timestamp"):
        audio_config["wordTimestamp"] = True

    language_codes = transcribe_config.get("language_codes", [])
    if language_codes:
        audio_config["languageCodes"] = language_codes

    custom_vocabulary = transcribe_config.get("custom_vocabulary", [])
    if custom_vocabulary:
        audio_config["customVocabulary"] = custom_vocabulary

    # Build request body
    body = {
        "contents": [
            {
                "parts": [
                    {
                        "fileData": {
                            "fileUri": file_uri,
                            "mimeType": mime_type,
                        }
                    }
                ]
            }
        ],
        "generationConfig": {
            "audioTranscriptionConfig": audio_config,
        },
    }

    key_label = provider.key_manager.get_key_label()
    key_str = str(key_label)
    if not key_str.startswith("#"):
        key_str = f"'{key_str}'"

    provider.log(
        "info",
        f"[Transcribe] Request: model={model}, mode={mode}, "
        f"diarization={transcribe_config.get('diarization', False)}, "
        f"key={key_str}, retry={retry_count}",
    )

    try:
        response = requests.post(url, headers=headers, json=body, timeout=timeout)

        if response.status_code != 200:
            error_text = response.text[:500]
            status_code = response.status_code

            reason = provider.get_retry_reason(status_code, error_text)

            if provider.should_retry(reason, retry_count):
                delay = provider.get_retry_delay(reason)
                error_brief = provider.sanitize_api_error(error_text, status_code)
                provider.log_retry(reason, retry_count + 1, delay, error_brief)

                if reason in (RetryReason.RATE_LIMITED, RetryReason.AUTH_ERROR):
                    provider.rotate_key_if_possible(f"({reason.value})")

                if delay > 0:
                    time.sleep(delay)

                return generate_transcription(provider, file_uri, mime_type, transcribe_config, retry_count + 1)

            provider.log_error(f"[Transcribe] API error: {error_text}", status_code)
            return None, f"Transcription error ({status_code}): {provider.sanitize_api_error(error_text, status_code)}"

        data = response.json()

        # Extract transcript text
        try:
            candidates = data.get("candidates", [])
            if not candidates:
                return None, "No candidates in transcription response"

            content = candidates[0].get("content", {})
            parts = content.get("parts", [])

            # Collect text from parts (plain text or audioTranscription annotations)
            text_parts = []
            for part in parts:
                if "text" in part:
                    text_parts.append(part["text"])
                elif "audioTranscription" in part or "audio_transcription" in part:
                    transcription = part.get("audioTranscription") or part.get("audio_transcription")
                    if transcription:
                        speaker = transcription.get("speakerLabel") or transcription.get("speaker_label", "")
                        words = transcription.get("words", [])
                        word_strs = []
                        for w in words:
                            word_text = w.get("word", "")
                            start = w.get("startOffset") or w.get("start_offset")
                            end = w.get("endOffset") or w.get("end_offset")
                            if start and end and transcribe_config.get("word_timestamp"):
                                word_strs.append(f"({start}->{end}) {word_text}")
                            else:
                                word_strs.append(word_text)
                        segment_text = " ".join(word_strs)
                        if speaker:
                            segment_text = f"[{speaker}] {segment_text}"
                        if segment_text:
                            text_parts.append(segment_text)

            transcript = "\n".join(text_parts) if text_parts else ""

            if not transcript.strip():
                # Check for blocked/safety
                finish_reason = candidates[0].get("finishReason", "")
                if finish_reason in ("SAFETY", "BLOCKED"):
                    return None, f"Transcription blocked: {finish_reason}"

                if provider.should_retry(RetryReason.EMPTY_RESPONSE, retry_count):
                    delay = provider.get_retry_delay(RetryReason.EMPTY_RESPONSE)
                    provider.log_retry(RetryReason.EMPTY_RESPONSE, retry_count + 1, delay, "empty transcript")
                    if delay > 0:
                        time.sleep(delay)
                    return generate_transcription(provider, file_uri, mime_type, transcribe_config, retry_count + 1)
                return None, "Empty transcription response"

        except (KeyError, IndexError) as e:
            return None, f"Failed to parse transcription response: {e}"

        usage_meta = data.get("usageMetadata", {})
        prompt_tokens = usage_meta.get("promptTokenCount", 0)
        total_tokens = usage_meta.get("totalTokenCount", 0)

        provider.log(
            "info",
            f"[Transcribe] Success: {len(transcript)} chars, "
            f"{prompt_tokens} prompt tokens, {total_tokens} total tokens",
        )

        return transcript, None

    except requests.exceptions.Timeout:
        provider.log_error(f"[Transcribe] Request timeout after {timeout}s")

        if provider.should_retry(RetryReason.NETWORK_ERROR, retry_count):
            delay = provider.get_retry_delay(RetryReason.NETWORK_ERROR)
            provider.log_retry(RetryReason.NETWORK_ERROR, retry_count + 1, delay, f"timeout after {timeout}s")
            provider.rotate_key_if_possible("(timeout)")
            if delay > 0:
                time.sleep(delay)
            return generate_transcription(provider, file_uri, mime_type, transcribe_config, retry_count + 1)
        return None, f"Transcription timeout after {timeout}s"

    except requests.exceptions.RequestException as e:
        error_msg = str(e)
        provider.log_error(f"[Transcribe] Network error: {error_msg}")

        if provider.should_retry(RetryReason.NETWORK_ERROR, retry_count):
            delay = provider.get_retry_delay(RetryReason.NETWORK_ERROR)
            provider.log_retry(RetryReason.NETWORK_ERROR, retry_count + 1, delay, error_msg[:100])
            provider.rotate_key_if_possible("(network error)")
            if delay > 0:
                time.sleep(delay)
            return generate_transcription(provider, file_uri, mime_type, transcribe_config, retry_count + 1)
        return None, f"Transcription network error: {error_msg}"

    except Exception as e:
        error_msg = str(e)
        provider.log_error(f"[Transcribe] Unexpected error: {error_msg}")
        return None, f"Transcription unexpected error: {error_msg}"
