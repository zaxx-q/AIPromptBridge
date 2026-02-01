#!/usr/bin/env python3
"""
API client for calling OpenRouter, Google Gemini, and custom OpenAI-compatible APIs

This module provides a unified interface using the providers package.
All API requests flow through the provider classes for consistent:
- Retry logic (429→rotate, 5xx→delay, empty→retry)
- Error handling
- Key rotation
- Streaming support
- Thinking/reasoning mode
"""

import base64
import re
import time
from typing import Dict, List, Optional, Tuple, Callable, Any

import requests

from .config import OPENROUTER_URL
from .providers import (
    OpenAICompatibleProvider,
    GeminiNativeProvider,
    ProviderResult,
    CallbackType,
    StreamCallback as ProviderStreamCallback,
)
from .providers.base import estimate_tokens, estimate_message_tokens


# ============================================================
# PROVIDER FACTORY AND MANAGEMENT
# ============================================================

def get_provider_for_type(
    provider_type: str,
    key_manager,
    config: Dict
):
    """
    Get the appropriate provider instance for the given type.
    
    Args:
        provider_type: Provider type (custom, openrouter, google)
        key_manager: Key manager for API keys
        config: Configuration dictionary
    
    Returns:
        Provider instance
    """
    provider_config = {
        "request_timeout": config.get("request_timeout", 120),
        "max_retries": config.get("max_retries", 3),
        "retry_delay": config.get("retry_delay", 5),
        "reasoning_effort": config.get("reasoning_effort", "high"),
        "thinking_budget": config.get("thinking_budget", -1),
        "thinking_level": config.get("thinking_level", "high"),
        "gemini_endpoint": config.get("gemini_endpoint")
    }
    
    if provider_type == "custom":
        url = config.get("custom_url", "")
        return OpenAICompatibleProvider(
            endpoint_type=OpenAICompatibleProvider.ENDPOINT_CUSTOM,
            base_url=url,
            key_manager=key_manager,
            config=provider_config
        )
    
    elif provider_type == "openrouter":
        return OpenAICompatibleProvider(
            endpoint_type=OpenAICompatibleProvider.ENDPOINT_OPENROUTER,
            base_url="https://openrouter.ai/api/v1",
            key_manager=key_manager,
            config=provider_config
        )
    
    elif provider_type == "google":
        # Use native Gemini provider for full feature support
        return GeminiNativeProvider(
            key_manager=key_manager,
            config=provider_config
        )
    
    else:
        raise ValueError(f"Unknown provider type: {provider_type}")



# ============================================================
# BACKWARD COMPATIBILITY - Legacy function signatures
# ============================================================

def call_openrouter_api(key_manager, model, messages, ai_params, timeout):
    """Call OpenRouter API (legacy compatibility)"""
    current_key = key_manager.get_current_key()
    if not current_key:
        return None, "No API key available"
    headers = {
        "Authorization": f"Bearer {current_key}",
        "Content-Type": "application/json",
        "HTTP-Referer": "http://localhost",
    }
    payload = {"model": model, "messages": messages}
    for param, value in ai_params.items():
        if value is not None:
            payload[param] = value
    response = requests.post(OPENROUTER_URL, headers=headers, json=payload, timeout=timeout)
    return response, None


def call_google_api(key_manager, model, messages, ai_params, timeout, config=None):
    """Call Google Gemini API (legacy compatibility - updated safety settings)"""
    current_key = key_manager.get_current_key()
    if not current_key:
        return None, "No API key available"
    base_url = config.get("gemini_endpoint") or "https://generativelanguage.googleapis.com/v1beta"
    url = f"{base_url}/models/{model}:generateContent"
    headers = {"x-goog-api-key": current_key, "Content-Type": "application/json"}
    
    contents = []
    for msg in messages:
        role = "user" if msg["role"] == "user" else "model"
        parts = []
        content = msg.get("content", "")
        if isinstance(content, str):
            parts.append({"text": content})
        elif isinstance(content, list):
            for item in content:
                if item.get("type") == "text":
                    parts.append({"text": item.get("text", "")})
                elif item.get("type") == "image_url":
                    url_data = item.get("image_url", {}).get("url", "")
                    if url_data.startswith("data:"):
                        match = re.match(r"data:([^;]+);base64,(.+)", url_data)
                        if match:
                            mime_type, b64_data = match.groups()
                            parts.append({"inline_data": {"mime_type": mime_type, "data": b64_data}})
        contents.append({"role": role, "parts": parts})
    
    payload = {
        "contents": contents, 
        "generationConfig": {},
        # FIXED: Use BLOCK_NONE instead of OFF (per JSON-request-reference.md)
        "safetySettings": [
            {"category": "HARM_CATEGORY_HARASSMENT", "threshold": "BLOCK_NONE"},
            {"category": "HARM_CATEGORY_HATE_SPEECH", "threshold": "BLOCK_NONE"},
            {"category": "HARM_CATEGORY_SEXUALLY_EXPLICIT", "threshold": "BLOCK_NONE"},
            {"category": "HARM_CATEGORY_DANGEROUS_CONTENT", "threshold": "BLOCK_NONE"},
        ]
    }
    for param, value in ai_params.items():
        if value is not None:
            payload["generationConfig"][param] = value
    response = requests.post(url, headers=headers, json=payload, timeout=timeout)
    return response, None


