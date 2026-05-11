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
    "api_key_pool",   # -> selects key pool (overrides provider_pool_map)
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

            if "api_key_pool" in preset or "api_key_name" in preset:
                resolved_km = _resolve_key_override(
                    preset.get("api_key_pool", ""),
                    preset.get("api_key_name", ""),
                    provider,
                    key_managers,
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


def resolve_preset_by_name(
    preset_name: str,
    config: Dict[str, Any],
    ai_params: Dict[str, Any],
    key_managers: Dict[str, Any],
) -> ResolvedPreset:
    """
    Resolve a preset by name (convenience wrapper for chat/audio window preset selector).

    Creates a synthetic action dict and delegates to resolve_preset().

    Args:
        preset_name: Name of the model preset to resolve.
        config: Global config dictionary.
        ai_params: Global AI parameters dictionary.
        key_managers: Dictionary of KeyManager instances.

    Returns:
        ResolvedPreset with effective settings from the named preset.
    """
    action = {"model_preset": preset_name}
    return resolve_preset(action, config, ai_params, key_managers)


def _get_preset(name: str) -> Optional[Dict[str, Any]]:
    """Look up a preset by name from PromptsConfig."""
    try:
        from .gui.prompts import PromptsConfig
        pc = PromptsConfig.get_instance()
        return pc.get_model_preset(name)
    except Exception as e:
        logging.error(f"[PresetResolver] Failed to look up preset '{name}': {e}")
        return None


def _resolve_key_override(
    pool_id: str,
    key_name: str,
    provider: str,
    key_managers: Dict[str, Any],
):
    """
    Resolve a key override from preset fields.

    Resolution order:
        1. If *pool_id* is set, build a KeyManager from that pool.
           If *key_name* is also set, filter to only the named key
           within that pool.
        2. If only *key_name* is set, look up the named key within
           the provider's default pool.

    Returns:
        A new KeyManager, or None if nothing matched.
    """
    try:
        from .key_store import KeyStore
        key_store = KeyStore.get_instance()
    except Exception:
        # Fallback: try legacy KeyManager.get_key_by_name()
        if key_name:
            return _legacy_resolve_by_name(key_name, provider, key_managers)
        return None

    # Case 1: pool override
    if pool_id and key_store.pool_exists(pool_id):
        if key_name:
            # Find specific key within the overridden pool
            keys_data = key_store.get_pool(pool_id)
            name_lower = key_name.lower().strip()
            for kd in keys_data:
                if kd.get("name", "").lower().strip() == name_lower:
                    from .key_manager import KeyManager
                    return KeyManager([kd["key"]], provider)
            logging.warning(
                f"[PresetResolver] Key '{key_name}' not found in pool '{pool_id}'"
            )
        # Return all keys from the overridden pool
        return key_store.build_key_manager_for_pool(pool_id, provider)

    # Case 2: key name only — resolve within provider's default pool
    if key_name:
        pool_for_provider = key_store.get_provider_pool_id(provider)
        keys_data = key_store.get_pool(pool_for_provider)
        name_lower = key_name.lower().strip()
        for kd in keys_data:
            if kd.get("name", "").lower().strip() == name_lower:
                from .key_manager import KeyManager
                return KeyManager([kd["key"]], provider)
        logging.warning(
            f"[PresetResolver] Key '{key_name}' not found in pool '{pool_for_provider}' for provider '{provider}'"
        )

    return None


def _legacy_resolve_by_name(
    key_name: str,
    provider: str,
    key_managers: Dict[str, Any],
):
    """Fallback: resolve key by name using KeyManager (pre-pool compat)."""
    km = key_managers.get(provider)
    if not km:
        return None
    named_key = km.get_key_by_name(key_name)
    if named_key:
        from .key_manager import KeyManager
        return KeyManager([named_key], provider)
    logging.warning(
        f"[PresetResolver] API key named '{key_name}' not found for provider '{provider}'"
    )
    return None
