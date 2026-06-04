"""
Fallback Model Lists

Curated featured/flagship model IDs per provider, used when live model
fetching fails or is unavailable (offline, no API key, timeout, etc.).
"""

from typing import List

# ──────────────────────────────────────────────────────────────
# Fallback model IDs keyed by provider ID
# ──────────────────────────────────────────────────────────────

FALLBACK_MODELS: dict[str, list[str]] = {
    "google": [
        "gemini-3.5-flash",
        "gemini-3.1-pro-preview",
        "gemini-3-pro-preview",
        "gemini-3-flash-preview",
        "gemini-3.1-flash-lite",
        "gemini-2.5-pro",
        "gemini-2.5-flash",
        "gemini-2.5-flash-lite",
        "gemini-2.0-flash",
    ],
    "anthropic": [
        "claude-opus-4-7",
        "claude-opus-4-6",
        "claude-sonnet-4-6",
        "claude-opus-4-5",
        "claude-sonnet-4-5",
        "claude-haiku-4-5",
        "claude-3-7-sonnet-latest",
        "claude-3-5-sonnet-latest",
    ],
    "openai": [
        "gpt-5.5",
        "gpt-5.4",
        "gpt-5.2",
        "gpt-5",
        "gpt-5-mini",
        "gpt-5-nano",
        "gpt-4.1",
        "gpt-4.1-mini",
        "gpt-4.1-nano",
        "gpt-4o",
        "gpt-4o-mini",
        "o3",
        "o3-mini",
        "o4-mini",
        "o1",
        "o1-pro",
    ],
    "xai": [
        "grok-4.3",
        "grok-4-1-fast",
        "grok-4.20-multi-agent",
    ],
    "mistral": [
        "mistral-large-latest",
        "mistral-medium-latest",
        "mistral-small-latest",
        "open-mixtral-8x22b",
        "open-mistral-nemo",
    ],
    "cohere": [
        "command-a-03-2025",
        "command-a-vision-07-2025",
        "command-r-plus",
        "command-r",
    ],
    "openrouter": [
        "nvidia/nemotron-3-super-120b-a12b:free",
        "openai/gpt-oss-120b:free",
        "z-ai/glm-4.5-air:free",
        "deepseek/deepseek-v4-flash:free",
        "arcee-ai/trinity-large-thinking:free",
        "minimax/minimax-m2.5:free",
        "google/gemma-4-31b-it:free",
        "google/gemma-4-26b-a4b-it:free",
        "qwen/qwen3-next-80b-a3b-instruct:free",
        "openrouter/free",
        "openrouter/auto",
    ],
    # Custom OAI-Compatible — placeholder only (unknown models)
    "custom": [
        "local-model",
    ],
}


def get_fallback_models(provider: str) -> List[str]:
    """Return fallback model IDs for a provider.

    Returns an empty list for unknown providers so callers can
    safely use the result without a KeyError check.
    """
    return FALLBACK_MODELS.get(provider, [])
