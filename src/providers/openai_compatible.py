"""
OpenAI-Compatible Provider

Supports:
- Custom OpenAI-compatible APIs
- OpenRouter
- Google's OpenAI-compatible endpoint (with extra_body.google for safety/thinking)
"""

import json
import re
import time
from typing import Any, Dict, List, Optional

import requests

from .base import (
    BaseProvider,
    CallbackType,
    ProviderResult,
    RetryReason,
    StreamCallback,
    UsageData,
    estimate_message_tokens,
    estimate_tokens,
)

# Safety settings for Google's OpenAI-compatible endpoint
# Must use BLOCK_NONE (not OFF)
GOOGLE_SAFETY_SETTINGS = [
    {"category": "HARM_CATEGORY_HATE_SPEECH", "threshold": "BLOCK_NONE"},
    {"category": "HARM_CATEGORY_DANGEROUS_CONTENT", "threshold": "BLOCK_NONE"},
    {"category": "HARM_CATEGORY_SEXUALLY_EXPLICIT", "threshold": "BLOCK_NONE"},
    {"category": "HARM_CATEGORY_HARASSMENT", "threshold": "BLOCK_NONE"},
]


class OpenAICompatibleProvider(BaseProvider):
    """
    Provider for OpenAI-compatible APIs.
    
    Handles:
    - Custom endpoints (any OpenAI-compatible API)
    - OpenRouter (openrouter.ai)
    - Google's OpenAI-compatible endpoint (generativelanguage.googleapis.com/v1beta/openai)
    
    Features:
    - Streaming with retry logic via BaseProvider
    - Empty response detection and retry via BaseProvider
    - Thinking/reasoning support via reasoning_effort and extra_body.google
    - Key rotation on errors via BaseProvider
    """

    # Known endpoint types
    ENDPOINT_CUSTOM = "custom"
    ENDPOINT_OPENROUTER = "openrouter"
    ENDPOINT_GOOGLE = "google"

    def __init__(
        self,
        endpoint_type: str,
        base_url: str,
        key_manager=None,
        config: Optional[Dict] = None
    ):
        """
        Initialize the OpenAI-compatible provider.
        """
        super().__init__(f"OpenAI-Compat/{endpoint_type}", key_manager, config)
        self.endpoint_type = endpoint_type
        self.base_url = self._normalize_url(base_url)

    def _normalize_url(self, url: str) -> str:
        """Normalize the base URL - strip trailing slash and /chat/completions"""
        if not url:
            return ""
        url = url.strip().rstrip("/")
        if url.endswith("/chat/completions"):
            url = url[:-17]
        return url

    def _get_completions_url(self) -> str:
        """Get the full chat completions URL"""
        return f"{self.base_url}/chat/completions"

    def _get_models_url(self) -> str:
        """Get the models endpoint URL"""
        return f"{self.base_url}/models"

    def _is_google_endpoint(self) -> bool:
        """
        Check if this is a Google endpoint (needs extra_body).
        """
        if self.endpoint_type == self.ENDPOINT_GOOGLE:
            return True

        url_lower = self.base_url.lower()
        return "googleapis.com" in url_lower or "google" in url_lower

    def _get_headers(self, api_key: str) -> Dict[str, str]:
        """Get request headers"""
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json"
        }

        if self.endpoint_type == self.ENDPOINT_OPENROUTER:
            headers["HTTP-Referer"] = "https://github.com/zaxx-q/AIPromptBridge"
            headers["X-Title"] = "AIPromptBridge"

        return headers

    def _is_openrouter_endpoint(self) -> bool:
        """
        Check if this is an OpenRouter endpoint.
        """
        if self.endpoint_type == self.ENDPOINT_OPENROUTER:
            return True

        url_lower = self.base_url.lower()
        return "openrouter.ai" in url_lower or "openrouter" in url_lower

    def _reorder_content_for_provider(self, content: List[Dict]) -> List[Dict]:
        if not self._is_openrouter_endpoint():
            return content

        media_count = 0
        for item in content:
            item_type = item.get("type", "")
            if item_type != "text":
                media_count += 1

        # OpenRouter Logic:
        # If exactly ONE media item, move it to the end (Text First).
        if media_count == 1:
            text_items = []
            media_items = []

            for item in content:
                item_type = item.get("type", "")
                if item_type == "text":
                    text_items.append(item)
                else:
                    media_items.append(item)

            return text_items + media_items

        return content

    def _process_messages(self, messages: List[Dict]) -> List[Dict]:
        """
        Process messages to handle specific content types like audio and files.
        """
        processed = []

        for msg in messages:
            content = msg.get("content")

            if not isinstance(content, list):
                processed.append(msg)
                continue

            new_content = []
            for item in content:
                item_type = item.get("type")

                if item_type == "input_audio" or item_type == "audio":
                    audio_data = None
                    audio_format = "wav"

                    if "input_audio" in item:
                        new_content.append(item)
                        continue

                    data_url = item.get("image_url", {}).get("url") or item.get("url") or item.get("data")
                    if data_url and isinstance(data_url, str) and data_url.startswith("data:"):
                        match = re.match(r"data:audio/([^;]+);base64,(.+)", data_url)
                        if match:
                            fmt, b64 = match.groups()
                            audio_format = fmt
                            audio_data = b64

                    if audio_data:
                        new_content.append({
                            "type": "input_audio",
                            "input_audio": {
                                "data": audio_data,
                                "format": audio_format
                            }
                        })
                    else:
                        new_content.append(item)

                elif item_type == "file":
                    file_info = item.get("file", {})

                    if not file_info and "url" in item:
                        new_content.append({
                            "type": "file",
                            "file": {
                                "url": item["url"]
                            }
                        })
                    elif not file_info and "data" in item:
                        new_content.append({
                            "type": "file",
                            "file": {
                                "file_data": item["data"]
                            }
                        })
                    else:
                        new_content.append(item)

                elif item_type == "inline_data":
                    inline = item.get("inline_data", {})
                    mime_type = inline.get("mime_type", "")

                    if mime_type.startswith("audio/"):
                        audio_format = mime_type.split("/")[-1]
                        mime_to_format = {
                            "mpeg": "mp3",
                            "x-wav": "wav",
                            "mp4": "m4a",
                            "x-m4a": "m4a",
                            "x-ms-wma": "wma",
                        }
                        audio_format = mime_to_format.get(audio_format, audio_format)

                        new_content.append({
                            "type": "input_audio",
                            "input_audio": {
                                "data": inline.get("data", ""),
                                "format": audio_format
                            }
                        })

                    elif mime_type.startswith("image/"):
                        data_url = f"data:{mime_type};base64,{inline.get('data', '')}"
                        new_content.append({
                            "type": "image_url",
                            "image_url": {
                                "url": data_url
                            }
                        })

                    elif mime_type.startswith("text/") or mime_type in (
                        "application/json", "application/xml", "application/javascript",
                        "application/x-python-code", "application/x-sh"
                    ):
                        try:
                            import base64
                            text_content = base64.b64decode(inline.get("data", "")).decode("utf-8")
                            new_content.append({
                                "type": "text",
                                "text": f"\n\n[File Content: {mime_type}]\n{text_content}"
                            })
                        except Exception:
                            new_content.append(item)

                    elif mime_type == "application/pdf":
                        b64_data = inline.get("data", "")
                        filename = item.get("filename", "document.pdf")

                        if self._is_openrouter_endpoint():
                            data_url = f"data:application/pdf;base64,{b64_data}"
                            new_content.append({
                                "type": "file",
                                "file": {
                                    "filename": filename,
                                    "file_data": data_url
                                }
                            })
                        else:
                            data_url = f"data:application/pdf;base64,{b64_data}"
                            new_content.append({
                                "type": "image_url",
                                "image_url": {
                                    "url": data_url
                                }
                            })

                    else:
                        new_content.append(item)

                else:
                    new_content.append(item)

            new_content = self._reorder_content_for_provider(new_content)

            new_msg = msg.copy()
            new_msg["content"] = new_content
            processed.append(new_msg)

        return processed

    def _build_request_body(
        self,
        messages: List[Dict],
        model: str,
        params: Dict,
        thinking_enabled: bool,
        streaming: bool
    ) -> Dict:
        """Build the request body with proper thinking/safety configuration."""
        body = {
            "model": model,
            "messages": self._process_messages(messages)
        }

        if streaming:
            body["stream"] = True
            body["stream_options"] = {"include_usage": True}
        else:
            body["stream"] = False

        for key, value in params.items():
            if key not in ("stream", "stream_options") and value is not None:
                body[key] = value

        if thinking_enabled:
            reasoning_effort = self.config.get("reasoning_effort", "high")
            body["reasoning_effort"] = reasoning_effort

            if self._is_google_endpoint():
                body["extra_body"] = {
                    "google": {
                        "thinking_config": {
                            "include_thoughts": True
                        },
                        "safety_settings": GOOGLE_SAFETY_SETTINGS
                    }
                }
        elif self._is_google_endpoint():
            body["extra_body"] = {
                "google": {
                    "safety_settings": GOOGLE_SAFETY_SETTINGS
                }
            }

        return body

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
        abort_event: Optional[Any]
    ) -> ProviderResult:
        timeout = self.config.get("request_timeout", 120)
        url = self._get_completions_url()
        headers = self._get_headers(api_key)
        body = self._build_request_body(messages, model, params, thinking_enabled, streaming=True)

        # Accumulators for content
        accumulated_content = ""
        accumulated_thinking = ""
        accumulated_tool_calls = []
        usage_data = None

        response = requests.post(
            url,
            headers=headers,
            json=body,
            timeout=timeout,
            stream=True
        )

        # Handle error responses
        if response.status_code != 200:
            error_text = response.text
            return ProviderResult(
                success=False,
                error=error_text,
                status_code=response.status_code
            )

        # Process streaming response
        response.encoding = 'utf-8'

        chunk_count = 0
        last_content_time = time.time()  # Track last meaningful content for idle timeout
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

            line = line.strip()

            if line == "data: [DONE]":
                callback(CallbackType.DONE, None)
                break

            # Ignore SSE comments/keep-alive heartbeats (lines starting with :)
            if line.startswith(":"):
                continue

            if not line.startswith("data: "):
                if line:
                    self.log("debug", f"Unexpected line format: {line[:100]}")
                continue

            try:
                json_str = line[6:]
                data = json.loads(json_str)
                chunk_count += 1

                # Check for error object in SSE stream
                if "error" in data:
                    error_obj = data["error"]
                    if isinstance(error_obj, dict):
                        error_code = error_obj.get("code", 0)
                        error_type = error_obj.get("type", "")
                        error_message = error_obj.get("message", str(error_obj))
                        prefix = f"{error_code} {error_type}" if error_type else str(error_code) if error_code else ""
                        error_text = f"{prefix}: {error_message}" if prefix else error_message
                    else:
                        error_text = str(error_obj)
                    return ProviderResult(
                        success=False,
                        error=error_text
                    )

                choices = data.get("choices", [])
                if choices:
                    choice = choices[0]

                    if choice is None or not isinstance(choice, dict):
                        continue

                    delta = choice.get("delta")
                    if delta is None:
                        delta = {}
                    if not isinstance(delta, dict):
                        continue

                    # Handle regular content
                    content = delta.get("content", "")
                    if content:
                        accumulated_content += content
                        callback(CallbackType.TEXT, content)
                        last_content_time = time.time()

                    # Handle reasoning_content (DeepSeek/thinking style)
                    reasoning = delta.get("reasoning_content", "")
                    if reasoning:
                        accumulated_thinking += reasoning
                        callback(CallbackType.THINKING, reasoning)
                        last_content_time = time.time()

                    # Also check for "reasoning" field
                    reasoning_alt = delta.get("reasoning", "")
                    if reasoning_alt:
                        accumulated_thinking += reasoning_alt
                        callback(CallbackType.THINKING, reasoning_alt)
                        last_content_time = time.time()

                    # Handle tool calls
                    tool_calls = delta.get("tool_calls")
                    if tool_calls:
                        accumulated_tool_calls.extend(tool_calls)
                        callback(CallbackType.TOOL_CALLS, tool_calls)
                        last_content_time = time.time()

                    # Check for blocked finish reasons
                    finish_reason = choice.get("finish_reason")
                    if finish_reason in ("content_filter", "blocked"):
                        if not accumulated_content.strip() and not accumulated_tool_calls:
                            block_msg = f"Response blocked: {finish_reason}"
                            callback(CallbackType.ERROR, block_msg)
                            return ProviderResult(
                                success=False,
                                error=block_msg
                            )

                if "usage" in data:
                    usage = data["usage"]
                    if usage and isinstance(usage, dict):
                        usage_data = UsageData(
                            prompt_tokens=usage.get("prompt_tokens", 0),
                            completion_tokens=usage.get("completion_tokens", 0),
                            total_tokens=usage.get("total_tokens", 0)
                        )
                        callback(CallbackType.USAGE, usage_data.to_dict())

            except json.JSONDecodeError as e:
                self.log("warn", f"Chunk {chunk_count}: JSON decode error: {e}, raw: {line[:200]}")
                continue

        # Extract inline thinking if native reasoning is empty
        if not accumulated_thinking and accumulated_content:
            from .inline_thinking import extract_leading_thinking_blocks
            extracted = extract_leading_thinking_blocks(accumulated_content)
            if extracted.stripped:
                accumulated_content = extracted.content
                accumulated_thinking = extracted.thinking

        # Check for empty response
        output_tokens = usage_data.completion_tokens if usage_data else 0
        if self.detect_empty_response(
            accumulated_content,
            accumulated_thinking,
            accumulated_tool_calls,
            output_tokens
        ):
            thinking_note = f", thinking: {len(accumulated_thinking)} chars" if accumulated_thinking else ""
            self.log("warn", f"Empty response detected (no content{thinking_note})")
            return ProviderResult(
                success=False,
                error="Empty response (0 output tokens, no content)"
            )

        if not usage_data:
            input_tokens = estimate_message_tokens(messages)
            output_tokens = estimate_tokens(accumulated_content + accumulated_thinking)
            usage_data = UsageData(
                prompt_tokens=input_tokens,
                completion_tokens=output_tokens,
                total_tokens=input_tokens + output_tokens,
                estimated=True
            )
            callback(CallbackType.USAGE, usage_data.to_dict())

        return ProviderResult(
            success=True,
            content=accumulated_content,
            thinking_content=accumulated_thinking,
            tool_calls=accumulated_tool_calls,
            usage=usage_data
        )

    def _do_generate(
        self,
        messages: List[Dict],
        model: str,
        params: Dict,
        thinking_enabled: bool,
        api_key: str,
        abort_event: Optional[Any]
    ) -> ProviderResult:
        timeout = self.config.get("request_timeout", 120)
        url = self._get_completions_url()
        headers = self._get_headers(api_key)
        body = self._build_request_body(messages, model, params, thinking_enabled, streaming=False)

        self._check_abort(abort_event)
        response = requests.post(url, headers=headers, json=body, timeout=timeout)
        self._check_abort(abort_event)

        if response.status_code != 200:
            error_text = response.text
            return ProviderResult(
                success=False,
                error=error_text,
                status_code=response.status_code
            )

        try:
            data = response.json()
        except Exception:
            response_text = response.text
            if not response_text or not response_text.strip():
                raise ValueError("Empty response body from server")
            data = json.loads(response_text)

        choices = data.get("choices", [])
        if not choices:
            choice = {}
        else:
            choice = choices[0]
            if choice is None or not isinstance(choice, dict):
                choice = {}

            if "error" in data:
                error_obj = data["error"]
                if isinstance(error_obj, dict):
                    error_code = error_obj.get("code", 0)
                    error_type = error_obj.get("type", "")
                    error_message = error_obj.get("message", str(error_obj))
                    prefix = f"{error_code} {error_type}" if error_type else str(error_code) if error_code else ""
                    error_text = f"{prefix}: {error_message}" if prefix else error_message
                else:
                    error_text = str(error_obj)
                return ProviderResult(
                    success=False,
                    error=error_text
                )

            if isinstance(choice, dict):
                finish_reason = choice.get("finish_reason")
                if finish_reason in ("content_filter", "blocked"):
                    block_msg = f"Response blocked: {finish_reason}"
                    return ProviderResult(
                        success=False,
                        error=block_msg
                    )

        message = choice.get("message") if isinstance(choice, dict) else None
        if message is None or not isinstance(message, dict):
            message = {}

        content = message.get("content", "") or ""
        reasoning = message.get("reasoning_content", "") or ""
        if not reasoning:
            reasoning = message.get("reasoning", "") or ""
        tool_calls = message.get("tool_calls", []) or []

        # Extract inline thinking if native reasoning is empty
        if not reasoning and content:
            from .inline_thinking import extract_leading_thinking_blocks
            extracted = extract_leading_thinking_blocks(content)
            if extracted.stripped:
                content = extracted.content
                reasoning = extracted.thinking

        usage = data.get("usage")
        if usage is None or not isinstance(usage, dict):
            usage = {}
        usage_data = UsageData(
            prompt_tokens=usage.get("prompt_tokens", 0),
            completion_tokens=usage.get("completion_tokens", 0),
            total_tokens=usage.get("total_tokens", 0)
        )

        if self.detect_empty_response(content, reasoning, tool_calls, usage_data.completion_tokens):
            thinking_note = f", thinking: {len(reasoning)} chars" if reasoning else ""
            self.log("warn", f"Empty response detected (no content{thinking_note})")
            return ProviderResult(
                success=False,
                error="Empty response (0 output tokens, no content)"
            )

        return ProviderResult(
            success=True,
            content=content,
            thinking_content=reasoning,
            tool_calls=tool_calls,
            usage=usage_data
        )

    # =========================================================================
    # HELPERS / METADATA
    # =========================================================================

    def _extract_error_brief(self, error_text: str, status_code: int = 0) -> str:
        """Extract a brief, readable error message from API error response."""
        try:
            error_data = json.loads(error_text)
            if "error" in error_data:
                error_obj = error_data["error"]
                if isinstance(error_obj, dict):
                    msg = error_obj.get("message", "")
                    err_type = error_obj.get("type", "")
                    if msg:
                        brief = msg[:80]
                        if err_type:
                            brief = f"{err_type}: {brief}"[:100]
                        return brief
                    if err_type:
                        return f"Type: {err_type}"
                elif isinstance(error_obj, str):
                    return error_obj[:100]
        except (json.JSONDecodeError, TypeError, KeyError):
            pass

        first_line = error_text.split('\n')[0][:100] if error_text else ""
        if status_code:
            return f"HTTP {status_code}: {first_line[:80]}"
        return first_line or "Unknown error"

    def fetch_models(self) -> tuple[List[Dict], Optional[str]]:
        """Fetch available models from the API with metadata."""
        if not self.key_manager or not self.key_manager.has_keys():
            return None, f"No API keys configured for {self.name}"

        current_key = self.key_manager.get_current_key()
        if not current_key:
            return None, "No API key available"

        url = self._get_models_url()
        headers = self._get_headers(current_key)

        try:
            response = requests.get(url, headers=headers, timeout=30)
            if response.status_code != 200:
                return None, f"Failed to fetch models ({response.status_code}): {response.text[:200]}"

            data = response.json()
            if "data" in data and isinstance(data["data"], list):
                models = []
                for model in data["data"]:
                    model_id = model.get("id", str(model))
                    supported_params = model.get("supported_parameters", [])
                    has_thinking_param = any(p in supported_params for p in ("include_reasoning", "reasoning"))

                    model_info = {
                        "id": model_id,
                        "name": model.get("name", model_id),
                        "owned_by": model.get("owned_by", "unknown"),
                        "context_length": (
                            model.get("context_length") or
                            model.get("context_window") or
                            model.get("max_context_length")
                        ),
                        "description": model.get("description", ""),
                        "pricing": model.get("pricing"),
                        "architecture": model.get("architecture"),
                        "top_provider": model.get("top_provider"),
                        "_raw": model
                    }

                    if has_thinking_param:
                        model_info["thinking"] = True
                    else:
                        model_id_lower = model_id.lower()
                        model_info["thinking"] = any(kw in model_id_lower for kw in [
                            "thinking", "reason", "o1", "o3", "deepseek-r1"
                        ])

                    models.append(model_info)
                return models, None

            if isinstance(data, list):
                models = []
                for model in data:
                    if isinstance(model, str):
                        models.append({
                            "id": model,
                            "name": model,
                            "_raw": {"id": model}
                        })
                    else:
                        model_id = model.get("id", str(model))
                        models.append({
                            "id": model_id,
                            "name": model.get("name", model_id),
                            "context_length": model.get("context_length"),
                            "_raw": model
                        })
                return models, None

            return None, "Unknown models response format"
        except requests.exceptions.RequestException as e:
            return None, f"Request failed: {e}"
        except Exception as e:
            return None, f"Error fetching models: {e}"