def call_custom_api(key_manager, url, model, messages, ai_params, timeout):
    """Call custom OpenAI-compatible API (legacy compatibility)"""
    current_key = key_manager.get_current_key()
    if not current_key:
        return None, "No API key available"
    
    # Ensure URL ends with /chat/completions
    if not url.endswith("/chat/completions"):
        url = url.rstrip("/") + "/chat/completions"
    
    headers = {"Authorization": f"Bearer {current_key}", "Content-Type": "application/json"}
    payload = {"model": model, "messages": messages}
    for param, value in ai_params.items():
        if value is not None:
            payload[param] = value
    response = requests.post(url, headers=headers, json=payload, timeout=timeout)
    return response, None


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
    thinking_output: str = "reasoning_content"
) -> Tuple[Optional[str], Optional[str], Optional[Dict], Optional[str]]:
    """
    Unified streaming API call using new provider classes.
    
    Args:
        provider_type: Provider type (custom, openrouter, google)
        messages: List of messages in OpenAI format
        model: Model name
        config: Configuration dictionary
        ai_params: AI generation parameters
        key_managers: Dictionary of key managers
        callback: Callback function (type, content)
        thinking_enabled: Enable thinking/reasoning mode
        thinking_output: How to handle thinking (filter, raw, reasoning_content)
    
    Returns:
        (full_text, reasoning_text, usage_data, error) tuple
    """
    key_manager = key_managers.get(provider_type)
    if not key_manager or not key_manager.has_keys():
        error = f"No API keys configured for provider: {provider_type}"
        callback("error", error)
        return None, None, None, error
    
    # Create provider instance
    provider = get_provider_for_type(provider_type, key_manager, config)
    
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
            if thinking_output != "filter":
                if thinking_output == "raw":
                    callback("text", content)
                else:
                    callback("thinking", content)
        
        elif cb_type == CallbackType.TOOL_CALLS:
            callback("tool_calls", content)
        
        elif cb_type == CallbackType.USAGE:
            usage_data = content
            callback("usage", content)
        
        elif cb_type == CallbackType.DONE:
            callback("done", None)
        
        elif cb_type == CallbackType.ERROR:
            callback("error", content)
    
    # Execute streaming request via provider
    result = provider.generate_stream(
        messages=messages,
        model=model,
        params=params,
        callback=provider_callback,
        thinking_enabled=thinking_enabled
    )
    
    if result.success:
        return (
            result.content,
            result.thinking_content,
            result.usage.to_dict() if result.usage else usage_data,
            None
        )
    else:
        return None, None, None, result.error


def call_custom_api_stream(key_manager, url, model, messages, ai_params, timeout, callback, thinking_output="reasoning_content"):
    """
    Call custom OpenAI-compatible API with streaming support.
    
    REFACTORED: Now uses OpenAICompatibleProvider for consistent retry logic.
    """
    if not key_manager or not key_manager.has_keys():
        return None, None, None, "No API key available"
    
    config = {
        "request_timeout": timeout,
        "custom_url": url,
    }
    
    provider = OpenAICompatibleProvider(
        endpoint_type=OpenAICompatibleProvider.ENDPOINT_CUSTOM,
        base_url=url,
        key_manager=key_manager,
        config=config
    )
    
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
            if thinking_output != "filter":
                if thinking_output == "raw":
                    callback("text", content)
                else:
                    callback("thinking", content)
        elif cb_type == CallbackType.USAGE:
            usage_data = content
            callback("usage", content)
        elif cb_type == CallbackType.DONE:
            callback("done", None)
        elif cb_type == CallbackType.ERROR:
            callback("error", content)
    
    # Determine if thinking should be enabled based on ai_params
    thinking_enabled = "reasoning_effort" in ai_params
    
    params = dict(ai_params)
    if "reasoning_effort" in params:
        del params["reasoning_effort"]  # Provider will add this from config
    
    result = provider.generate_stream(
        messages=messages,
        model=model,
        params=params,
        callback=provider_callback,
        thinking_enabled=thinking_enabled
    )
    
    if result.success:
        return (
            result.content,
            result.thinking_content,
            result.usage.to_dict() if result.usage else usage_data,
            None
        )
    else:
        return None, None, None, result.error


# ============================================================
# NON-STREAMING API - Uses new provider classes  
# ============================================================

