#!/usr/bin/env python3
"""
Connection Profile Resolver

Resolves effective settings for API requests by merging:
  1. Action's connection_profile field (per-action override)
  2. Active global connection profile (from profiles.json)
  3. Hard-coded defaults (last resort)

Usage:
    from src.profile_resolver import resolve_profile

    resolved = resolve_profile(action, config, ai_params, key_managers)
    # resolved.provider, resolved.model, resolved.config, resolved.ai_params
"""

import logging
from dataclasses import dataclass
from typing import Dict, Any, Optional


@dataclass
class ResolvedProfile:
    """Result of profile resolution with all effective settings."""
    provider: str
    model: str
    streaming: bool
    thinking_enabled: bool
    config: Dict[str, Any]
    ai_params: Dict[str, Any]
    key_managers: Dict[str, Any]
    profile_name: Optional[str] = None


def resolve_profile(
    action: Optional[Dict[str, Any]],
    config: Dict[str, Any],
    ai_params: Dict[str, Any],
    key_managers: Dict[str, Any],
) -> ResolvedProfile:
    """
    Resolve effective settings for an action, applying connection profile overrides.

    Resolution chain:
    Action's connection_profile -> SESSION_OVERRIDES -> ACTIVE_PROFILE -> hard-coded defaults

    The merged_config dict always contains config-style keys (default_provider,
    {provider}_model, streaming_enabled, etc.) for provider compatibility,
    regardless of whether an action profile is specified.

    Args:
        action: Action config dict (may contain "connection_profile" field).
        config: Runtime config dictionary (non-connection keys only after migration).
        ai_params: Runtime AI parameters dictionary.
        key_managers: Dictionary of KeyManager instances.

    Returns:
        ResolvedProfile with effective provider, model, streaming, thinking,
        and merged config/ai_params dicts ready for the request pipeline.
    """
    from . import web_server as _ws

    # Step 1: Base values from ACTIVE_PROFILE + SESSION_OVERRIDES
    active = _ws.ACTIVE_PROFILE
    provider = _ws.SESSION_OVERRIDES.get("provider", active.provider if active else "google")
    model = _ws.SESSION_OVERRIDES.get("model", active.model if active else "")
    streaming = _ws.SESSION_OVERRIDES.get("streaming", active.streaming if active else True)
    thinking = _ws.SESSION_OVERRIDES.get("thinking", active.thinking if active else False)

    merged_config = dict(config)
    merged_ai_params = dict(ai_params)
    effective_key_managers = key_managers

    # Step 2: Always write config-style connection keys into merged_config
    # This ensures providers receive the keys they expect, regardless
    # of whether CONFIG has connection keys populated.
    merged_config["default_provider"] = provider
    merged_config[f"{provider}_model"] = model
    merged_config["streaming_enabled"] = streaming
    merged_config["thinking_enabled"] = thinking

    if active:
        if active.thinking_budget is not None:
            merged_config["thinking_budget"] = active.thinking_budget
        if active.thinking_level:
            merged_config["thinking_level"] = active.thinking_level
        if active.reasoning_effort:
            merged_config["reasoning_effort"] = active.reasoning_effort
        if active.request_timeout is not None:
            merged_config["request_timeout"] = active.request_timeout
        if active.custom_url:
            merged_config["custom_url"] = active.custom_url
        if active.gemini_endpoint:
            merged_config["gemini_endpoint"] = active.gemini_endpoint
        if active.temperature is not None:
            merged_ai_params["temperature"] = active.temperature
        if active.max_tokens is not None:
            merged_ai_params["max_tokens"] = active.max_tokens

    # Step 3: If action specifies a profile, override with action profile values
    profile_name = None

    if action:
        profile_name = action.get("connection_profile")

        if profile_name:
            profile = _get_profile(profile_name)
            if profile:
                if profile.provider:
                    provider = profile.provider
                    merged_config["default_provider"] = provider

                if profile.model:
                    model = profile.model
                    merged_config[f"{provider}_model"] = model

                streaming = profile.streaming
                merged_config["streaming_enabled"] = streaming

                thinking = profile.thinking
                merged_config["thinking_enabled"] = thinking

                if profile.thinking_budget is not None:
                    merged_config["thinking_budget"] = profile.thinking_budget
                if profile.thinking_level:
                    merged_config["thinking_level"] = profile.thinking_level
                if profile.reasoning_effort:
                    merged_config["reasoning_effort"] = profile.reasoning_effort
                if profile.request_timeout is not None:
                    merged_config["request_timeout"] = profile.request_timeout

                if profile.custom_url:
                    merged_config["custom_url"] = profile.custom_url
                if profile.gemini_endpoint:
                    merged_config["gemini_endpoint"] = profile.gemini_endpoint

                if profile.temperature is not None:
                    merged_ai_params["temperature"] = profile.temperature
                if profile.max_tokens is not None:
                    merged_ai_params["max_tokens"] = profile.max_tokens

                if profile.api_key_pool or profile.api_key_name:
                    resolved_km = _resolve_key_override(
                        profile.api_key_pool,
                        profile.api_key_name,
                        provider,
                        key_managers,
                    )
                    if resolved_km is not None:
                        effective_key_managers = dict(key_managers)
                        effective_key_managers[provider] = resolved_km
            else:
                logging.warning(
                    f"[ProfileResolver] Profile '{profile_name}' not found, using defaults"
                )

    if not model and provider:
        model = merged_config.get(f"{provider}_model", "")

    return ResolvedProfile(
        provider=provider,
        model=model,
        streaming=streaming,
        thinking_enabled=thinking,
        config=merged_config,
        ai_params=merged_ai_params,
        key_managers=effective_key_managers,
        profile_name=profile_name,
    )


