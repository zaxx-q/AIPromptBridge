"""
Native Gemini API Provider

Uses the native Gemini API format (camelCase) with full feature support:
- thinkingConfig with thinkingBudget (Gemini 2.5) or thinkingLevel (Gemini 3)
- Safety settings with BLOCK_NONE
- Streaming via streamGenerateContent endpoint
- Full retry logic matching reverse-proxy behavior via BaseProvider
- Files API, Batch API, and TTS API delegated to gemini_services.py
"""

import json
import re
import time
from pathlib import Path
from typing import List, Dict, Optional, Any, Tuple
import requests

from .base import (
    BaseProvider,
    ProviderResult,
    StreamCallback,
    UsageData,
    CallbackType,
    RetryReason,
    estimate_tokens,
    estimate_message_tokens,
)
import src.providers.gemini_services as gemini_services


# Base URL for Gemini API
GEMINI_BASE_URL = "https://generativelanguage.googleapis.com/v1beta"

# Safety settings
SAFETY_SETTINGS = [
    {"category": "HARM_CATEGORY_HATE_SPEECH", "threshold": "BLOCK_NONE"},
    {"category": "HARM_CATEGORY_DANGEROUS_CONTENT", "threshold": "BLOCK_NONE"},
    {"category": "HARM_CATEGORY_SEXUALLY_EXPLICIT", "threshold": "BLOCK_NONE"},
    {"category": "HARM_CATEGORY_HARASSMENT", "threshold": "BLOCK_NONE"},
]

# Maximum size for inline data (15 MB to be safe, actual limit is 20 MB for total request)
MAX_INLINE_SIZE_BYTES = 15 * 1024 * 1024


