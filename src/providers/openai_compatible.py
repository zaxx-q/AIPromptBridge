"""
OpenAI-Compatible Provider

Supports:
- Custom OpenAI-compatible APIs
- OpenRouter
- Google's OpenAI-compatible endpoint (with extra_body.google for safety/thinking)

"""

import json
import time
import re
from typing import List, Dict, Optional, Any
import requests

from .base import (
    BaseProvider, 
    ProviderResult, 
    StreamCallback,
    UsageData,
    CallbackType,
    RetryReason,
    estimate_tokens,
    estimate_message_tokens
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
    - Streaming with retry logic
    - Empty response detection and retry
    - Thinking/reasoning support via reasoning_effort and extra_body.google
    - Key rotation on errors
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
        
        Args:
            endpoint_type: Type of endpoint (custom, openrouter, google)
            base_url: Base URL for the API (will be normalized)
            key_manager: Key manager for API key rotation
            config: Configuration dict with thinking settings etc.
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
    
    def _extract_error_brief(self, error_text: str, status_code: int = 0) -> str:
        """
        Extract a brief, readable error message from API error response.
        
        Args:
            error_text: Raw error response text (may be JSON or plain text)
            status_code: HTTP status code
            
        Returns:
            Brief error description (max ~100 chars)
        """
        try:
            # Try to parse as JSON and extract error message
            error_data = json.loads(error_text)
            if "error" in error_data:
                error_obj = error_data["error"]
                if isinstance(error_obj, dict):
                    # OpenAI format: {"error": {"message": "...", "type": "..."}}
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
        
        # Fallback: use first line or truncated text
        first_line = error_text.split('\n')[0][:100] if error_text else ""
        if status_code:
            return f"HTTP {status_code}: {first_line[:80]}"
        return first_line or "Unknown error"
    
    def _get_completions_url(self) -> str:
        """Get the full chat completions URL"""
        return f"{self.base_url}/chat/completions"
    
    def _get_models_url(self) -> str:
        """Get the models endpoint URL"""
        return f"{self.base_url}/models"
    
    def _is_google_endpoint(self) -> bool:
        """
        Check if this is a Google endpoint (needs extra_body).
        
        Detects Google endpoints by:
        - Explicit endpoint_type == ENDPOINT_GOOGLE
        - URL containing "googleapis.com"
        - URL containing "google" keyword (flexible detection)
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
        
        # OpenRouter requires HTTP-Referer header
        if self.endpoint_type == self.ENDPOINT_OPENROUTER:
            headers["HTTP-Referer"] = "https://github.com/zaxx-q/AIPromptBridge"
            headers["X-Title"] = "AIPromptBridge"
            
        return headers
    
    def _is_openrouter_endpoint(self) -> bool:
        """
        Check if this is an OpenRouter endpoint.
        
        OpenRouter requires Text First, Media Last ordering per their documentation
        to prevent parsing errors in their middleware.
        """
        if self.endpoint_type == self.ENDPOINT_OPENROUTER:
            return True
        
        url_lower = self.base_url.lower()
        return "openrouter.ai" in url_lower or "openrouter" in url_lower
    
    def _reorder_content_for_provider(self, content: List[Dict]) -> List[Dict]:
        if not self._is_openrouter_endpoint():
            # Non-OpenRouter: preserve original order
            return content
        
        # Count media items
        media_count = 0
        for item in content:
            item_type = item.get("type", "")
            if item_type != "text":
                media_count += 1
        
        # OpenRouter Logic:
        # If exactly ONE media item, move it to the end (Text First).
        # This prevents middleware parsing errors for simple cases.
        # If multiple media items (e.g. interleaved document), preserve original order.
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
        
        Transforms:
        - Audio data URLs -> OpenAI 'input_audio' format
        - PDF files -> OpenRouter 'file' format
        
        Also applies provider-specific content ordering:
        - OpenRouter: Text First, Media Last (per their documentation)
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
                
                # Handle Audio (input_audio or explicit audio type)
                if item_type == "input_audio" or item_type == "audio":
                    # Check for inline data or data URL
                    audio_data = None
                    audio_format = "wav" # default
                    
                    if "input_audio" in item:
                        # Already in correct format?
                        new_content.append(item)
                        continue
                        
                    # Parse data URL if present
                    data_url = item.get("image_url", {}).get("url") or item.get("url") or item.get("data")
                    if data_url and isinstance(data_url, str) and data_url.startswith("data:"):
                        match = re.match(r"data:audio/([^;]+);base64,(.+)", data_url)
                        if match:
                            fmt, b64 = match.groups()
                            # key mappings often used: "mp3"->"mp3", "wav"->"wav"
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
                        # Pass through if we couldn't process (might be valid already)
                        new_content.append(item)
                
                # Handle Files (PDFs for OpenRouter)
                elif item_type == "file":
                    # OpenRouter format: { "type": "file", "file": { "url": "...", "file_data": "..." } }
                    file_info = item.get("file", {})
                    
                    # Convert internal "file_data" or "url" into proper structure if needed
                    # If it's already in OpenRouter format, it stays.
                    # If it's a data URL in "url", OpenRouter supports it.
                    
                    # Ensure specific fields are present if we were passed a flat dict
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
                                "file_data": item["data"]  # Base64
                            }
                        })
                    else:
                        new_content.append(item)
                
                # Handle inline_data (Gemini format) -> input_audio (OpenAI format)
                # This allows file_handler.py to use a unified format that both providers understand
                elif item_type == "inline_data":
                    inline = item.get("inline_data", {})
                    mime_type = inline.get("mime_type", "")
                    
                    # Check if this is audio content
                    if mime_type.startswith("audio/"):
                        # Extract format from mime type (e.g., "audio/mp3" -> "mp3")
                        audio_format = mime_type.split("/")[-1]
                        # Handle special cases for mime type variations
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
                        # Handle inline images -> image_url (data URI)
                        # This bridges the gap for FileProcessor which uses build_inline_message for images
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
                        # Handle inline text/code -> decode to text content
                        # This allows FileProcessor to use build_inline_message for code files
                        try:
                            # It was base64 encoded for inline_data, decode it back to text
                            import base64
                            text_content = base64.b64decode(inline.get("data", "")).decode("utf-8")
                            new_content.append({
                                "type": "text",
                                "text": f"\n\n[File Content: {mime_type}]\n{text_content}"
                            })
                        except Exception:
                            # If decoding fails, pass through or warn
                            new_content.append(item)
                    
                    elif mime_type == "application/pdf":
                        # PDF document handling
                        b64_data = inline.get("data", "")
                        filename = item.get("filename", "document.pdf")
                        
                        if self._is_openrouter_endpoint():
                            # OpenRouter format: {"type": "file", "file": {"filename": "...", "file_data": "data:...;base64,..."}}
                            data_url = f"data:application/pdf;base64,{b64_data}"
                            new_content.append({
                                "type": "file",
                                "file": {
                                    "filename": filename,
                                    "file_data": data_url
                                }
                            })
                        else:
                            # Other OpenAI-compatible endpoints: use data URI in image_url
                            # (Google OpenAI-compat and some others accept this)
                            data_url = f"data:application/pdf;base64,{b64_data}"
                            new_content.append({
                                "type": "image_url",
                                "image_url": {
                                    "url": data_url
                                }
                            })
                    
                    else:
                        # Non-supported inline data - pass through (may be handled by server or fail)
                        new_content.append(item)
                
                else:
                    new_content.append(item)
            
            # Apply provider-specific content ordering
            # OpenRouter: Text First, Media Last (per their documentation)
            new_content = self._reorder_content_for_provider(new_content)
            
            # Create new message with processed content
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
        """
        Build the request body with proper thinking/safety configuration.

        - stream: true + stream_options: { include_usage: true } for streaming
        - reasoning_effort: "high"/"medium"/"low" for thinking
        - extra_body.google.thinking_config.include_thoughts: true for Google
        - extra_body.google.safety_settings with BLOCK_NONE for Google
        """
        body = {
            "model": model,
            "messages": self._process_messages(messages)
        }
        
        # Streaming configuration - MUST explicitly set stream to false
        # because some servers default to streaming
        # unless stream is explicitly set to false
        if streaming:
            body["stream"] = True
            body["stream_options"] = {"include_usage": True}
        else:
            body["stream"] = False
        
        # Copy generation parameters
        for key, value in params.items():
            if key not in ("stream", "stream_options") and value is not None:
                body[key] = value
        
        # Thinking/reasoning configuration
        if thinking_enabled:
            reasoning_effort = self.config.get("reasoning_effort", "high")
            body["reasoning_effort"] = reasoning_effort
            
            # For Google endpoint, add extra_body with thinking_config and safety
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
            # Still add safety settings even without thinking
            body["extra_body"] = {
                "google": {
                    "safety_settings": GOOGLE_SAFETY_SETTINGS
                }
            }
        
        return body
    
    def generate_stream(
        self,
        messages: List[Dict],
        model: str,
        params: Dict,
        callback: StreamCallback,
        thinking_enabled: bool = False,
        retry_count: int = 0
    ) -> ProviderResult:
        """
        Generate a streaming response with full retry logic.
        
        Retry behavior (matching reverse-proxy):
        - 429: Immediate key rotation, retry
        - 401/402/403: Immediate key rotation, retry
        - 5xx: 2 second delay, retry
        - Empty response: Key rotation, 2 second delay, retry
        - Network error: Key rotation, 1 second delay, retry
        """
        if not self.key_manager or not self.key_manager.has_keys():
            return ProviderResult(
                success=False,
                error=f"No API keys configured for {self.name}"
            )
        
        current_key = self.key_manager.get_current_key()
        if not current_key:
            return ProviderResult(
                success=False,
                error="No API key available"
            )
        
        key_num = self.key_manager.get_key_number()
        timeout = self.config.get("request_timeout", 120)
        
        url = self._get_completions_url()
        headers = self._get_headers(current_key)
        body = self._build_request_body(messages, model, params, thinking_enabled, streaming=True)
        
        self.log_request(model, key_num, thinking_enabled, streaming=True, retry=retry_count)
        
        # Accumulators for content
        accumulated_content = ""
        accumulated_thinking = ""
        accumulated_tool_calls = []
        usage_data = None
        
        try:
            # Make streaming request
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
                status_code = response.status_code
    
                reason = self.get_retry_reason(status_code, error_text)
    
                if self.should_retry(reason, retry_count):
                    delay = self.get_retry_delay(reason)
                    error_brief = self._extract_error_brief(error_text[:500], status_code)
                    self.log_retry(reason, retry_count + 1, delay, error_brief)
    
                    # Rotate key for rate limit and auth errors
                    if reason in (RetryReason.RATE_LIMITED, RetryReason.AUTH_ERROR):
                        self.rotate_key_if_possible(f"({reason.value})")
    
                    if delay > 0:
                        time.sleep(delay)
    
                    return self.generate_stream(
                        messages, model, params, callback, thinking_enabled, retry_count + 1
                    )
    
                # Extract the actual API error message from the response
                error_message = self._extract_error_brief(error_text[:500], status_code) if error_text else f"HTTP {status_code}"
                # Prepend status code: "429: <message>"
                full_error = f"{status_code}: {error_message}" if error_message != f"HTTP {status_code}" else error_message
                callback(CallbackType.ERROR, full_error)
                return ProviderResult(
                    success=False,
                    error=full_error,
                    retry_count=retry_count
                )
            
            # Process streaming response
            response.encoding = 'utf-8'
            
            chunk_count = 0
            last_content_time = time.time()  # Track last meaningful content for idle timeout
            for line in response.iter_lines(decode_unicode=True):
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
                    # Log unexpected line format for debugging
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
                            # Compact format: "429 rate_limit_exceeded: <message>"
                            prefix = f"{error_code} {error_type}" if error_type else str(error_code) if error_code else ""
                            error_text = f"{prefix}: {error_message}" if prefix else error_message
                        else:
                            error_text = str(error_obj)
                        callback(CallbackType.ERROR, error_text)
                        return ProviderResult(
                            success=False,
                            error=error_text,
                            retry_count=retry_count
                        )

                    # Get choices array - may be empty in usage-only chunks
                    choices = data.get("choices", [])
                    if choices:
                        choice = choices[0]
                        
                        # Defensive check: ensure choice is not None
                        if choice is None:
                            self.log("warn", f"Chunk {chunk_count}: choices[0] is None, raw: {json_str[:200]}")
                            continue
                        
                        # Defensive check: ensure choice is a dict
                        if not isinstance(choice, dict):
                            self.log("warn", f"Chunk {chunk_count}: choice is not dict: {type(choice)}, raw: {json_str[:200]}")
                            continue
                        
                        delta = choice.get("delta")
                        
                        # Defensive check: ensure delta is not None
                        if delta is None:
                            # Some servers send delta: null, use empty dict
                            delta = {}
                        
                        # Defensive check: ensure delta is a dict
                        if not isinstance(delta, dict):
                            self.log("warn", f"Chunk {chunk_count}: delta is not dict: {type(delta)}, raw: {json_str[:200]}")
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
                        
                        # Also check for "reasoning" field (some servers use this)
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

                        # Check for blocked finish reasons (content_filter, etc.)
                        finish_reason = choice.get("finish_reason")
                        if finish_reason in ("content_filter", "blocked"):
                            if not accumulated_content.strip() and not accumulated_tool_calls:
                                block_msg = f"Response blocked: {finish_reason}"
                                self.log_error(block_msg)
                                callback(CallbackType.ERROR, block_msg)
                                return ProviderResult(
                                    success=False,
                                    error=block_msg,
                                    retry_count=retry_count
                                )

                    # Handle usage data (comes with stream_options.include_usage)
                    # This may come in a chunk with empty choices array
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
                
                if self.should_retry(RetryReason.EMPTY_RESPONSE, retry_count):
                    delay = self.get_retry_delay(RetryReason.EMPTY_RESPONSE)
                    self.log_retry(RetryReason.EMPTY_RESPONSE, retry_count + 1, delay, "0 output tokens, no content")
                    
                    if delay > 0:
                        time.sleep(delay)
                    
                    return self.generate_stream(
                        messages, model, params, callback, thinking_enabled, retry_count + 1
                    )
                
                return ProviderResult(
                    success=False,
                    error="Empty response after retries exhausted",
                    retry_count=retry_count
                )
            
            # Estimate usage if not provided
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
            
            self.log_success(key_num)
            
            return ProviderResult(
                success=True,
                content=accumulated_content,
                thinking_content=accumulated_thinking,
                tool_calls=accumulated_tool_calls,
                usage=usage_data,
                retry_count=retry_count
            )
        
        except requests.exceptions.Timeout:
            self.log_error(f"Request timeout after {timeout}s")
            
            if self.should_retry(RetryReason.NETWORK_ERROR, retry_count):
                delay = self.get_retry_delay(RetryReason.NETWORK_ERROR)
                self.log_retry(RetryReason.NETWORK_ERROR, retry_count + 1, delay, f"timeout after {timeout}s")
                self.rotate_key_if_possible("(timeout)")
                
                if delay > 0:
                    time.sleep(delay)
                
                return self.generate_stream(
                    messages, model, params, callback, thinking_enabled, retry_count + 1
                )
            
            callback(CallbackType.ERROR, f"Request timeout after {timeout}s")
            return ProviderResult(
                success=False,
                error=f"Request timeout after {timeout}s",
                retry_count=retry_count
            )
        
        except requests.exceptions.RequestException as e:
            error_msg = str(e)
            self.log_error(f"Network error: {error_msg}")
            
            if self.should_retry(RetryReason.NETWORK_ERROR, retry_count):
                delay = self.get_retry_delay(RetryReason.NETWORK_ERROR)
                self.log_retry(RetryReason.NETWORK_ERROR, retry_count + 1, delay, error_msg[:100])
                self.rotate_key_if_possible("(network error)")
                
                if delay > 0:
                    time.sleep(delay)
                
                return self.generate_stream(
                    messages, model, params, callback, thinking_enabled, retry_count + 1
                )
            
            callback(CallbackType.ERROR, error_msg)
            return ProviderResult(
                success=False,
                error=f"Network error: {error_msg}",
                retry_count=retry_count
            )
        
        except Exception as e:
            error_msg = str(e)
            self.log_error(f"Unexpected error: {error_msg}")
            
            if self.should_retry(RetryReason.SERVER_ERROR, retry_count):
                delay = self.get_retry_delay(RetryReason.SERVER_ERROR)
                self.log_retry(RetryReason.SERVER_ERROR, retry_count + 1, delay, error_msg[:100])
                
                if delay > 0:
                    time.sleep(delay)
                
                return self.generate_stream(
                    messages, model, params, callback, thinking_enabled, retry_count + 1
                )
            
            callback(CallbackType.ERROR, error_msg)
            return ProviderResult(
                success=False,
                error=f"Unexpected error: {error_msg}",
                retry_count=retry_count
            )
    
    def generate(
        self,
        messages: List[Dict],
        model: str,
        params: Dict,
        thinking_enabled: bool = False,
        retry_count: int = 0
    ) -> ProviderResult:
        """
        Generate a non-streaming response with retry logic.
        """
        if not self.key_manager or not self.key_manager.has_keys():
            return ProviderResult(
                success=False,
                error=f"No API keys configured for {self.name}"
            )
        
        current_key = self.key_manager.get_current_key()
        if not current_key:
            return ProviderResult(
                success=False,
                error="No API key available"
            )
        
        key_num = self.key_manager.get_key_number()
        timeout = self.config.get("request_timeout", 120)
        
        url = self._get_completions_url()
        headers = self._get_headers(current_key)
        body = self._build_request_body(messages, model, params, thinking_enabled, streaming=False)
        
        self.log_request(model, key_num, thinking_enabled, streaming=False, retry=retry_count)
        
        try:
            response = requests.post(url, headers=headers, json=body, timeout=timeout)
            
            # Handle error responses
            if response.status_code != 200:
                error_text = response.text
                status_code = response.status_code
    
                reason = self.get_retry_reason(status_code, error_text)
    
                if self.should_retry(reason, retry_count):
                    delay = self.get_retry_delay(reason)
                    error_brief = self._extract_error_brief(error_text[:500], status_code)
                    self.log_retry(reason, retry_count + 1, delay, error_brief)
    
                    if reason in (RetryReason.RATE_LIMITED, RetryReason.AUTH_ERROR):
                        self.rotate_key_if_possible(f"({reason.value})")
    
                    if delay > 0:
                        time.sleep(delay)
    
                    return self.generate(messages, model, params, thinking_enabled, retry_count + 1)
    
                # Extract the actual API error message from the response
                error_message = self._extract_error_brief(error_text[:500], status_code) if error_text else f"HTTP {status_code}"
                # Prepend status code: "429: <message>"
                full_error = f"{status_code}: {error_message}" if error_message != f"HTTP {status_code}" else error_message
                return ProviderResult(
                    success=False,
                    error=full_error,
                    retry_count=retry_count
                )
            
            # Parse response - with better error handling for malformed responses
            response_text = response.text
            
            # Debug: log raw response if it looks problematic
            if not response_text or not response_text.strip():
                self.log_error(f"Empty response body (Content-Length: {response.headers.get('Content-Length', 'not set')})")
                raise ValueError("Empty response body from server")
            
            try:
                data = json.loads(response_text)
            except json.JSONDecodeError as e:
                self.log_error(f"JSON decode error: {e}, raw response: {response_text[:500]}")
                raise
            
            # Defensive parsing of choices
            choices = data.get("choices", [])
            if not choices:
                self.log("warn", f"No choices in response: {json.dumps(data)[:500]}")
                choice = {}
            else:
                choice = choices[0]
                if choice is None:
                    self.log("warn", f"choices[0] is None, full response: {json.dumps(data)[:500]}")
                    choice = {}
                elif not isinstance(choice, dict):
                    self.log("warn", f"choice is not dict: {type(choice)}, raw: {json.dumps(data)[:500]}")
                    choice = {}
        
                # Check for error object in response body
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
                        error=error_text,
                        retry_count=retry_count
                    )
        
                # Check for blocked finish reasons
                if isinstance(choice, dict):
                    finish_reason = choice.get("finish_reason")
                    if finish_reason in ("content_filter", "blocked"):
                        block_msg = f"Response blocked: {finish_reason}"
                        return ProviderResult(
                            success=False,
                            error=block_msg,
                            retry_count=retry_count
                        )
        
                message = choice.get("message") if isinstance(choice, dict) else None
            if message is None:
                message = {}
            elif not isinstance(message, dict):
                self.log("warn", f"message is not dict: {type(message)}")
                message = {}
            
            content = message.get("content", "") or ""
            reasoning = message.get("reasoning_content", "") or ""
            # Also check for "reasoning" field (some servers use this)
            if not reasoning:
                reasoning = message.get("reasoning", "") or ""
            tool_calls = message.get("tool_calls", []) or []
            
            # Parse usage
            usage = data.get("usage")
            if usage is None or not isinstance(usage, dict):
                usage = {}
            usage_data = UsageData(
                prompt_tokens=usage.get("prompt_tokens", 0),
                completion_tokens=usage.get("completion_tokens", 0),
                total_tokens=usage.get("total_tokens", 0)
            )
            
            # Check for empty response
            if self.detect_empty_response(content, reasoning, tool_calls, usage_data.completion_tokens):
                thinking_note = f", thinking: {len(reasoning)} chars" if reasoning else ""
                self.log("warn", f"Empty response detected (no content{thinking_note})")
                
                if self.should_retry(RetryReason.EMPTY_RESPONSE, retry_count):
                    delay = self.get_retry_delay(RetryReason.EMPTY_RESPONSE)
                    self.log_retry(RetryReason.EMPTY_RESPONSE, retry_count + 1, delay, "0 output tokens, no content")
                    
                    if delay > 0:
                        time.sleep(delay)
                    
                    return self.generate(messages, model, params, thinking_enabled, retry_count + 1)
                
                return ProviderResult(
                    success=False,
                    error="Empty response after retries exhausted",
                    retry_count=retry_count
                )
            
            self.log_success(key_num)
            
            return ProviderResult(
                success=True,
                content=content,
                thinking_content=reasoning,
                tool_calls=tool_calls,
                usage=usage_data,
                retry_count=retry_count
            )
        
        except requests.exceptions.Timeout:
            self.log_error(f"Request timeout after {timeout}s")
            
            if self.should_retry(RetryReason.NETWORK_ERROR, retry_count):
                delay = self.get_retry_delay(RetryReason.NETWORK_ERROR)
                self.log_retry(RetryReason.NETWORK_ERROR, retry_count + 1, delay, f"timeout after {timeout}s")
                self.rotate_key_if_possible("(timeout)")
                
                if delay > 0:
                    time.sleep(delay)
                
                return self.generate(messages, model, params, thinking_enabled, retry_count + 1)
            
            return ProviderResult(
                success=False,
                error=f"Request timeout after {timeout}s",
                retry_count=retry_count
            )
        
        except requests.exceptions.RequestException as e:
            error_msg = str(e)
            self.log_error(f"Network error: {error_msg}")
            
            if self.should_retry(RetryReason.NETWORK_ERROR, retry_count):
                delay = self.get_retry_delay(RetryReason.NETWORK_ERROR)
                self.log_retry(RetryReason.NETWORK_ERROR, retry_count + 1, delay, error_msg[:100])
                self.rotate_key_if_possible("(network error)")
                
                if delay > 0:
                    time.sleep(delay)
                
                return self.generate(messages, model, params, thinking_enabled, retry_count + 1)
            
            return ProviderResult(
                success=False,
                error=f"Network error: {error_msg}",
                retry_count=retry_count
            )
        
        except Exception as e:
            error_msg = str(e)
            self.log_error(f"Unexpected error: {error_msg}")
            
            return ProviderResult(
                success=False,
                error=f"Unexpected error: {error_msg}",
                retry_count=retry_count
            )
    
    def fetch_models(self) -> tuple[List[Dict], Optional[str]]:
        """
        Fetch available models from the API with metadata.
        
        Returns models with fields:
        - id: Model ID
        - name: Display name
        - context_length: Context window size (if available)
        - owned_by: Model owner/provider
        - _raw: Original API response for future-proofing
        
        OpenRouter provides additional fields like:
        - description, pricing, context_length, etc.
        """
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
            
            # OpenAI format: { "data": [...] }
            if "data" in data and isinstance(data["data"], list):
                models = []
                for model in data["data"]:
                    model_id = model.get("id", str(model))
                    
                    # OpenRouter specific detection
                    supported_params = model.get("supported_parameters", [])
                    has_thinking_param = any(p in supported_params for p in ("include_reasoning", "reasoning"))
                    
                    model_info = {
                        "id": model_id,
                        "name": model.get("name", model_id),
                        "owned_by": model.get("owned_by", "unknown"),
                        # Context length may be in different fields
                        "context_length": (
                            model.get("context_length") or  # OpenRouter
                            model.get("context_window") or  # Some APIs
                            model.get("max_context_length")  # Others
                        ),
                        # Metadata
                        "description": model.get("description", ""),
                        "pricing": model.get("pricing"),
                        "architecture": model.get("architecture"),
                        "top_provider": model.get("top_provider"),
                        "_raw": model
                    }
                    
                    # Detect thinking support - prefer explicit parameter if found
                    if has_thinking_param:
                        model_info["thinking"] = True
                    else:
                        # Fallback to ID-based detection
                        model_id_lower = model_id.lower()
                        model_info["thinking"] = any(kw in model_id_lower for kw in [
                            "thinking", "reason", "o1", "o3", "deepseek-r1"
                        ])
                    
                    models.append(model_info)
                return models, None
            
            # Some APIs return array directly
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