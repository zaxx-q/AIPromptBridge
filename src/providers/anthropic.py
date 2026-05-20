"""
Anthropic Claude Provider

Supports:
- Anthropic Messages API
- SSE streaming with thinking & text delta extraction
- Consecutive same-role message merging (Claude strict alternation requirement)
- Multimodal inputs (images and PDF documents)
"""

import json
import time
import re
import requests
from typing import List, Dict, Optional, Any

from .base import (
    BaseProvider,
    ProviderResult,
    StreamCallback,
    UsageData,
    CallbackType,
    estimate_tokens,
    estimate_message_tokens
)


class AnthropicProvider(BaseProvider):
    """
    Provider for Anthropic Claude API using the Messages API.
    
    Features:
    - Native Messages API format: system separate, alternating user/assistant
    - Extended thinking with content blocks: type=thinking and type=text
    - SSE streaming with typed events
    - Automatic consecutive message merging
    - Multimodal support: images and PDFs as base64 content blocks
    """
    
    ANTHROPIC_API_VERSION = "2023-06-01"
    
    def __init__(
        self,
        base_url: Optional[str] = None,
        key_manager=None,
        config: Optional[Dict] = None
    ):
        super().__init__("Anthropic", key_manager, config)
        self.base_url = (base_url or "https://api.anthropic.com/v1").rstrip("/")
        
    def _get_headers(self, api_key: str) -> Dict[str, str]:
        return {
            "Content-Type": "application/json",
            "x-api-key": api_key,
            "anthropic-version": self.ANTHROPIC_API_VERSION,
        }
        
    def _extract_text_content(self, content: Any) -> str:
        """Extract plain text from message content which could be a string or list."""
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            parts = []
            for item in content:
                if isinstance(item, dict):
                    if item.get("type") == "text":
                        parts.append(item.get("text", ""))
                elif isinstance(item, str):
                    parts.append(item)
            return "".join(parts)
        return str(content) if content is not None else ""
        
    def _copy_content(self, content: Any) -> Any:
        if isinstance(content, list):
            return [dict(item) if isinstance(item, dict) else item for item in content]
        return content
        
    def _separate_system_messages(self, messages: List[Dict]) -> tuple[List[str], List[Dict]]:
        """Split system messages out (Anthropic puts them in a top-level field)."""
        system_texts = []
        chat_msgs = []
        for msg in messages:
            if msg.get("role") == "system":
                content = msg.get("content", "")
                text = self._extract_text_content(content)
                if text.strip():
                    system_texts.append(text)
            else:
                chat_msgs.append(msg)
        return system_texts, chat_msgs
        
    def _merge_consecutive_messages(self, messages: List[Dict]) -> List[Dict]:
        """Merge consecutive same-role messages (Claude requires alternation)."""
        merged = []
        for msg in messages:
            role = msg.get("role", "user")
            content = msg.get("content", "")
            
            if merged and merged[-1]["role"] == role:
                existing_content = merged[-1]["content"]
                new_text = self._extract_text_content(content)
                
                if isinstance(existing_content, str):
                    merged[-1]["content"] = existing_content + "\n\n" + new_text
                elif isinstance(existing_content, list):
                    existing_content.append({"type": "text", "text": "\n\n" + new_text})
            else:
                merged.append({
                    "role": role,
                    "content": self._copy_content(content)
                })
                
        # Ensure starts with user message
        if not merged:
            merged.append({"role": "user", "content": "[Start]"})
        elif merged[0]["role"] != "user":
            merged.insert(0, {"role": "user", "content": "[Start]"})
        return merged
        
    def _format_messages(self, messages: List[Dict]) -> List[Dict]:
        """Format messages for Anthropic API (handle images, pdf documents, etc.)."""
        formatted = []
        for msg in messages:
            content = msg.get("content", "")
            if isinstance(content, list):
                parts = []
                for item in content:
                    item_type = item.get("type", "")
                    
                    if item_type == "text":
                        parts.append({"type": "text", "text": item.get("text", "")})
                        
                    elif item_type == "image_url":
                        url = item.get("image_url", {}).get("url", "")
                        if not url and "url" in item:
                            url = item["url"]
                        match = re.match(r"data:([^;]+);base64,(.+)", url)
                        if match:
                            parts.append({
                                "type": "image",
                                "source": {
                                    "type": "base64",
                                    "media_type": match.group(1),
                                    "data": match.group(2),
                                }
                            })
                            
                    elif item_type == "inline_data":
                        inline = item.get("inline_data", {})
                        mime_type = inline.get("mime_type", "")
                        data = inline.get("data", "")
                        
                        if mime_type.startswith("image/"):
                            parts.append({
                                "type": "image",
                                "source": {
                                    "type": "base64",
                                    "media_type": mime_type,
                                    "data": data,
                                }
                            })
                        elif mime_type == "application/pdf":
                            parts.append({
                                "type": "document",
                                "source": {
                                    "type": "base64",
                                    "media_type": "application/pdf",
                                    "data": data,
                                }
                            })
                        elif mime_type.startswith("text/") or mime_type in (
                            "application/json", "application/xml", "application/javascript"
                        ):
                            try:
                                import base64
                                text_content = base64.b64decode(data).decode("utf-8")
                                parts.append({
                                    "type": "text",
                                    "text": f"\n\n[File Content: {mime_type}]\n{text_content}"
                                })
                            except Exception:
                                pass
                                
                formatted.append({"role": msg["role"], "content": parts})
            else:
                formatted.append({"role": msg["role"], "content": content})
        return formatted
        
    def _build_request_body(
        self,
        messages: List[Dict],
        model: str,
        params: Dict,
        thinking_enabled: bool,
        streaming: bool
    ) -> Dict:
        """Build Anthropic Messages API request body."""
        system_messages, chat_messages = self._separate_system_messages(messages)
        merged = self._merge_consecutive_messages(chat_messages)
        
        body = {
            "model": model,
            "max_tokens": params.get("max_tokens", 4096),
            "messages": self._format_messages(merged),
            "stream": streaming,
        }
        
        # System field
        if system_messages:
            body["system"] = "\n\n".join(m for m in system_messages if m.strip())
            
        # Add extra params (temperature, etc.) if thinking is NOT enabled
        # If thinking is enabled, sampling parameters are forbidden for some models.
        model_lower = model.lower()
        is_adaptive_only = bool(re.search(r"claude-opus-4-(?:[7-9]|\d{2,})", model_lower))
        
        # Temperature is forbidden if thinking is enabled
        if not thinking_enabled:
            for key, val in params.items():
                if key not in ("max_tokens", "stream") and val is not None:
                    body[key] = val
        else:
            # Temperature and top_p are forbidden when thinking is enabled
            for key, val in params.items():
                if key not in ("max_tokens", "stream", "temperature", "top_p") and val is not None:
                    body[key] = val
                    
            if is_adaptive_only:
                body["thinking"] = {"type": "adaptive"}
                effort = self.config.get("reasoning_effort", "high")
                body["output_config"] = {"effort": effort}
            else:
                supports_adaptive = bool(re.search(r"claude-(opus|sonnet)-4-[56]", model_lower))
                if supports_adaptive:
                    body["thinking"] = {"type": "adaptive"}
                    effort = self.config.get("reasoning_effort", "high")
                    body["output_config"] = {"effort": effort}
                else:
                    budget = max(1024, min(params.get("max_tokens", 4096), 16000))
                    body["thinking"] = {"type": "enabled", "budget_tokens": budget}
                    body["max_tokens"] = params.get("max_tokens", 4096) + budget
                    
        return body

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
        url = f"{self.base_url}/messages"
        headers = self._get_headers(api_key)
        body = self._build_request_body(messages, model, params, thinking_enabled, streaming=True)
        
        accumulated_content = ""
        accumulated_thinking = ""
        input_tokens = 0
        output_tokens = 0
        
        response = requests.post(
            url,
            headers=headers,
            json=body,
            timeout=timeout,
            stream=True
        )
        
        if response.status_code != 200:
            error_text = response.text
            return ProviderResult(
                success=False,
                error=error_text,
                status_code=response.status_code
            )
            
        response.encoding = 'utf-8'
        last_content_time = time.time()
        
        for line in response.iter_lines(decode_unicode=True):
            self._check_abort(abort_event)
            
            if time.time() - last_content_time > timeout:
                response.close()
                raise requests.exceptions.Timeout(
                    f"No content received for {timeout}s (content-idle timeout)"
                )
                
            if not line:
                continue
                
            line = line.strip()
            
            # Anthropic SSE format uses:
            # event: event_name
            # data: json_payload
            # Or some proxies send only data: lines. Let's just focus on lines starting with data:
            if not line.startswith("data: "):
                continue
                
            try:
                json_str = line[6:]
                data = json.loads(json_str)
                event_type = data.get("type")
                
                if event_type == "error":
                    error_obj = data.get("error", {})
                    error_message = error_obj.get("message", "Unknown error")
                    return ProviderResult(
                        success=False,
                        error=error_message
                    )
                    
                elif event_type == "message_start":
                    msg_obj = data.get("message", {})
                    usage = msg_obj.get("usage", {})
                    if usage:
                        input_tokens = usage.get("input_tokens", input_tokens)
                        output_tokens = usage.get("output_tokens", output_tokens)
                        
                elif event_type == "content_block_delta":
                    delta = data.get("delta", {})
                    
                    # Handle text delta
                    text = delta.get("text", "")
                    if text:
                        accumulated_content += text
                        callback(CallbackType.TEXT, text)
                        last_content_time = time.time()
                        
                    # Handle thinking delta
                    thinking = delta.get("thinking", "")
                    if thinking:
                        accumulated_thinking += thinking
                        callback(CallbackType.THINKING, thinking)
                        last_content_time = time.time()
                        
                elif event_type == "message_delta":
                    usage = data.get("usage", {})
                    if usage:
                        input_tokens = usage.get("input_tokens", input_tokens)
                        output_tokens = usage.get("output_tokens", output_tokens)
                        
                elif event_type == "message_stop":
                    callback(CallbackType.DONE, None)
                    break
                    
            except json.JSONDecodeError:
                continue
                
        # Check for empty response
        if self.detect_empty_response(accumulated_content, accumulated_thinking, [], output_tokens):
            thinking_note = f", thinking: {len(accumulated_thinking)} chars" if accumulated_thinking else ""
            self.log("warn", f"Empty response detected (no content{thinking_note})")
            return ProviderResult(
                success=False,
                error="Empty response (0 output tokens, no content)"
            )
            
        usage_data = UsageData(
            prompt_tokens=input_tokens,
            completion_tokens=output_tokens,
            total_tokens=input_tokens + output_tokens
        )
        
        if not input_tokens and not output_tokens:
            # Fallback estimation if not returned
            usage_data = self._estimate_usage_fallback(messages, accumulated_content, accumulated_thinking)
            
        callback(CallbackType.USAGE, usage_data.to_dict())
        
        return ProviderResult(
            success=True,
            content=accumulated_content,
            thinking_content=accumulated_thinking,
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
        url = f"{self.base_url}/messages"
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
            
        data = response.json()
        
        accumulated_content = ""
        accumulated_thinking = ""
        
        for block in data.get("content", []):
            block_type = block.get("type")
            if block_type == "text":
                accumulated_content += block.get("text", "")
            elif block_type == "thinking":
                accumulated_thinking += block.get("thinking", "")
                
        usage = data.get("usage", {})
        input_tokens = usage.get("input_tokens", 0)
        output_tokens = usage.get("output_tokens", 0)
        
        if self.detect_empty_response(accumulated_content, accumulated_thinking, [], output_tokens):
            thinking_note = f", thinking: {len(accumulated_thinking)} chars" if accumulated_thinking else ""
            self.log("warn", f"Empty response detected (no content{thinking_note})")
            return ProviderResult(
                success=False,
                error="Empty response (0 output tokens, no content)"
            )
            
        usage_data = UsageData(
            prompt_tokens=input_tokens,
            completion_tokens=output_tokens,
            total_tokens=input_tokens + output_tokens
        )
        
        if not input_tokens and not output_tokens:
            usage_data = self._estimate_usage_fallback(messages, accumulated_content, accumulated_thinking)
            
        return ProviderResult(
            success=True,
            content=accumulated_content,
            thinking_content=accumulated_thinking,
            usage=usage_data
        )

    def fetch_models(self) -> tuple[List[Dict], Optional[str]]:
        """Fetch available models from Anthropic API."""
        if not self.key_manager or not self.key_manager.has_keys():
            return None, "No API keys configured for Anthropic"
            
        current_key = self.key_manager.get_current_key()
        if not current_key:
            return None, "No API key available"
            
        url = f"{self.base_url}/models"
        headers = self._get_headers(current_key)
        
        try:
            response = requests.get(url, headers=headers, timeout=30)
            if response.status_code != 200:
                return None, f"Failed to fetch models ({response.status_code}): {response.text[:200]}"
                
            data = response.json()
            models = []
            for model in data.get("data", []):
                model_id = model.get("id", "")
                models.append({
                    "id": model_id,
                    "name": model.get("display_name", model_id),
                    "context_length": model.get("max_tokens", None),
                    "thinking": any(kw in model_id.lower() for kw in ["opus", "sonnet", "thinking"]),
                    "_raw": model,
                })
            return models, None
        except requests.exceptions.RequestException as e:
            return None, f"Request failed: {e}"
        except Exception as e:
            return None, f"Error fetching models: {e}"
