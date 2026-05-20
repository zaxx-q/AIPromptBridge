"""
API Providers Module

This module provides a unified interface for different AI API providers:
- OpenAICompatibleProvider: For custom APIs, OpenRouter, and OpenAI-compatible endpoints
- GeminiNativeProvider: For native Gemini API with full feature support
- AnthropicProvider: For native Anthropic Claude API support
"""

from .base import BaseProvider, ProviderResult, StreamCallback, CallbackType, UsageData, AbortedError
from .openai_compatible import OpenAICompatibleProvider
from .gemini_native import GeminiNativeProvider
from .anthropic import AnthropicProvider
from .registry import create_provider, get_provider_definitions, get_provider_definition, ProviderDefinition

__all__ = [
    'BaseProvider',
    'ProviderResult',
    'StreamCallback',
    'CallbackType',
    'UsageData',
    'AbortedError',
    'OpenAICompatibleProvider',
    'GeminiNativeProvider',
    'AnthropicProvider',
    'create_provider',
    'get_provider_definitions',
    'get_provider_definition',
    'ProviderDefinition',
]