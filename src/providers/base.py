"""
Base Provider Abstract Class

Provides common retry logic, error handling, and callback interface for all providers.
Retry behavior modeled after reverse-proxy/src/upstream/gemini.js and openai-compatible.js
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Callable, Optional, Any, List, Dict
from enum import Enum
import time
import requests
import json
import re

from src.console import console, HAVE_RICH

class CallbackType(Enum):
    """Types of callback events during streaming"""
    TEXT = "text"
    THINKING = "thinking"
    TOOL_CALLS = "tool_calls"
    USAGE = "usage"
    DONE = "done"
    ERROR = "error"
    ABORTED = "aborted"


class AbortedError(Exception):
    """Raised when a request is aborted via abort_event."""
    pass


@dataclass
class UsageData:
    """Token usage information"""
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    estimated: bool = False
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
            "total_tokens": self.total_tokens,
            "estimated": self.estimated
        }


@dataclass
class ProviderResult:
    """Result from a provider request"""
    success: bool
    content: str = ""
    thinking_content: str = ""
    tool_calls: List[Dict] = field(default_factory=list)
    usage: Optional[UsageData] = None
    error: Optional[str] = None
    retry_count: int = 0
    status_code: Optional[int] = None
    _retryable: bool = False
    
    def has_content(self) -> bool:
        """Check if result has any meaningful content"""
        return bool(
            self.content.strip() or 
            self.thinking_content.strip() or 
            self.tool_calls
        )


# Type alias for streaming callback
# Callback signature: (type: CallbackType, content: Any) -> None
StreamCallback = Callable[[CallbackType, Any], None]


class RetryReason(Enum):
    """Reasons for retry"""
    RATE_LIMITED = "rate_limited"
    AUTH_ERROR = "auth_error"
    SERVER_ERROR = "server_error"
    EMPTY_RESPONSE = "empty_response"
    NETWORK_ERROR = "network_error"
    NON_RETRYABLE = "non_retryable"


class BaseProvider(ABC):
    """
    Abstract base provider with common retry logic.
    
    Retry behavior (matching reverse-proxy):
    - 429 Rate Limit: Immediate key rotation, no delay
    - 401/402/403 Auth Error: Immediate key rotation
    - 5xx Server Error: 2 second delay, then retry
    - Empty Response: 2 second delay, then retry (no key rotation)
    - Network Error: Key rotation, 1 second delay
    
    Configuration (from config dict):
    - max_retries: Maximum number of retry attempts (default: 3)
    - retry_delay: Delay between retries in seconds (default: 5, used for server errors)
    """
    
    # Default retry configuration (used when not specified in config)
    DEFAULT_MAX_RETRIES = 3
    DEFAULT_RETRY_DELAY = 5.0  # seconds - configurable from config.ini
    RETRY_DELAY_RATE_LIMITED = 0.0  # Immediate retry with key rotation
    RETRY_DELAY_AUTH_ERROR = 0.0  # Immediate retry with key rotation
    RETRY_DELAY_NETWORK_ERROR = 1.0  # seconds
    
    def __init__(self, name: str, key_manager=None, config: Optional[Dict] = None):
        self.name = name
        self.key_manager = key_manager
        self.config = config or {}
    
    def generate_stream(
        self, 
        messages: List[Dict], 
        model: str, 
        params: Dict,
        callback: StreamCallback,
        thinking_enabled: bool = False,
        abort_event: Optional[Any] = None
    ) -> ProviderResult:
        """Centralized retry loop for streaming requests — subclasses implement _do_generate_stream()."""
        if not self.key_manager or not self.key_manager.has_keys():
            return ProviderResult(success=False, error=f"No API keys configured for {self.name}")
        
        max_retries = self.config.get("max_retries", self.DEFAULT_MAX_RETRIES)
        
        for retry in range(max_retries + 1):
            try:
                self._check_abort(abort_event)
                
                current_key = self.key_manager.get_current_key()
                if not current_key:
                    return ProviderResult(success=False, error="No API key available")
                
                key_num = self.key_manager.get_key_number()
                self.log_request(model, key_num, thinking_enabled, streaming=True, retry=retry)
                
                result = self._do_generate_stream(
                    messages, model, params, callback,
                    thinking_enabled, current_key, abort_event
                )
                
                if result.success:
                    self.log_success(key_num)
                    result.retry_count = retry
                    return result
                
                # Non-success (like empty response)
                if result.error and not self._should_retry_result(result, retry, max_retries):
                    return result
                    
            except AbortedError:
                callback(CallbackType.ABORTED, None)
                return ProviderResult(success=False, error="Request aborted")
                
            except requests.exceptions.Timeout as e:
                if not self._handle_exception_retry(
                    RetryReason.NETWORK_ERROR, retry, max_retries, str(e)
                ):
                    callback(CallbackType.ERROR, "Request timeout")
                    return ProviderResult(success=False, error=str(e), retry_count=retry)
                    
            except requests.exceptions.RequestException as e:
                if not self._handle_exception_retry(
                    RetryReason.NETWORK_ERROR, retry, max_retries, str(e)
                ):
                    callback(CallbackType.ERROR, str(e))
                    return ProviderResult(success=False, error=str(e), retry_count=retry)
                    
            except Exception as e:
                if not self._handle_exception_retry(
                    RetryReason.SERVER_ERROR, retry, max_retries, str(e)
                ):
                    callback(CallbackType.ERROR, str(e))
                    return ProviderResult(success=False, error=str(e), retry_count=retry)
        
        return ProviderResult(success=False, error="Max retries exhausted")
    
    def generate(
        self,
        messages: List[Dict],
        model: str,
        params: Dict,
        thinking_enabled: bool = False,
        abort_event: Optional[Any] = None
    ) -> ProviderResult:
        """Centralized retry loop for non-streaming requests — subclasses implement _do_generate()."""
        if not self.key_manager or not self.key_manager.has_keys():
            return ProviderResult(success=False, error=f"No API keys configured for {self.name}")
        
        max_retries = self.config.get("max_retries", self.DEFAULT_MAX_RETRIES)
        
        for retry in range(max_retries + 1):
            try:
                self._check_abort(abort_event)
                
                current_key = self.key_manager.get_current_key()
                if not current_key:
                    return ProviderResult(success=False, error="No API key available")
                
                key_num = self.key_manager.get_key_number()
                self.log_request(model, key_num, thinking_enabled, streaming=False, retry=retry)
                
                result = self._do_generate(
                    messages, model, params,
                    thinking_enabled, current_key, abort_event
                )
                
                if result.success:
                    self.log_success(key_num)
                    result.retry_count = retry
                    return result
                
                # Non-success (like empty response)
                if result.error and not self._should_retry_result(result, retry, max_retries):
                    return result
                    
            except AbortedError:
                return ProviderResult(success=False, error="Request aborted")
                
            except requests.exceptions.Timeout as e:
                if not self._handle_exception_retry(
                    RetryReason.NETWORK_ERROR, retry, max_retries, str(e)
                ):
                    return ProviderResult(success=False, error=str(e), retry_count=retry)
                    
            except requests.exceptions.RequestException as e:
                if not self._handle_exception_retry(
                    RetryReason.NETWORK_ERROR, retry, max_retries, str(e)
                ):
                    return ProviderResult(success=False, error=str(e), retry_count=retry)
                    
            except Exception as e:
                if not self._handle_exception_retry(
                    RetryReason.SERVER_ERROR, retry, max_retries, str(e)
                ):
                    return ProviderResult(success=False, error=str(e), retry_count=retry)
        
        return ProviderResult(success=False, error="Max retries exhausted")
    
    @abstractmethod
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
        """Single streaming attempt — provider-specific. No retry logic needed."""
        pass

    @abstractmethod
    def _do_generate(
        self,
        messages: List[Dict],
        model: str,
        params: Dict,
        thinking_enabled: bool,
        api_key: str,
        abort_event: Optional[Any]
    ) -> ProviderResult:
        """Single non-streaming attempt — provider-specific. No retry logic needed."""
        pass
    
    @abstractmethod
    def fetch_models(self) -> tuple[List[Dict], Optional[str]]:
        """
        Fetch available models from the provider.
        
        Returns:
            Tuple of (models_list, error_message)
            models_list is a list of dicts with 'id' and 'name' keys
        """
        raise NotImplementedError
    
    def get_retry_reason(self, status_code: int, error_text: str = "") -> RetryReason:
        """
        Determine if an error is retryable and why.
        
        Args:
            status_code: HTTP status code
            error_text: Error response text
            
        Returns:
            RetryReason enum value
        """
        if status_code == 429:
            return RetryReason.RATE_LIMITED
        if status_code in (401, 402, 403):
            return RetryReason.AUTH_ERROR
        if 500 <= status_code < 600:
            return RetryReason.SERVER_ERROR
        return RetryReason.NON_RETRYABLE
    
    def should_retry(self, reason: RetryReason, retry_count: int) -> bool:
        """
        Check if we should retry based on reason and retry count.
        
        Args:
            reason: The RetryReason
            retry_count: Current retry attempt number
            
        Returns:
            True if should retry
        """
        if reason == RetryReason.NON_RETRYABLE:
            return False
        max_retries = self.config.get("max_retries", self.DEFAULT_MAX_RETRIES)
        return retry_count < max_retries
    
    def get_retry_delay(self, reason: RetryReason) -> float:
        """
        Get the delay before retrying based on reason.
        
        Uses config.retry_delay for server errors and empty responses,
        with fixed delays for rate limiting (0) and network errors (1s).
        
        Args:
            reason: The RetryReason
            
        Returns:
            Delay in seconds (0 for immediate retry)
        """
        if reason == RetryReason.RATE_LIMITED:
            return self.RETRY_DELAY_RATE_LIMITED  # Immediate retry with different key (0.0)
        if reason == RetryReason.AUTH_ERROR:
            return self.RETRY_DELAY_AUTH_ERROR  # Immediate retry with different key (0.0)

        # First check for retry_delays dictionary (used in tests to speed up tests)
        retry_delays_dict = self.config.get("retry_delays")
        if isinstance(retry_delays_dict, dict):
            key_map = {
                RetryReason.SERVER_ERROR: "server_error",
                RetryReason.EMPTY_RESPONSE: "empty_response",
                RetryReason.NETWORK_ERROR: "network_error"
            }
            dict_key = key_map.get(reason)
            if dict_key and dict_key in retry_delays_dict:
                return float(retry_delays_dict[dict_key])

        # Get configurable delay (used for server errors and empty responses)
        retry_delay = self.config.get("retry_delay", self.DEFAULT_RETRY_DELAY)
        
        if reason == RetryReason.SERVER_ERROR:
            return float(retry_delay)  # Use config value
        if reason == RetryReason.EMPTY_RESPONSE:
            return float(retry_delay)  # Use config value
        if reason == RetryReason.NETWORK_ERROR:
            return self.RETRY_DELAY_NETWORK_ERROR
        return 0.0
    
    def rotate_key_if_possible(self, reason: str) -> bool:
        """
        Attempt to rotate to the next API key.
        
        Args:
            reason: Reason for rotation (for logging)
            
        Returns:
            True if rotation was successful, False if no more keys
        """
        if self.key_manager:
            new_key = self.key_manager.rotate_key(reason)
            return new_key is not None and self.key_manager.has_more_keys()
        return False
    
    def detect_empty_response(
        self,
        content: str,
        thinking: str,
        tool_calls: List,
        output_tokens: int
    ) -> bool:
        """
        Detect an empty response that should be retried.
        
        A valid response must have actual text content OR tool calls.
        Thinking/reasoning content alone is NOT sufficient — sometimes the
        model streams thinking but cuts off before producing the actual
        response (upstream issue). This ensures we retry in those cases.
        
        Args:
            content: Accumulated text content
            thinking: Accumulated thinking/reasoning content
            tool_calls: List of tool calls
            output_tokens: Number of output tokens from API
            
        Returns:
            True if response is considered empty
        """
        has_actual_content = bool(
            content.strip() or
            tool_calls
        )
        return not has_actual_content
    
    def _check_abort(self, abort_event: Optional[Any]) -> None:
        """Check if request has been aborted."""
        if abort_event and abort_event.is_set():
            raise AbortedError("Request aborted")
            
    def _handle_http_error(self, status_code: int, error_text: str, retry: int, max_retries: int) -> bool:
        """
        Classify HTTP error, rotate key if needed, sleep if needed.
        Returns True if should retry, False if should give up.
        """
        reason = self.get_retry_reason(status_code, error_text)
        if not self.should_retry(reason, retry):
            return False
        delay = self.get_retry_delay(reason)
        error_brief = self.sanitize_api_error(error_text, status_code)
        self.log_retry(reason, retry + 1, delay, error_brief)
        if reason in (RetryReason.RATE_LIMITED, RetryReason.AUTH_ERROR):
            self.rotate_key_if_possible(f"({reason.value})")
        if delay > 0:
            time.sleep(delay)
        return True
        
    def _handle_exception_retry(self, reason: RetryReason, retry: int, max_retries: int, error_brief: str) -> bool:
        """Handle retry on exception (network/timeout)."""
        if not self.should_retry(reason, retry):
            return False
        delay = self.get_retry_delay(reason)
        brief = error_brief[:100]
        self.log_retry(reason, retry + 1, delay, brief)
        if reason == RetryReason.NETWORK_ERROR:
            self.rotate_key_if_possible(f"({reason.value})")
        if delay > 0:
            time.sleep(delay)
        return True
        
    def _should_retry_result(self, result: ProviderResult, retry: int, max_retries: int) -> bool:
        """Determine if a result containing an error should be retried."""
        status_code = getattr(result, "status_code", None)
        if status_code is not None:
            return self._handle_http_error(status_code, result.error or "", retry, max_retries)
            
        if getattr(result, "_retryable", False):
            return True
            
        if result.error and "Empty response" in result.error:
            reason = RetryReason.EMPTY_RESPONSE
            if not self.should_retry(reason, retry):
                return False
            delay = self.get_retry_delay(reason)
            self.log_retry(reason, retry + 1, delay, result.error)
            self.rotate_key_if_possible(f"({reason.value})")
            if delay > 0:
                time.sleep(delay)
            return True
            
        return False
        
    def sanitize_api_error(self, error_text: str, status_code: int = 0) -> str:
        """
        Sanitize raw API error response, stripping HTML or parsing JSON error structures.
        Supports OpenAI/Anthropic/Google formats.
        """
        if not error_text:
            return f"HTTP {status_code}" if status_code else "Unknown error"
            
        # Strip HTML tags if present (e.g. proxy pages or Cloudflare/NGINX blocks)
        if error_text.strip().startswith("<!DOCTYPE") or error_text.strip().startswith("<html"):
            stripped = re.sub(r'<[^>]+>', ' ', error_text)
            stripped = " ".join(stripped.split())
            return f"HTTP {status_code}: {stripped[:80]}" if status_code else stripped[:100]
            
        try:
            error_data = json.loads(error_text)
            if "error" in error_data:
                error_obj = error_data["error"]
                if isinstance(error_obj, dict):
                    msg = error_obj.get("message", "")
                    err_type = error_obj.get("type") or error_obj.get("status") or ""
                    if msg:
                        brief = msg[:80]
                        if err_type:
                            brief = f"{err_type}: {brief}"[:100]
                        return brief
                    if err_type:
                        return f"Error status/type: {err_type}"
                elif isinstance(error_obj, str):
                    return error_obj[:100]
                    
            if "message" in error_data:
                return str(error_data["message"])[:100]
        except Exception:
            pass
            
        first_line = error_text.split('\n')[0].strip()[:100]
        if status_code:
            return f"HTTP {status_code}: {first_line[:80]}"
        return first_line or "Unknown error"
        
    def _estimate_usage_fallback(self, messages: List[Dict], content: str, thinking: str) -> UsageData:
        """Estimate token usage when the API does not provide it."""
        input_tokens = estimate_message_tokens(messages)
        output_tokens = estimate_tokens(content + thinking)
        return UsageData(
            prompt_tokens=input_tokens,
            completion_tokens=output_tokens,
            total_tokens=input_tokens + output_tokens,
            estimated=True
        )

    def log(self, level: str, message: str, **kwargs):
        """
        Log a message with provider context.
        
        Args:
            level: Log level (info, warn, error, debug)
            message: Log message
            **kwargs: Additional context
        """
        prefix = f"[bold dim][{self.name}][/bold dim]"
        if HAVE_RICH:
            details = ""
            if kwargs:
                details = " (" + ", ".join(f"[cyan]{k}[/cyan]=[yellow]{v}[/yellow]" for k, v in kwargs.items()) + ")"
            
            style = "white"
            if level == "error": style = "red"
            elif level == "warn": style = "yellow"
            elif level == "debug": style = "dim"
            
            console.print(f"    {prefix} [{style}]{message}[/{style}]{details}")
        else:
            prefix = f"[{self.name}]"
            if kwargs:
                details = ", ".join(f"{k}={v}" for k, v in kwargs.items())
                print(f"    {prefix} {message} ({details})")
            else:
                print(f"    {prefix} {message}")
    
    def log_request(self, model: str, key_num: int, thinking: bool, streaming: bool, retry: int = 0):
        """Log request start"""
        retry_str = f", retry {retry}" if retry > 0 else ""
        self.log("info", f"Request to {model} with key #{key_num} (thinking: {thinking}, stream: {streaming}{retry_str})")
    
    def log_success(self, key_num: int):
        """Log successful completion"""
        self.log("info", f"Request completed successfully with key #{key_num}")
    
    def log_retry(self, reason: RetryReason, retry_count: int, delay: float, error_detail: str = ""):
        """Log retry attempt with optional error detail"""
        max_retries = self.config.get("max_retries", self.DEFAULT_MAX_RETRIES)
        delay_str = f" after {delay}s delay" if delay > 0 else " immediately"
        detail_str = f": {error_detail}" if error_detail else ""
        self.log("warn", f"{reason.value}{detail_str}, retrying{delay_str} ({retry_count}/{max_retries})")
    
    def log_error(self, message: str, status_code: int = 0):
        """Log error"""
        if status_code:
            self.log("error", f"{message} (status: {status_code})")
        else:
            self.log("error", message)


def estimate_tokens(text: str) -> int:
    """Estimate token count (roughly 4 characters per token)"""
    if not text:
        return 0
    return max(1, len(text) // 4)


def estimate_message_tokens(messages: List[Dict]) -> int:
    """Estimate token count for a list of messages"""
    total = 0
    for msg in messages:
        content = msg.get("content", "")
        if isinstance(content, str):
            total += estimate_tokens(content)
        elif isinstance(content, list):
            for item in content:
                if item.get("type") == "text":
                    total += estimate_tokens(item.get("text", ""))
                elif item.get("type") == "image_url":
                    # Estimate ~85 tokens per image (conservative)
                    total += 85
        # Add overhead for role, etc.
        total += 4
    return total