def resolve_profile_by_name(
    profile_name: str,
    config: Dict[str, Any],
    ai_params: Dict[str, Any],
    key_managers: Dict[str, Any],
) -> ResolvedProfile:
    """
    Resolve a profile by name (convenience wrapper for chat/audio window profile selector).
    """
    action = {"connection_profile": profile_name}
    return resolve_profile(action, config, ai_params, key_managers)


def _get_profile(name: str):
    """Look up a connection profile by name from ProfileStore."""
    try:
        from .connection_profiles import ProfileStore
        store = ProfileStore.get_instance()
        return store.get_profile(name)
    except Exception as e:
        logging.error(f"[ProfileResolver] Failed to look up profile '{name}': {e}")
        return None


def _resolve_key_override(
    pool_id: str,
    key_name: str,
    provider: str,
    key_managers: Dict[str, Any],
):
    """
    Resolve a key override from profile fields.

    Resolution order:
        1. If pool_id is set, build a KeyManager from that pool.
           If key_name is also set, filter to only the named key.
        2. If only key_name is set, look up within the provider's default pool.
    """
    try:
        from .key_store import KeyStore
        key_store = KeyStore.get_instance()
    except Exception:
        if key_name:
            return _legacy_resolve_by_name(key_name, provider, key_managers)
        return None

    if pool_id and key_store.pool_exists(pool_id):
        if key_name:
            keys_data = key_store.get_pool(pool_id)
            name_lower = key_name.lower().strip()
            for kd in keys_data:
                if kd.get("name", "").lower().strip() == name_lower:
                    from .key_manager import KeyManager
                    return KeyManager([kd["key"]], provider)
            logging.warning(
                f"[ProfileResolver] Key '{key_name}' not found in pool '{pool_id}'"
            )
        return key_store.build_key_manager_for_pool(pool_id, provider)

    if key_name:
        pool_for_provider = key_store.get_provider_pool_id(provider)
        keys_data = key_store.get_pool(pool_for_provider)
        name_lower = key_name.lower().strip()
        for kd in keys_data:
            if kd.get("name", "").lower().strip() == name_lower:
                from .key_manager import KeyManager
                return KeyManager([kd["key"]], provider)
        logging.warning(
            f"[ProfileResolver] Key '{key_name}' not found in pool '{pool_for_provider}' for provider '{provider}'"
        )

    return None


def _legacy_resolve_by_name(
    key_name: str,
    provider: str,
    key_managers: Dict[str, Any],
):
    """Fallback: resolve key by name using KeyManager."""
    km = key_managers.get(provider)
    if not km:
        return None
    named_key = km.get_key_by_name(key_name)
    if named_key:
        from .key_manager import KeyManager
        return KeyManager([named_key], provider)
    logging.warning(
        f"[ProfileResolver] API key named '{key_name}' not found for provider '{provider}'"
    )
    return None
