#!/usr/bin/env python3
"""
Windows package - modular GUI window implementations.

This package provides:
- Chat windows (StandaloneChatWindow, AttachedChatWindow)
- Session browser windows (StandaloneSessionBrowserWindow, AttachedBrowserWindow)
- Settings window (SettingsWindow, show_settings_window)
- Prompt editor window (PromptEditorWindow, show_prompt_editor)
- Audio analyzer window (AudioAnalyzerWindow)
- Utility functions (get_icon_path, set_window_icon)
- Base classes for extension
"""

# Utility functions
# Audio analyzer window
from .audio_analyzer import AudioAnalyzerWindow, create_audio_analyzer_window

# Base classes (for extension)
from .chat_base import ChatWindowBase

# Chat windows
from .chat_window import AttachedChatWindow, StandaloneChatWindow, create_attached_chat_window

# Onboarding window
from .onboarding_window import OnboardingWizard, create_attached_onboarding_window, show_onboarding_blocking

# Prompt editor window
from .prompt_editor import PromptEditorWindow, create_attached_prompt_editor_window, show_prompt_editor

# Session list components
# Session browser windows
from .session_browser import (
    AttachedBrowserWindow,
    BrowserWindowBase,
    SessionListHeader,
    SessionListItem,
    StandaloneSessionBrowserWindow,
    create_attached_browser_window,
)

# Settings window
from .settings_window import SettingsWindow, create_attached_settings_window, show_settings_window

# TTS window
from .tts_window import TTSWindow, create_tts_window
from .utils import get_icon_path, set_window_icon

__all__ = [
    "AttachedBrowserWindow",
    "AttachedChatWindow",
    # Audio analyzer
    "AudioAnalyzerWindow",
    "BrowserWindowBase",
    # Base classes
    "ChatWindowBase",
    # Onboarding window
    "OnboardingWizard",
    # Prompt editor window
    "PromptEditorWindow",
    "SessionListHeader",
    # List components
    "SessionListItem",
    # Settings window
    "SettingsWindow",
    # Chat windows
    "StandaloneChatWindow",
    # Browser windows
    "StandaloneSessionBrowserWindow",
    # TTS window
    "TTSWindow",
    "create_attached_browser_window",
    "create_attached_chat_window",
    "create_attached_onboarding_window",
    "create_attached_prompt_editor_window",
    "create_attached_settings_window",
    "create_audio_analyzer_window",
    "create_tts_window",
    # Utils
    "get_icon_path",
    "set_window_icon",
    "show_onboarding_blocking",
    "show_prompt_editor",
    "show_settings_window",
]
