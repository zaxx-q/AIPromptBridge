#!/usr/bin/env python3
"""
API client for calling OpenRouter, Google Gemini, Anthropic Claude, and custom OpenAI-compatible APIs

This module provides a unified interface using the providers package.
All API requests flow through the provider classes for consistent retry, key rotation, and abort logic.
"""

import base64
import re
import time
from typing import Any, Callable, Dict, List, Optional, Tuple

from .providers import (
    BaseProvider,
    CallbackType,
    ProviderResult,
    create_provider,
)
from .providers import (
    StreamCallback as ProviderStreamCallback,
)

# ============================================================
# STREAMING API - Uses new provider classes
# ============================================================


def call_api_stream_unified(
    provider_type: str,
    messages: List[Dict],
    model: str,
    config: Dict,
    ai_params: Dict,
    key_managers: Dict,
    callback: Callable[[str, Any], None],
    thinking_enabled: bool = False,
    abort_event: Optional[Any] = None,
) -> Tuple[Optional[str], Optional[str], Optional[Dict], Optional[str]]:
    """
    Unified streaming API call using new provider classes.

    Args:
        provider_type: Provider type (custom, openrouter, google, anthropic, etc.)
        messages: List of messages in OpenAI format
        model: Model name
        config: Configuration dictionary
        ai_params: AI generation parameters
        key_managers: Dictionary of key managers
        callback: Callback function (type, content)
        thinking_enabled: Enable thinking/reasoning mode
        abort_event: Event to trigger request abort

    Returns:
        (full_text, reasoning_text, usage_data, error) tuple
    """
    key_manager = key_managers.get(provider_type)
    if not key_manager or not key_manager.has_keys():
        error = f"No API keys configured for provider: {provider_type}"
        callback("error", error)
        return None, None, None, error

    # Build provider configuration
    provider_config = {
        "request_timeout": config.get("request_timeout", 120),
        "max_retries": config.get("max_retries", 3),
        "retry_delay": config.get("retry_delay", 5),
        "reasoning_effort": config.get("reasoning_effort", "high"),
        "thinking_budget": config.get("thinking_budget", -1),
        "thinking_level": config.get("thinking_level", "high"),
        "base_url": config.get("base_url"),
        "tts_use_official_endpoint": config.get("tts_use_official_endpoint", False),
    }

    # Create provider instance using registry factory
    try:
        provider = create_provider(provider_type, key_manager, provider_config)
    except ValueError as e:
        callback("error", str(e))
        return None, None, None, str(e)

    # Build params from ai_params
    params = dict(ai_params)

    # Track content for the callback adapter
    accumulated_text = ""
    accumulated_thinking = ""
    usage_data = None

    def provider_callback(cb_type: CallbackType, content: Any):
        nonlocal accumulated_text, accumulated_thinking, usage_data

        if cb_type == CallbackType.TEXT:
            accumulated_text += content
            callback("text", content)

        elif cb_type == CallbackType.THINKING:
            accumulated_thinking += content
            callback("thinking", content)

        elif cb_type == CallbackType.TOOL_CALLS:
            callback("tool_calls", content)

        elif cb_type == CallbackType.USAGE:
            usage_data = content
            callback("usage", content)

        elif cb_type == CallbackType.RESPONSE_PARTS:
            callback("response_parts", content)

        elif cb_type == CallbackType.DONE:
            callback("done", None)

        elif cb_type == CallbackType.ERROR:
            callback("error", content)

        elif cb_type == CallbackType.ABORTED:
            callback("aborted", None)

    # Execute streaming request via provider
    result = provider.generate_stream(
        messages=messages,
        model=model,
        params=params,
        callback=provider_callback,
        thinking_enabled=thinking_enabled,
        abort_event=abort_event,
    )

    if result.success:
        return (result.content, result.thinking_content, result.usage.to_dict() if result.usage else usage_data, None)
    else:
        return None, None, None, result.error


def call_custom_api_stream(key_manager, url, model, messages, ai_params, timeout, callback, abort_event=None):
    """
    Call custom OpenAI-compatible API with streaming support.
    """
    if not key_manager or not key_manager.has_keys():
        return None, None, None, "No API key available"

    config = {
        "request_timeout": timeout,
        "base_url": url,
    }

    # Create provider config
    provider_config = {
        "request_timeout": timeout,
        "max_retries": 3,
        "retry_delay": 5,
        "base_url": url,
    }

    provider = create_provider("custom", key_manager, provider_config)

    # Track accumulated content
    accumulated_text = ""
    accumulated_thinking = ""
    usage_data = None

    def provider_callback(cb_type: CallbackType, content: Any):
        nonlocal accumulated_text, accumulated_thinking, usage_data

        if cb_type == CallbackType.TEXT:
            accumulated_text += content
            callback("text", content)
        elif cb_type == CallbackType.THINKING:
            accumulated_thinking += content
            callback("thinking", content)
        elif cb_type == CallbackType.USAGE:
            usage_data = content
            callback("usage", content)
        elif cb_type == CallbackType.RESPONSE_PARTS:
            callback("response_parts", content)
        elif cb_type == CallbackType.DONE:
            callback("done", None)
        elif cb_type == CallbackType.ERROR:
            callback("error", content)
        elif cb_type == CallbackType.ABORTED:
            callback("aborted", None)

    # Determine if thinking should be enabled based on ai_params
    thinking_enabled = "reasoning_effort" in ai_params

    params = dict(ai_params)
    params.pop("reasoning_effort", None)

    result = provider.generate_stream(
        messages=messages,
        model=model,
        params=params,
        callback=provider_callback,
        thinking_enabled=thinking_enabled,
        abort_event=abort_event,
    )

    if result.success:
        return (result.content, result.thinking_content, result.usage.to_dict() if result.usage else usage_data, None)
    else:
        return None, None, None, result.error


