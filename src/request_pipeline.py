#!/usr/bin/env python3
"""
Unified API Request Pipeline
All API requests flow through this module for consistent logging and handling.

This pipeline ensures:
1. Consistent console logging for ALL requests regardless of origin
2. Token usage tracking for every request
3. Retry status logging
4. Unified error handling
"""

import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, List, Optional

from src.console import HAVE_RICH, console, print_panel


class RequestOrigin(Enum):
    """Origin of an API request - helps identify request source in logs"""

    CHAT_WINDOW = "chat_window"
    POPUP_INPUT = "popup_input"
    POPUP_PROMPT = "popup_prompt"
    SNIP_TOOL = "snip_tool"
    AUDIO_TOOL = "audio_tool"
    TTS_TOOL = "tts_tool"


@dataclass
class RequestContext:
    """Context for a single API request with complete tracking"""

    # Request parameters
    origin: RequestOrigin
    provider: str
    model: str
    streaming: bool
    thinking_enabled: bool
    session_id: Optional[str] = None

    # Populated after response
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    estimated: bool = False
    elapsed_time: float = 0.0
    retry_count: int = 0

    # Response content
    response_text: str = ""
    reasoning_text: str = ""
    tool_calls: List[Dict] = field(default_factory=list)
    error: Optional[str] = None
    gemini_parts: Optional[List[Dict]] = None

    def get_usage_summary(self) -> str:
        """Get formatted usage summary"""
        est = " (est)" if self.estimated else ""
        return f"📊 Tokens: {self.input_tokens} in | {self.output_tokens} out | {self.total_tokens} total{est}"


@dataclass
class StreamCallback:
    """Callbacks for streaming response handling"""

    on_text: Optional[Callable[[str], None]] = None
    on_thinking: Optional[Callable[[str], None]] = None
    on_usage: Optional[Callable[[Dict], None]] = None
    on_done: Optional[Callable[[], None]] = None
    on_error: Optional[Callable[[str], None]] = None
    on_tool_calls: Optional[Callable[[List], None]] = None
    on_gemini_parts: Optional[Callable[[List], None]] = None


