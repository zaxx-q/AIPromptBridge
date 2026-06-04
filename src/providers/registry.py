"""
Provider Registry

Centralizes metadata for all supported AI providers and acts as the factory
for creating provider instances.
"""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from .base import BaseProvider


@dataclass
class ProviderDefinition:
    """Metadata for a provider type."""

    id: str  # e.g. "google", "openrouter", "anthropic"
    name: str  # e.g. "Google Gemini", "Anthropic Claude"
    default_base_url: str  # e.g. "https://api.anthropic.com/v1"
    auth_style: str  # "bearer" | "x-api-key" | "x-goog-api-key"
    supports_streaming: bool
    default_key_pool: str  # maps to KeyStore pool name
    provider_class: str  # e.g. "openai_compatible", "gemini_native", "anthropic"
    extra_headers: Optional[Dict[str, str]] = None  # e.g. OpenRouter tracking headers


PROVIDER_REGISTRY: Dict[str, ProviderDefinition] = {
    "google": ProviderDefinition(
        id="google",
        name="Google Gemini",
        default_base_url="https://generativelanguage.googleapis.com/v1beta",
        auth_style="x-goog-api-key",
        supports_streaming=True,
        default_key_pool="google",
        provider_class="gemini_native",
    ),
    "anthropic": ProviderDefinition(
        id="anthropic",
        name="Anthropic Claude",
        default_base_url="https://api.anthropic.com/v1",
        auth_style="x-api-key",
        supports_streaming=True,
        default_key_pool="anthropic",
        provider_class="anthropic",
    ),
    "openai": ProviderDefinition(
        id="openai",
        name="OpenAI",
        default_base_url="https://api.openai.com/v1",
        auth_style="bearer",
        supports_streaming=True,
        default_key_pool="openai",
        provider_class="openai_compatible",
    ),
    "openrouter": ProviderDefinition(
        id="openrouter",
        name="OpenRouter",
        default_base_url="https://openrouter.ai/api/v1",
        auth_style="bearer",
        supports_streaming=True,
        default_key_pool="openrouter",
        provider_class="openai_compatible",
        extra_headers={
            "HTTP-Referer": "https://github.com/zaxx-q/AIPromptBridge",
            "X-Title": "AIPromptBridge",
        },
    ),
    "xai": ProviderDefinition(
        id="xai",
        name="xAI / Grok",
        default_base_url="https://api.x.ai/v1",
        auth_style="bearer",
        supports_streaming=True,
        default_key_pool="xai",
        provider_class="openai_compatible",
    ),
    "mistral": ProviderDefinition(
        id="mistral",
        name="Mistral",
        default_base_url="https://api.mistral.ai/v1",
        auth_style="bearer",
        supports_streaming=True,
        default_key_pool="mistral",
        provider_class="openai_compatible",
    ),
    "cohere": ProviderDefinition(
        id="cohere",
        name="Cohere",
        default_base_url="https://api.cohere.ai/compatibility/v1",
        auth_style="bearer",
        supports_streaming=True,
        default_key_pool="cohere",
        provider_class="openai_compatible",
    ),
    "custom": ProviderDefinition(
        id="custom",
        name="Custom (OAI-Compatible)",
        default_base_url="",
        auth_style="bearer",
        supports_streaming=True,
        default_key_pool="custom",
        provider_class="openai_compatible",
    ),
}


def get_provider_definitions() -> Dict[str, ProviderDefinition]:
    """Return all registered provider definitions."""
    return dict(PROVIDER_REGISTRY)


def get_provider_definition(provider_id: str) -> Optional[ProviderDefinition]:
    """Look up a single provider definition by ID."""
    return PROVIDER_REGISTRY.get(provider_id)


def create_provider(provider_type: str, key_manager=None, config: Optional[Dict] = None) -> BaseProvider:
    """
    Registry-based provider factory.

    Resolves base_url from config -> registry default.
    """
    if config is None:
        config = {}

    definition = PROVIDER_REGISTRY.get(provider_type)
    if not definition:
        raise ValueError(f"Unknown provider type: {provider_type}")

    base_url = config.get("base_url") or definition.default_base_url

    provider_config = {
        "request_timeout": config.get("request_timeout", 120),
        "max_retries": config.get("max_retries", 3),
        "retry_delay": config.get("retry_delay", 5),
        "reasoning_effort": config.get("reasoning_effort", "high"),
        "thinking_budget": config.get("thinking_budget", -1),
        "thinking_level": config.get("thinking_level", "high"),
        "tts_use_official_endpoint": config.get("tts_use_official_endpoint", False),
    }

    # Forward base_url field into the config dictionary as well for backward compatibility
    provider_config["base_url"] = base_url

    if definition.provider_class == "gemini_native":
        from .gemini_native import GeminiNativeProvider

        # Also set gemini_endpoint for backward compat with GeminiNativeProvider's config-based init
        provider_config["gemini_endpoint"] = base_url
        return GeminiNativeProvider(base_url=base_url, key_manager=key_manager, config=provider_config)

    elif definition.provider_class == "anthropic":
        from .anthropic import AnthropicProvider

        return AnthropicProvider(base_url=base_url, key_manager=key_manager, config=provider_config)

    else:  # openai_compatible
        from .openai_compatible import OpenAICompatibleProvider

        return OpenAICompatibleProvider(
            endpoint_type=provider_type, base_url=base_url, key_manager=key_manager, config=provider_config
        )
