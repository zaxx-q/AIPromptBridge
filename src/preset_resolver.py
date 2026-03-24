#!/usr/bin/env python3
"""
Model Preset Resolver

Central module for resolving model presets at request time.
When an action has a `model_preset` field, this module merges the preset's
fields into the runtime config/ai_params, falling back to global config
values for any fields not specified by the preset.

Usage:
    from src.preset_resolver import resolve_preset

    resolved = resolve_preset(action, config, ai_params, key_managers)
    # resolved.provider, resolved.model, resolved.config, resolved.ai_params
"""

import logging
from dataclasses import dataclass, field
from typing import Dict, Any, Optional


# Fields that override config values
CONFIG_OVERRIDE_FIELDS = {
    "provider",       # -> default_provider
    "model",          # -> {provider}_model
    "streaming",      # -> streaming_enabled
    "thinking",       # -> thinking_enabled
    "thinking_budget", # -> thinking_budget
    "thinking_level", # -> thinking_level
    "reasoning_effort", # -> reasoning_effort
    "temperature",    # -> temperature (in ai_params)
    "max_tokens",     # -> max_tokens (in ai_params)
    "request_timeout", # -> request_timeout
    "custom_url",     # -> custom_url
    "gemini_endpoint", # -> gemini_endpoint
    "api_key_name",   # -> selects key by name
}


@dataclass
class ResolvedPreset:
    """Result of preset resolution with all effective settings."""
    provider: str
    model: str
    streaming: bool
    thinking_enabled: bool
    config: Dict[str, Any]
    ai_params: Dict[str, Any]
    key_managers: Dict[str, Any]
    preset_name: Optional[str] = None


def resolve_preset(
    action: Optional[Dict[str, Any]],
    config: Dict[str, Any],
    ai_params: Dict[str, Any],
    key_managers: Dict[str, Any],
) -> ResolvedPreset:
    """
    Resolve effective settings for an action, applying model preset overrides.

    Resolution chain:
        Action's model_preset -> Preset fields -> config.ini globals (fallback)

    Args:
        action: Action config dict (may contain "model_preset" field).
                 Can be None for actions without preset support.
        config: Global config dictionary (from config.ini).
        ai_params: Global AI parameters dictionary.
        key_managers: Dictionary of KeyManager instances.

    Returns:
        ResolvedPreset with effective provider, model, streaming, thinking,
        and merged config/ai_params dicts ready for the request pipeline.
    """
    # Start with defaults from global config
    provider = config.get("default_provider", "google")
    model = config.get(f"{provider}_model", "")
    streaming = config.get("streaming_enabled", True)
    thinking = config.get("thinking_enabled", False)

    # Build merged dicts (shallow copy to avoid mutating originals)
    merged_config = dict(config)
    merged_ai_params = dict(ai_params)
    effective_key_managers = key_managers

    preset_name = None

    if action:
        preset_name = action.get("model_preset")

    if preset_name:
        preset = _get_preset(preset_name)
        if preset:
            # Apply preset overrides
            if "provider" in preset:
                provider = preset["provider"]
                merged_config["default_provider"] = provider

            if "model" in preset:
                model = preset["model"]
                # Also set into the provider-specific key so downstream code
                # that reads e.g. config["google_model"] still works
                merged_config[f"{provider}_model"] = model

            if "streaming" in preset:
                streaming = preset["streaming"]
                merged_config["streaming_enabled"] = streaming

            if "thinking" in preset:
                thinking = preset["thinking"]
                merged_config["thinking_enabled"] = thinking

            if "thinking_budget" in preset:
                merged_config["thinking_budget"] = preset["thinking_budget"]

            if "thinking_level" in preset:
                merged_config["thinking_level"] = preset["thinking_level"]

            if "reasoning_effort" in preset:
                merged_config["reasoning_effort"] = preset["reasoning_effort"]

            if "temperature" in preset:
                merged_ai_params["temperature"] = preset["temperature"]

            if "max_tokens" in preset:
                merged_ai_params["max_tokens"] = preset["max_tokens"]

            if "request_timeout" in preset:
                merged_config["request_timeout"] = preset["request_timeout"]

            if "custom_url" in preset:
                merged_config["custom_url"] = preset["custom_url"]

            if "gemini_endpoint" in preset:
                merged_config["gemini_endpoint"] = preset["gemini_endpoint"]

            if "api_key_name" in preset:
                resolved_km = _resolve_key_manager_by_name(
                    preset["api_key_name"], provider, key_managers
                )
                if resolved_km is not None:
                    effective_key_managers = dict(key_managers)
                    effective_key_managers[provider] = resolved_km
        else:
            logging.warning(
                f"[PresetResolver] Preset '{preset_name}' not found, using defaults"
            )

    # If model is still empty (provider changed but no model in preset),
    # try to read from global config for the new provider
    if not model and provider:
        model = config.get(f"{provider}_model", "")

    return ResolvedPreset(
        provider=provider,
        model=model,
        streaming=streaming,
        thinking_enabled=thinking,
        config=merged_config,
        ai_params=merged_ai_params,
        key_managers=effective_key_managers,
        preset_name=preset_name,
    )


def _get_preset(name: str) -> Optional[Dict[str, Any]]:
    """Look up a preset by name from PromptsConfig."""
    try:
        from .gui.prompts import PromptsConfig
        pc = PromptsConfig.get_instance()
        return pc.get_model_preset(name)
    except Exception as e:
        logging.error(f"[PresetResolver] Failed to look up preset '{name}': {e}")
        return None


def _resolve_key_manager_by_name(
    key_name: str,
    provider: str,
    key_managers: Dict[str, Any],
):
    """
    Create a KeyManager that uses a specific key identified by its name.

    Args:
        key_name: The display name of the key (from config.ini inline comment).
        provider: Provider type to look up keys for.
        key_managers: Current key managers.

    Returns:
        A new KeyManager with only the named key, or None if not found.
    """
    km = key_managers.get(provider)
    if not km:
        return None

    # KeyManager stores key_names alongside keys (if available)
    named_key = km.get_key_by_name(key_name)
    if named_key:
        from .key_manager import KeyManager
        return KeyManager([named_key], provider)

    logging.warning(
        f"[PresetResolver] API key named '{key_name}' not found for provider '{provider}'"
    )
    return None
