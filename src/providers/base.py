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

from src.console import console, HAVE_RICH

class CallbackType(Enum):
    """Types of callback events during streaming"""
    TEXT = "text"
    THINKING = "thinking"
    TOOL_CALLS = "tool_calls"
    USAGE = "usage"
    DONE = "done"
    ERROR = "error"


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
    
    @abstractmethod
    def generate_stream(
        self, 
        messages: List[Dict], 
        model: str, 
        params: Dict,
        callback: StreamCallback,
        thinking_enabled: bool = False
    ) -> ProviderResult:
        """
        Generate a streaming response.
        
        Args:
            messages: List of message dicts in OpenAI format
            model: Model name
            params: Generation parameters (temperature, max_tokens, etc.)
            callback: Callback function for streaming chunks
            thinking_enabled: Whether to enable thinking/reasoning mode
            
        Returns:
            ProviderResult with accumulated content and metadata
        """
        raise NotImplementedError
    
    @abstractmethod
    def generate(
        self,
        messages: List[Dict],
        model: str,
        params: Dict,
        thinking_enabled: bool = False
    ) -> ProviderResult:
        """
        Generate a non-streaming response.
        
        Args:
            messages: List of message dicts in OpenAI format
            model: Model name
            params: Generation parameters
            thinking_enabled: Whether to enable thinking/reasoning mode
            
        Returns:
            ProviderResult with content and metadata
        """
        raise NotImplementedError
    
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
        # Get configurable delay (used for server errors and empty responses)
        retry_delay = self.config.get("retry_delay", self.DEFAULT_RETRY_DELAY)
        
        if reason == RetryReason.RATE_LIMITED:
            return self.RETRY_DELAY_RATE_LIMITED  # Immediate retry with different key
        if reason == RetryReason.AUTH_ERROR:
            return self.RETRY_DELAY_AUTH_ERROR  # Immediate retry with different key
        if reason == RetryReason.SERVER_ERROR:
            return float(retry_delay)  # Use config value
        if reason == RetryReason.EMPTY_RESPONSE:
            return float(retry_delay)  # Use config value
        if reason == RetryReason.NETWORK_ERROR:
            return self.RETRY_DELAY_NETWORK_ERROR
        return 0
    
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