class GeminiNativeProvider(BaseProvider):
    """
    Provider for native Gemini API.

    Features:
    - Native Gemini format (camelCase)
    - thinkingConfig with budget (2.5) or level (3.x)
    - Streaming with retry logic via BaseProvider
    - Files API, Batch API, and TTS API delegated to gemini_services.py
    """

    def __init__(
        self,
        key_manager=None,
        config: Optional[Dict] = None,
        base_url: Optional[str] = None,
    ):
        """
        Initialize the Gemini Native provider.
        """
        super().__init__("Gemini-Native", key_manager, config)

        self.base_url = (
            base_url
            or self.config.get("base_url")
            or self.config.get("gemini_endpoint")
        )
        if not self.base_url:
            self.base_url = GEMINI_BASE_URL

        self._uploaded_files: Dict[
            str, gemini_services.UploadedFile
        ] = {}  # Cache of uploaded files

    # =========================================================================
    # DELEGATED GOOGLE SERVICES (Files, Batch, and TTS APIs)
    # =========================================================================

    def upload_file(
        self, filepath: Path, display_name: Optional[str] = None
    ) -> Tuple[Optional[gemini_services.UploadedFile], Optional[str]]:
        return gemini_services.upload_file(self, filepath, display_name)

    def get_file_info(self, file_name: str) -> Tuple[Optional[Dict], Optional[str]]:
        return gemini_services.get_file_info(self, file_name)

    def delete_file(self, file_name: str) -> Tuple[bool, Optional[str]]:
        return gemini_services.delete_file(self, file_name)

    def list_files(
        self, page_size: int = 100
    ) -> Tuple[Optional[List[Dict]], Optional[str]]:
        return gemini_services.list_files(self, page_size)

    @staticmethod
    def should_use_files_api(filepath: Path) -> bool:
        """Check if a file should be uploaded via Files API (>15 MB)"""
        try:
            return filepath.stat().st_size > MAX_INLINE_SIZE_BYTES
        except Exception:
            return False

    def create_batch(
        self,
        messages: List[Dict],
        model: str,
        params: Dict,
        display_name: Optional[str] = None,
    ) -> Tuple[Optional[Dict], Optional[str]]:
        return gemini_services.create_batch(self, messages, model, params, display_name)

    def get_batch(self, batch_name: str) -> Tuple[Optional[Dict], Optional[str]]:
        return gemini_services.get_batch(self, batch_name)

    def list_batches(
        self, page_size: int = 50
    ) -> Tuple[Optional[List[Dict]], Optional[str]]:
        return gemini_services.list_batches(self, page_size)

    def cancel_batch(self, batch_name: str) -> Tuple[bool, Optional[str]]:
        return gemini_services.cancel_batch(self, batch_name)

    def generate_tts(
        self,
        text: str,
        model: str,
        voice_name: str,
        multi_speaker_config: Optional[List[Dict]] = None,
        retry_count: int = 0,
    ) -> Tuple[Optional[bytes], Optional[str]]:
        return gemini_services.generate_tts(
            self, text, model, voice_name, multi_speaker_config, retry_count
        )

    # =========================================================================
    # CORE GENERATION PIPELINE (TEMPLATE METHOD IMPLEMENTATIONS)
    # =========================================================================

    def _do_generate_stream(
        self,
        messages: List[Dict],
        model: str,
        params: Dict,
        callback: StreamCallback,
        thinking_enabled: bool,
        api_key: str,
        abort_event: Optional[Any],
    ) -> ProviderResult:
        timeout = self.config.get("request_timeout", 120)
        url = self._get_url(model, streaming=True)
        headers = {"Content-Type": "application/json", "x-goog-api-key": api_key}
        body = self._build_request_body(messages, model, params, thinking_enabled)

        # Accumulators
        accumulated_content = ""
        accumulated_thinking = ""
        accumulated_tool_calls = []
        usage_data = None
        last_signature = None

        response = requests.post(
            url, headers=headers, json=body, timeout=timeout, stream=True
        )

        # Handle error responses
        if response.status_code != 200:
            error_text = response.text
            return ProviderResult(
                success=False, error=error_text, status_code=response.status_code
            )

        # Process streaming response
        response.encoding = "utf-8"

        last_content_time = (
            time.time()
        )  # Track last meaningful content for idle timeout
        for line in response.iter_lines(decode_unicode=True):
            self._check_abort(abort_event)

            # Content-idle timeout: detect hangs masked by SSE heartbeats
            if time.time() - last_content_time > timeout:
                response.close()
                raise requests.exceptions.Timeout(
                    f"No content received for {timeout}s (content-idle timeout)"
                )

            if not line:
                continue

            if not line.startswith("data: "):
                continue

            try:
                data = json.loads(line[6:])

                # Check for error object in SSE stream (e.g., 503 overloaded)
                if "error" in data:
                    error_obj = data["error"]
                    if isinstance(error_obj, dict):
                        error_code = error_obj.get("code", 0)
                        error_status = error_obj.get("status", "")
                        error_message = error_obj.get("message", str(error_obj))
                        prefix = (
                            f"{error_code} {error_status}"
                            if error_status
                            else str(error_code)
                            if error_code
                            else ""
                        )
                        error_text = (
                            f"{prefix}: {error_message}" if prefix else error_message
                        )
                    else:
                        error_text = str(error_obj)
                    return ProviderResult(success=False, error=error_text)

                candidate = data.get("candidates", [{}])[0]
                content_parts = candidate.get("content", {}).get("parts", [])

                for part in content_parts:
                    # Capture thought signature if present
                    sig = part.get("thoughtSignature") or part.get("thought_signature")
                    if sig:
                        last_signature = sig

                    # Handle thinking content (thought: true)
                    if part.get("thought") is True and part.get("text"):
                        thinking_text = part["text"]
                        accumulated_thinking += thinking_text
                        callback(CallbackType.THINKING, thinking_text)
                        last_content_time = time.time()

                    # Handle regular text
                    elif "text" in part and not part.get("thought"):
                        text = part["text"]
                        accumulated_content += text
                        callback(CallbackType.TEXT, text)
                        last_content_time = time.time()

                    # Handle function calls
                    elif "functionCall" in part:
                        fc = part["functionCall"]
                        tool_call = {
                            "id": fc.get("id", f"call_{len(accumulated_tool_calls)}"),
                            "type": "function",
                            "function": {
                                "name": fc.get("name", ""),
                                "arguments": json.dumps(fc.get("args", {})),
                            },
                        }
                        accumulated_tool_calls.append(tool_call)
                        callback(CallbackType.TOOL_CALLS, [tool_call])
                        last_content_time = time.time()

                # Check for blocked finish reasons (SAFETY, RECITATION, etc.)
                if isinstance(candidate, dict):
                    finish_reason = candidate.get("finishReason")
                    if finish_reason in (
                        "SAFETY",
                        "RECITATION",
                        "BLOCKED",
                        "PROHIBITED",
                    ):
                        if (
                            not accumulated_content.strip()
                            and not accumulated_tool_calls
                        ):
                            block_msg = f"Response blocked: {finish_reason}"
                            return ProviderResult(success=False, error=block_msg)

                # Capture usage metadata
                if "usageMetadata" in data:
                    usage = data["usageMetadata"]
                    usage_data = UsageData(
                        prompt_tokens=usage.get("promptTokenCount", 0),
                        completion_tokens=usage.get("candidatesTokenCount", 0),
                        total_tokens=usage.get("totalTokenCount", 0),
                    )
                    callback(CallbackType.USAGE, usage_data.to_dict())

            except json.JSONDecodeError:
                continue

        # Reconstruct Gemini native parts for storage/preservation
        gemini_parts = []
        if accumulated_thinking:
            gemini_parts.append({"text": accumulated_thinking, "thought": True})

        if accumulated_tool_calls:
            for idx, tc in enumerate(accumulated_tool_calls):
                fc_part = {
                    "functionCall": {
                        "name": tc["function"]["name"],
                        "args": json.loads(tc["function"]["arguments"])
                        if isinstance(tc["function"]["arguments"], str)
                        else tc["function"]["arguments"],
                    }
                }
                if idx == 0 and last_signature:
                    fc_part["thoughtSignature"] = last_signature
                gemini_parts.append(fc_part)

        if accumulated_content:
            text_part = {"text": accumulated_content}
            if not accumulated_tool_calls and last_signature:
                text_part["thoughtSignature"] = last_signature
            gemini_parts.append(text_part)

        callback(CallbackType.RESPONSE_PARTS, gemini_parts)
        callback(CallbackType.DONE, None)

        # Check for empty response
        output_tokens = usage_data.completion_tokens if usage_data else 0

        if self.detect_empty_response(
            accumulated_content,
            accumulated_thinking,
            accumulated_tool_calls,
            output_tokens,
        ):
            thinking_note = (
                f", thinking: {len(accumulated_thinking)} chars"
                if accumulated_thinking
                else ""
            )
            self.log("warn", f"Empty response detected (no content{thinking_note})")
            return ProviderResult(
                success=False, error="Empty response (0 output tokens, no content)"
            )

        # Estimate usage if not provided
        if not usage_data:
            input_tokens = estimate_message_tokens(messages)
            output_tokens = estimate_tokens(accumulated_content + accumulated_thinking)
            usage_data = UsageData(
                prompt_tokens=input_tokens,
                completion_tokens=output_tokens,
                total_tokens=input_tokens + output_tokens,
                estimated=True,
            )
            callback(CallbackType.USAGE, usage_data.to_dict())

        return ProviderResult(
            success=True,
            content=accumulated_content,
            thinking_content=accumulated_thinking,
            tool_calls=accumulated_tool_calls,
            usage=usage_data,
            gemini_parts=gemini_parts,
        )

    def _do_generate(
        self,
        messages: List[Dict],
        model: str,
        params: Dict,
        thinking_enabled: bool,
        api_key: str,
        abort_event: Optional[Any],
    ) -> ProviderResult:
        timeout = self.config.get("request_timeout", 120)
        url = self._get_url(model, streaming=False)
        headers = {"Content-Type": "application/json", "x-goog-api-key": api_key}
        body = self._build_request_body(messages, model, params, thinking_enabled)

        self._check_abort(abort_event)
        response = requests.post(url, headers=headers, json=body, timeout=timeout)
        self._check_abort(abort_event)

        # Handle error responses
        if response.status_code != 200:
            error_text = response.text
            return ProviderResult(
                success=False, error=error_text, status_code=response.status_code
            )

        # Parse response
        data = response.json()
        candidate = data.get("candidates", [{}])[0]

        # Check for error object in response body
        if "error" in data:
            error_obj = data["error"]
            if isinstance(error_obj, dict):
                error_code = error_obj.get("code", 0)
                error_status = error_obj.get("status", "")
                error_message = error_obj.get("message", str(error_obj))
                prefix = (
                    f"{error_code} {error_status}"
                    if error_status
                    else str(error_code)
                    if error_code
                    else ""
                )
                error_text = f"{prefix}: {error_message}" if prefix else error_message
            else:
                error_text = str(error_obj)
            return ProviderResult(success=False, error=error_text)

        # Check for blocked finish reasons
        if isinstance(candidate, dict):
            finish_reason = candidate.get("finishReason")
            if finish_reason in ("SAFETY", "RECITATION", "BLOCKED", "PROHIBITED"):
                content_parts_check = candidate.get("content", {}).get("parts", [])
                has_content = any(
                    "text" in p and not p.get("thought")
                    for p in content_parts_check
                    if isinstance(p, dict)
                )
                if not has_content:
                    block_msg = f"Response blocked: {finish_reason}"
                    return ProviderResult(success=False, error=block_msg)

        content_parts = candidate.get("content", {}).get("parts", [])

        accumulated_content = ""
        accumulated_thinking = ""
        tool_calls = []

        for part in content_parts:
            if part.get("thought") is True and part.get("text"):
                accumulated_thinking += part["text"]
            elif "text" in part and not part.get("thought"):
                accumulated_content += part["text"]
            elif "functionCall" in part:
                fc = part["functionCall"]
                tool_calls.append(
                    {
                        "id": fc.get("id", f"call_{len(tool_calls)}"),
                        "type": "function",
                        "function": {
                            "name": fc.get("name", ""),
                            "arguments": json.dumps(fc.get("args", {})),
                        },
                    }
                )

        # Parse usage
        usage_meta = data.get("usageMetadata", {})
        usage_data = UsageData(
            prompt_tokens=usage_meta.get("promptTokenCount", 0),
            completion_tokens=usage_meta.get("candidatesTokenCount", 0),
            total_tokens=usage_meta.get("totalTokenCount", 0),
        )

        # Check for empty response
        if self.detect_empty_response(
            accumulated_content,
            accumulated_thinking,
            tool_calls,
            usage_data.completion_tokens,
        ):
            thinking_note = (
                f", thinking: {len(accumulated_thinking)} chars"
                if accumulated_thinking
                else ""
            )
            self.log("warn", f"Empty response detected (no content{thinking_note})")
            return ProviderResult(
                success=False, error="Empty response (0 output tokens, no content)"
            )

        # Normalize keys in content_parts for consistency
        normalized_parts = []
        for part in content_parts:
            part_copy = dict(part)
            if "thought_signature" in part_copy and "thoughtSignature" not in part_copy:
                part_copy["thoughtSignature"] = part_copy.pop("thought_signature")
            normalized_parts.append(part_copy)

        return ProviderResult(
            success=True,
            content=accumulated_content,
            thinking_content=accumulated_thinking,
            tool_calls=tool_calls,
            usage=usage_data,
            gemini_parts=normalized_parts,
        )

    # =========================================================================
    # HELPERS
    # =========================================================================

    def get_retry_reason(self, status_code: int, error_text: str = "") -> RetryReason:
        """
        Override to handle Google's specific 400 error for invalid keys.
        """
        if status_code == 400:
            if "API_KEY_INVALID" in error_text or "API key not valid" in error_text:
                return RetryReason.AUTH_ERROR
        return super().get_retry_reason(status_code, error_text)

    def detect_empty_response(
        self, content: str, thinking: str, tool_calls: List, output_tokens: int
    ) -> bool:
        """
        Detect an empty response.
        Overridden for Gemini to treat "Thinking only" responses as empty/failed.
        """
        has_actual_content = bool(content.strip() or tool_calls)
        return not has_actual_content

    def _is_gemini_3(self, model: str) -> bool:
        """Check if model is Gemini 3.x"""
        lower = model.lower()
        return "gemini" in lower and "3" in lower

    def _is_gemini_25(self, model: str) -> bool:
        """Check if model is Gemini 2.5"""
        lower = model.lower()
        return "gemini" in lower and "2.5" in lower

    def _is_legacy_gemma(self, model: str) -> bool:
        """Check if model is a legacy Gemma (1/2/3) that lacks systemInstruction support."""
        lower = model.lower()
        if "gemma" not in lower:
            return False
        return bool(re.search(r"gemma[-_]?[123](?:[^0-9]|$)", lower))

    def _get_url(self, model: str, streaming: bool) -> str:
        """Build the API URL"""
        if streaming:
            return f"{self.base_url}/models/{model}:streamGenerateContent?alt=sse"
        else:
            return f"{self.base_url}/models/{model}:generateContent"

    def _convert_messages_to_contents(
        self, messages: List[Dict], prepend_system_to_user: bool = False
    ) -> tuple[List[Dict], Optional[str]]:
        """Convert OpenAI-format messages to Gemini native format."""
        contents = []
        system_instruction = None
        pending_system_text = None

        for message in messages:
            role = message.get("role", "user")
            content = message.get("content", "")

            # Handle system message
            if role == "system":
                system_text = self._extract_text_content(content)
                if prepend_system_to_user:
                    pending_system_text = system_text
                else:
                    system_instruction = system_text
                continue

            gemini_role = "model" if role == "assistant" else "user"
            if "gemini_parts" in message:
                parts = message["gemini_parts"]
            else:
                parts = self._convert_content_to_parts(content)

            if pending_system_text and gemini_role == "user" and parts:
                system_parts = [{"text": pending_system_text + "\n\n"}]
                parts = system_parts + parts
                pending_system_text = None  # Only prepend once

            if parts:
                contents.append({"role": gemini_role, "parts": parts})

        return contents, system_instruction

    def _extract_text_content(self, content: Any) -> str:
        """Extract text from content"""
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            texts = []
            for item in content:
                if item.get("type") == "text":
                    texts.append(item.get("text", ""))
            return " ".join(texts)
        return ""

    def _convert_content_to_parts(self, content: Any) -> List[Dict]:
        """Convert OpenAI content format to Gemini parts"""
        if isinstance(content, str):
            return [{"text": content}]

        if isinstance(content, list):
            all_parts = []
            media_count = 0

            for item in content:
                part = None
                is_media = False

                if item.get("type") == "text":
                    part = {"text": item.get("text", "")}
                elif item.get("type") == "image_url":
                    image_url = item.get("image_url", {}).get("url", "")
                    match = re.match(r"data:([^;]+);base64,(.+)", image_url)
                    if match:
                        mime_type, b64_data = match.groups()
                        part = {
                            "inline_data": {"mime_type": mime_type, "data": b64_data}
                        }
                        is_media = True
                elif item.get("type") == "inline_data":
                    inline = item.get("inline_data", {})
                    part = {
                        "inline_data": {
                            "mime_type": inline.get("mime_type", ""),
                            "data": inline.get("data", ""),
                        }
                    }
                    is_media = True
                elif item.get("type") == "file":
                    file_obj = item.get("file", {})
                    url = file_obj.get("url", "") or item.get("url", "")
                    match = re.match(r"data:([^;]+);base64,(.+)", url)
                    if match:
                        mime_type, b64_data = match.groups()
                        part = {
                            "inline_data": {"mime_type": mime_type, "data": b64_data}
                        }
                        is_media = True
                elif item.get("type") == "file_data":
                    file_data = item.get("file_data", {})
                    part = {
                        "fileData": {
                            "mimeType": file_data.get("mime_type", ""),
                            "fileUri": file_data.get("file_uri", ""),
                        }
                    }
                    is_media = True

                if part:
                    all_parts.append(part)
                    if is_media:
                        media_count += 1

            # Gemini Native Reordering Logic: Media First
            if media_count == 1:
                media_parts = [p for p in all_parts if "text" not in p]
                text_parts = [p for p in all_parts if "text" in p]
                return media_parts + text_parts

            return all_parts

        return [{"text": str(content)}]

    def _build_generation_config(
        self, params: Dict, thinking_enabled: bool, model: str
    ) -> Dict:
        """Build generationConfig with thinking settings."""
        config = {
            "temperature": params.get("temperature", 1.0),
            "topP": params.get("top_p", 0.95),
        }

        if "max_tokens" in params and params["max_tokens"] is not None:
            config["maxOutputTokens"] = params["max_tokens"]

        if thinking_enabled:
            if self._is_gemini_3(model):
                level = self.config.get("thinking_level", "high")
                config["thinkingConfig"] = {
                    "thinkingLevel": level,
                    "includeThoughts": True,
                }
            else:
                budget = self.config.get("thinking_budget", -1)
                config["thinkingConfig"] = {
                    "thinkingBudget": budget,
                    "includeThoughts": True,
                }

        return config

    def _build_request_body(
        self, messages: List[Dict], model: str, params: Dict, thinking_enabled: bool
    ) -> Dict:
        """Build the full request body"""
        is_old_gemma = self._is_legacy_gemma(model)

        contents, system_instruction = self._convert_messages_to_contents(
            messages, prepend_system_to_user=is_old_gemma
        )

        body = {
            "contents": contents,
            "generationConfig": self._build_generation_config(
                params, thinking_enabled, model
            ),
            "safetySettings": SAFETY_SETTINGS,
        }

        if system_instruction and not is_old_gemma:
            body["systemInstruction"] = {"parts": [{"text": system_instruction}]}

        return body

    def fetch_models(self) -> tuple[List[Dict], Optional[str]]:
        """Fetch available models from Gemini API with full metadata."""
        if not self.key_manager or not self.key_manager.has_keys():
            return None, "No API keys configured for Gemini"

        current_key = self.key_manager.get_current_key()
        if not current_key:
            return None, "No API key available"

        url = f"{self.base_url}/models?pageSize=1000"
        headers = {"x-goog-api-key": current_key}

        try:
            response = requests.get(url, headers=headers, timeout=30)
            if response.status_code != 200:
                return (
                    None,
                    f"Failed to fetch models ({response.status_code}): {response.text[:200]}",
                )

            data = response.json()
            if "models" in data and isinstance(data["models"], list):
                models = []
                for model in data["models"]:
                    model_name = model.get("name", "")
                    model_id = (
                        model_name.replace("models/", "")
                        if model_name.startswith("models/")
                        else model_name
                    )
                    display_name = model.get("displayName", model_id)

                    supported_methods = model.get("supportedGenerationMethods", [])
                    if "generateContent" in supported_methods:
                        models.append(
                            {
                                "id": model_id,
                                "name": display_name,
                                "context_length": model.get("inputTokenLimit"),
                                "input_token_limit": model.get("inputTokenLimit"),
                                "output_token_limit": model.get("outputTokenLimit"),
                                "thinking": model.get("thinking", False),
                                "description": model.get("description", ""),
                                "version": model.get("version", ""),
                                "supported_methods": supported_methods,
                                "temperature": model.get("temperature"),
                                "top_p": model.get("topP"),
                                "top_k": model.get("topK"),
                                "max_temperature": model.get("maxTemperature"),
                                "_raw": model,
                            }
                        )
                return models, None
            return None, "Unknown models response format"
        except requests.exceptions.RequestException as e:
            return None, f"Request failed: {e}"
        except Exception as e:
            return None, f"Error fetching models: {e}"