# ============================================================
# NON-STREAMING API - Uses new provider classes
# ============================================================


def call_api_with_retry(
    provider, messages, model_override, config, ai_params, key_managers, abort_event=None, result_out=None
):
    """
    Call API with retry logic and key rotation.
    """
    key_manager = key_managers.get(provider)
    if not key_manager or not key_manager.has_keys():
        return None, f"No API keys configured for provider: {provider}"

    # Determine model
    if model_override:
        model = model_override
    elif provider == "openrouter":
        model = config.get("openrouter_model", "openai/gpt-oss-120b:free")
    elif provider == "google":
        model = config.get("google_model", "gemini-2.5-flash")
    elif provider == "custom":
        model = config.get("custom_model")
    elif provider == "anthropic":
        model = config.get("anthropic_model", "claude-3-5-sonnet-latest")
    else:
        model = None

    if not model:
        return None, f"No model configured for provider: {provider}"

    # Create provider and execute
    try:
        # Build provider configuration
        provider_config = {
            "request_timeout": config.get("request_timeout", 120),
            "max_retries": config.get("max_retries", 3),
            "retry_delay": config.get("retry_delay", 5),
            "reasoning_effort": config.get("reasoning_effort", "high"),
            "thinking_budget": config.get("thinking_budget", -1),
            "thinking_level": config.get("thinking_level", "high"),
            "base_url": config.get("base_url"),
            "tts_use_official_endpoint": config.get("tts_use_official_endpoint", False),
        }

        prov = create_provider(provider, key_manager, provider_config)

        params = dict(ai_params)
        thinking_enabled = config.get("thinking_enabled", False)

        result = prov.generate(
            messages=messages, model=model, params=params, thinking_enabled=thinking_enabled, abort_event=abort_event
        )

        if result.success:
            if isinstance(result_out, dict):
                result_out["gemini_parts"] = result.gemini_parts
            return result.content, None
        else:
            return None, result.error

    except Exception as e:
        return None, f"Provider error: {e}"


def call_api_simple(
    provider, prompt, image_base64, mime_type, model_override, config, ai_params, key_managers, abort_event=None
):
    """Simple API call with image and prompt"""
    data_url = f"data:{mime_type};base64,{image_base64}"
    messages = [
        {
            "role": "user",
            "content": [{"type": "image_url", "image_url": {"url": data_url}}, {"type": "text", "text": prompt}],
        }
    ]
    return call_api_with_retry(
        provider, messages, model_override, config, ai_params, key_managers, abort_event=abort_event
    )


def call_api_chat(
    session,
    config,
    ai_params,
    key_managers,
    provider_override=None,
    model_override=None,
    system_instruction=None,
    abort_event=None,
    result_out=None,
):
    """
    API call for chat session.
    Uses current config settings for provider/model, not session-stored values.
    """
    messages = session.get_conversation_for_api(include_image=True)

    # Prepend system instruction if provided
    if system_instruction:
        messages = [{"role": "system", "content": system_instruction}] + messages

    provider = provider_override or config.get("default_provider", "google")
    model = model_override or config.get(f"{provider}_model")
    return call_api_with_retry(
        provider, messages, model, config, ai_params, key_managers, abort_event=abort_event, result_out=result_out
    )


def call_api_chat_stream(
    session,
    config,
    ai_params,
    key_managers,
    callback,
    provider_override=None,
    model_override=None,
    system_instruction=None,
    abort_event=None,
):
    """
    API call for chat session with streaming support.
    Uses current config settings for provider/model, not session-stored values.
    """
    messages = session.get_conversation_for_api(include_image=True)

    # Prepend system instruction if provided
    if system_instruction:
        messages = [{"role": "system", "content": system_instruction}] + messages

    # Use provided overrides or get from current config
    provider = provider_override or config.get("default_provider", "google")
    model = model_override

    # Determine model if not set
    if not model:
        if provider == "custom":
            model = config.get("custom_model")
        elif provider == "openrouter":
            model = config.get("openrouter_model", "openai/gpt-oss-120b:free")
        elif provider == "google":
            model = config.get("google_model", "gemini-2.5-flash")
        elif provider == "anthropic":
            model = config.get("anthropic_model", "claude-3-5-sonnet-latest")

    if not model:
        error = "No model configured"
        callback("error", error)
        return None, None, None, error

    thinking_enabled = config.get("thinking_enabled", False)

    return call_api_stream_unified(
        provider_type=provider,
        messages=messages,
        model=model,
        config=config,
        ai_params=ai_params,
        key_managers=key_managers,
        callback=callback,
        thinking_enabled=thinking_enabled,
        abort_event=abort_event,
    )


# ============================================================
# MODEL FETCHING - Uses provider classes
# ============================================================


def fetch_models(config, key_managers, provider_override=None):
    """
    Fetch available models from the configured API.
    """
    provider_type = provider_override or config.get("default_provider", "custom")

    key_manager = key_managers.get(provider_type)
    if not key_manager or not key_manager.has_keys():
        return None, f"No API keys configured for provider: {provider_type}"

    try:
        # Build provider configuration
        provider_config = {
            "request_timeout": config.get("request_timeout", 120),
            "max_retries": config.get("max_retries", 3),
            "retry_delay": config.get("retry_delay", 5),
            "base_url": config.get("base_url"),
        }

        provider = create_provider(provider_type, key_manager, provider_config)
        models, error = provider.fetch_models()
        return models, error
    except Exception as e:
        return None, f"Error fetching models: {e}"