class RequestPipeline:
    """
    Unified request pipeline with mandatory logging.

    All API requests should flow through this pipeline to ensure:
    - Consistent console output showing request type, model, origin
    - Token usage logging for every request
    - Retry attempt visibility
    - Error tracking
    """

    @staticmethod
    def log_request_start(ctx: RequestContext):
        """Log when request starts"""
        if HAVE_RICH:
            info = [
                f"[bold]Provider:[/bold] {ctx.provider}",
                f"[bold]Model:[/bold] {ctx.model}",
                f"[bold]Streaming:[/bold] {'[green]ON[/green]' if ctx.streaming else '[red]OFF[/red]'}",
                f"[bold]Thinking:[/bold] {'[green]ON[/green]' if ctx.thinking_enabled else '[red]OFF[/red]'}",
            ]
            if ctx.session_id:
                info.append(f"[bold]Session:[/bold] {ctx.session_id}")

            console.print()
            print_panel(
                "\n".join(info),
                title=f"[bold]API REQUEST: {ctx.origin.value}[/bold]",
                border_style="blue",
                style="white",
            )
        else:
            print(f"\n{'=' * 60}")
            print(f"[API REQUEST] {ctx.origin.value}")
            print(f"  Provider: {ctx.provider}")
            print(f"  Model: {ctx.model}")
            print(f"  Streaming: {'ON' if ctx.streaming else 'OFF'}")
            print(f"  Thinking: {'ON' if ctx.thinking_enabled else 'OFF'}")
            if ctx.session_id:
                print(f"  Session: {ctx.session_id}")

    @staticmethod
    def log_request_complete(ctx: RequestContext):
        """Log when request completes - always includes token usage"""
        if HAVE_RICH:
            style = "green" if not ctx.error else "red"
            if ctx.error:
                # Use brief error in title to avoid stretching the panel
                error_brief = ctx.error[:80] + "..." if len(ctx.error) > 80 else ctx.error
                title = f"[bold red]FAILED: {error_brief}[/bold red]"
            else:
                title = "[bold green]SUCCESS[/bold green]"

            summary = []
            if not ctx.error:
                summary.append(f"Length: {len(ctx.response_text)} chars")
                if ctx.reasoning_text:
                    summary.append(f"Thinking: {len(ctx.reasoning_text)} chars")

            summary.append(f"Elapsed: {ctx.elapsed_time:.2f}s")
            if ctx.retry_count > 0:
                summary.append(f"Retries: {ctx.retry_count}")

            # Show full error inside the panel body (not title) so it wraps naturally
            if ctx.error and len(ctx.error) > 80:
                summary.insert(0, ctx.error)

            summary.append(f"\n{ctx.get_usage_summary()}")

            print_panel("\n".join(summary), title=title, border_style=style, style="white")
            console.print()
        else:
            if ctx.error:
                print(f"  [FAILED] {ctx.error}")
                if ctx.elapsed_time > 0:
                    print(f"  Elapsed: {ctx.elapsed_time:.1f}s")
            else:
                print(f"  [SUCCESS] {len(ctx.response_text)} chars")
                if ctx.reasoning_text:
                    print(f"  Thinking: {len(ctx.reasoning_text)} chars")
                print(f"  Elapsed: {ctx.elapsed_time:.1f}s")
                if ctx.retry_count > 0:
                    print(f"  Retries: {ctx.retry_count}")

            # ALWAYS log token usage
            print(f"  {ctx.get_usage_summary()}")
            print(f"{'=' * 60}\n")

    @staticmethod
    def log_raw_response(ctx: RequestContext, log_full: bool = False):
        """
        Log raw AI output to console.

        Args:
            ctx: Request context with response
            log_full: If True, log full content; if False, log truncated
        """
        if ctx.response_text:
            if HAVE_RICH:
                if log_full:
                    print_panel(
                        ctx.response_text,
                        title=f"RAW AI OUTPUT ({ctx.origin.value})",
                        border_style="dim white",
                    )
                else:
                    preview = ctx.response_text[:200] + "..." if len(ctx.response_text) > 200 else ctx.response_text
                    console.print(f"[dim]Preview: {preview}[/dim]")
            else:
                if log_full:
                    print(f"\n--- RAW AI OUTPUT ({ctx.origin.value}) ---")
                    print(ctx.response_text)
                    print("--- END RAW OUTPUT ---\n")
                else:
                    preview = ctx.response_text[:200] + "..." if len(ctx.response_text) > 200 else ctx.response_text
                    print(f"  Preview: {preview}")

    @staticmethod
    def execute_streaming(
        ctx: RequestContext,
        session,
        config: Dict,
        ai_params: Dict,
        key_managers: Dict,
        callbacks: StreamCallback,
        log_raw: bool = False,
        abort_event: Optional[Any] = None,
    ) -> RequestContext:
        """
        Execute streaming API request with logging.

        Args:
            ctx: Request context
            session: Chat session object
            config: Configuration dictionary
            ai_params: AI parameters
            key_managers: Dictionary of key managers
            callbacks: Streaming callbacks
            log_raw: Whether to log raw AI output
            abort_event: Optional abort event

        Returns:
            Updated RequestContext with response data
        """
        from .api_client import call_api_chat_stream

        RequestPipeline.log_request_start(ctx)
        start_time = time.time()

        # Wrap the user's callback to capture data
        def stream_wrapper(data_type, content):
            if data_type == "text":
                ctx.response_text += content
                if callbacks.on_text:
                    callbacks.on_text(content)

            elif data_type == "thinking":
                ctx.reasoning_text += content
                if callbacks.on_thinking:
                    callbacks.on_thinking(content)

            elif data_type == "tool_calls":
                if isinstance(content, list):
                    ctx.tool_calls.extend(content)
                if callbacks.on_tool_calls:
                    callbacks.on_tool_calls(content)

            elif data_type == "usage":
                ctx.input_tokens = content.get("prompt_tokens", 0)
                ctx.output_tokens = content.get("completion_tokens", 0)
                ctx.total_tokens = content.get("total_tokens", 0)
                ctx.estimated = content.get("estimated", False)
                if callbacks.on_usage:
                    callbacks.on_usage(content)

            elif data_type == "done":
                if callbacks.on_done:
                    callbacks.on_done()

            elif data_type == "response_parts":
                ctx.gemini_parts = content
                if callbacks.on_gemini_parts:
                    callbacks.on_gemini_parts(content)

            elif data_type == "error":
                ctx.error = content
                if callbacks.on_error:
                    callbacks.on_error(content)

            elif data_type == "aborted":
                ctx.error = "Request aborted"
                if callbacks.on_error:
                    callbacks.on_error("Request aborted")

        # Execute the actual API call — pass model_override so per-session
        # model selection is respected in the streaming path
        text, reasoning, usage, error = call_api_chat_stream(
            session,
            config,
            ai_params,
            key_managers,
            stream_wrapper,
            model_override=ctx.model,
            abort_event=abort_event,
        )

        ctx.elapsed_time = time.time() - start_time
        if error:
            ctx.error = error
        else:
            if text is not None:
                ctx.response_text = text
            if reasoning is not None:
                ctx.reasoning_text = reasoning

        RequestPipeline.log_request_complete(ctx)

        if log_raw:
            RequestPipeline.log_raw_response(ctx, log_full=True)

        return ctx

    @staticmethod
    def execute_simple(
        ctx: RequestContext,
        messages: list,
        config: Dict,
        ai_params: Dict,
        key_managers: Dict,
        log_raw: bool = False,
        abort_event: Optional[Any] = None,
    ) -> RequestContext:
        """
        Execute non-streaming API request with logging.

        Args:
            ctx: Request context
            messages: List of messages
            config: Configuration dictionary
            ai_params: AI parameters
            key_managers: Dictionary of key managers
            log_raw: Whether to log raw AI output
            abort_event: Optional abort event

        Returns:
            Updated RequestContext with response data
        """
        from .api_client import call_api_with_retry
        from .providers.base import estimate_message_tokens, estimate_tokens

        RequestPipeline.log_request_start(ctx)
        start_time = time.time()

        result_out = {}
        text, error = call_api_with_retry(
            provider=ctx.provider,
            messages=messages,
            model_override=ctx.model,
            config=config,
            ai_params=ai_params,
            key_managers=key_managers,
            abort_event=abort_event,
            result_out=result_out,
        )

        ctx.elapsed_time = time.time() - start_time

        if error:
            ctx.error = error
        else:
            ctx.response_text = text or ""
            ctx.gemini_parts = result_out.get("gemini_parts")
            # Estimate tokens for non-streaming response
            ctx.input_tokens = estimate_message_tokens(messages)
            ctx.output_tokens = estimate_tokens(text or "")
            ctx.total_tokens = ctx.input_tokens + ctx.output_tokens
            ctx.estimated = True

        RequestPipeline.log_request_complete(ctx)

        if log_raw and not error:
            RequestPipeline.log_raw_response(ctx, log_full=True)

        return ctx

    @staticmethod
    def execute_unified_stream(
        ctx: RequestContext,
        messages: List[Dict],
        config: Dict,
        ai_params: Dict,
        key_managers: Dict,
        callbacks: StreamCallback,
        log_raw: bool = False,
        abort_event: Optional[Any] = None,
    ) -> RequestContext:
        """
        Execute streaming API request using the unified streaming API.

        This is the preferred method for new code - uses call_api_stream_unified
        which supports all providers consistently.

        Args:
            ctx: Request context
            messages: List of messages in OpenAI format
            config: Configuration dictionary
            ai_params: AI parameters
            key_managers: Dictionary of key managers
            callbacks: Streaming callbacks
            log_raw: Whether to log raw AI output
            abort_event: Optional abort event

        Returns:
            Updated RequestContext with response data
        """
        from .api_client import call_api_stream_unified

        RequestPipeline.log_request_start(ctx)
        start_time = time.time()

        # Wrap callbacks
        def stream_wrapper(data_type, content):
            if data_type == "text":
                ctx.response_text += content
                if callbacks.on_text:
                    callbacks.on_text(content)

            elif data_type == "thinking":
                ctx.reasoning_text += content
                if callbacks.on_thinking:
                    callbacks.on_thinking(content)

            elif data_type == "tool_calls":
                if isinstance(content, list):
                    ctx.tool_calls.extend(content)
                if callbacks.on_tool_calls:
                    callbacks.on_tool_calls(content)

            elif data_type == "usage":
                ctx.input_tokens = content.get("prompt_tokens", 0)
                ctx.output_tokens = content.get("completion_tokens", 0)
                ctx.total_tokens = content.get("total_tokens", 0)
                ctx.estimated = content.get("estimated", False)
                if callbacks.on_usage:
                    callbacks.on_usage(content)

            elif data_type == "done":
                if callbacks.on_done:
                    callbacks.on_done()

            elif data_type == "response_parts":
                ctx.gemini_parts = content
                if callbacks.on_gemini_parts:
                    callbacks.on_gemini_parts(content)

            elif data_type == "error":
                ctx.error = content
                if callbacks.on_error:
                    callbacks.on_error(content)

            elif data_type == "aborted":
                ctx.error = "Request aborted"
                if callbacks.on_error:
                    callbacks.on_error("Request aborted")

        text, reasoning, usage, error = call_api_stream_unified(
            provider_type=ctx.provider,
            messages=messages,
            model=ctx.model,
            config=config,
            ai_params=ai_params,
            key_managers=key_managers,
            callback=stream_wrapper,
            thinking_enabled=ctx.thinking_enabled,
            abort_event=abort_event,
        )

        ctx.elapsed_time = time.time() - start_time
        if error:
            ctx.error = error
        else:
            if text is not None:
                ctx.response_text = text
            if reasoning is not None:
                ctx.reasoning_text = reasoning

        RequestPipeline.log_request_complete(ctx)

        if log_raw and not error:
            RequestPipeline.log_raw_response(ctx, log_full=True)

        return ctx


# Convenience function for creating request contexts
def create_request_context(
    origin: RequestOrigin,
    provider: str,
    model: str,
    streaming: bool = True,
    thinking_enabled: bool = False,
    session_id: Optional[str] = None,
) -> RequestContext:
    """Create a new request context"""
    return RequestContext(
        origin=origin,
        provider=provider,
        model=model,
        streaming=streaming,
        thinking_enabled=thinking_enabled,
        session_id=session_id,
    )