def extract_text_from_response(response_json, provider):
    """Extract text from API response"""
    try:
        if provider in ["openrouter", "custom"]:
            choices = response_json.get("choices", [])
            if choices:
                message = choices[0].get("message", {})
                content = message.get("content", "")
                if content:
                    return content
        elif provider == "google":
            candidates = response_json.get("candidates", [])
            if candidates:
                content = candidates[0].get("content", {})
                parts = content.get("parts", [])
                if parts:
                    return parts[0].get("text", "")
        return None
    except Exception as e:
        print(f"    [Error] Failed to extract text: {e}")
        return None


def call_api_with_retry(provider, messages, model_override, config, ai_params, key_managers):
    """
    Call API with retry logic and key rotation.
    
    REFACTORED: Now uses provider classes for consistent retry behavior.
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
    else:
        model = None
    
    if not model:
        return None, f"No model configured for provider: {provider}"
    
    # Create provider and execute
    try:
        prov = get_provider_for_type(provider, key_manager, config)
        
        params = dict(ai_params)
        
        thinking_enabled = config.get("thinking_enabled", False)
        
        result = prov.generate(
            messages=messages,
            model=model,
            params=params,
            thinking_enabled=thinking_enabled
        )
        
        if result.success:
            return result.content, None
        else:
            return None, result.error
    
    except Exception as e:
        return None, f"Provider error: {e}"


def call_api_simple(provider, prompt, image_base64, mime_type, model_override, config, ai_params, key_managers):
    """Simple API call with image and prompt"""
    data_url = f"data:{mime_type};base64,{image_base64}"
    messages = [{
        "role": "user",
        "content": [
            {"type": "image_url", "image_url": {"url": data_url}},
            {"type": "text", "text": prompt}
        ]
    }]
    return call_api_with_retry(provider, messages, model_override, config, ai_params, key_managers)


def call_api_chat(session, config, ai_params, key_managers, provider_override=None, model_override=None, system_instruction=None):
    """
    API call for chat session.
    Uses current config settings for provider/model, not session-stored values.
    
    Args:
        session: Chat session object
        config: Configuration dictionary
        ai_params: AI parameters
        key_managers: Dictionary of key managers
        provider_override: Optional provider override
        model_override: Optional model override
        system_instruction: Optional system instruction to prepend
    """
    messages = session.get_conversation_for_api(include_image=True)
    
    # Prepend system instruction if provided
    if system_instruction:
        messages = [{"role": "system", "content": system_instruction}] + messages
    
    provider = provider_override or config.get("default_provider", "google")
    model = model_override or config.get(f"{provider}_model")
    return call_api_with_retry(provider, messages, model, config, ai_params, key_managers)


def call_api_chat_stream(session, config, ai_params, key_managers, callback, provider_override=None, model_override=None, system_instruction=None):
    """
    API call for chat session with streaming support.
    Uses current config settings for provider/model, not session-stored values.
    
    REFACTORED: Now uses unified streaming with provider classes.
    
    Args:
        session: Chat session object
        config: Configuration dictionary
        ai_params: AI parameters
        key_managers: Dictionary of key managers
        callback: Streaming callback function
        provider_override: Optional provider override
        model_override: Optional model override
        system_instruction: Optional system instruction to prepend
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
    
    if not model:
        error = "No model configured"
        callback("error", error)
        return None, None, None, error
    
    thinking_enabled = config.get("thinking_enabled", False)
    thinking_output = config.get("thinking_output", "reasoning_content")
    
    return call_api_stream_unified(
        provider_type=provider,
        messages=messages,
        model=model,
        config=config,
        ai_params=ai_params,
        key_managers=key_managers,
        callback=callback,
        thinking_enabled=thinking_enabled,
        thinking_output=thinking_output
    )


# ============================================================
# MODEL FETCHING - Uses provider classes
# ============================================================

def fetch_models(config, key_managers, provider_override=None):
    """
    Fetch available models from the configured API.
    
    REFACTORED: Now uses provider classes.
    """
    provider_type = provider_override or config.get("default_provider", "custom")
    
    key_manager = key_managers.get(provider_type)
    if not key_manager or not key_manager.has_keys():
        return None, f"No API keys configured for provider: {provider_type}"
    
    try:
        provider = get_provider_for_type(provider_type, key_manager, config)
        models, error = provider.fetch_models()
        return models, error
    except Exception as e:
        return None, f"Error fetching models: {e}"


def _parse_models_response(data):
    """Parse models response in OpenAI format"""
    # OpenAI format: {"data": [...]}
    if "data" in data and isinstance(data["data"], list):
        models = []
        for model in data["data"]:
            model_id = model.get("id", str(model))
            models.append({
                "id": model_id,
                "name": model_id,
                "owned_by": model.get("owned_by", "unknown"),
                "architecture": model.get("architecture"),
                "context_length": model.get("context_length"),
                "pricing": model.get("pricing"),
            })
        return models, None
    
    # Some APIs return array directly
    if isinstance(data, list):
        models = []
        for model in data:
            if isinstance(model, str):
                models.append({"id": model, "name": model})
            else:
                model_id = model.get("id", str(model))
                models.append({"id": model_id, "name": model_id})
        return models, None
    
    return None, "Unknown models response format"
