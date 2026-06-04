"""
API Providers Module

This module provides a unified interface for different AI API providers:
- OpenAICompatibleProvider: For custom APIs, OpenRouter, and OpenAI-compatible endpoints
- GeminiNativeProvider: For native Gemini API with full feature support
- AnthropicProvider: For native Anthropic Claude API support
"""

from .anthropic import AnthropicProvider
from .base import AbortedError, BaseProvider, CallbackType, ProviderResult, StreamCallback, UsageData
from .gemini_native import GeminiNativeProvider
from .openai_compatible import OpenAICompatibleProvider
from .registry import ProviderDefinition, create_provider, get_provider_definition, get_provider_definitions

__all__ = [
    'AbortedError',
    'AnthropicProvider',
    'BaseProvider',
    'CallbackType',
    'GeminiNativeProvider',
    'OpenAICompatibleProvider',
    'ProviderDefinition',
    'ProviderResult',
    'StreamCallback',
    'UsageData',
    'create_provider',
    'get_provider_definition',
    'get_provider_definitions',
]
